"""'Add knowledge' intake: document upload, screenshot OCR, pasted staff announcements (admins + supporters)."""
from __future__ import annotations

import json

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, UploadFile
from fastapi.responses import Response
from pydantic import ValidationError

from app.api.admin_sources import job_view
from app.api.deps import Pagination, get_services
from app.core.errors import ValidationFailed
from app.core.rate_limit import rate_limit
from app.repositories.base import Query as DbQuery
from app.repositories.base import get_many
from app.schemas.api import AnnouncementPaste, ScreenshotSubmit, SourceMeta
from app.security.auth import AuthUser, require_staff
from app.services.container import Services

router = APIRouter(prefix="/api/v1/admin/intake", tags=["admin: intake"])


def _meta(raw: str | None) -> dict | None:  # type: ignore[type-arg]
    if not raw:
        return None
    try:
        return SourceMeta.model_validate(json.loads(raw)).model_dump()
    except (ValueError, ValidationError) as exc:
        details = exc.errors() if isinstance(exc, ValidationError) else None
        raise ValidationFailed("Invalid source details (metadata).", details=details) from exc


@router.get("/ocr-status")
def ocr_status(svc: Services = Depends(get_services), _: AuthUser = Depends(require_staff)) -> dict:  # type: ignore[type-arg]
    return svc.intake.ocr_status()


@router.post("/document", status_code=202, dependencies=[Depends(rate_limit("ingest"))])
def upload_document(background: BackgroundTasks, file: UploadFile = File(...), metadata: str | None = Form(None),
                    source_id: str | None = Form(None), svc: Services = Depends(get_services),
                    user: AuthUser = Depends(require_staff)) -> dict:  # type: ignore[type-arg]
    """PDF / DOCX / TXT / Markdown. ``metadata`` (JSON) creates a new source; ``source_id`` adds a new version."""
    data = file.file.read(svc.settings.max_upload_bytes + 1)
    out = svc.intake.upload_document(data=data, filename=file.filename, content_type=file.content_type, actor=user,
                                     source_id=source_id, meta=_meta(metadata))
    svc.jobs.enqueue(out["job"], background)
    return dict(source=svc.sources.view(out["source"]), job_id=out["job"]["id"], status="queued")


@router.post("/screenshot", status_code=201, dependencies=[Depends(rate_limit("ingest"))])
def upload_screenshot(file: UploadFile = File(...), metadata: str | None = Form(None), source_id: str | None = Form(None),
                      authorized_for_distribution: bool = Form(False), svc: Services = Depends(get_services),
                      user: AuthUser = Depends(require_staff)) -> dict:  # type: ignore[type-arg]
    """Store the screenshot privately and return OCR text for correction. No document version is created yet."""
    data = file.file.read(svc.settings.max_image_bytes + 1)
    out = svc.intake.screenshot_extract(data=data, filename=file.filename, content_type=file.content_type, actor=user,
                                        source_id=source_id, meta=_meta(metadata), authorized=authorized_for_distribution)
    return dict(source=svc.sources.view(out["source"]), job=job_view(svc.store, out["job"], out["source"]["title"]),
                ocr=out["ocr"], detected=out["detected"], image=out["image"])


@router.get("/screenshot/{job_id}")
def get_screenshot_intake(job_id: str, svc: Services = Depends(get_services),
                          user: AuthUser = Depends(require_staff)) -> dict:  # type: ignore[type-arg]
    out = svc.intake.screenshot_intake(job_id, user)
    return dict(job=job_view(svc.store, out["job"]), ocr=out["ocr"], detected=out["detected"], image=out["image"])


@router.get("/screenshot/{job_id}/image")
def screenshot_image(job_id: str, svc: Services = Depends(get_services),
                     user: AuthUser = Depends(require_staff)) -> Response:
    """The stored original image, streamed through the API (the private bucket is never exposed)."""
    data, mime, name = svc.intake.screenshot_image(job_id, user)
    return Response(data, media_type=mime, headers={"Content-Disposition": f'inline; filename="{name}"',
                                                     "X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"})


@router.post("/screenshot/{job_id}/retry-ocr", dependencies=[Depends(rate_limit("ingest"))])
def retry_screenshot_ocr(job_id: str, svc: Services = Depends(get_services),
                         user: AuthUser = Depends(require_staff)) -> dict:  # type: ignore[type-arg]
    out = svc.intake.retry_ocr(job_id, user)
    return dict(job=job_view(svc.store, out["job"]), ocr=out["ocr"], detected=out["detected"], image=out["image"])


@router.post("/screenshot/{job_id}/submit", status_code=201, dependencies=[Depends(rate_limit("ingest"))])
def submit_screenshot(job_id: str, body: ScreenshotSubmit, svc: Services = Depends(get_services),
                      user: AuthUser = Depends(require_staff)) -> dict:  # type: ignore[type-arg]
    """Create a draft (or pending) version from the corrected text. The raw OCR text is kept as evidence."""
    job = svc.intake.screenshot_submit(job_id, title=body.title, text=body.text, actor=user, submit=body.submit,
                                       redact=body.redact_personal_info, fields=body.fields,
                                       source_published_at=body.source_published_at)
    return job_view(svc.store, job)


@router.post("/announcement", status_code=201, dependencies=[Depends(rate_limit("ingest"))])
def paste_announcement(body: AnnouncementPaste, svc: Services = Depends(get_services),
                       user: AuthUser = Depends(require_staff)) -> dict:  # type: ignore[type-arg]
    """Pasted staff announcement (e.g. from KakaoTalk). Saved as draft unless ``submit`` is true."""
    job = svc.intake.paste_announcement(body.model_dump(), user)
    return job_view(svc.store, job)


@router.get("/mine")
def my_submissions(pg: Pagination = Depends(), svc: Services = Depends(get_services),
                   user: AuthUser = Depends(require_staff)) -> dict:  # type: ignore[type-arg]
    """Versions the caller created (drafts, pending, reviewed) so supporters can follow their submissions."""
    rows, total = svc.store.select("document_versions", DbQuery(
        eq={"created_by": user.id}, order=[("created_at", True)], limit=pg.page_size, offset=(pg.page - 1) * pg.page_size,
        cols="id,document_id,version_number,verification_status,review_note,created_at,submitted_at,approved_at,"
             "rejected_reason,indexing_status"), count=True)
    docs = get_many(svc.store, "source_documents", [r["document_id"] for r in rows])
    return pg.wrap([{**r, "document_title": (docs.get(r["document_id"]) or {}).get("title")} for r in rows], total or 0)
