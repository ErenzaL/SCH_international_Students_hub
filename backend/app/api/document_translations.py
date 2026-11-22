"""Admin / Global Supporter API for knowledge-document translations (migration 0011).

Access is language-scoped in the service (and approval again in the database trigger): a supporter only sees and
edits the languages assigned to them; approve / reject / request changes need the language's review permission.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends

from app.api.deps import Pagination, get_services
from app.schemas.api import (
    DocLanguage,
    DocTranslationDraftRequest,
    DocTranslationSave,
    Lang,
    ReasonBody,
    TranslationApprove,
)
from app.security.auth import AuthUser, require_admin, require_staff
from app.services.container import Services

router = APIRouter(prefix="/api/v1/admin", tags=["admin: document translations"])

DocStatus = Literal["todo", "machine_draft", "draft", "in_review", "changes_requested", "human_approved", "rejected"]


@router.get("/documents/{document_id}/translations")
def translations_overview(document_id: str, svc: Services = Depends(get_services),
                          user: AuthUser = Depends(require_staff)) -> dict:  # type: ignore[type-arg]
    """Per-language status for the document's current approved version (Admin → Documents → Translations)."""
    return svc.doc_translations.overview(document_id, user)


@router.post("/documents/{document_id}/translations/drafts", status_code=202)
def generate_drafts(document_id: str, body: DocTranslationDraftRequest, background: BackgroundTasks,
                    svc: Services = Depends(get_services), user: AuthUser = Depends(require_staff)) -> dict:  # type: ignore[type-arg]
    """Queue durable AI draft jobs (one per language). Drafts are never shown as verified."""
    return {"items": svc.doc_translations.request_drafts(document_id, list(body.languages), user, background,
                                                         force=body.force)}


@router.get("/documents/{document_id}/translations/{language}")
def get_doc_translation(document_id: str, language: Lang, svc: Services = Depends(get_services),
                        user: AuthUser = Depends(require_staff)) -> dict:  # type: ignore[type-arg]
    """Original (current approved version) + translation side by side, previous version, revisions, permissions."""
    return svc.doc_translations.detail(document_id, language, user)


@router.put("/documents/{document_id}/translations/{language}")
def save_doc_translation(document_id: str, language: Lang, body: DocTranslationSave,
                         svc: Services = Depends(get_services), user: AuthUser = Depends(require_staff)) -> dict:  # type: ignore[type-arg]
    return svc.doc_translations.save(document_id, language, body.model_dump(), user)


@router.post("/documents/{document_id}/translations/{language}/approve")
def approve_doc_translation(document_id: str, language: Lang, body: TranslationApprove,
                            svc: Services = Depends(get_services), user: AuthUser = Depends(require_staff)) -> dict:  # type: ignore[type-arg]
    return svc.doc_translations.approve(document_id, language, user, body.original_verified, body.note)


@router.post("/documents/{document_id}/translations/{language}/reject")
def reject_doc_translation(document_id: str, language: Lang, body: ReasonBody, svc: Services = Depends(get_services),
                           user: AuthUser = Depends(require_staff)) -> dict:  # type: ignore[type-arg]
    return svc.doc_translations.reject(document_id, language, user, body.reason)


@router.post("/documents/{document_id}/translations/{language}/request-changes")
def request_doc_translation_changes(document_id: str, language: Lang, body: ReasonBody,
                                    svc: Services = Depends(get_services),
                                    user: AuthUser = Depends(require_staff)) -> dict:  # type: ignore[type-arg]
    return svc.doc_translations.request_changes(document_id, language, user, body.reason)


@router.patch("/documents/{document_id}/language")
def set_document_language(document_id: str, body: DocLanguage, svc: Services = Depends(get_services),
                          user: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    """Correct the ORIGINAL language label (the text is unchanged); translation tasks are adjusted."""
    return svc.doc_translations.set_original_language(document_id, body.language, user)


@router.get("/document-translations")
def list_doc_translations(status: DocStatus | None = None, language: Lang | None = None, outdated: bool | None = None,
                          pg: Pagination = Depends(), svc: Services = Depends(get_services),
                          user: AuthUser = Depends(require_staff)) -> dict:  # type: ignore[type-arg]
    """Knowledge-document translation tasks in the caller's assigned languages only."""
    items, total = svc.doc_translations.tasks(user, status=status, language=language, outdated=outdated,
                                              page=pg.page, size=pg.page_size)
    return pg.wrap(items, total)
