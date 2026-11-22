from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, Query, UploadFile

from app.api.deps import Pagination, get_services
from app.core.errors import AppError, Forbidden, InvalidState, NotFound, ValidationFailed
from app.core.rate_limit import rate_limit
from app.repositories.base import Query as DbQuery
from app.repositories.base import get_many, get_one
from app.schemas.api import SourceCreate, SourcePatch, SubmitText
from app.security.auth import AuthUser, require_admin, require_staff
from app.services.container import Services
from app.services.ingestion.errors import ExtractionError
from app.services.ingestion.extractors_files import validate_upload

router = APIRouter(prefix="/api/v1/admin", tags=["admin: sources"])


def job_view(store, j: dict, source_title: str | None = None) -> dict:  # type: ignore[no-untyped-def,type-arg]
    if source_title is None:
        s = get_one(store, "knowledge_sources", id=j["source_id"])
        source_title = s["title"] if s else None
    return dict(
        id=j["id"], source_id=j["source_id"], source_title=source_title, status=j["status"], trigger=j["trigger"],
        outcome=j.get("outcome"), document_id=j.get("document_id"), version_id=j.get("version_id"),
        error_code=j.get("error_code"), error_message=j.get("error_message"), statistics=j.get("statistics") or {},
        created_at=j["created_at"], started_at=j.get("started_at"), completed_at=j.get("completed_at"))


def _file_error(exc: ExtractionError) -> AppError:
    status = {"file_too_large": 413, "unsupported_file_type": 415}.get(exc.code, 422)
    return AppError(exc.message, code=exc.code, status_code=status)


