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

import copy
import logging
import re
import threading
import time
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.config import Settings
from app.core.constants import FETCHABLE_SOURCE_TYPES
from app.core.errors import AppError, Conflict, DuplicateError, InvalidState, NotFound
from app.models.domain import ExtractedDocument
from app.repositories.base import FileStorage, Query, Store, get_one
from app.security.url_guard import canonicalize_url
from app.services import document_attachments, document_titles
from app.services.indexing import IndexingService
from app.services.ingestion.errors import ExtractionError, FetchError, IngestionError
from app.services.ingestion.extractors_files import (
    extract_docx,
    extract_pdf,
    extract_text_file,
    iter_pdf_pages_png,
    open_pdf,
    process_manual_text,
    validate_upload,
)
from app.services.ingestion.extractors_html import extract_html
from app.services.ingestion.fetcher import BLOCKED_CODES, GuardedFetcher
from app.services.ingestion.normalize import content_hash, normalize_text, text_fingerprint
from app.services.ingestion.notice_reader import read_notice
from app.services.ingestion.pdf_isolation import extract_pdf_isolated
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
from app.services.source_quality import age_review_warning, review_checklist
from app.services.source_status import derive_source_status

log = logging.getLogger("app.ingest")
_WORD_RE = re.compile(r"\w+")   # re-extraction preview: word coverage of chunk text
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
        self.rag_health: Any = None     # RagHealthService (wired by the container): post-activation verification
        self.announcement_translator: Any = None   # AnnouncementAutoTranslator (translate_announcement jobs)
        self._sleep = sleep
        # at most INGESTION_MAX_CONCURRENT_JOBS jobs execute at once in this process, whatever starts them (the worker thread,
        # inline background tasks, the CLI): extraction + embedding of two large files at the same time do not fit 512 MB
        self._slots = threading.BoundedSemaphore(max(1, settings.ingestion_max_concurrent_jobs))
        self._slot_held = threading.local()
        self._slot_lock = threading.Lock()
        self._active = self._waiting = 0

    @contextmanager
    def _slot(self) -> Iterator[None]:
        if getattr(self._slot_held, "on", False):   # a job started inline from inside a running job: same slot
            yield
            return
        with self._slot_lock:
            self._waiting += 1
        self._slots.acquire()
        with self._slot_lock:
            self._waiting -= 1
            self._active += 1
        self._slot_held.on = True
        try:
            yield
        finally:
            self._slot_held.on = False
            with self._slot_lock:
                self._active -= 1
            self._slots.release()

    def slots(self) -> dict[str, int]:
        """Ingestion slots of this process (for /admin/system/runtime)."""
        with self._slot_lock:
            return dict(limit=max(1, self.settings.ingestion_max_concurrent_jobs), active=self._active, waiting=self._waiting)

    # ---------------------------------------------------------------- jobs
    def create_job(self, source: dict[str, Any], trigger: str = "manual", requested_by: str | None = None,
                   payload: dict[str, Any] | None = None, job_type: str | None = None,
                   executor: str | None = None) -> dict[str, Any]:
        jt = job_type or ("board_sync" if source["source_type"] == "sch_board" else "ingest")
        row = dict(source_id=source["id"], status="queued", trigger=trigger, requested_by=requested_by,
                   payload=payload or {}, statistics={}, job_type=jt)
        if executor == "gpu":     # only then: the column exists since migration 0016
            row["executor"] = "gpu"
        if jt not in ("ingest", "board_sync"):
            return self.store.insert("ingestion_jobs", row)   # e.g. index_version handles its own duplicates
        try:
            return self.store.insert("ingestion_jobs", row)
        except DuplicateError as exc:   # partial unique indexes (migration 0012): one active job per file / source
            active = self.active_job(source_id=source["id"]) or self.active_job(sha256=(payload or {}).get("sha256"))
            raise Conflict("This file or source is already being processed; wait for that job to finish.",
                           details={"job_id": active["id"] if active else None,
                                    "status": active["status"] if active else None}) from exc

    def event(self, job_id: str | None, step: str, message: str, level: str = "info", **data: Any) -> None:
        """Append to the job's step log. Logging must never break ingestion."""
        if not job_id:
            return
        try:
            self.store.insert("ingestion_events", dict(job_id=job_id, level=level, step=step, message=message[:2000],
                                                        data=data))
        except Exception:  # noqa: BLE001
            log.warning("could not record ingestion event for job %s", job_id)

    # ----------------------------------------------------- stages + liveness
    @contextmanager
    def _stage(self, job: dict[str, Any], stats: dict[str, Any], name: str) -> Iterator[dict[str, Any]]:
        """Time one pipeline stage. The current stage is persisted (by the ticker) so the admin UI and the next
        attempt after a restart know where a job was; durations are logged as logfmt (never document content)."""
        t0 = time.perf_counter()
        stats.update(stage=name, stage_started_at=utcnow())
        stats.pop("progress", None)
        log.info("ingest stage=%s status=start job=%s attempt=%s", name, job["id"], job.get("attempts"))
        info: dict[str, Any] = {}
        try:
            yield info
        except Exception as exc:
            ms = int((time.perf_counter() - t0) * 1000)
            code = getattr(exc, "code", None) or type(exc).__name__
            stats.setdefault("stages", []).append({"stage": name, "ms": ms, "ok": False, "error": code})
            log.warning("ingest stage=%s status=failed job=%s duration_ms=%d error=%s", name, job["id"], ms, code)
            raise
        ms = int((time.perf_counter() - t0) * 1000)
        stats.setdefault("stages", []).append({"stage": name, "ms": ms, "ok": True, **info})
        log.info("ingest stage=%s status=done job=%s duration_ms=%d %s", name, job["id"], ms,
                 " ".join(f"{k}={v}" for k, v in info.items()))

    def _heartbeat(self, job_id: str) -> None:
        try:
            self.store.update("ingestion_jobs", {"heartbeat_at": utcnow()}, {"id": job_id})
        except Exception:  # noqa: BLE001
            log.warning("heartbeat failed for job %s", job_id)

    def run_job(self, job_id: str) -> dict[str, Any]:
        """Inline execution of a queued job (tests / scripts / CLI). Waits for a free slot while still 'queued'."""
        with self._slot():
            job = get_one(self.store, "ingestion_jobs", id=job_id)
            if job is None:
                raise NotFound("job not found")
            if job["status"] != "queued" or job.get("executor") == "gpu":
                return job
            job = self.store.update("ingestion_jobs", dict(status="running", started_at=utcnow(), heartbeat_at=utcnow(),
                                                           attempts=(job.get("attempts") or 0) + 1), {"id": job_id})[0]
            return self.execute(job)

    def execute(self, job: dict[str, Any]) -> dict[str, Any]:
        """Run a job that is already marked running. Never raises: failures are persisted on job and source."""
        with self._slot():
            return self._execute(job)

    def _execute(self, job: dict[str, Any]) -> dict[str, Any]:
        source = get_one(self.store, "knowledge_sources", id=job["source_id"]) if job.get("source_id") else None
        if source is None:   # deleted while queued: never recreate anything for it
            return self._finish(job, None, error=IngestionError("source_deleted", "The source was deleted."))
        started = time.perf_counter()
        previous = job.get("statistics") or {}
        stats: dict[str, Any] = {}
        if int(job.get("attempts") or 1) > 1:
            stats["resumed_from_stage"] = previous.get("stage")
            self.event(job["id"], "resume",
                       f"Attempt {job.get('attempts')} of {job.get('max_attempts') or 3}: the previous attempt did not "
                       f"finish{' (it stopped during ' + previous['stage'] + ')' if previous.get('stage') else ''}, "
                       "for example because the service restarted. Starting this stage again; nothing from the "
                       "interrupted attempt was published.", level="warning",
                       previous_stage=previous.get("stage"), previous_error=job.get("error_code"))
        self.event(job["id"], "start", f"Job started ({job.get('job_type', 'ingest')}, trigger {job.get('trigger')}).",
                   attempt=job.get("attempts"))
        ticker = _JobTicker(self.store, job, stats, self.settings.job_heartbeat_seconds,
                            self.settings.job_max_runtime_seconds)
        ticker.start()
        try:
            return self._execute_body(job, source, stats, started)
        finally:
            ticker.stop()

    def _execute_body(self, job: dict[str, Any], source: dict[str, Any], stats: dict[str, Any],
                      started: float) -> dict[str, Any]:
        try:
            if not source["is_active"]:
                raise IngestionError("source_inactive", "The source is disabled; enable it before ingesting.")
            if job.get("job_type") == "index_version":
                result = self._run_index(source, job, stats)
            elif job.get("job_type") == "translate_document":
                if self.translations is None:
                    raise IngestionError("translation_unavailable", "Document translation is not configured.")
                result = self.translations.run_job(job, self._heartbeat, self.event)
            elif job.get("job_type") == "translate_announcement":
                if self.announcement_translator is None:
                    raise IngestionError("translation_unavailable", "Announcement translation is not configured.")
                result = self.announcement_translator.run_job(job, self._heartbeat, self.event)
            elif source["source_type"] == "sch_board":
                result = self._run_board(source, job, stats)
            else:
                extracted, canonical_url, external_id, extra = self._acquire(source, job, stats)
                self._set_source_status(source["id"], "processing")
                with self._stage(job, stats, "process") as info:   # version + chunks (idempotent by content hash)
                    result = self.process_extracted(source, extracted, canonical_url, external_id,
                                                    created_by=job.get("requested_by"), stats=stats, job_id=job["id"],
                                                    **extra)
                    info.update(outcome=result.get("outcome"))
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
                extracted = self._extract_pdf(res.content, res.url.rsplit("/", 1)[-1] or "document.pdf", job, stats)
            elif (reader := (source.get("config") or {}).get("reader")):
                extracted = read_notice(reader, res.content, source)      # found by discovery: read by the same parser
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
            with self._stage(job, stats, "download") as info:
                data = self.storage.download(path)
                info["bytes"] = len(data)
            stats["fetched_bytes"] = len(data)
            with self._stage(job, stats, "validate"):
                mime = validate_upload(stype, filename, None, data, self.settings.max_upload_bytes)
            self.event(jid, "file", f"Loaded {filename} ({len(data)} bytes) from private storage.",
                       duration_ms=stats["stages"][0]["ms"] if stats.get("stages") else None)
            extra: dict[str, Any] = {"original_file": {k: payload.get(k) for k in
                                                       ("storage_path", "filename", "mime_type", "size", "sha256")}}
            if stype == "pdf":
                try:
                    extracted = self._extract_pdf(data, filename, job, stats)
                except ExtractionError as exc:
                    if exc.code != "needs_ocr":
                        raise
                    extracted = self._ocr_pdf(data, filename, jid, exc, job=job, stats=stats)
                    extra["requires_field_confirmation"] = True
            elif stype == "docx":
                with self._stage(job, stats, "extract"):
                    extracted = extract_docx(data, filename)
            else:
                with self._stage(job, stats, "extract"):
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

    def _extract_pdf(self, data: bytes, filename: str, job: dict[str, Any], stats: dict[str, Any]) -> ExtractedDocument:
        """Text-layer extraction, isolated in a child process by default (hard timeout, crash containment)."""
        s = self.settings

        def progress(done: int, total: int) -> None:
            stats["progress"] = {"done": done, "total": total, "unit": "pages"}

        self.event(job["id"], "extract", f"Extracting text from {filename} ({len(data)} bytes; "
                                         f"{'isolated process' if s.pdf_extraction_isolation == 'subprocess' else 'in-process'}"
                                         f", timeout {int(s.pdf_extract_timeout_seconds)} s, tables {s.pdf_table_detection}).")
        with self._stage(job, stats, "extract") as info:
            if s.pdf_extraction_isolation == "subprocess":
                ex = extract_pdf_isolated(data, filename, timeout_seconds=s.pdf_extract_timeout_seconds,
                                          table_mode=s.pdf_table_detection, max_table_items=s.pdf_max_table_items,
                                          max_pages=s.pdf_max_pages, memory_limit_mb=s.pdf_extract_memory_mb,
                                          on_progress=progress)
            else:
                ex = extract_pdf(data, filename, table_mode=s.pdf_table_detection, max_table_items=s.pdf_max_table_items,
                                 max_pages=s.pdf_max_pages, on_page=progress)
            m = ex.metadata
            info.update(pages=m.get("pages"), pages_with_text=m.get("pages_with_text"), chars=len(ex.text),
                        hangul_ratio=m.get("hangul_ratio"), needs_ocr_pages=m.get("needs_ocr_pages"))
        stats["pdf"] = {k: ex.metadata.get(k) for k in ("pages", "pages_with_text", "needs_ocr_pages", "scanned_pages",
                                                        "vector_text_pages", "hangul_ratio", "chars", "table_mode")}
        return ex

    def _ocr_pdf(self, data: bytes, filename: str, job_id: str, original: ExtractionError,
                 job: dict[str, Any] | None = None, stats: dict[str, Any] | None = None) -> ExtractedDocument:
        ok, why = self.ocr.available()
        if not ok:
            raise IngestionError("needs_ocr", f"{original.message} OCR is not available here: {why}")
        stats = stats if stats is not None else {}
        n_pages = min(self.settings.ocr_max_pdf_pages, _pdf_page_count(data))
        self.event(job_id, "ocr", f"{original.message} Running {self.ocr.name} OCR on {n_pages} page(s).")
        if job is not None:
            with self._stage(job, stats, "ocr") as info:
                out = self._ocr_pages(data, filename, n_pages, stats)
                info.update(pages=n_pages, chars=len(out.text))
            return out
        return self._ocr_pages(data, filename, n_pages, stats)

    def _ocr_pages(self, data: bytes, filename: str, n_pages: int, stats: dict[str, Any]) -> ExtractedDocument:
        parts, confs, warnings = [], [], []
        for i, png in enumerate(iter_pdf_pages_png(data, n_pages), start=1):   # one page image in memory at a time
            stats["progress"] = {"done": i - 1, "total": n_pages, "unit": "pages"}
            try:
                r = self.ocr.extract(png, "image/png")
            except OCRUnavailable as exc:
                raise IngestionError(exc.code, exc.message) from exc
            if r.text.strip():
                parts.append(f"[Page {i}]\n{normalize_text(r.text)}")
            if r.mean_confidence is not None:
                confs.append(r.mean_confidence)
            warnings += r.warnings
            stats["progress"] = {"done": i, "total": n_pages, "unit": "pages"}
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

    def request_reextraction(self, version_id: str, actor_id: str | None) -> dict[str, Any]:
        """Queue an ingest job that re-extracts a version's STORED original file with the current extractor.

        This is the normal upload path with the file that is already in private storage (re-uploading the same bytes
        is refused as a duplicate). If the new text differs, the job creates a new 'pending_review' version; the
        approved version stays live until a reviewer approves the new one. Identical text creates nothing.
        """
        v, original, _doc, source, blocked = self._reextraction_target(version_id)
        if blocked:
            raise InvalidState(blocked)
        payload = {k: original.get(k) for k in ("storage_path", "filename", "mime_type", "size", "sha256")}
        payload["reextract_of"] = version_id
        job = self.create_job(source, "manual", actor_id, payload=payload, job_type="ingest")
        self.store.insert("audit_log", dict(action="version.reextract_requested", entity_type="document_version",
                                            entity_id=version_id, actor_id=actor_id,
                                            details={"document_id": v["document_id"], "job_id": job["id"],
                                                     "version_number": v["version_number"]}))
        self.event(job["id"], "queued", f"Re-extracting the stored original of v{v['version_number']} with the current "
                                        "extractor. A changed result becomes a new version waiting for review; the "
                                        "live version is not changed.")
        return job

    def _reextraction_target(self, version_id: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any],
                                                              dict[str, Any], str | None]:
        """(version, original_file, document, source, reason re-extraction is blocked or None)."""
        v = get_one(self.store, "document_versions", id=version_id)
        if v is None:
            raise NotFound("Version not found.")
        original = v.get("original_file") or {}
        if not original.get("storage_path"):
            raise InvalidState("This version has no stored original file to re-extract.")
        doc = get_one(self.store, "source_documents", id=v["document_id"]) or {}
        source = get_one(self.store, "knowledge_sources", id=doc["source_id"]) if doc.get("source_id") else None
        if source is None:
            raise NotFound("Source not found for this version.")
        blocked = None
        if doc.get("is_canceled") or doc.get("archived_at"):
            blocked = "This document is withdrawn or archived; restore it before re-extracting."
        elif source["source_type"] not in ("pdf", "docx", "text_file"):
            blocked = "Only uploaded files (pdf, docx, text) can be re-extracted."
        elif not source["is_active"]:
            blocked = "The source is disabled; enable it before re-extracting."
        elif self.has_open_job(source["id"]):
            blocked = "A job for this source is already queued or running."
        return v, original, doc, source, blocked

    def reextraction_preview(self, version_id: str) -> dict[str, Any]:
        """DRY RUN of :meth:`request_reextraction`: re-extract the stored original with the CURRENT extractor and
        compare it with the stored version. Read-only: downloads the original from private storage, extracts (in the
        isolated child process for PDFs, like ingestion jobs) and chunks in memory; writes nothing."""
        from app.services.chunking import chunk_text

        v, original, doc, source, blocked = self._reextraction_target(version_id)
        if self.storage is None:
            raise InvalidState("No file storage is configured.")
        data = self.storage.download(original["storage_path"])
        name = original.get("filename") or "document"
        st = self.settings
        if name.lower().endswith(".pdf"):
            if st.pdf_extraction_isolation == "subprocess":
                ex = extract_pdf_isolated(data, name, timeout_seconds=st.pdf_extract_timeout_seconds,
                                          table_mode=st.pdf_table_detection, max_table_items=st.pdf_max_table_items,
                                          max_pages=st.pdf_max_pages, memory_limit_mb=st.pdf_extract_memory_mb)
            else:
                ex = extract_pdf(data, name, table_mode=st.pdf_table_detection, max_table_items=st.pdf_max_table_items,
                                 max_pages=st.pdf_max_pages)
        elif name.lower().endswith(".docx"):
            ex = extract_docx(data, name)
        else:
            ex = extract_text_file(data, name)
        stem = name.rsplit(".", 1)[0]
        if ex.title == stem and source.get("title"):     # same title handling as the ingestion job
            ex.text = ex.text.replace(f"# {stem}", f"# {source['title']}", 1)
        new_text = normalize_text(ex.text)
        stored_text = v.get("extracted_text") or ""
        old_chunks, new_chunks = chunk_text(stored_text, self.indexer.cfg), chunk_text(new_text, self.indexer.cfg)
        # reference vocabulary: every word of the new extraction (it contains the whole text layer, including the
        # lines an older extractor tagged as headings)
        reference = Counter(_WORD_RE.findall(re.sub(r"(?m)^#+\s|\[Page \d+\]", " ", new_text).lower()))
        total_pages = ex.metadata.get("pages")

        def coverage(words: Counter[str]) -> float:
            total = sum(reference.values())
            return round(sum(min(n, words[w]) for w, n in reference.items()) / total, 4) if total else 0.0

        def stats(chunks: list[Any]) -> dict[str, Any]:
            lens = sorted(len(c.content) for c in chunks)
            pages = {p for c in chunks if c.page_start for p in range(c.page_start, (c.page_end or c.page_start) + 1)}
            body = Counter(w for c in chunks for w in _WORD_RE.findall(c.content.lower()))
            with_headings = body + Counter(w for c in chunks for w in _WORD_RE.findall((c.heading or "").lower()))
            return dict(chunks=len(chunks), median_chars=lens[len(lens) // 2] if lens else 0,
                        under_100_chars=sum(n < 100 for n in lens), content_chars=sum(lens),
                        word_coverage=coverage(body), word_coverage_with_headings=coverage(with_headings),
                        pages_with_chunks=len(pages),
                        pages_without_chunks=sorted(set(range(1, total_pages + 1)) - pages) if total_pages else None)

        heading_chars = sum(len(line) for line in new_text.splitlines() if line.startswith("#"))
        warnings = list(ex.metadata.get("warnings", []))
        aged = age_review_warning(ex.source_published_at, ex.title, new_text, st.source_review_age_days)
        checklist = review_checklist(new_text) if aged else None
        return dict(version_id=version_id, version_number=v["version_number"], status=v["verification_status"],
                    document=doc.get("title"), file=name, dry_run=True,
                    unchanged=content_hash(new_text) == v["content_hash"], can_apply=blocked is None,
                    blocked_reason=blocked, stored_chars=len(stored_text), new_chars=len(new_text),
                    new_heading_char_share=round(heading_chars / len(new_text), 4) if new_text else 0.0,
                    pdf={k: ex.metadata.get(k) for k in ("pages", "pages_with_text", "needs_ocr_pages", "table_mode")},
                    source_published_at=_iso(ex.source_published_at),
                    stored=stats(old_chunks), new=stats(new_chunks),
                    warnings=warnings + [w for w in (aged, checklist) if w])

    def _run_index(self, source: dict[str, Any], job: dict[str, Any], stats: dict[str, Any]) -> dict[str, Any]:
        jid = job["id"]
        vid = (job.get("payload") or {}).get("version_id")
        v = get_one(self.store, "document_versions", id=vid) if vid else None
        if v is None:
            raise IngestionError("version_missing", "The version to index no longer exists.")
        doc = get_one(self.store, "source_documents", id=v["document_id"]) or {}
        if v["verification_status"] == "approved" and doc.get("current_version_id") == v["id"]:
            document_titles.apply_title(self.store, v["id"])     # an earlier attempt stopped right after the switch
            document_attachments.apply_details(self.store, v["id"])
            return dict(outcome="activated", document_id=v["document_id"], version_id=v["id"], changed=False,
                        message=f"v{v['version_number']} is already active.")
        if v["verification_status"] != "pending_review":
            raise IngestionError("invalid_state", f"v{v['version_number']} is '{v['verification_status']}', not awaiting "
                                                  "activation; nothing was published.")
        if doc.get("is_canceled"):
            raise IngestionError("invalid_state", "The document was withdrawn; nothing was published.")
        self.store.update("document_versions", {"indexing_status": "indexing"}, {"id": vid})
        self.event(jid, "chunk", f"Indexing v{v['version_number']} of '{document_titles.version_title(v, doc)[:100]}'.")

        def progress(done: int, total: int) -> None:
            self._heartbeat(jid)
            if done == total or done % 32 == 0:
                self.event(jid, "embed", f"Embedded {done}/{total} new chunk(s).")

        try:
            st = self.indexer.index_version(vid, raise_on_embedding_error=True, embed=True, progress=progress)
        except AppError as exc:  # EmbeddingUnavailable
            raise IngestionError("embedding_unavailable", exc.message) from exc
        stats.update({k: st[k] for k in ("chunk_count", "embedded_chunks", "reused_embeddings",
                                         "reused_from_other_versions", "embedding_model", "embedding_ms")})
        total, ok = self.indexer.chunk_counts(vid)
        self.event(jid, "validate", f"Validated {ok}/{total} chunk embeddings with {st['embedding_model']} "
                                    f"({st['reused_embeddings']} reused, {st['embedding_ms']} ms).")
        if total == 0 or total != st["chunk_count"] or ok != total:
            raise IngestionError("not_indexed", f"Index incomplete: {ok}/{total} chunks embedded "
                                                f"(expected {st['chunk_count']}). The previous version stays active.")
        document_titles.remember_current_title(self.store, v["document_id"])
        try:
            self.store.rpc("activate_document_version", dict(
                p_version_id=vid, p_actor=v.get("activation_requested_by"), p_note=v.get("activation_note"),
                p_expected_chunks=total, p_model=self.indexer.embedder.model_id))
        except AppError as exc:
            code = "not_indexed" if "not_indexed" in exc.message else exc.code
            raise IngestionError(code, exc.message) from exc
        new_title = document_titles.apply_title(self.store, vid)
        document_attachments.apply_details(self.store, vid)
        doc = doc | ({"title": new_title} if new_title else {})
        self.event(jid, "activate", f"v{v['version_number']} is now the active version."
                                    f"{' The title changed with it.' if new_title else ''}")
        health = self._verify_searchable(jid, vid, stats)
        if self.translations is not None:
            try:   # outdate translations of the previous version, create tasks for this one (never blocks activation)
                sync = self.translations.sync(v["document_id"], v.get("activation_requested_by"))
                if sync["created"] or sync["outdated"]:
                    self.event(jid, "translations", f"Translations: {sync['outdated']} marked outdated, "
                                                    f"{sync['created']} new review task(s).")
            except Exception:  # noqa: BLE001
                log.exception("translation sync failed for document %s", v["document_id"])
        self._announcement_changed(v["document_id"])
        if self.notifications and (health is None or health["ok"]):
            hidden = (health or {}).get("hidden_reason")
            self.notifications.notify("version_activated",
                                      (f"Activated (not yet visible: {hidden}): " if hidden else "Now searchable: ")
                                      + doc.get("title", "")[:150],
                                      f"v{v['version_number']} indexed ({total} chunks) and activated.",
                                      entity_type="source_document", entity_id=v["document_id"],
                                      link=f"/admin/documents/{v['document_id']}")
        return dict(outcome="activated", document_id=v["document_id"], version_id=vid, changed=True,
                    message=f"v{v['version_number']} indexed ({total} chunks) and activated.")

    def _announcement_changed(self, document_id: str) -> None:
        """An approved edit of a published announcement: its translations are outdated and the language teams are told
        (they work from the approved text, so they have not seen the edit before). Never blocks the activation."""
        reviews = getattr(self.announcement_translator, "reviews", None)
        ann = get_one(self.store, "announcements", document_id=document_id) if reviews is not None else None
        if ann and ann["publication_status"] == "published":
            try:
                reviews.on_original_published(ann["id"], None)
            except Exception:  # noqa: BLE001
                log.exception("translation tasks not updated for announcement %s", ann["id"])

    def _verify_searchable(self, jid: str, vid: str, stats: dict[str, Any]) -> dict[str, Any] | None:
        """After activation: confirm students can actually find the version (searchable_chunks view + current
        embedding model). A failure does not undo the activation (the switch itself was validated); it is recorded on
        the job and admins are alerted so the document can be re-indexed."""
        health_svc = getattr(self, "rag_health", None)
        if health_svc is None:
            return None
        try:
            health = health_svc.check_version(vid)
        except Exception:  # noqa: BLE001 - verification must never break a completed activation
            log.exception("searchability check failed for version %s", vid)
            return None
        stats.update(searchable_chunks=health.get("searchable_chunks"), searchability_ok=health["ok"],
                     searchability_problems=health.get("problems"), hidden_reason=health.get("hidden_reason"))
        if health["ok"]:
            msg = (f"Verified: {health['searchable_chunks']}/{health['chunks']} chunks are searchable."
                   if not health.get("hidden_reason") else
                   f"Verified index; not visible to students yet ({health['hidden_reason']}).")
            self.event(jid, "verify", msg)
        else:
            self.event(jid, "verify", f"Activated but NOT searchable: {', '.join(health['problems'])} "
                                      f"({health.get('searchable_chunks')}/{health.get('chunks')} chunks searchable).",
                       level="error")
            health_svc.alert(health)
        return health

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
            name = res.url.rsplit("/", 1)[-1] or "document.pdf"
            st = self.settings
            if st.pdf_extraction_isolation == "subprocess":   # never parse untrusted PDFs inside the API process
                ex = extract_pdf_isolated(res.content, name, timeout_seconds=min(60.0, st.pdf_extract_timeout_seconds),
                                          table_mode=st.pdf_table_detection, max_table_items=st.pdf_max_table_items,
                                          max_pages=st.pdf_max_pages, memory_limit_mb=st.pdf_extract_memory_mb)
            else:
                ex = extract_pdf(res.content, name, table_mode=st.pdf_table_detection, max_pages=st.pdf_max_pages)
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
            self._title_only_change(doc, same, extracted.title, job_id)
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
        aged = age_review_warning(extracted.source_published_at, extracted.title, text,
                                  self.settings.source_review_age_days)
        if aged:
            warnings.append(aged)
            checklist = review_checklist(text)     # where the immigration / work / insurance / fee guidance is
            if checklist:
                warnings.append(checklist)
        meta = {k: v for k, v in extracted.metadata.items() if k != "warnings"}
        meta[document_titles.KEY] = (extracted.title or doc["title"])[:document_titles.MAX_TITLE]
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

    def _title_only_change(self, doc: dict[str, Any], version: dict[str, Any], title: str | None, job_id: str | None) -> None:
        """The same text under another title (rare: extracted texts contain their title). An open version takes the new
        title, it is reviewed anyway; a published title is kept."""
        title = (title or "")[:document_titles.MAX_TITLE]
        if not title or title == document_titles.version_title(version, doc):
            return
        if version["verification_status"] in ("draft", "pending_review"):
            document_titles.set_meta(self.store, version, title)
        elif version["id"] == doc.get("current_version_id"):
            self.event(job_id, "compare", "The source uses another title for the same text; the published title was kept.",
                       level="warning")

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
            # a published title only changes with the approved version (document_titles.py)
            if extracted.title and doc["title"] != extracted.title[:500] and not doc.get("current_version_id"):
                patch["title"] = extracted.title[:500]
            if metadata:      # the public details of a published notice only change with it as well (document_attachments.py)
                kept = document_attachments.imported(doc, metadata)
                if kept != (doc.get("metadata") or {}):
                    patch["metadata"] = kept
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
            deferred = self._defer_translation(job, error, stats)
            if deferred is not None:
                return deferred
            if is_transient(error.code) and attempts < int(job.get("max_attempts") or 3):
                delay = self.settings.job_retry_base_seconds * (2 ** (attempts - 1))
                run_after = (datetime.now(UTC) + timedelta(seconds=delay)).isoformat()
                self.event(job["id"], "retry", f"Transient failure ({error.code}): {error.message} Retrying in {delay}s "
                                               f"(attempt {attempts + 1} of {job.get('max_attempts') or 3}).", level="warning")
                done = self._update_owned(job, dict(
                    status="queued", run_after=run_after, locked_by=None, error_code=error.code,
                    error_message=error.message, statistics=stats))
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
        done = self._update_owned(job, patch)
        if error is None and result is not None and result.get("changed") and job.get("job_type") != "index_version" \
                and source is not None and self.notifications:
            via = {"schedule": "Scheduled check", "retry": "Retry"}.get(job.get("trigger"), "Ingestion")
            self.notifications.notify("review_needed", f"Changes to review: {source['title'][:150]}",
                                      f"{via}: {result['message']}", entity_type="knowledge_source",
                                      entity_id=source["id"], link="/admin/review")
        if job.get("job_type") in ("translate_document", "translate_announcement"):
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

    def _defer_translation(self, job: dict[str, Any], error: IngestionError, stats: dict[str, Any]
                           ) -> dict[str, Any] | None:
        """Translation jobs that hit the provider's quota or today's translation budget wait (re-queued for later,
        the attempt is not counted) instead of failing - up to TRANSLATION_MAX_DEFERRALS times."""
        if job.get("job_type") not in ("translate_document", "translate_announcement") \
                or error.code not in ("llm_quota", "translation_daily_limit", "llm_background_budget"):
            return None
        from app.services.translation.auto import seconds_until_tomorrow

        deferrals = int((job.get("statistics") or {}).get("deferrals") or 0) + 1
        if deferrals > self.settings.translation_max_deferrals:
            return None
        # provider quota: retry later today; translation / background budget: tomorrow (KST budgets reset at midnight)
        delay = self.settings.translation_quota_retry_seconds if error.code == "llm_quota" else seconds_until_tomorrow()
        run_after = (datetime.now(UTC) + timedelta(seconds=delay)).isoformat()
        self.event(job["id"], "deferred", f"{error.message} Trying again in {delay // 60} min "
                                          f"(deferral {deferrals} of {self.settings.translation_max_deferrals}).",
                   level="warning")
        return self._update_owned(job, dict(
            status="queued", run_after=run_after, locked_by=None, error_code=error.code, error_message=error.message,
            attempts=max(0, int(job.get("attempts") or 1) - 1), statistics=stats | {"deferrals": deferrals}))

    def _update_owned(self, job: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
        """Write the job's outcome only if this attempt still owns it. If the job went stale (e.g. this process
        stalled) and was re-queued, a later attempt owns it now and this late result must not overwrite it."""
        eq: dict[str, Any] = {"id": job["id"]}
        if job.get("attempts") is not None:
            eq["attempts"] = job["attempts"]
        rows = self.store.update("ingestion_jobs", patch, eq)
        if rows:
            return rows[0]
        log.warning("ingest job=%s attempt=%s result discarded: the job was taken over by a newer attempt",
                    job["id"], job.get("attempts"))
        return get_one(self.store, "ingestion_jobs", id=job["id"]) or job

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
        if job.get("job_type") == "translate_announcement":
            p = job.get("payload") or {}
            self.notifications.notify("translation_failed", f"Translation draft failed ({p.get('language')}): {title}",
                                      f"{error.message} The original stays published; translate manually or retry.",
                                      severity="warning", entity_type="ingestion_job", entity_id=job["id"],
                                      link=f"/admin/translations/{p.get('announcement_id', '')}/{p.get('language', '')}")
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
        rows = [r for r in rows if r.get("executor") != "gpu"]      # leased to a GPU worker, not to this process
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

    def active_job(self, *, source_id: str | None = None, sha256: str | None = None) -> dict[str, Any] | None:
        """The queued/running ingest job for a source or for an uploaded file (by its sha256), if any."""
        if not source_id and not sha256:
            return None
        eq: dict[str, Any] = {"source_id": source_id} if source_id else {"payload->>sha256": sha256}
        rows, _ = self.store.select("ingestion_jobs", Query(
            eq=eq, in_={"status": ["queued", "running"], "job_type": ["ingest", "board_sync"]},
            order=[("created_at", True)], limit=1))
        return rows[0] if rows else None

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


def _pdf_page_count(data: bytes) -> int:
    doc = open_pdf(data)
    with doc:
        return int(doc.page_count)


class _JobTicker:
    """Persists heartbeat + current stage/progress of a running job every ``interval`` seconds from a background
    thread, so long but healthy work (an extraction, OCR, embedding) is never mistaken for a dead worker. It stops
    after ``max_runtime`` so a genuinely hung job DOES go stale and is recovered by the claim RPC. Updates are
    conditional on the job still running under this attempt."""

    def __init__(self, store: Store, job: dict[str, Any], stats: dict[str, Any], interval: float, max_runtime: float):
        self.store, self.job, self.stats = store, job, stats
        self.interval, self.max_runtime = max(1.0, float(interval)), float(max_runtime)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name=f"job-ticker-{self.job['id'][:8]}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        started = time.monotonic()
        while not self._stop.wait(self.interval):
            if time.monotonic() - started > self.max_runtime:
                log.warning("ingest job=%s exceeded max runtime %ss; heartbeats stop so it can be recovered",
                            self.job["id"], int(self.max_runtime))
                return
            try:
                snapshot = copy.deepcopy(self.stats)
                eq: dict[str, Any] = {"id": self.job["id"], "status": "running"}
                if self.job.get("attempts") is not None:
                    eq["attempts"] = self.job["attempts"]
                self.store.update("ingestion_jobs", {"heartbeat_at": utcnow(), "statistics": snapshot}, eq)
            except Exception:  # noqa: BLE001 - a missed heartbeat is not fatal
                log.warning("ingest job=%s heartbeat failed", self.job["id"])
