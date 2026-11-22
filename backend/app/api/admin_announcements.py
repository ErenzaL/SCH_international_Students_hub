from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import Pagination, get_services
from app.schemas.api import (
    AnnouncementCreate,
    AnnouncementPatch,
    Lang,
    NoteBody,
    ReasonBody,
    TranslationUpsert,
)
from app.security.auth import AuthUser, require_admin, require_staff
from app.services.container import Services

router = APIRouter(prefix="/api/v1/admin", tags=["admin: announcements"])


@router.get("/announcements")
def list_announcements(status: str | None = None, q: str | None = Query(None, max_length=200),
                       pg: Pagination = Depends(), svc: Services = Depends(get_services),
                       user: AuthUser = Depends(require_staff)) -> dict:  # type: ignore[type-arg]
    items, total = svc.announcements.list_admin(user, status, q, pg.page, pg.page_size)
    return pg.wrap(items, total)


@router.post("/announcements", status_code=201)
def create_announcement(body: AnnouncementCreate, svc: Services = Depends(get_services),
                        user: AuthUser = Depends(require_staff)) -> dict:  # type: ignore[type-arg]
    return svc.announcements.create(body.model_dump(), user)


@router.get("/announcements/{announcement_id}")
def get_announcement(announcement_id: str, svc: Services = Depends(get_services),
                     user: AuthUser = Depends(require_staff)) -> dict:  # type: ignore[type-arg]
    return svc.announcements.get_admin(announcement_id, user)


@router.patch("/announcements/{announcement_id}")
def patch_announcement(announcement_id: str, body: AnnouncementPatch, svc: Services = Depends(get_services),
                       user: AuthUser = Depends(require_staff)) -> dict:  # type: ignore[type-arg]
    return svc.announcements.update(announcement_id, body.model_dump(exclude_unset=True), user)


@router.post("/announcements/{announcement_id}/submit")
def submit_announcement(announcement_id: str, svc: Services = Depends(get_services),
                        user: AuthUser = Depends(require_staff)) -> dict:  # type: ignore[type-arg]
    return svc.announcements.submit(announcement_id, user)


@router.post("/announcements/{announcement_id}/approve")
def approve_announcement(announcement_id: str, body: NoteBody | None = None, svc: Services = Depends(get_services),
                         user: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    return svc.announcements.approve(announcement_id, user, body.note if body else None)


@router.post("/announcements/{announcement_id}/reject")
def reject_announcement(announcement_id: str, body: ReasonBody, svc: Services = Depends(get_services),
                        user: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    return svc.announcements.reject(announcement_id, user, body.reason)


@router.post("/announcements/{announcement_id}/cancel")
def cancel_announcement(announcement_id: str, body: ReasonBody, svc: Services = Depends(get_services),
                        user: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    return svc.announcements.cancel(announcement_id, user, body.reason)


@router.get("/announcements/{announcement_id}/history")
def announcement_history(announcement_id: str, svc: Services = Depends(get_services),
                         user: AuthUser = Depends(require_staff)) -> dict:  # type: ignore[type-arg]
    return {"items": svc.announcements.history(announcement_id, user)}


@router.put("/announcements/{announcement_id}/translations/{language}")
def save_translation(announcement_id: str, language: Lang, body: TranslationUpsert,
                     svc: Services = Depends(get_services), user: AuthUser = Depends(require_staff)) -> dict:  # type: ignore[type-arg]
    return svc.announcements.upsert_translation(announcement_id, language, body.model_dump(), user)


@router.post("/announcements/{announcement_id}/translations/{language}/approve")
def approve_translation(announcement_id: str, language: Lang, svc: Services = Depends(get_services),
                        user: AuthUser = Depends(require_staff)) -> dict:  # type: ignore[type-arg]
    return svc.announcements.approve_translation(announcement_id, language, user)


@router.get("/translations")
def list_translations(status: str | None = None, language: Lang | None = None, pg: Pagination = Depends(),
                      svc: Services = Depends(get_services), user: AuthUser = Depends(require_staff)) -> dict:  # type: ignore[type-arg]
    items, total = svc.announcements.list_translations(user, status, language, pg.page, pg.page_size)
    return pg.wrap(items, total)