@router.get("/sources")
def list_sources(status: str | None = None, source_type: str | None = None, q: str | None = Query(None, max_length=200),
                 pg: Pagination = Depends(), svc: Services = Depends(get_services),
                 _: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    items, total = svc.sources.list(status=status, source_type=source_type, q=q, page=pg.page, size=pg.page_size)
    return pg.wrap(items, total)


@router.post("/sources", status_code=201)
def create_source(body: SourceCreate, svc: Services = Depends(get_services),
                  user: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    src = svc.sources.create(body.model_dump(), user.id)
    svc.store.insert("audit_log", dict(action="source.create", entity_type="knowledge_source", entity_id=src["id"],
                                       actor_id=user.id, details={"source_type": src["source_type"],
                                                                  "url": src.get("original_url")}))
    return svc.sources.view(src)


@router.get("/sources/{source_id}")
def get_source(source_id: str, svc: Services = Depends(get_services),
               _: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    return svc.sources.detail(source_id)


@router.patch("/sources/{source_id}")
def patch_source(source_id: str, body: SourcePatch, svc: Services = Depends(get_services),
                 _: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    return svc.sources.view(svc.sources.patch(source_id, body.model_dump(exclude_unset=True)))


@router.post("/sources/{source_id}/disable")
def disable_source(source_id: str, svc: Services = Depends(get_services),
                   user: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    return svc.sources.view(svc.sources.set_active(source_id, False, user.id))


@router.post("/sources/{source_id}/enable")
def enable_source(source_id: str, svc: Services = Depends(get_services),
                  user: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    return svc.sources.view(svc.sources.set_active(source_id, True, user.id))


@router.post("/sources/{source_id}/ingest", status_code=202, dependencies=[Depends(rate_limit("ingest"))])
def ingest_source(source_id: str, background: BackgroundTasks, svc: Services = Depends(get_services),
                  user: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    """Queue a fetch+extract job for a website source and return its id immediately (never blocks)."""
    source = svc.sources.get(source_id)
    svc.ingestion.require_fetchable(source)
    job = svc.ingestion.create_job(source, "manual", user.id)
    svc.store.update("knowledge_sources", {"status": "fetching"}, {"id": source_id})
    background.add_task(svc.ingestion.run_job, job["id"])
    return dict(job_id=job["id"], status="queued")


@router.post("/sources/{source_id}/upload", status_code=202, dependencies=[Depends(rate_limit("ingest"))])
def upload_file(source_id: str, background: BackgroundTasks, file: UploadFile = File(...),
                svc: Services = Depends(get_services), user: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    source = svc.sources.get(source_id)
    if source["source_type"] not in ("pdf", "docx"):
        raise InvalidState("Uploads are only accepted for pdf and docx sources.")
    if not source["is_active"]:
        raise InvalidState("The source is disabled.")
    if svc.storage is None:
        raise InvalidState("Private file storage is not configured.")
    max_bytes = svc.settings.max_upload_bytes
    data = file.file.read(max_bytes + 1)
    filename = re.sub(r"[^A-Za-z0-9._-]", "_", (file.filename or "upload"))[:120]
    try:
        validate_upload(source["source_type"], filename, file.content_type, data, max_bytes)
    except ExtractionError as exc:
        raise _file_error(exc) from exc
    path = f"sources/{source_id}/{uuid.uuid4().hex}-{filename}"
    svc.storage.upload(path, data, file.content_type or "application/octet-stream")  # private bucket
    job = svc.ingestion.create_job(source, "manual", user.id, payload=dict(storage_path=path, filename=filename))
    svc.store.update("knowledge_sources", {"status": "processing"}, {"id": source_id})
    background.add_task(svc.ingestion.run_job, job["id"])
    return dict(job_id=job["id"], status="queued")


@router.post("/sources/{source_id}/submit-text", status_code=201, dependencies=[Depends(rate_limit("ingest"))])
def submit_text(source_id: str, body: SubmitText, svc: Services = Depends(get_services),
                user: AuthUser = Depends(require_staff)) -> dict:  # type: ignore[type-arg]
    source = svc.sources.get(source_id)
    if user.role == "supporter" and source.get("created_by") != user.id:
        raise Forbidden("Supporters can only submit text to sources they created.")
    if source["source_type"] == "kakao_message" and not body.authorized_by_supporter:
        raise ValidationFailed("KakaoTalk submissions require confirmation that an authorized supporter provided "
                               "this material (authorized_by_supporter = true).")
    job = svc.ingestion.ingest_text(source, title=body.title, text=body.text, requested_by=user.id,
                                    source_published_at=body.source_published_at, external_id=body.external_id)
    return job_view(svc.store, job, source["title"])


@router.get("/ingestion-jobs")
def list_jobs(source_id: str | None = None, status: str | None = None, pg: Pagination = Depends(),
              svc: Services = Depends(get_services), _: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    eq = {k: v for k, v in (("source_id", source_id), ("status", status)) if v}
    rows, total = svc.store.select("ingestion_jobs", DbQuery(eq=eq, order=[("created_at", True)], limit=pg.page_size,
                                                            offset=(pg.page - 1) * pg.page_size), count=True)
    titles = {k: v["title"] for k, v in get_many(svc.store, "knowledge_sources", [r["source_id"] for r in rows]).items()}
    return pg.wrap([job_view(svc.store, r, titles.get(r["source_id"])) for r in rows], total or 0)


@router.get("/ingestion-jobs/{job_id}")
def get_job(job_id: str, svc: Services = Depends(get_services), _: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    j = get_one(svc.store, "ingestion_jobs", id=job_id)
    if j is None:
        raise NotFound("Job not found.")
    return job_view(svc.store, j)


@router.post("/ingestion-jobs/{job_id}/retry", status_code=202, dependencies=[Depends(rate_limit("ingest"))])
def retry_job(job_id: str, background: BackgroundTasks, svc: Services = Depends(get_services),
              user: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    j = get_one(svc.store, "ingestion_jobs", id=job_id)
    if j is None:
        raise NotFound("Job not found.")
    if j["status"] != "failed":
        raise InvalidState("Only failed jobs can be retried.")
    source = svc.sources.get(j["source_id"])
    if source["source_type"] == "website":
        svc.ingestion.require_fetchable(source)
        payload: dict = {}  # type: ignore[type-arg]
    elif source["source_type"] in ("pdf", "docx"):
        payload = j.get("payload") or {}
        if not payload.get("storage_path"):
            raise InvalidState("This job has no stored file to retry; upload the file again.")
    else:
        raise InvalidState("Text submissions cannot be retried; submit the text again.")
    new = svc.ingestion.create_job(source, "retry", user.id, payload=payload)
    background.add_task(svc.ingestion.run_job, new["id"])
    return dict(job_id=new["id"], status="queued")
