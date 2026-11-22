"""Unified 'Add knowledge' intake for files, screenshots and pasted staff announcements.

Every path ends in the same versioning pipeline (IngestionService.process_extracted), so duplicate
detection, versioning, chunking, embedding and review are identical for all source types.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime
from typing import Any

from app.core.config import Settings
from app.core.errors import AppError, Conflict, Forbidden, InvalidState, NotFound, ValidationFailed
from app.repositories.base import FileStorage, Query, Store, get_one
from app.security.auth import AuthUser
from app.services.ingestion.errors import ExtractionError
from app.services.ingestion.extractors_files import file_extension, sha256_hex, validate_upload
from app.services.ingestion.pipeline import IngestionService, utcnow
from app.services.ingestion.privacy import redact_personal_info
from app.services.ingestion.structured import extract_structured_fields
from app.services.ocr.providers import OCRProvider, OCRUnavailable

log = logging.getLogger("app.intake")
KIND_BY_EXT = {"pdf": "pdf", "docx": "docx", "txt": "text_file", "md": "text_file", "markdown": "text_file"}


def safe_filename(name: str | None) -> str:
    base = re.sub(r"[^A-Za-z0-9._-]", "_", (name or "upload"))[:120].strip("._") or "upload"
    return base


def file_error(exc: ExtractionError) -> AppError:
    status = {"file_too_large": 413, "unsupported_file_type": 415}.get(exc.code, 422)
    return AppError(exc.message, code=exc.code, status_code=status)


class IntakeService:
    def __init__(self, store: Store, storage: FileStorage | None, settings: Settings, ingestion: IngestionService,
                 ocr: OCRProvider):
        self.store = store
        self.storage = storage
        self.settings = settings
        self.ingestion = ingestion
        self.ocr = ocr

    # ------------------------------------------------------------- helpers
    def _require_storage(self) -> FileStorage:
        if self.storage is None:
            raise InvalidState("Private file storage is not configured.")
        return self.storage

    def find_file_duplicate(self, sha: str) -> dict[str, Any] | None:
        rows, _ = self.store.select("document_versions", Query(eq={"original_file->>sha256": sha}, limit=1,
                                                               cols="id,document_id,version_number,verification_status"))
        return rows[0] if rows else None

    def store_file(self, prefix: str, filename: str, data: bytes, mime: str) -> dict[str, Any]:
        storage = self._require_storage()
        sha = sha256_hex(data)
        path = f"{prefix}/{uuid.uuid4().hex}-{filename}"
        storage.upload(path, data, mime)  # private bucket; never a public URL
        return dict(storage_path=path, filename=filename, mime_type=mime, size=len(data), sha256=sha)

    def _cleanup(self, info: dict[str, Any] | None) -> None:
        if info and self.storage is not None:
            try:
                self.storage.remove(info["storage_path"])
            except Exception:  # noqa: BLE001
                log.warning("could not remove orphaned upload %s", info.get("storage_path"))

    def _create_source(self, meta: dict[str, Any], source_type: str, actor: AuthUser) -> dict[str, Any]:
        row = dict(title=meta["title"], organization=meta["organization"], source_type=source_type,
                   authority_type=meta["authority_type"], scope=meta["scope"], category=meta["category"],
                   language=meta.get("language") or "ko", original_url=meta.get("original_url") or None,
                   created_by=actor.id, status="processing", sync_frequency="manual")
        if row["original_url"] and not str(row["original_url"]).lower().startswith(("http://", "https://")):
            raise ValidationFailed("The reference URL must start with http:// or https://")
        if actor.role == "supporter" and row["authority_type"] in ("official_government", "official_university"):
            # supporters relay information; an admin decides whether it is official when reviewing
            row["authority_type"] = "staff_communication" if source_type in ("screenshot", "kakao_message",
                                                                             "manual_text") else "supporter_submitted"
        src = self.store.insert("knowledge_sources", row)
        self.store.insert("audit_log", dict(action="source.create", entity_type="knowledge_source", entity_id=src["id"],
                                            actor_id=actor.id, details={"source_type": source_type, "via": "intake"}))
        return src

    def _source_for(self, source_id: str | None, meta: dict[str, Any] | None, source_type: str | tuple[str, ...],
                    actor: AuthUser) -> dict[str, Any]:
        types = (source_type,) if isinstance(source_type, str) else source_type
        if source_id:
            src = get_one(self.store, "knowledge_sources", id=source_id)
            if src is None:
                raise NotFound("Source not found.")
            if src["source_type"] not in types:
                raise InvalidState(f"This source is a '{src['source_type']}' source; expected {' or '.join(types)}.")
            if actor.role == "supporter" and src.get("created_by") != actor.id:
                raise Forbidden("Supporters can only add content to sources they created.")
            if not src["is_active"]:
                raise InvalidState("The source is disabled.")
            return src
        if not meta:
            raise ValidationFailed("Source details (title, organization, category, scope, authority) are required.")
        return self._create_source(meta, types[0], actor)

    # ------------------------------------------------------ document upload
    def upload_document(self, *, data: bytes, filename: str | None, content_type: str | None, actor: AuthUser,
                        source_id: str | None = None, meta: dict[str, Any] | None = None) -> dict[str, Any]:
        """PDF / DOCX / TXT / MD. Returns {source, job}. The job is queued (extraction runs asynchronously)."""
        name = safe_filename(filename)
        kind = KIND_BY_EXT.get(file_extension(name))
        if kind is None:
            raise AppError("Supported documents: .pdf, .docx, .txt, .md", code="unsupported_file_type", status_code=415)
        try:
            mime = validate_upload(kind, name, content_type, data, self.settings.max_upload_bytes)
        except ExtractionError as exc:
            raise file_error(exc) from exc
        sha = sha256_hex(data)
        dup = self.find_file_duplicate(sha)
        if dup:
            raise Conflict("This exact file was already uploaded.", details={
                "document_id": dup["document_id"], "version_id": dup["id"], "version_number": dup["version_number"],
                "verification_status": dup["verification_status"]})
        src = self._source_for(source_id, meta, kind, actor)
        info = None
        try:
            info = self.store_file(f"sources/{src['id']}", name, data, mime)
            job = self.ingestion.create_job(src, "manual", actor.id, payload=info, job_type="ingest")
            self.store.update("knowledge_sources", {"status": "processing"}, {"id": src["id"]})
            self.ingestion.event(job["id"], "upload", f"Stored {name} ({len(data)} bytes, sha256 {sha[:12]}…).")
        except Exception:
            self._cleanup(info)
            if not source_id:  # do not leave an empty source behind
                self.store.delete("knowledge_sources", {"id": src["id"]})
            raise
        return dict(source=src, job=job)

    # ------------------------------------------------------------ screenshots
    def ocr_status(self) -> dict[str, Any]:
        ok, why = self.ocr.available()
        return dict(provider=self.ocr.name, available=ok, reason=why,
                    languages=self.settings.ocr_languages if self.ocr.name == "tesseract" else
                    (self.settings.ocr_space_language if self.ocr.name == "ocr_space" else None),
                    external_processing=self.ocr.name == "ocr_space")

    def screenshot_extract(self, *, data: bytes, filename: str | None, content_type: str | None, actor: AuthUser,
                           source_id: str | None, meta: dict[str, Any] | None, authorized: bool) -> dict[str, Any]:
        """Store the image privately, run OCR (if configured) and return an editable preview. No version yet."""
        if not authorized:
            raise ValidationFailed("Confirm that this screenshot is an authorized staff announcement that may be "
                                   "processed and shared (authorized_for_distribution = true).")
        name = safe_filename(filename)
        try:
            mime = validate_upload("screenshot", name, content_type, data, self.settings.max_image_bytes)
        except ExtractionError as exc:
            raise file_error(exc) from exc
        sha = sha256_hex(data)
        dup = self.find_file_duplicate(sha)
        if dup:
            raise Conflict("This exact screenshot was already submitted.", details={
                "document_id": dup["document_id"], "version_id": dup["id"]})
        src = self._source_for(source_id, meta, "screenshot", actor)
        info = None
        try:
            info = self.store_file(f"screenshots/{src['id']}", name, data, mime)
            job = self.ingestion.create_job(src, "manual", actor.id, payload=info, job_type="ocr_intake")
            job = self.store.update("ingestion_jobs", dict(status="running", started_at=utcnow(), attempts=1),
                                    {"id": job["id"]})[0]
        except Exception:
            self._cleanup(info)
            if not source_id:
                self.store.delete("knowledge_sources", {"id": src["id"]})
            raise
        return self._run_ocr(job, src, info)

    def _run_ocr(self, job: dict[str, Any], src: dict[str, Any], info: dict[str, Any]) -> dict[str, Any]:
        ocr: dict[str, Any] = dict(provider=self.ocr.name, available=True, text="", mean_confidence=None,
                                   uncertain_lines=[], warnings=[], model=None, extracted_at=utcnow())
        self.ingestion.event(job["id"], "ocr", f"Running OCR with provider '{self.ocr.name}'.")
        try:
            data = self._require_storage().download(info["storage_path"])
            r = self.ocr.extract(data, info["mime_type"])
            ocr.update(text=r.text, raw_text=r.raw_text, mean_confidence=r.mean_confidence,
                       uncertain_lines=r.uncertain_lines(), warnings=r.warnings, model=r.model)
            self.ingestion.event(job["id"], "ocr", f"OCR produced {len(r.text)} characters"
                                 + (f" (mean confidence {r.mean_confidence})." if r.mean_confidence is not None else "."))
            if not r.text.strip():
                ocr["warnings"].append("OCR found no text in the image. Type the announcement text manually.")
        except OCRUnavailable as exc:
            ocr.update(available=False, warnings=[exc.message], error_code=exc.code)
            self.ingestion.event(job["id"], "ocr", f"OCR unavailable: {exc.message}", level="warning")
        detected = extract_structured_fields(ocr["text"]) if ocr["text"] else None
        payload = {**info, "ocr": ocr}
        done = self.store.update("ingestion_jobs", dict(
            status="succeeded", outcome="extracted", completed_at=utcnow(), payload=payload,
            statistics={"ocr_provider": ocr["provider"], "ocr_chars": len(ocr["text"]),
                        "ocr_mean_confidence": ocr["mean_confidence"], "warnings": ocr["warnings"]},
            error_code=ocr.get("error_code"), error_message=(ocr["warnings"][0] if not ocr["available"] else None)),
            {"id": job["id"]})[0]
        self.store.update("knowledge_sources", {"status": "registered", "last_checked_at": utcnow()}, {"id": src["id"]})
        return dict(source=src, job=done, ocr=ocr, detected=detected,
                    image=dict(filename=info["filename"], mime_type=info["mime_type"], size=info["size"]))

    def retry_ocr(self, job_id: str, actor: AuthUser) -> dict[str, Any]:
        job = get_one(self.store, "ingestion_jobs", id=job_id)
        if job is None or job.get("job_type") != "ocr_intake":
            raise NotFound("Screenshot intake not found.")
        src = get_one(self.store, "knowledge_sources", id=job["source_id"])
        if src is None:
            raise NotFound("Source not found.")
        if actor.role == "supporter" and job.get("requested_by") != actor.id:
            raise Forbidden("Supporters can only retry their own screenshots.")
        info = {k: (job.get("payload") or {}).get(k) for k in ("storage_path", "filename", "mime_type", "size", "sha256")}
        if not info["storage_path"]:
            raise InvalidState("This intake has no stored image.")
        new = self.ingestion.create_job(src, "retry", actor.id, payload=info, job_type="ocr_intake")
        new = self.store.update("ingestion_jobs", dict(status="running", started_at=utcnow(), attempts=1),
                                {"id": new["id"]})[0]
        return self._run_ocr(new, src, info)

    def screenshot_intake(self, job_id: str, actor: AuthUser) -> dict[str, Any]:
        job = get_one(self.store, "ingestion_jobs", id=job_id)
        if job is None or job.get("job_type") != "ocr_intake":
            raise NotFound("Screenshot intake not found.")
        if actor.role == "supporter" and job.get("requested_by") != actor.id:
            raise Forbidden("Supporters can only view their own screenshots.")
        payload = job.get("payload") or {}
        ocr = payload.get("ocr") or {}
        return dict(job=job, ocr=ocr, detected=extract_structured_fields(ocr.get("text", "")) if ocr.get("text") else None,
                    image={k: payload.get(k) for k in ("filename", "mime_type", "size")})

    def screenshot_image(self, job_id: str, actor: AuthUser) -> tuple[bytes, str, str]:
        job = get_one(self.store, "ingestion_jobs", id=job_id)
        if job is None or job.get("job_type") != "ocr_intake":
            raise NotFound("Screenshot intake not found.")
        if actor.role == "supporter" and job.get("requested_by") != actor.id:
            raise Forbidden("Supporters can only view their own screenshots.")
        p = job.get("payload") or {}
        return self._require_storage().download(p["storage_path"]), p["mime_type"], p["filename"]

    def screenshot_submit(self, job_id: str, *, title: str, text: str, actor: AuthUser, submit: bool,
                          redact: bool, fields: dict[str, Any], source_published_at: datetime | None) -> dict[str, Any]:
        """Create the document version from the (corrected) OCR text. Raw OCR is kept as immutable evidence."""
        job = get_one(self.store, "ingestion_jobs", id=job_id)
        if job is None or job.get("job_type") != "ocr_intake" or job["status"] != "succeeded":
            raise NotFound("Screenshot intake not found or OCR has not finished.")
        if actor.role == "supporter" and job.get("requested_by") != actor.id:
            raise Forbidden("Supporters can only submit their own screenshots.")
        if job.get("version_id"):
            raise Conflict("A version was already created from this screenshot.", details={"version_id": job["version_id"]})
        src = get_one(self.store, "knowledge_sources", id=job["source_id"])
        if src is None:
            raise NotFound("Source not found.")
        payload = job.get("payload") or {}
        ocr = payload.get("ocr") or {}
        original_file = {k: payload.get(k) for k in ("storage_path", "filename", "mime_type", "size", "sha256")}
        result = self.ingestion.ingest_text(
            src, title=title, text=text, requested_by=actor.id, source_published_at=source_published_at,
            external_id=f"screenshot:{payload.get('sha256', job_id)[:24]}",
            raw_text=ocr.get("raw_text") or ocr.get("text") or None,  # exact OCR output = evidence
            redact=redact, manual_fields=fields, initial_status="pending_review" if submit else "draft",
            document_type="screenshot", original_file=original_file, requires_field_confirmation=True,
            extraction_extra={"extractor": f"ocr:{ocr.get('provider', 'none')}" if ocr.get("text") else "manual-transcription",
                              "ocr_provider": ocr.get("provider"), "ocr_model": ocr.get("model"),
                              "ocr_mean_confidence": ocr.get("mean_confidence"),
                              "ocr_uncertain_lines": ocr.get("uncertain_lines", []), "ocr_extracted_at": ocr.get("extracted_at"),
                              "corrected_by_submitter": bool(ocr.get("text")) and ocr.get("text", "").strip() != text.strip(),
                              "warnings": ocr.get("warnings", [])})
        if result["status"] == "succeeded" and result.get("version_id"):
            self.store.update("ingestion_jobs", {"version_id": result["version_id"], "document_id": result["document_id"]},
                              {"id": job_id})
        return result

    # -------------------------------------------------- pasted announcement
    def paste_announcement(self, body: dict[str, Any], actor: AuthUser) -> dict[str, Any]:
        """Paste of an SCH staff announcement (e.g. received via KakaoTalk). Original text = immutable evidence."""
        if not body.get("authorized_by_supporter"):
            raise ValidationFailed("Confirm this is an authorized staff announcement that may be shared with students "
                                   "(authorized_by_supporter = true). Private conversations must not be submitted.")
        stype = "kakao_message" if body.get("received_via") == "kakaotalk" else "manual_text"
        meta = {k: body.get(k) for k in ("title", "organization", "category", "language", "scope", "original_url")}
        meta["authority_type"] = body.get("authority_type") or "staff_communication"
        meta["scope"] = meta.get("scope") or "university"
        other = "manual_text" if stype == "kakao_message" else "kakao_message"
        src = self._source_for(body.get("source_id"), meta, (stype, other), actor)
        original = body["original_text"]
        normalized = body.get("normalized_text") or original
        if body.get("redact_personal_info", True):
            normalized, _ = redact_personal_info(normalized)
        fields = {k: body.get(k) for k in ("target_audience", "event_date", "deadline", "location",
                                            "application_method", "notes")}
        fields = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in fields.items()}
        return self.ingestion.ingest_text(
            src, title=body["title"], text=normalized, requested_by=actor.id,
            source_published_at=body.get("source_published_at"), raw_text=original, redact=False,
            manual_fields=fields, initial_status="pending_review" if body.get("submit") else "draft",
            document_type="manual_text",
            external_id=body.get("external_id"))
