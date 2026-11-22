"""Ingestion pipeline: fetch/extract -> normalize -> hash -> compare -> new version -> chunk -> embed -> review.

Invariants (see docs/ingestion.md):
  * The last approved version is never modified; new content always lands as `pending_review`.
  * A failed fetch/extraction never creates content (and never blanks an existing version).
  * Identical content (same normalized hash) never creates a new version.
"""
from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Any

from app.core.config import Settings
from app.core.errors import AppError, DuplicateError, InvalidState, NotFound
from app.models.domain import ExtractedDocument
from app.repositories.base import FileStorage, Query, Store, get_one
from app.security.url_guard import canonicalize_url
from app.services.indexing import IndexingService
from app.services.ingestion.errors import ExtractionError, FetchError, IngestionError
from app.services.ingestion.extractors_files import (
    extract_docx,
    extract_pdf,
    process_manual_text,
    validate_upload,
)
from app.services.ingestion.extractors_html import extract_html
from app.services.ingestion.fetcher import GuardedFetcher
from app.services.ingestion.normalize import content_hash, normalize_text
from app.services.ingestion.privacy import redact_personal_info
from app.services.source_status import derive_source_status

log = logging.getLogger("app.ingest")


def utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _iso(dt: datetime | None) -> str | None:
    return dt.astimezone(UTC).isoformat() if dt else None


