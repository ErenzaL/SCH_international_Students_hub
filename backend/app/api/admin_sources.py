from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, File, Query, UploadFile

from app.api.deps import Pagination, get_services
from app.core.errors import AppError, Forbidden, InvalidState, NotFound, UrlNotAllowed, ValidationFailed
from app.core.rate_limit import rate_limit
from app.repositories.base import Query as DbQuery
from app.repositories.base import get_many, get_one
from app.schemas.api import SourceCreate, SourcePatch, SubmitText, UrlCheck
from app.security.auth import AuthUser, require_admin, require_staff
from app.security.url_guard import validate_fetch_url, validate_url_syntax
from app.services.container import Services
from app.services.ingestion.errors import ExtractionError, FetchError, IngestionError
from app.services.intake import file_error

router = APIRouter(prefix="/api/v1/admin", tags=["admin: sources"])


def job_view(store, j: dict, source_title: str | None = None) -> dict:  # type: ignore[no-untyped-def,type-arg]
    if source_title is None:
        s = get_one(store, "knowledge_sources", id=j["source_id"])
        source_title = s["title"] if s else None
    payload = j.get("payload") or {}
    return dict(
        id=j["id"], source_id=j["source_id"], source_title=source_title, status=j["status"], trigger=j["trigger"],
        job_type=j.get("job_type", "ingest"), outcome=j.get("outcome"), document_id=j.get("document_id"),
        version_id=j.get("version_id"), error_code=j.get("error_code"), error_message=j.get("error_message"),
        statistics=j.get("statistics") or {}, attempts=j.get("attempts", 0), max_attempts=j.get("max_attempts", 3),
        file=({k: payload.get(k) for k in ("filename", "mime_type", "size")} if payload.get("filename") else None),
        created_at=j["created_at"], started_at=j.get("started_at"), completed_at=j.get("completed_at"),
        heartbeat_at=j.get("heartbeat_at"))


def _ingest_error(exc: IngestionError | FetchError | ExtractionError) -> AppError:
    status = 422 if exc.code in ("invalid_board_url", "url_not_allowed", "empty_extraction", "needs_ocr",
                                 "board_structure_changed") else 502
    blocked = exc.code in ("robots_disallowed", "http_401", "http_403", "http_406", "http_429")
    return AppError(exc.message, code=exc.code, status_code=409 if blocked else status,
                    details={"blocked": blocked, "manual_import_available": True})


# ------------------------------------------------------------------- sources
@router.get("/sources")
def list_sources(status: str | None = None, source_type: str | None = None, category: str | None = None,
                 q: str | None = Query(None, max_length=200), active: bool | None = None,
                 sort: Literal["title", "organization", "created_at", "updated_at", "last_checked_at", "last_success_at",
                               "status", "category", "source_type"] = "created_at",
                 order: Literal["asc", "desc"] = "desc",
                 pg: Pagination = Depends(), svc: Services = Depends(get_services),
                 user: AuthUser = Depends(require_staff)) -> dict:  # type: ignore[type-arg]
    """Admins see every source; supporters see only the sources they created."""
    items, total = svc.sources.list(status=status, source_type=source_type, q=q, page=pg.page, size=pg.page_size,
                                    category=category, sort=sort, desc=order == "desc", active=active,
                                    mine=user.id if user.role == "supporter" else None)
    return pg.wrap(items, total)


