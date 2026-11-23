from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response

from app.api.deps import Pagination, get_services
from app.core.config import Settings, get_settings
from app.core.constants import CATEGORIES, CATEGORY_SLUGS
from app.core.errors import ValidationFailed
from app.core.rate_limit import rate_limit
from app.schemas.api import Lang, SearchRequest
from app.security.auth import AuthUser, get_current_user
from app.services.container import Services

TARGET_LANGS = ("ko", "en", "id", "vi", "zh-CN")

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
    display_language: Lang | None = None,
    pg: Pagination = Depends(), svc: Services = Depends(get_services),
) -> dict:  # type: ignore[type-arg]
    """``display_language``: titles in that language where a translation students may see exists
    (``display_title`` + ``display_title_status`` verified | machine); originals otherwise."""
    _check_category(category)
    items, total = svc.public.list_announcements(q=q, category=category, language=language, status=status,
                                                 page=pg.page, size=pg.page_size, display_language=display_language)
    return pg.wrap(items, total)


@router.get("/announcements/{announcement_id}")
def get_announcement(announcement_id: str, lang: Lang | None = None,
                     svc: Services = Depends(get_services)) -> dict:  # type: ignore[type-arg]
    """The original announcement plus, for ``lang``, the translation students may see (``translation``: verified,
    or a labelled machine translation when enabled; null = show the original)."""
    return svc.public.get_announcement(announcement_id, lang)


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
    lang: Lang | None = None,
    pg: Pagination = Depends(), svc: Services = Depends(get_services),
) -> dict:  # type: ignore[type-arg]
    """``lang``: show verified (human-approved, current) translated titles where they exist; originals otherwise."""
    _check_category(category)
    items, total = svc.public.list_documents(q=q, category=category, scope=scope, page=pg.page, size=pg.page_size,
                                             authority=authority)
    vids = [i["version_id"] for i in items if i.get("version_id")]
    verified = svc.doc_translations.verified_languages(vids)
    titles = svc.doc_translations.display_titles(vids, lang) if lang and lang in TARGET_LANGS else {}
    for i in items:
        i["verified_languages"] = sorted(verified.get(i.get("version_id") or "", []))
        t = titles.get(i.get("version_id") or "")
        i["translated_title"] = t[0] if t and i["language"] != lang else None
        i["translated_title_status"] = t[1] if t and i["language"] != lang else None
        i["display_language"] = lang if i["translated_title"] else i["language"]
    return pg.wrap(items, total)


@router.get("/knowledge/documents/{document_id}")
def get_document(document_id: str, lang: Lang | None = None,
                 svc: Services = Depends(get_services)) -> dict:  # type: ignore[type-arg]
    """The authoritative original (``title``/``content``) plus, for ``lang``, the human-approved translation of
    exactly the current original version (``translation.status = verified``). Without one the original is shown
    (``translation = null``). Drafts, rejected and outdated translations are never returned."""
    out = svc.public.get_document(document_id)
    doc = {"id": document_id, "language": out["language"]}
    out["translation"] = svc.doc_translations.public_translation(doc, out["version_id"], lang)
    out["requested_language"] = lang
    out["verified_languages"] = sorted(svc.doc_translations.verified_languages([out["version_id"]])
                                       .get(out["version_id"], []))
    return out


@router.get("/knowledge/documents/{document_id}/original")
def get_document_original(document_id: str, download: bool = False,
                          svc: Services = Depends(get_services)) -> Response:
    """The ORIGINAL file (PDF / Word / text) of a public document's current approved version, streamed from private
    storage after the same checks as the document page. ``?download=1`` asks the browser to save it."""
    from urllib.parse import quote

    data, filename, mime = svc.public.original_file(document_id)
    attach = download or not mime.startswith(("application/pdf", "text/plain"))   # Word files are always downloads
    disposition = "attachment" if attach else "inline"
    return Response(content=data, media_type=mime, headers={
        "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(filename)}",
        "Cache-Control": "private, max-age=300", "X-Content-Type-Options": "nosniff",
        "Content-Length": str(len(data))})


@router.get("/knowledge/documents/{document_id}/original/preview")
def get_document_original_preview(document_id: str, svc: Services = Depends(get_services)) -> dict:  # type: ignore[type-arg]
    """Formatted HTML preview of a Word original (escaped, script-free; shown in a sandboxed iframe)."""
    out = svc.public.original_preview(document_id)
    return dict(html=out["html"], omitted_images=out["omitted_images"])


@router.get("/me", tags=["auth"])
def me(user: AuthUser = Depends(get_current_user)) -> dict:  # type: ignore[type-arg]
    return dict(id=user.id, email=user.email, display_name=user.display_name, role=user.role,
                preferred_language=user.preferred_language, languages=user.languages, is_staff=user.is_staff,
                preferred_language_confirmed=user.preferred_language_confirmed,
                language_permissions=user.perms)
