"""Unified ingestion pipeline.

    acquire (fetch / board connector / stored file / OCR) -> normalize -> SHA-256 -> duplicate check
    -> new version (pending_review or draft) -> chunk -> embed -> admin review -> approve (atomic) -> searchable

Invariants (see docs/ingestion.md):
  * The last approved version is never modified; new content always lands as a new draft/pending version.
  * A failed fetch/extraction never creates content and never removes approved knowledge.
  * Identical content (same normalized hash) never creates a new version, chunks or embeddings.
  * Every step is logged to ``ingestion_events`` so admins can see what happened.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.config import Settings
from app.core.constants import FETCHABLE_SOURCE_TYPES
from app.core.errors import AppError, DuplicateError, InvalidState, NotFound
from app.models.domain import ExtractedDocument
from app.repositories.base import FileStorage, Query, Store, get_one
from app.security.url_guard import canonicalize_url
from app.services.indexing import IndexingService
from app.services.ingestion.errors import ExtractionError, FetchError, IngestionError
from app.services.ingestion.extractors_files import (
    extract_docx,
    extract_pdf,
    extract_text_file,
    process_manual_text,
    render_pdf_pages,
    validate_upload,
)
from app.services.ingestion.extractors_html import extract_html
from app.services.ingestion.fetcher import BLOCKED_CODES, GuardedFetcher
from app.services.ingestion.normalize import content_hash, normalize_text, text_fingerprint
from app.services.ingestion.privacy import redact_personal_info
from app.services.ingestion.sch_board import (
    is_sch_board_url,
    notice_document,
    page_url,
    parse_listing,
    parse_notice,
)
from app.services.ingestion.structured import extract_structured_fields, merge_manual_fields
from app.services.language_detect import detect_language
from app.services.ocr.providers import NoOCR, OCRProvider, OCRUnavailable
from app.services.source_status import derive_source_status

log = logging.getLogger("app.ingest")
DOC_TYPES = {"website": "webpage", "sch_board": "notice", "pdf": "pdf", "docx": "docx", "text_file": "text",
             "screenshot": "screenshot", "manual_text": "manual_text", "kakao_message": "manual_text"}
PREVIEW_CHARS = 20000
# failures worth retrying automatically (with backoff) before the job is marked failed
TRANSIENT_CODES = {"timeout", "network_error", "robots_unavailable", "embedding_unavailable", "not_indexed",
                   "upstream_error", "internal_error", "version_conflict", "llm_rate_limited", "llm_unavailable"}


def is_transient(code: str | None) -> bool:
    return bool(code) and (code in TRANSIENT_CODES or str(code).startswith("http_5"))


def utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _iso(dt: datetime | None) -> str | None:
    return dt.astimezone(UTC).isoformat() if dt else None


class IngestionService:
    def __init__(self, store: Store, storage: FileStorage | None, settings: Settings, indexer: IndexingService,
                 fetcher: GuardedFetcher | None = None, ocr: OCRProvider | None = None,
                 sleep: Callable[[float], None] = time.sleep, notifications: Any = None):
        self.notifications = notifications
        self.store = store
        self.storage = storage
        self.settings = settings
        self.indexer = indexer
        self.fetcher = fetcher or GuardedFetcher(settings)
        self.ocr: OCRProvider = ocr or NoOCR()
        self.translations: Any = None   # DocumentTranslationService (wired by the container)
        self._sleep = sleep

    # ---------------------------------------------------------------- jobs
    def create_job(self, source: dict[str, Any], trigger: str = "manual", requested_by: str | None = None,
                   payload: dict[str, Any] | None = None, job_type: str | None = None) -> dict[str, Any]:
        jt = job_type or ("board_sync" if source["source_type"] == "sch_board" else "ingest")
        return self.store.insert("ingestion_jobs", dict(
            source_id=source["id"], status="queued", trigger=trigger, requested_by=requested_by,
            payload=payload or {}, statistics={}, job_type=jt))

    def event(self, job_id: str | None, step: str, message: str, level: str = "info", **data: Any) -> None:
        """Append to the job's step log. Logging must never break ingestion."""
        if not job_id:
            return
        try:
            self.store.insert("ingestion_events", dict(job_id=job_id, level=level, step=step, message=message[:2000],
                                                        data=data))
        except Exception:  # noqa: BLE001
            log.warning("could not record ingestion event for job %s", job_id)

    def _heartbeat(self, job_id: str) -> None:
        try:
            self.store.update("ingestion_jobs", {"heartbeat_at": utcnow()}, {"id": job_id})
        except Exception:  # noqa: BLE001
            log.warning("heartbeat failed for job %s", job_id)

    def run_job(self, job_id: str) -> dict[str, Any]:
        """Inline execution of a queued job (tests / scripts / CLI)."""
        job = get_one(self.store, "ingestion_jobs", id=job_id)
        if job is None:
            raise NotFound("job not found")
        if job["status"] != "queued":
            return job
        job = self.store.update("ingestion_jobs", dict(status="running", started_at=utcnow(), heartbeat_at=utcnow(),
                                                       attempts=(job.get("attempts") or 0) + 1), {"id": job_id})[0]
        return self.execute(job)

    def execute(self, job: dict[str, Any]) -> dict[str, Any]:
        """Run a job that is already marked running. Never raises: failures are persisted on job and source."""
        source = get_one(self.store, "knowledge_sources", id=job["source_id"]) if job.get("source_id") else None
        if source is None:   # deleted while queued: never recreate anything for it
            return self._finish(job, None, error=IngestionError("source_deleted", "The source was deleted."))
        started = time.perf_counter()
        stats: dict[str, Any] = {}
        self.event(job["id"], "start", f"Job started ({job.get('job_type', 'ingest')}, trigger {job.get('trigger')}).",
                   attempt=job.get("attempts"))
        try:
            if not source["is_active"]:
                raise IngestionError("source_inactive", "The source is disabled; enable it before ingesting.")
            if job.get("job_type") == "index_version":
                result = self._run_index(source, job, stats)
            elif job.get("job_type") == "translate_document":
                if self.translations is None:
                    raise IngestionError("translation_unavailable", "Document translation is not configured.")
                result = self.translations.run_job(job, self._heartbeat, self.event)
            elif source["source_type"] == "sch_board":
                result = self._run_board(source, job, stats)
            else:
                extracted, canonical_url, external_id, extra = self._acquire(source, job, stats)
                self._set_source_status(source["id"], "processing")
                result = self.process_extracted(source, extracted, canonical_url, external_id,
                                                created_by=job.get("requested_by"), stats=stats, job_id=job["id"], **extra)
            stats["duration_ms"] = int((time.perf_counter() - started) * 1000)
            return self._finish(job, source, result=result, stats=stats)
        except IngestionError as exc:
            stats["duration_ms"] = int((time.perf_counter() - started) * 1000)
            return self._finish(job, source, error=exc, stats=stats)
        except AppError as exc:
            stats["duration_ms"] = int((time.perf_counter() - started) * 1000)
            return self._finish(job, source, error=IngestionError(exc.code, exc.message), stats=stats)
        except Exception as exc:  # noqa: BLE001 - persisted, not swallowed
            log.exception("ingestion job %s crashed", job["id"])
            stats["duration_ms"] = int((time.perf_counter() - started) * 1000)
            return self._finish(job, source, error=IngestionError("internal_error", f"Unexpected error: {type(exc).__name__}"),
                                stats=stats)

    # ------------------------------------------------------------- acquire
    def _acquire(self, source: dict[str, Any], job: dict[str, Any], stats: dict[str, Any]
                 ) -> tuple[ExtractedDocument, str | None, str | None, dict[str, Any]]:
        stype = source["source_type"]
        jid = job["id"]
        if stype == "website":
            self._set_source_status(source["id"], "fetching")
            self.event(jid, "fetch", f"Fetching {source['original_url']}")
            res = self.fetcher.fetch(source["original_url"], source.get("language"))
            stats.update(fetched_bytes=len(res.content), final_url=res.url, redirects=len(res.redirects),
                         http_status=res.status_code, content_type=res.content_type)
            self.event(jid, "fetch", f"HTTP {res.status_code}, {len(res.content)} bytes, {res.content_type}",
                       final_url=res.url, redirects=res.redirects)
            if res.content_type == "application/pdf":
                extracted = extract_pdf(res.content, res.url.rsplit("/", 1)[-1] or "document.pdf")
            else:
                extracted = extract_html(res.content, res.url, res.encoding, self.settings.min_extracted_chars)
            stats["content_chars"] = len(extracted.text)
            self.event(jid, "extract", f"Extracted {len(extracted.text)} characters with {extracted.metadata.get('extractor')}.",
                       warnings=extracted.metadata.get("warnings", []))
            return extracted, canonicalize_url(source["original_url"]), None, {}
        if stype in ("pdf", "docx", "text_file"):
            payload = job.get("payload") or {}
            path, filename = payload.get("storage_path"), payload.get("filename", f"document.{stype}")
            if not path or self.storage is None:
                raise IngestionError("no_file", "No uploaded file is attached to this job. Upload a file first.")
            self._set_source_status(source["id"], "processing")
            data = self.storage.download(path)
            stats["fetched_bytes"] = len(data)
            mime = validate_upload(stype, filename, None, data, self.settings.max_upload_bytes)
            self.event(jid, "file", f"Loaded {filename} ({len(data)} bytes) from private storage.")
            extra: dict[str, Any] = {"original_file": {k: payload.get(k) for k in
                                                       ("storage_path", "filename", "mime_type", "size", "sha256")}}
            if stype == "pdf":
                try:
                    extracted = extract_pdf(data, filename)
                except ExtractionError as exc:
                    if exc.code != "needs_ocr":
                        raise
                    extracted = self._ocr_pdf(data, filename, jid, exc)
                    extra["requires_field_confirmation"] = True
            elif stype == "docx":
                extracted = extract_docx(data, filename)
            else:
                extracted = extract_text_file(data, filename)
            extra["original_file"]["mime_type"] = extra["original_file"].get("mime_type") or mime
            stem = filename.rsplit(".", 1)[0]
            if extracted.title == stem and source.get("title"):
                # no title in the file's metadata: use the title the submitter entered, not the file name
                extracted.title = source["title"]
                extracted.text = extracted.text.replace(f"# {stem}", f"# {source['title']}", 1)
            stats["content_chars"] = len(extracted.text)
            self.event(jid, "extract", f"Extracted {len(extracted.text)} characters with {extracted.metadata.get('extractor')}.",
                       warnings=extracted.metadata.get("warnings", []))
            return extracted, None, "primary", extra
        raise IngestionError("not_fetchable", f"Sources of type '{stype}' are added through the intake forms, not fetched.")

    def _ocr_pdf(self, data: bytes, filename: str, job_id: str, original: ExtractionError) -> ExtractedDocument:
        ok, why = self.ocr.available()
        if not ok:
            raise IngestionError("needs_ocr", f"{original.message} OCR is not available: {why}")
        pages = render_pdf_pages(data, self.settings.ocr_max_pdf_pages)
        self.event(job_id, "ocr", f"Image-only PDF: running {self.ocr.name} OCR on {len(pages)} page(s).")
        parts, confs, warnings = [], [], []
        for i, png in enumerate(pages, start=1):
            try:
                r = self.ocr.extract(png, "image/png")
            except OCRUnavailable as exc:
                raise IngestionError(exc.code, exc.message) from exc
            if r.text.strip():
                parts.append(f"[Page {i}]\n{normalize_text(r.text)}")
            if r.mean_confidence is not None:
                confs.append(r.mean_confidence)
            warnings += r.warnings
        if not parts:
            raise IngestionError("empty_extraction", "OCR found no text in the scanned PDF.")
        title = filename.rsplit(".", 1)[0]
        mean = round(sum(confs) / len(confs), 1) if confs else None
        return ExtractedDocument(title=title, text=f"# {title}\n\n" + "\n\n".join(parts), metadata={
            "extractor": f"ocr:{self.ocr.name}", "ocr_provider": self.ocr.name, "ocr_mean_confidence": mean,
            "warnings": list(dict.fromkeys(warnings + ["Text was produced by OCR: verify dates, places, fees and "
                                                       "contacts against the original before approval."]))})

    # ------------------------------------------------------- board connector
    def _run_board(self, source: dict[str, Any], job: dict[str, Any], stats: dict[str, Any]) -> dict[str, Any]:
        jid = job["id"]
        url = source["original_url"]
        if not is_sch_board_url(url):
            raise IngestionError("invalid_board_url", "This connector only supports SCH notice01.php board pages.")
        cfg = source.get("config") or {}
        max_items = max(1, min(int(cfg.get("max_items") or self.settings.board_max_items), self.settings.board_max_items_cap))
        max_pages = max(1, min(int(cfg.get("max_pages") or self.settings.board_max_pages), 5))
        self._set_source_status(source["id"], "fetching")
        refs = []
        for page in range(1, max_pages + 1):
            purl = url if page == 1 else page_url(url, page)
            self.event(jid, "list", f"Fetching board page {page}: {purl}")
            res = self.fetcher.fetch(purl, "ko")
            found = parse_listing(res.content, purl)
            self.event(jid, "list", f"Found {len(found)} notice link(s) on page {page}.")
            refs += [r for r in found if r.notice_no not in {x.notice_no for x in refs}]
            if len(refs) >= max_items:
                break
            self._sleep(self.settings.board_request_delay_seconds)
        refs = refs[:max_items]
        stats.update(items_found=len(refs), items_new=0, items_unchanged=0, items_failed=0, failures=[], notices=[])
        if not refs:
            raise IngestionError("no_notices", "The board page contained no notices.")
        self._set_source_status(source["id"], "processing")
        first_new: dict[str, Any] | None = None
        for ref in refs:
            self._sleep(self.settings.board_request_delay_seconds)
            self._heartbeat(jid)
            try:
                res = self.fetcher.fetch(ref.url, "ko")
                notice = parse_notice(res.content, ref)
                doc = notice_document(notice, source["organization"])
                result = self.process_extracted(
                    source, doc, ref.url, f"{ref.table}:{ref.notice_no}", created_by=job.get("requested_by"),
                    stats={}, job_id=jid, doc_metadata={k: doc.metadata.get(k) for k in
                                                        ("notice_no", "board_table", "author", "attachments", "pinned")})
            except (FetchError, ExtractionError, IngestionError) as exc:
                stats["items_failed"] += 1
                stats["failures"].append({"notice_no": ref.notice_no, "title": ref.title, "code": exc.code,
                                          "message": exc.message})
                self.event(jid, "notice", f"Notice {ref.notice_no} failed: {exc.message}", level="warning",
                           code=exc.code, url=ref.url)
                if exc.code in BLOCKED_CODES:
                    raise  # the site refuses access: stop instead of hammering it
                continue
            key = "items_new" if result["outcome"] == "new_version" else "items_unchanged"
            stats[key] += 1
            if result.get("skipped"):
                stats["items_skipped"] = stats.get("items_skipped", 0) + 1
            stats["notices"].append({"notice_no": ref.notice_no, "title": notice.title,
                                     "outcome": "skipped" if result.get("skipped") else result["outcome"],
                                     "document_id": result["document_id"], "version_id": result["version_id"]})
            if result["outcome"] == "new_version" and first_new is None:
                first_new = result
        if stats["items_failed"] == len(refs):
            first = stats["failures"][0]
            raise IngestionError(first["code"], f"All {len(refs)} notices failed. First error: {first['message']}")
        outcome = "partial" if stats["items_failed"] else ("new_version" if stats["items_new"] else "unchanged")
        msg = (f"{stats['items_new']} new/changed notice(s) waiting for review, {stats['items_unchanged']} unchanged"
               + (f", {stats['items_failed']} failed" if stats["items_failed"] else "") + ".")
        anchor = first_new or (stats["notices"][0] if stats["notices"] else {})
        return dict(outcome=outcome, document_id=anchor.get("document_id"), version_id=anchor.get("version_id"),
                    message=msg, warning=None, changed=bool(stats["items_new"]))

    # ------------------------------------------------------- approval -> index -> activate
    def request_activation(self, version: dict[str, Any], actor_id: str, note: str | None) -> dict[str, Any]:
        """Record the approval decision and queue a durable index_version job (idempotent)."""
        open_jobs, _ = self.store.select("ingestion_jobs", Query(
            eq={"job_type": "index_version", "payload->>version_id": version["id"]}, in_={"status": ["queued", "running"]}))
        if open_jobs:
            return open_jobs[0]
        doc = get_one(self.store, "source_documents", id=version["document_id"])
        source = get_one(self.store, "knowledge_sources", id=doc["source_id"]) if doc else None
        if source is None:
            raise NotFound("Source not found for this version.")
        self.store.update("document_versions", dict(activation_requested_by=actor_id, activation_requested_at=utcnow(),
                                                    activation_note=note, indexing_status="queued", indexing_error=None),
                          {"id": version["id"]})
        try:
            job = self.create_job(source, "manual", actor_id, payload={"version_id": version["id"], "note": note},
                                  job_type="index_version")
        except DuplicateError:  # another request queued it a moment ago
            rows, _ = self.store.select("ingestion_jobs", Query(
                eq={"job_type": "index_version", "payload->>version_id": version["id"]}, in_={"status": ["queued", "running"]}))
            return rows[0]
        self.store.insert("audit_log", dict(action="version.approval_requested", entity_type="document_version",
                                            entity_id=version["id"], actor_id=actor_id,
                                            details={"document_id": version["document_id"], "job_id": job["id"],
                                                     "version_number": version["version_number"], "note": note}))
        self.event(job["id"], "queued", f"Approved by reviewer; indexing queued for v{version['version_number']}.")
        return job

    def _run_index(self, source: dict[str, Any], job: dict[str, Any], stats: dict[str, Any]) -> dict[str, Any]:
        jid = job["id"]
        vid = (job.get("payload") or {}).get("version_id")
        v = get_one(self.store, "document_versions", id=vid) if vid else None
        if v is None:
            raise IngestionError("version_missing", "The version to index no longer exists.")
        doc = get_one(self.store, "source_documents", id=v["document_id"]) or {}
        if v["verification_status"] == "approved" and doc.get("current_version_id") == v["id"]:
            return dict(outcome="activated", document_id=v["document_id"], version_id=v["id"], changed=False,
                        message=f"v{v['version_number']} is already active.")
        if v["verification_status"] != "pending_review":
            raise IngestionError("invalid_state", f"v{v['version_number']} is '{v['verification_status']}', not awaiting "
                                                  "activation; nothing was published.")
        if doc.get("is_canceled"):
            raise IngestionError("invalid_state", "The document was withdrawn; nothing was published.")
        self.store.update("document_versions", {"indexing_status": "indexing"}, {"id": vid})
        self.event(jid, "chunk", f"Indexing v{v['version_number']} of '{doc.get('title', '')[:100]}'.")

        def progress(done: int, total: int) -> None:
            self._heartbeat(jid)
            if done == total or done % 32 == 0:
                self.event(jid, "embed", f"Embedded {done}/{total} new chunk(s).")

        try:
            st = self.indexer.index_version(vid, raise_on_embedding_error=True, embed=True, progress=progress)
        except AppError as exc:  # EmbeddingUnavailable
            raise IngestionError("embedding_unavailable", exc.message) from exc
        stats.update({k: st[k] for k in ("chunk_count", "embedded_chunks", "reused_embeddings", "embedding_model",
                                         "embedding_ms")})
        total, ok = self.indexer.chunk_counts(vid)
        self.event(jid, "validate", f"Validated {ok}/{total} chunk embeddings with {st['embedding_model']} "
                                    f"({st['reused_embeddings']} reused, {st['embedding_ms']} ms).")
        if total == 0 or total != st["chunk_count"] or ok != total:
            raise IngestionError("not_indexed", f"Index incomplete: {ok}/{total} chunks embedded "
                                                f"(expected {st['chunk_count']}). The previous version stays active.")
        try:
            self.store.rpc("activate_document_version", dict(
                p_version_id=vid, p_actor=v.get("activation_requested_by"), p_note=v.get("activation_note"),
                p_expected_chunks=total, p_model=self.indexer.embedder.model_id))
        except AppError as exc:
            code = "not_indexed" if "not_indexed" in exc.message else exc.code
            raise IngestionError(code, exc.message) from exc
        self.event(jid, "activate", f"v{v['version_number']} is now the active version and searchable.")
        if self.translations is not None:
            try:   # outdate translations of the previous version, create tasks for this one (never blocks activation)
                sync = self.translations.sync(v["document_id"], v.get("activation_requested_by"))
                if sync["created"] or sync["outdated"]:
                    self.event(jid, "translations", f"Translations: {sync['outdated']} marked outdated, "
                                                    f"{sync['created']} new review task(s).")
            except Exception:  # noqa: BLE001
                log.exception("translation sync failed for document %s", v["document_id"])
        if self.notifications:
            self.notifications.notify("version_activated", f"Now searchable: {doc.get('title', '')[:150]}",
                                      f"v{v['version_number']} indexed ({total} chunks) and activated.",
                                      entity_type="source_document", entity_id=v["document_id"],
                                      link=f"/admin/documents/{v['document_id']}")
        return dict(outcome="activated", document_id=v["document_id"], version_id=vid, changed=True,
                    message=f"v{v['version_number']} indexed ({total} chunks) and activated.")

    # ------------------------------------------------------------- previews
    def preview_url(self, url: str, source_type: str, language: str | None) -> dict[str, Any]:
        """Fetch + extract WITHOUT saving anything (the 'Fetch and Preview' button)."""
        if source_type == "sch_board":
            if not is_sch_board_url(url):
                raise IngestionError("invalid_board_url", "Not an SCH notice01.php board URL.")
            res = self.fetcher.fetch(url, "ko")
            refs = parse_listing(res.content, url)
            sample = None
            if refs:
                self._sleep(self.settings.board_request_delay_seconds)
                n = parse_notice(self.fetcher.fetch(refs[0].url, "ko").content, refs[0])
                d = notice_document(n, "")
                sample = dict(title=d.title, text=d.text[:PREVIEW_CHARS], posted_at=_iso(d.source_published_at),
                              attachments=n.attachments, warnings=d.metadata.get("warnings", []))
            return dict(kind="board", final_url=res.url, notices=[dict(notice_no=r.notice_no, title=r.title, url=r.url,
                                                                        posted=r.posted, author=r.author, pinned=r.pinned)
                                                                   for r in refs[:30]],
                        notice_count=len(refs), sample_notice=sample)
        res = self.fetcher.fetch(url, language)
        if res.content_type == "application/pdf":
            ex = extract_pdf(res.content, res.url.rsplit("/", 1)[-1] or "document.pdf")
        else:
            ex = extract_html(res.content, res.url, res.encoding, self.settings.min_extracted_chars)
        text = normalize_text(ex.text)
        from app.services.chunking import chunk_text

        return dict(kind="page", final_url=res.url, redirects=res.redirects, http_status=res.status_code,
                    content_type=res.content_type, title=ex.title, text=text[:PREVIEW_CHARS], truncated=len(text) > PREVIEW_CHARS,
                    content_chars=len(text), content_hash=content_hash(text), source_published_at=_iso(ex.source_published_at),
                    links=ex.links[:40], warnings=ex.metadata.get("warnings", []), extractor=ex.metadata.get("extractor"),
                    estimated_chunks=len(chunk_text(text, self.indexer.cfg)), structured=extract_structured_fields(text))

    # ------------------------------------------------------- manual text
    def ingest_text(self, source: dict[str, Any], *, title: str, text: str, requested_by: str | None,
                    source_published_at: datetime | None = None, external_id: str | None = None,
                    raw_text: str | None = None, redact: bool | None = None, manual_fields: dict[str, Any] | None = None,
                    initial_status: str = "pending_review", document_type: str | None = None,
                    original_file: dict[str, Any] | None = None, extraction_extra: dict[str, Any] | None = None,
                    requires_field_confirmation: bool = False) -> dict[str, Any]:
        """Text submissions (manual / KakaoTalk paste / corrected OCR). Runs inline with a job record for traceability."""
        job = self.create_job(source, "manual", requested_by, job_type="ingest")
        job = self.store.update("ingestion_jobs", dict(status="running", started_at=utcnow(), attempts=1),
                                {"id": job["id"]})[0]
        started = time.perf_counter()
        stats: dict[str, Any] = {}
        try:
            if not source["is_active"]:
                raise IngestionError("source_inactive", "The source is disabled; enable it before submitting.")
            if source["source_type"] not in ("manual_text", "kakao_message", "screenshot"):
                raise IngestionError("invalid_source_type", "Text can only be submitted to manual, KakaoTalk or screenshot sources.")
            do_redact = (source["source_type"] == "kakao_message") if redact is None else redact
            if do_redact:
                text, red = redact_personal_info(text)
                stats["redactions"] = red
                self.event(job["id"], "privacy", f"Redacted personal details: {red}.")
            extracted = process_manual_text(title, text, source_published_at)
            if extraction_extra:
                extracted.metadata.update(extraction_extra)
            stats["content_chars"] = len(extracted.text)
            ext = external_id or text_fingerprint(normalize_text(title).lower())[:24]
            result = self.process_extracted(
                source, extracted, None, ext, created_by=requested_by, stats=stats, job_id=job["id"],
                raw_text=raw_text, manual_fields=manual_fields, initial_status=initial_status,
                document_type=document_type, original_file=original_file,
                requires_field_confirmation=requires_field_confirmation)
            stats["duration_ms"] = int((time.perf_counter() - started) * 1000)
            return self._finish(job, source, result=result, stats=stats)
        except IngestionError as exc:
            return self._finish(job, source, error=exc, stats=stats)
        except AppError as exc:
            return self._finish(job, source, error=IngestionError(exc.code, exc.message), stats=stats)

    # -------------------------------------------------- core versioning
    def process_extracted(self, source: dict[str, Any], extracted: ExtractedDocument, canonical_url: str | None,
                          external_id: str | None, *, created_by: str | None, stats: dict[str, Any],
                          job_id: str | None = None, raw_text: str | None = None,
                          original_file: dict[str, Any] | None = None, manual_fields: dict[str, Any] | None = None,
                          initial_status: str = "pending_review", document_type: str | None = None,
                          doc_metadata: dict[str, Any] | None = None,
                          requires_field_confirmation: bool = False) -> dict[str, Any]:
        text = normalize_text(extracted.text)
        h = content_hash(text)

        skip = self._skip_reason(source, canonical_url, external_id)
        if skip:
            self.event(job_id, "skip", skip)
            return dict(outcome="unchanged", document_id=None, version_id=None, message=skip, changed=False, skipped=True)
        doc = self._find_or_create_document(source, extracted, canonical_url, external_id, document_type, doc_metadata)
        if doc.get("is_canceled") or doc.get("archived_at"):
            state = "withdrawn" if doc.get("is_canceled") else "archived"
            msg = f"Skipped: '{doc['title'][:100]}' is {state}. Restore it to accept new versions."
            self.event(job_id, "skip", msg)
            return dict(outcome="unchanged", document_id=doc["id"], version_id=None, message=msg, changed=False,
                        skipped=True)
        versions, _ = self.store.select("document_versions", Query(eq={"document_id": doc["id"]},
                                                                    order=[("version_number", False)]))
        same = next((v for v in versions if v["content_hash"] == h), None)
        if same is not None:
            labels = {
                "approved": "identical to the current approved version",
                "superseded": "identical to an earlier approved version (use rollback to restore it)",
                "pending_review": "identical to the version already waiting for review",
                "rejected": "identical to a version that was previously rejected",
                "draft": "identical to an existing draft",
            }
            msg = (f"No change: content is {labels.get(same['verification_status'], 'unchanged')} "
                   f"(v{same['version_number']}). No new version, chunks or embeddings were created.")
            self.event(job_id, "compare", msg, content_hash=h)
            return dict(outcome="unchanged", document_id=doc["id"], version_id=same["id"], message=msg, changed=False)

        # an unreviewed predecessor is replaced by the newer extraction (it is kept as 'superseded', never deleted)
        for v in versions:
            if v["verification_status"] in ("pending_review", "draft"):
                self.store.update("document_versions", {"verification_status": "superseded"}, {"id": v["id"]})
                self.event(job_id, "compare", f"Unreviewed v{v['version_number']} superseded by the newer extraction.")

        structured = extract_structured_fields(text)
        if manual_fields:
            structured = merge_manual_fields(structured, manual_fields)
        warnings = list(dict.fromkeys(list(extracted.metadata.get("warnings", [])) + structured.get("warnings", [])))
        meta = {k: v for k, v in extracted.metadata.items() if k != "warnings"}
        meta.update(warnings=warnings, links=(extracted.links or [])[:60],
                    requires_field_confirmation=bool(requires_field_confirmation or
                                                     str(meta.get("extractor", "")).startswith("ocr")))
        version = None
        number = (versions[-1]["version_number"] if versions else 0) + 1
        for _attempt in range(3):
            try:
                version = self.store.insert("document_versions", dict(
                    document_id=doc["id"], version_number=number, extracted_text=text, content_hash=h,
                    source_published_at=_iso(extracted.source_published_at), fetched_at=utcnow(),
                    verification_status=initial_status, created_by=created_by,
                    submitted_at=utcnow() if initial_status == "pending_review" else None,
                    raw_text=raw_text, structured_data=structured, extraction_meta=meta, original_file=original_file,
                    indexing_status="indexing"))
                break
            except DuplicateError:
                number += 1  # raced with another writer
        if version is None:
            raise IngestionError("version_conflict", "Could not allocate a version number; please retry.")
        self.event(job_id, "version", f"Created v{number} ({initial_status}) for '{doc['title'][:120]}'.",
                   version_id=version["id"], content_hash=h)

        index_stats = self.indexer.index_version(version["id"])
        stats.update({k: index_stats[k] for k in ("chunk_count", "embedded_chunks", "embedding_model")})
        stats["embedding_ms"] = index_stats.get("embedding_ms")
        if index_stats["embedding_error"]:
            warnings.append(f"Embeddings not generated: {index_stats['embedding_error']}")
            self.event(job_id, "embed", f"Embedding failed: {index_stats['embedding_error']}", level="warning")
        else:
            self.event(job_id, "embed", f"{index_stats['chunk_count']} chunk(s), {index_stats['embedded_chunks']} embedded "
                                        f"({index_stats['reused_embeddings']} reused) with {index_stats['embedding_model']}.")
        if warnings:
            stats["warnings"] = warnings
        self.store.update("knowledge_sources", {"last_change_at": utcnow()}, {"id": source["id"]})
        msg = f"New version v{number} created and {'saved as a draft' if initial_status == 'draft' else 'waiting for review'}."
        if index_stats["embedding_error"]:
            msg += " Embeddings could not be generated yet; use 'Reprocess' before approving."
        return dict(outcome="new_version", document_id=doc["id"], version_id=version["id"], message=msg,
                    warning=index_stats["embedding_error"], changed=True)

    def _skip_reason(self, source: dict[str, Any], canonical_url: str | None, external_id: str | None) -> str | None:
        """Deliberately deleted website/board documents are never re-imported automatically."""
        if external_id:
            hit = get_one(self.store, "document_suppressions", source_id=source["id"], external_id=external_id)
        elif canonical_url:
            hit = get_one(self.store, "document_suppressions", source_id=source["id"], canonical_url=canonical_url)
        else:
            hit = None
        return (f"Skipped: '{(hit.get('title') or canonical_url or external_id)[:100]}' was deliberately deleted and "
                "is blocked from re-import (an admin can allow it again).") if hit else None

    def _find_or_create_document(self, source: dict[str, Any], extracted: ExtractedDocument, canonical_url: str | None,
                                 external_id: str | None, document_type: str | None = None,
                                 metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        eq: dict[str, Any] = {"source_id": source["id"]}
        if external_id:
            eq["external_id"] = external_id
        else:
            eq["canonical_url"] = canonical_url
        doc = get_one(self.store, "source_documents", **eq)
        if doc:
            patch: dict[str, Any] = {}
            if extracted.title and doc["title"] != extracted.title[:500]:
                patch["title"] = extracted.title[:500]
            if metadata and metadata != (doc.get("metadata") or {}):
                patch["metadata"] = metadata
            detected = detect_language(extracted.text)
            if detected and detected != doc.get("language") and not doc.get("current_version_id"):
                patch["language"] = detected   # nothing approved yet: correct the original language silently
            if patch:
                doc = self.store.update("source_documents", patch, {"id": doc["id"]})[0]
            return doc
        dtype = document_type or DOC_TYPES.get(source["source_type"], "manual_text")
        try:
            return self.store.insert("source_documents", dict(
                source_id=source["id"], canonical_url=canonical_url, external_id=external_id,
                title=(extracted.title or source["title"])[:500],
                # content wins over site-wide HTML lang attributes / source defaults when the evidence is clear
                language=detect_language(extracted.text) or extracted.language or source["language"],
                document_type=dtype, metadata=metadata or {}))
        except DuplicateError:  # concurrent creation: use the winner
            found = get_one(self.store, "source_documents", **eq)
            assert found is not None
            return found

    # --------------------------------------------------------- bookkeeping
    def _set_source_status(self, source_id: str, status: str) -> None:
        self.store.update("knowledge_sources", {"status": status}, {"id": source_id})

    def derive_source_status(self, source_id: str) -> str:
        return derive_source_status(self.store, source_id)

    def _finish(self, job: dict[str, Any], source: dict[str, Any] | None, *, result: dict[str, Any] | None = None,
                error: IngestionError | None = None, stats: dict[str, Any] | None = None) -> dict[str, Any]:
        now = utcnow()
        stats = stats or {}
        src_patch: dict[str, Any] = {"last_checked_at": now}
        if error is None and result is not None:
            patch = dict(status="succeeded", outcome=result["outcome"], document_id=result.get("document_id"),
                         version_id=result.get("version_id"), completed_at=now, statistics=stats, locked_by=None,
                         error_code="embedding_unavailable" if result.get("warning") else None,
                         error_message=result.get("warning"))
            summary = dict(job_id=job["id"], status="succeeded", outcome=result["outcome"],
                           message=result["message"], completed_at=now)
            src_patch["last_success_at"] = now
            self.event(job["id"], "finish", result["message"])
        else:
            assert error is not None
            attempts = int(job.get("attempts") or 1)
            if is_transient(error.code) and attempts < int(job.get("max_attempts") or 3):
                delay = self.settings.job_retry_base_seconds * (2 ** (attempts - 1))
                run_after = (datetime.now(UTC) + timedelta(seconds=delay)).isoformat()
                self.event(job["id"], "retry", f"Transient failure ({error.code}): {error.message} Retrying in {delay}s "
                                               f"(attempt {attempts + 1} of {job.get('max_attempts') or 3}).", level="warning")
                done = self.store.update("ingestion_jobs", dict(
                    status="queued", run_after=run_after, locked_by=None, error_code=error.code,
                    error_message=error.message, statistics=stats), {"id": job["id"]})[0]
                if job.get("job_type") == "index_version":
                    self.store.update("document_versions", {"indexing_status": "queued", "indexing_error": error.message},
                                      {"id": (job.get("payload") or {}).get("version_id")})
                return done
            patch = dict(status="failed", completed_at=now, error_code=error.code, error_message=error.message,
                         statistics=stats, locked_by=None)
            summary = dict(job_id=job["id"], status="failed", outcome=None, message=error.message, completed_at=now,
                           error_code=error.code)
            self.event(job["id"], "finish", f"Failed ({error.code}): {error.message}", level="error")
            if job.get("job_type") == "index_version" and (job.get("payload") or {}).get("version_id"):
                self.store.update("document_versions", {"indexing_status": "failed", "indexing_error": error.message},
                                  {"id": job["payload"]["version_id"]})
            self._notify_failure(job, source, error)
        done = self.store.update("ingestion_jobs", patch, {"id": job["id"]})[0]
        if error is None and result is not None and result.get("changed") and job.get("job_type") != "index_version" \
                and source is not None and self.notifications:
            via = {"schedule": "Scheduled check", "retry": "Retry"}.get(job.get("trigger"), "Ingestion")
            self.notifications.notify("review_needed", f"Changes to review: {source['title'][:150]}",
                                      f"{via}: {result['message']}", entity_type="knowledge_source",
                                      entity_id=source["id"], link="/admin/review")
        if job.get("job_type") == "translate_document":
            pass   # a translation draft says nothing about the source's freshness
        elif source is not None and job.get("job_type") == "index_version":
            # indexing is not a source check: only refresh the derived status (pending_review -> approved)
            self.store.update("knowledge_sources", {"status": self.derive_source_status(source["id"])}, {"id": source["id"]})
        elif source is not None:
            if error is not None:
                src_patch["status"] = "blocked" if error.code in BLOCKED_CODES else "failed"
            else:
                src_patch["status"] = self.derive_source_status(source["id"])
            src_patch["last_ingestion_result"] = summary
            self.store.update("knowledge_sources", src_patch, {"id": source["id"]})
        log.info("job %s finished: %s %s", job["id"], patch["status"], patch.get("error_code") or patch.get("outcome"))
        return done

    def _notify_failure(self, job: dict[str, Any], source: dict[str, Any] | None, error: IngestionError) -> None:
        if not self.notifications or source is None:   # a deleted source is not a sync failure
            return
        title = source["title"][:150] if source else "Unknown source"
        if job.get("job_type") == "translate_document":
            self.notifications.notify("translation_failed", f"Translation draft failed: {title}",
                                      f"{error.message} The original stays searchable; translate manually or retry.",
                                      severity="warning", entity_type="ingestion_job", entity_id=job["id"],
                                      link=f"/admin/documents/{(job.get('payload') or {}).get('document_id', '')}")
            return
        if job.get("job_type") == "index_version":
            self.notifications.notify("indexing_failed", f"Indexing failed: {title}",
                                      f"{error.message} The previously approved version remains active.",
                                      severity="error", entity_type="ingestion_job", entity_id=job["id"],
                                      link="/admin/rag-sync")
        elif error.code in BLOCKED_CODES:
            self.notifications.notify("source_blocked", f"Source blocked: {title}",
                                      f"{error.message} Use manual import (upload or paste) instead.", severity="warning",
                                      entity_type="knowledge_source", entity_id=job["source_id"],
                                      link=f"/admin/knowledge-sources/{job['source_id']}")
        elif job.get("job_type") != "ocr_intake":
            self.notifications.notify("sync_failed", f"Sync failed: {title}", error.message, severity="error",
                                      entity_type="knowledge_source", entity_id=job["source_id"],
                                      link=f"/admin/knowledge-sources/{job['source_id']}")

    # ------------------------------------------------------------ recovery
    def recover_interrupted_jobs(self) -> int:
        """Inline mode only: jobs left 'running' cannot still be running; mark them failed (visible + retryable).
        In worker mode the claim RPC re-queues stale jobs instead."""
        rows, _ = self.store.select("ingestion_jobs", Query(eq={"status": "running"}))
        for r in rows:
            self.store.update("ingestion_jobs", dict(status="failed", completed_at=utcnow(), error_code="interrupted",
                                                     error_message="The server restarted while this job was running."),
                              {"id": r["id"]})
            if r.get("source_id"):
                self.store.update("knowledge_sources", {"status": "failed"}, {"id": r["source_id"]})
        return len(rows)

    def due_sources(self, now: datetime | None = None) -> list[dict[str, Any]]:
        """Active website/board sources whose daily/weekly sync is due."""
        now = now or datetime.now(UTC)
        rows, _ = self.store.select("knowledge_sources", Query(
            eq={"is_active": True}, in_={"sync_frequency": ["daily", "weekly"], "source_type": list(FETCHABLE_SOURCE_TYPES)}))
        due = []
        for s in rows:
            interval = 86400 if s["sync_frequency"] == "daily" else 7 * 86400
            last = s.get("last_checked_at")
            if last is None or (now - datetime.fromisoformat(last)).total_seconds() >= interval - 300:
                due.append(s)
        return due

    def has_open_job(self, source_id: str) -> bool:
        rows, _ = self.store.select("ingestion_jobs", Query(eq={"source_id": source_id},
                                                             in_={"status": ["queued", "running"],
                                                                  "job_type": ["ingest", "board_sync"]}, limit=1))
        return bool(rows)

    def require_fetchable(self, source: dict[str, Any]) -> None:
        if source["source_type"] not in FETCHABLE_SOURCE_TYPES:
            raise InvalidState(
                f"'{source['source_type']}' sources are not fetched. Upload a file (pdf/docx/txt/md), upload a "
                "screenshot, or submit text instead."
            )
        if not source["is_active"]:
            raise InvalidState("The source is disabled.")
