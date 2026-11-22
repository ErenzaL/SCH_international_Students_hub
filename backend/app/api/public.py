from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import Pagination, get_services
from app.core.config import Settings, get_settings
from app.core.constants import CATEGORIES, CATEGORY_SLUGS
from app.core.errors import ValidationFailed
from app.core.rate_limit import rate_limit
from app.schemas.api import SearchRequest
from app.security.auth import AuthUser, get_current_user
from app.services.container import Services

router = APIRouter(prefix="/api/v1", tags=["public"], dependencies=[Depends(rate_limit("public"))])


def _check_category(category: str | None) -> None:
    if category and category not in CATEGORY_SLUGS:
        raise ValidationFailed(f"Unknown category '{category}'.", details=list(CATEGORY_SLUGS))


@router.get("/categories")
def categories(request: Request) -> dict:  # type: ignore[type-arg]
    """Static category list; counts come from the database when Supabase is configured (else null)."""
    svc: Services | None = getattr(request.app.state, "services", None)
    if svc is None:
        return {"items": [dict(slug=s, name=n, description=d, sort_order=o, document_count=None,
                               announcement_count=None) for s, n, d, o in CATEGORIES]}
    return {"items": svc.public.categories(with_counts=True)}


@router.get("/announcements")
def list_announcements(
    q: str | None = Query(None, max_length=200), category: str | None = None,
    language: Literal["ko", "en", "id", "vi", "zh-CN"] | None = None,
    status: Literal["active", "upcoming", "expired"] | None = None,
    pg: Pagination = Depends(), svc: Services = Depends(get_services),
) -> dict:  # type: ignore[type-arg]
    _check_category(category)
    items, total = svc.public.list_announcements(q=q, category=category, language=language, status=status,
                                                 page=pg.page, size=pg.page_size)
    return pg.wrap(items, total)


@router.get("/announcements/{announcement_id}")
def get_announcement(announcement_id: str, svc: Services = Depends(get_services)) -> dict:  # type: ignore[type-arg]
    return svc.public.get_announcement(announcement_id)


@router.get("/assistant/status")
def assistant_status(request: Request, settings: Settings = Depends(get_settings)) -> dict:  # type: ignore[type-arg]
    svc: Services | None = getattr(request.app.state, "services", None)
    if svc is None:
        return dict(answer_generation="disabled", retrieval="unavailable",
                    reason="Supabase is not configured on the backend.")
    return dict(answer_generation="enabled" if svc.llm.enabled else "disabled", retrieval="available", reason=None)


@router.post("/knowledge/search", dependencies=[Depends(rate_limit("search"))])
def search_knowledge(body: SearchRequest, svc: Services = Depends(get_services)) -> dict:  # type: ignore[type-arg]
    """Hybrid (vector + keyword, RRF) search over approved, currently applicable content only."""
    return svc.retrieval.search(body.query, language=body.language, category=body.category, top_k=body.top_k,
                                mode=body.mode, scope=body.scope, authority=body.authority)


@router.get("/knowledge/documents")
def list_documents(
    q: str | None = Query(None, max_length=200), category: str | None = None,
    scope: Literal["university", "national"] | None = None,
    authority: Literal["official_university", "official_government", "staff_communication", "other"] | None = None,
    pg: Pagination = Depends(), svc: Services = Depends(get_services),
) -> dict:  # type: ignore[type-arg]
    _check_category(category)
    items, total = svc.public.list_documents(q=q, category=category, scope=scope, page=pg.page, size=pg.page_size,
                                             authority=authority)
    return pg.wrap(items, total)


@router.get("/knowledge/documents/{document_id}")
def get_document(document_id: str, svc: Services = Depends(get_services)) -> dict:  # type: ignore[type-arg]
    return svc.public.get_document(document_id)


@router.get("/me", tags=["auth"])
def me(user: AuthUser = Depends(get_current_user)) -> dict:  # type: ignore[type-arg]
    return dict(id=user.id, email=user.email, display_name=user.display_name, role=user.role,
                preferred_language=user.preferred_language, languages=user.languages, is_staff=user.is_staff,
                preferred_language_confirmed=user.preferred_language_confirmed,
                language_permissions=user.perms)