class IngestionService:
    def __init__(self, store: Store, storage: FileStorage | None, settings: Settings, indexer: IndexingService,
                 fetcher: GuardedFetcher | None = None):
        self.store = store
        self.storage = storage
        self.settings = settings
        self.indexer = indexer
        self.fetcher = fetcher or GuardedFetcher(settings)

    # ---------------------------------------------------------------- jobs
    def create_job(self, source: dict[str, Any], trigger: str = "manual", requested_by: str | None = None,
                   payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.store.insert("ingestion_jobs", dict(
            source_id=source["id"], status="queued", trigger=trigger, requested_by=requested_by,
            payload=payload or {}, statistics={}))

    def run_job(self, job_id: str) -> dict[str, Any]:
        """Execute a queued job. Never raises: failures are persisted on the job and the source."""
        job = get_one(self.store, "ingestion_jobs", id=job_id)
        if job is None:
            raise NotFound("job not found")
        if job["status"] not in ("queued",):
            return job
        source = get_one(self.store, "knowledge_sources", id=job["source_id"])
        if source is None:
            return self._finish(job, None, error=IngestionError("source_missing", "Source no longer exists."))
        started = time.perf_counter()
        self.store.update("ingestion_jobs", dict(status="running", started_at=utcnow()), {"id": job_id})
        stats: dict[str, Any] = {}
        try:
            extracted, canonical_url, external_id = self._acquire(source, job, stats)
            self._set_source_status(source["id"], "processing")
            result = self.process_extracted(source, extracted, canonical_url, external_id, created_by=job.get("requested_by"),
                                            stats=stats)
            stats["duration_ms"] = int((time.perf_counter() - started) * 1000)
            return self._finish(job, source, result=result, stats=stats)
        except IngestionError as exc:
            stats["duration_ms"] = int((time.perf_counter() - started) * 1000)
            return self._finish(job, source, error=exc, stats=stats)
        except AppError as exc:
            stats["duration_ms"] = int((time.perf_counter() - started) * 1000)
            return self._finish(job, source, error=IngestionError(exc.code, exc.message), stats=stats)
        except Exception as exc:  # noqa: BLE001 - persisted, not swallowed
            log.exception("ingestion job %s crashed", job_id)
            stats["duration_ms"] = int((time.perf_counter() - started) * 1000)
            return self._finish(job, source, error=IngestionError("internal_error", f"Unexpected error: {type(exc).__name__}"),
                                stats=stats)

    def _acquire(self, source: dict[str, Any], job: dict[str, Any], stats: dict[str, Any]
                 ) -> tuple[ExtractedDocument, str | None, str | None]:
        stype = source["source_type"]
        if not source["is_active"]:
            raise IngestionError("source_inactive", "The source is disabled; enable it before ingesting.")
        if stype == "website":
            self._set_source_status(source["id"], "fetching")
            res = self.fetcher.fetch(source["original_url"], source.get("language"))
            stats.update(fetched_bytes=len(res.content), final_url=res.url, redirects=len(res.redirects),
                         http_status=res.status_code, content_type=res.content_type)
            if res.content_type == "application/pdf":
                extracted = extract_pdf(res.content, res.url.rsplit("/", 1)[-1] or "document.pdf")
            else:
                extracted = extract_html(res.content, res.url, res.encoding, self.settings.min_extracted_chars)
            stats["content_chars"] = len(extracted.text)
            # identity = the exact URL the admin registered (redirect targets are recorded separately)
            return extracted, canonicalize_url(source["original_url"]), None
        if stype in ("pdf", "docx"):
            path = job.get("payload", {}).get("storage_path")
            filename = job.get("payload", {}).get("filename", f"document.{stype}")
            if not path or self.storage is None:
                raise IngestionError("no_file", "No uploaded file is attached to this job. Upload a file first.")
            self._set_source_status(source["id"], "processing")
            data = self.storage.download(path)
            stats["fetched_bytes"] = len(data)
            validate_upload(stype, filename, None, data, self.settings.max_upload_bytes)
            extracted = extract_pdf(data, filename) if stype == "pdf" else extract_docx(data, filename)
            stats["content_chars"] = len(extracted.text)
            return extracted, None, "primary"  # one tracked document per file source; re-upload => new version
        raise IngestionError("not_fetchable", f"Sources of type '{stype}' are ingested by submitting text, not fetching.")

    # ------------------------------------------------------- manual text
    def ingest_text(self, source: dict[str, Any], *, title: str, text: str, requested_by: str | None,
                    source_published_at: datetime | None = None, external_id: str | None = None) -> dict[str, Any]:
        """Manual / KakaoTalk text submission (runs inline; creates a job record for traceability)."""
        job = self.create_job(source, "manual", requested_by)
        started = time.perf_counter()
        self.store.update("ingestion_jobs", dict(status="running", started_at=utcnow()), {"id": job["id"]})
        stats: dict[str, Any] = {}
        try:
            if not source["is_active"]:
                raise IngestionError("source_inactive", "The source is disabled; enable it before submitting.")
            if source["source_type"] not in ("manual_text", "kakao_message"):
                raise IngestionError("invalid_source_type", "Text can only be submitted to manual or KakaoTalk sources.")
            if source["source_type"] == "kakao_message":
                text, red = redact_personal_info(text)
                stats["redactions"] = red
            extracted = process_manual_text(title, text, source_published_at)
            stats["content_chars"] = len(extracted.text)
            from app.services.ingestion.normalize import text_fingerprint

            ext = external_id or text_fingerprint(normalize_text(title).lower())[:24]
            result = self.process_extracted(source, extracted, None, ext, created_by=requested_by, stats=stats)
            stats["duration_ms"] = int((time.perf_counter() - started) * 1000)
            return self._finish(job, source, result=result, stats=stats)
        except IngestionError as exc:
            return self._finish(job, source, error=exc, stats=stats)
        except AppError as exc:
            return self._finish(job, source, error=IngestionError(exc.code, exc.message), stats=stats)

    # -------------------------------------------------- core versioning
    def process_extracted(self, source: dict[str, Any], extracted: ExtractedDocument, canonical_url: str | None,
                          external_id: str | None, *, created_by: str | None, stats: dict[str, Any]) -> dict[str, Any]:
        text = normalize_text(extracted.text)
        h = content_hash(text)

        doc = self._find_or_create_document(source, extracted, canonical_url, external_id)
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
            return dict(outcome="unchanged", document_id=doc["id"], version_id=same["id"],
                        message=f"No change: content is {labels.get(same['verification_status'], 'unchanged')} "
                                f"(v{same['version_number']}).")

        # a not-yet-reviewed predecessor is replaced by the newer extraction (never an approved one)
        for v in versions:
            if v["verification_status"] == "pending_review":
                self.store.update("document_versions", {"verification_status": "superseded"}, {"id": v["id"]})

        version = None
        number = (versions[-1]["version_number"] if versions else 0) + 1
        for _attempt in range(3):
            try:
                version = self.store.insert("document_versions", dict(
                    document_id=doc["id"], version_number=number, extracted_text=text, content_hash=h,
                    source_published_at=_iso(extracted.source_published_at), fetched_at=utcnow(),
                    verification_status="pending_review", created_by=created_by))
                break
            except DuplicateError:
                number += 1  # raced with another writer
        if version is None:
            raise IngestionError("version_conflict", "Could not allocate a version number; please retry.")

        index_stats = self.indexer.index_version(version["id"])
        stats.update({k: index_stats[k] for k in ("chunk_count", "embedded_chunks", "embedding_model")})
        warnings = list(extracted.metadata.get("warnings", []))
        if index_stats["embedding_error"]:
            warnings.append(f"Embeddings not generated: {index_stats['embedding_error']}")
        if warnings:
            stats["warnings"] = warnings
        msg = f"New version v{number} created and waiting for review."
        if index_stats["embedding_error"]:
            msg += " Embeddings could not be generated yet; use 'Reprocess' before approving."
        return dict(outcome="new_version", document_id=doc["id"], version_id=version["id"], message=msg,
                    warning=index_stats["embedding_error"])

    def _find_or_create_document(self, source: dict[str, Any], extracted: ExtractedDocument, canonical_url: str | None,
                                 external_id: str | None) -> dict[str, Any]:
        eq: dict[str, Any] = {"source_id": source["id"]}
        if canonical_url:
            eq["canonical_url"] = canonical_url
        else:
            eq["external_id"] = external_id
        doc = get_one(self.store, "source_documents", **eq)
        if doc:
            if extracted.title and doc["title"] != extracted.title:
                self.store.update("source_documents", {"title": extracted.title[:500]}, {"id": doc["id"]})
                doc["title"] = extracted.title[:500]
            return doc
        dtype = {"website": "webpage", "pdf": "pdf", "docx": "docx"}.get(source["source_type"], "manual_text")
        try:
            return self.store.insert("source_documents", dict(
                source_id=source["id"], canonical_url=canonical_url, external_id=external_id,
                title=(extracted.title or source["title"])[:500], language=source["language"], document_type=dtype))
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
        if error is None and result is not None:
            patch = dict(status="succeeded", outcome=result["outcome"], document_id=result["document_id"],
                         version_id=result["version_id"], completed_at=now, statistics=stats,
                         error_code="embedding_unavailable" if result.get("warning") else None,
                         error_message=result.get("warning"))
            summary = dict(job_id=job["id"], status="succeeded", outcome=result["outcome"],
                           message=result["message"], completed_at=now)
        else:
            assert error is not None
            patch = dict(status="failed", completed_at=now, error_code=error.code, error_message=error.message,
                         statistics=stats)
            summary = dict(job_id=job["id"], status="failed", outcome=None, message=error.message,
                           completed_at=now)
        done = self.store.update("ingestion_jobs", patch, {"id": job["id"]})[0]
        if source is not None:
            new_status = "failed" if error is not None else self.derive_source_status(source["id"])
            self.store.update("knowledge_sources", dict(status=new_status, last_checked_at=now,
                                                        last_ingestion_result=summary), {"id": source["id"]})
        log.info("job %s finished: %s %s", job["id"], patch["status"], patch.get("error_code") or patch.get("outcome"))
        return done

    # ------------------------------------------------------------ recovery
    def recover_interrupted_jobs(self) -> int:
        """After a restart: jobs left 'running' cannot still be running; mark them failed (visible + retryable)."""
        rows, _ = self.store.select("ingestion_jobs", Query(eq={"status": "running"}))
        for r in rows:
            self.store.update("ingestion_jobs", dict(status="failed", completed_at=utcnow(), error_code="interrupted",
                                                     error_message="The server restarted while this job was running."),
                              {"id": r["id"]})
            self.store.update("knowledge_sources", {"status": "failed"}, {"id": r["source_id"]})
        return len(rows)

    def due_sources(self, now: datetime | None = None) -> list[dict[str, Any]]:
        """Active website sources whose daily/weekly sync is due (called by the cron entrypoint)."""
        now = now or datetime.now(UTC)
        rows, _ = self.store.select("knowledge_sources", Query(
            eq={"source_type": "website", "is_active": True}, in_={"sync_frequency": ["daily", "weekly"]}))
        due = []
        for s in rows:
            interval = 86400 if s["sync_frequency"] == "daily" else 7 * 86400
            last = s.get("last_checked_at")
            if last is None or (now - datetime.fromisoformat(last)).total_seconds() >= interval - 300:
                due.append(s)
        return due

    def require_fetchable(self, source: dict[str, Any]) -> None:
        if source["source_type"] != "website":
            raise InvalidState(
                f"'{source['source_type']}' sources are not fetched. Upload a file (pdf/docx) or submit text "
                "(manual_text/kakao_message) instead."
            )
        if not source["is_active"]:
            raise InvalidState("The source is disabled.")


_ = (ExtractionError, FetchError)
