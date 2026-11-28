from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Query

from app.api.deps import Pagination, get_services
from app.schemas.api import (
    AnnouncementCreate,
    AnnouncementPatch,
    Lang,
    NoteBody,
    ReasonBody,
    TranslationApprove,
    TranslationBackfill,
    TranslationTargets,
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
    out = svc.announcements.update(announcement_id, body.model_dump(exclude_unset=True), user)
    svc.translations.mark_outdated(announcement_id, user)  # translations of the old text need re-review
    return out


@router.post("/announcements/{announcement_id}/submit")
def submit_announcement(announcement_id: str, svc: Services = Depends(get_services),
                        user: AuthUser = Depends(require_staff)) -> dict:  # type: ignore[type-arg]
    return svc.announcements.submit(announcement_id, user)


@router.post("/announcements/{announcement_id}/approve")
def approve_announcement(announcement_id: str, background: BackgroundTasks, body: NoteBody | None = None,
                         svc: Services = Depends(get_services),
                         user: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    out = svc.announcements.approve(announcement_id, user, body.note if body else None)
    # per-language tasks + team notifications; machine translations (if enabled) run after the response
    svc.translations.on_original_published(announcement_id, user, background)
    return out


@router.post("/announcements/{announcement_id}/reject")
def reject_announcement(announcement_id: str, body: ReasonBody, svc: Services = Depends(get_services),
                        user: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    return svc.announcements.reject(announcement_id, user, body.reason)


@router.post("/announcements/{announcement_id}/cancel")
def cancel_announcement(announcement_id: str, body: ReasonBody, svc: Services = Depends(get_services),
                        user: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    return svc.announcements.cancel(announcement_id, user, body.reason)


@router.put("/announcements/{announcement_id}/translation-targets")
def set_translation_targets(announcement_id: str, body: TranslationTargets, background: BackgroundTasks,
                            svc: Services = Depends(get_services),
                            user: AuthUser = Depends(require_staff)) -> dict:  # type: ignore[type-arg]
    """Choose the machine-translation languages (ko / en / id, never the original). Saved with the announcement and
    used when it is approved; for a published announcement the missing drafts of these languages are queued now
    (approved, current translations and a reviewer's work are never replaced)."""
    out = svc.announcements.set_translation_targets(announcement_id, body.languages, user)
    queued: list[dict] = []  # type: ignore[type-arg]
    if out["publication_status"] == "published":
        queued = svc.announcement_translator.on_published(announcement_id, user.id, background)
    return out | {"queued": [dict(job_id=j["id"], language=(j.get("payload") or {}).get("language"),
                                  status=j["status"]) for j in queued]}


@router.get("/announcements/{announcement_id}/history")
def announcement_history(announcement_id: str, svc: Services = Depends(get_services),
                         user: AuthUser = Depends(require_staff)) -> dict:  # type: ignore[type-arg]
    return {"items": svc.announcements.history(announcement_id, user)}


def _flat(detail: dict) -> dict:  # type: ignore[type-arg]
    """Translation fields at the top level (Phase 1 shape) + original / revisions / permissions."""
    return {**(detail.get("translation") or {}), "original": detail["original"], "revisions": detail["revisions"],
            "permissions": detail["permissions"], "language": detail["language"], "machine": detail.get("machine")}


@router.get("/announcements/{announcement_id}/translations/{language}")
def get_translation(announcement_id: str, language: Lang, svc: Services = Depends(get_services),
                    user: AuthUser = Depends(require_staff)) -> dict:  # type: ignore[type-arg]
    """Original + translation side by side, revision history and the caller's permissions for the language."""
    return svc.translations.detail(announcement_id, language, user)


@router.put("/announcements/{announcement_id}/translations/{language}")
def save_translation(announcement_id: str, language: Lang, body: TranslationUpsert,
                     svc: Services = Depends(get_services), user: AuthUser = Depends(require_staff)) -> dict:  # type: ignore[type-arg]
    """Save a draft (translation_status=machine_draft) or submit it for review (in_review)."""
    return _flat(svc.translations.save(announcement_id, language, body.model_dump(), user))


@router.post("/announcements/{announcement_id}/translations/{language}/approve")
def approve_translation(announcement_id: str, language: Lang, body: TranslationApprove,
                        svc: Services = Depends(get_services), user: AuthUser = Depends(require_staff)) -> dict:  # type: ignore[type-arg]
    """Reviewer approval = publication for this language. Requires original_verified=true."""
    return _flat(svc.translations.approve(announcement_id, language, user, body.original_verified, body.note))


@router.post("/announcements/{announcement_id}/translations/{language}/reject")
def reject_translation(announcement_id: str, language: Lang, body: ReasonBody, svc: Services = Depends(get_services),
                       user: AuthUser = Depends(require_staff)) -> dict:  # type: ignore[type-arg]
    return _flat(svc.translations.reject(announcement_id, language, user, body.reason))


@router.post("/announcements/{announcement_id}/translations/{language}/request-changes")
def request_translation_changes(announcement_id: str, language: Lang, body: ReasonBody,
                                svc: Services = Depends(get_services), user: AuthUser = Depends(require_staff)) -> dict:  # type: ignore[type-arg]
    return _flat(svc.translations.request_changes(announcement_id, language, user, body.reason))


@router.post("/announcements/{announcement_id}/translations/{language}/machine-translate", status_code=202)
def machine_translate(announcement_id: str, language: Lang, background: BackgroundTasks, force: bool = False,
                      svc: Services = Depends(get_services), user: AuthUser = Depends(require_staff)) -> dict:  # type: ignore[type-arg]
    """Queue (or retry) the machine translation of a published announcement for one language. ``force`` replaces
    a person's draft and needs the review permission for the language."""
    from app.core.errors import Forbidden

    perms = svc.translations.permissions(user, language)
    if not (perms["can_edit"] or perms["can_review"] or user.role in ("admin", "super_admin")):
        raise Forbidden("You are not assigned to translations in this language.")
    if force and not (perms["can_review"] or user.role == "super_admin"):
        raise Forbidden("Replacing a person's translation needs the review permission for this language.")
    job = svc.announcement_translator.queue(announcement_id, language, user.id, force=force, background=background)
    return dict(job_id=job["id"], status=job["status"])


@router.get("/announcements/{announcement_id}/translations/{language}/share-text")
def translation_share_text(announcement_id: str, language: Lang, svc: Services = Depends(get_services),
                           user: AuthUser = Depends(require_staff)) -> dict:  # type: ignore[type-arg]
    """Approved translation formatted for posting in the language's KakaoTalk group (copy-paste; nothing is sent)."""
    return svc.translations.share_text(announcement_id, language, user)


@router.post("/translations/backfill")
def backfill_translations(body: TranslationBackfill, svc: Services = Depends(get_services),
                          user: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    """Missing / outdated machine drafts of PUBLISHED announcements: ``dry_run`` lists them; otherwise at most ``limit``
    jobs are queued (oldest first). Approved current translations, a reviewer's work and translations made from the
    same text (content hash) are skipped, so repeating it queues nothing twice."""
    return svc.announcement_translator.backfill(user.id, languages=body.languages, limit=body.limit,
                                                dry_run=body.dry_run)


@router.get("/translations")
def list_translations(status: str | None = None, language: Lang | None = None, outdated: bool | None = None,
                      pg: Pagination = Depends(), svc: Services = Depends(get_services),
                      user: AuthUser = Depends(require_staff)) -> dict:  # type: ignore[type-arg]
    """Translation tasks in the caller's assigned languages only."""
    items, total = svc.translations.tasks(user, status, language, outdated, pg.page, pg.page_size)
    return pg.wrap(items, total)