@router.post("/sources", status_code=201)
def create_source(body: SourceCreate, svc: Services = Depends(get_services),
                  user: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    data = body.model_dump()
    if data.get("config") is not None:
        data["config"] = dict(data["config"])
    src = svc.sources.create(data, user.id)
    svc.store.insert("audit_log", dict(action="source.create", entity_type="knowledge_source", entity_id=src["id"],
                                       actor_id=user.id, details={"source_type": src["source_type"],
                                                                  "url": src.get("original_url")}))
    return svc.sources.view(src)


@router.post("/sources/validate-url", dependencies=[Depends(rate_limit("ingest"))])
def validate_url(body: UrlCheck, svc: Services = Depends(get_services),
                 _: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    """Syntax + allowlist, DNS (public addresses only) and robots.txt checks. Nothing is stored."""
    checks: list[dict] = []  # type: ignore[type-arg]
    ok = True
    allowed = svc.domains.domains()
    try:
        validate_url_syntax(body.url, allowed)
        checks.append(dict(name="allowlist", ok=True, message="http(s) URL on the trusted-domain allowlist."))
    except UrlNotAllowed as exc:
        checks.append(dict(name="allowlist", ok=False, message=exc.message))
        return dict(ok=False, url=body.url, checks=checks, allowed_domains=allowed)
    try:
        validate_fetch_url(body.url, allowed, svc.ingestion.fetcher.resolver)
        checks.append(dict(name="network", ok=True, message="Host resolves to public addresses only."))
    except UrlNotAllowed as exc:
        checks.append(dict(name="network", ok=False, message=exc.message))
        ok = False
    if ok:
        allowed_robots, msg = svc.ingestion.fetcher.check_robots(body.url)
        checks.append(dict(name="robots", ok=allowed_robots is True, message=msg))
        ok = allowed_robots is True
    if body.source_type == "sch_board":
        from app.services.ingestion.sch_board import is_sch_board_url

        good = is_sch_board_url(body.url)
        checks.append(dict(name="board", ok=good, message="SCH notice board URL." if good else
                           "Notice-board sources must be an SCH notice01.php list page."))
        ok = ok and good
    dup = get_one(svc.store, "knowledge_sources", original_url=body.url)
    if dup:
        checks.append(dict(name="duplicate", ok=False, message=f"Already registered as '{dup['title']}'.",
                           source_id=dup["id"]))
        ok = False
    return dict(ok=ok, url=body.url, checks=checks)


@router.post("/sources/preview", dependencies=[Depends(rate_limit("ingest"))])
def preview_url(body: UrlCheck, svc: Services = Depends(get_services),
                _: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    """Fetch + extract and return what would be stored. Nothing is saved."""
    try:
        validate_url_syntax(body.url, svc.domains.domains())
        return svc.ingestion.preview_url(body.url, body.source_type, body.language)
    except (FetchError, ExtractionError, IngestionError) as exc:
        raise _ingest_error(exc) from exc


@router.get("/sources/{source_id}")
def get_source(source_id: str, svc: Services = Depends(get_services),
               user: AuthUser = Depends(require_staff)) -> dict:  # type: ignore[type-arg]
    out = svc.sources.detail(source_id)
    if user.role == "supporter" and out.get("created_by") != user.id:
        raise Forbidden("Supporters can only view sources they created.")
    return out


@router.get("/sources/{source_id}/history")
def source_history(source_id: str, svc: Services = Depends(get_services),
                   _: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    src = svc.sources.get(source_id)
    jobs, _c = svc.store.select("ingestion_jobs", DbQuery(eq={"source_id": source_id}, order=[("created_at", True)],
                                                          limit=50))
    audit, _c = svc.store.select("audit_log", DbQuery(eq={"entity_id": source_id}, order=[("created_at", True)], limit=50))
    return dict(jobs=[job_view(svc.store, j, src["title"]) for j in jobs],
                audit=[dict(id=a["id"], action=a["action"], actor_id=a.get("actor_id"), details=a.get("details") or {},
                            created_at=a["created_at"]) for a in audit])


@router.patch("/sources/{source_id}")
def patch_source(source_id: str, body: SourcePatch, svc: Services = Depends(get_services),
                 user: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    patch = body.model_dump(exclude_unset=True)
    if patch.get("config") is not None:
        patch["config"] = dict(patch["config"])
    updated = svc.sources.patch(source_id, patch)
    svc.store.insert("audit_log", dict(action="source.update", entity_type="knowledge_source", entity_id=source_id,
                                       actor_id=user.id, details={"fields": sorted(patch)}))
    return svc.sources.view(updated)


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
    """Queue a fetch job for a website or notice-board source and return its id immediately (never blocks)."""
    source = svc.sources.get(source_id)
    svc.ingestion.require_fetchable(source)
    if svc.ingestion.has_open_job(source_id):
        raise InvalidState("A job for this source is already queued or running.")
    job = svc.ingestion.create_job(source, "manual", user.id)
    svc.store.update("knowledge_sources", {"status": "fetching"}, {"id": source_id})
    svc.jobs.enqueue(job, background)
    return dict(job_id=job["id"], status="queued")


@router.post("/sources/{source_id}/upload", status_code=202, dependencies=[Depends(rate_limit("ingest"))])
def upload_file(source_id: str, background: BackgroundTasks, file: UploadFile = File(...),
                svc: Services = Depends(get_services), user: AuthUser = Depends(require_staff)) -> dict:  # type: ignore[type-arg]
    """New file version for an existing pdf / docx / text_file source."""
    source = svc.sources.get(source_id)
    if source["source_type"] not in ("pdf", "docx", "text_file"):
        raise InvalidState("Uploads are accepted for pdf, docx and text_file sources (use the screenshot intake for images).")
    data = file.file.read(svc.settings.max_upload_bytes + 1)
    try:
        out = svc.intake.upload_document(data=data, filename=file.filename, content_type=file.content_type, actor=user,
                                         source_id=source_id)
    except ExtractionError as exc:
        raise file_error(exc) from exc
    svc.jobs.enqueue(out["job"], background)
    return dict(job_id=out["job"]["id"], status="queued")


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
                                    source_published_at=body.source_published_at, external_id=body.external_id,
                                    raw_text=body.text if source["source_type"] == "kakao_message" else None)
    return job_view(svc.store, job, source["title"])


# ---------------------------------------------------------------------- jobs
@router.get("/ingestion-jobs")
def list_jobs(source_id: str | None = None, status: str | None = None, job_type: str | None = None,
              pg: Pagination = Depends(), svc: Services = Depends(get_services),
              _: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    eq = {k: v for k, v in (("source_id", source_id), ("status", status), ("job_type", job_type)) if v}
    rows, total = svc.store.select("ingestion_jobs", DbQuery(eq=eq, order=[("created_at", True)], limit=pg.page_size,
                                                            offset=(pg.page - 1) * pg.page_size), count=True)
    titles = {k: v["title"] for k, v in get_many(svc.store, "knowledge_sources", [r["source_id"] for r in rows]).items()}
    return pg.wrap([job_view(svc.store, r, titles.get(r["source_id"])) for r in rows], total or 0)


@router.get("/ingestion-jobs/{job_id}")
def get_job(job_id: str, svc: Services = Depends(get_services), user: AuthUser = Depends(require_staff)) -> dict:  # type: ignore[type-arg]
    j = get_one(svc.store, "ingestion_jobs", id=job_id)
    if j is None:
        raise NotFound("Job not found.")
    if user.role == "supporter" and j.get("requested_by") != user.id:
        raise Forbidden("Supporters can only view their own jobs.")
    return job_view(svc.store, j)


@router.get("/ingestion-jobs/{job_id}/events")
def job_events(job_id: str, svc: Services = Depends(get_services), user: AuthUser = Depends(require_staff)) -> dict:  # type: ignore[type-arg]
    j = get_one(svc.store, "ingestion_jobs", id=job_id)
    if j is None:
        raise NotFound("Job not found.")
    if user.role == "supporter" and j.get("requested_by") != user.id:
        raise Forbidden("Supporters can only view their own jobs.")
    rows, _c = svc.store.select("ingestion_events", DbQuery(eq={"job_id": job_id}, order=[("id", False)], limit=500))
    return {"items": [dict(id=r["id"], level=r["level"], step=r["step"], message=r["message"], data=r.get("data") or {},
                           created_at=r["created_at"]) for r in rows]}


@router.post("/ingestion-jobs/{job_id}/retry", status_code=202, dependencies=[Depends(rate_limit("ingest"))])
def retry_job(job_id: str, background: BackgroundTasks, svc: Services = Depends(get_services),
              user: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    j = get_one(svc.store, "ingestion_jobs", id=job_id)
    if j is None:
        raise NotFound("Job not found.")
    if j["status"] != "failed" and j.get("job_type") != "ocr_intake":
        raise InvalidState("Only failed jobs can be retried.")
    source = svc.sources.get(j["source_id"])
    if j.get("job_type") == "index_version":
        v = svc.review.check_approvable((j.get("payload") or {}).get("version_id", ""))
        # keep the original approver (the decision was theirs); the retry itself is audited by the job row
        new = svc.ingestion.request_activation(v, j.get("requested_by") or user.id, (j.get("payload") or {}).get("note"))
        svc.jobs.enqueue(new, background)
        return dict(job_id=new["id"], status=new["status"])
    if j.get("job_type") == "ocr_intake":
        out = svc.intake.retry_ocr(job_id, user)
        return dict(job_id=out["job"]["id"], status=out["job"]["status"])
    if source["source_type"] in ("website", "sch_board"):
        svc.ingestion.require_fetchable(source)
        payload: dict = {}  # type: ignore[type-arg]
    elif source["source_type"] in ("pdf", "docx", "text_file"):
        payload = j.get("payload") or {}
        if not payload.get("storage_path"):
            raise InvalidState("This job has no stored file to retry; upload the file again.")
    else:
        raise InvalidState("Text submissions cannot be retried; submit the text again.")
    if svc.ingestion.has_open_job(source["id"]):
        raise InvalidState("A job for this source is already queued or running.")
    new = svc.ingestion.create_job(source, "retry", user.id, payload=payload, job_type=j.get("job_type"))
    svc.jobs.enqueue(new, background)
    return dict(job_id=new["id"], status="queued")
