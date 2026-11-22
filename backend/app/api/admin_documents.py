from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import Pagination, get_services
from app.core.errors import NotFound
from app.repositories.base import Query as DbQuery
from app.repositories.base import get_many, get_one
from app.schemas.api import NoteBody, ReasonBody, RollbackBody
from app.security.auth import AuthUser, require_admin
from app.services.container import Services

router = APIRouter(prefix="/api/v1/admin", tags=["admin: documents & review"])


@router.get("/documents")
def list_documents(source_id: str | None = None, has_pending: bool = False, q: str | None = Query(None, max_length=200),
                   pg: Pagination = Depends(), svc: Services = Depends(get_services),
                   _: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    eq = {"source_id": source_id} if source_id else {}
    in_: dict[str, list] = {}  # type: ignore[type-arg]
    if has_pending:
        pend, _c = svc.store.select("document_versions", DbQuery(
            in_={"verification_status": ["pending_review"]}, cols="id,document_id"))
        in_["id"] = list({p["document_id"] for p in pend}) or ["00000000-0000-0000-0000-000000000000"]
    rows, total = svc.store.select("source_documents", DbQuery(
        eq=eq, in_=in_, or_ilike=[("title", q)] if q else [], order=[("created_at", True)], limit=pg.page_size,
        offset=(pg.page - 1) * pg.page_size), count=True)
    sources = get_many(svc.store, "knowledge_sources", [r["source_id"] for r in rows])
    versions, _c = svc.store.select("document_versions", DbQuery(
        in_={"document_id": [r["id"] for r in rows]}, cols="id,document_id,version_number,verification_status")) \
        if rows else ([], None)
    by_doc: dict[str, list] = {}  # type: ignore[type-arg]
    for v in versions:
        by_doc.setdefault(v["document_id"], []).append(v)
    items = [svc.review.document_item(r, sources.get(r["source_id"]), by_doc.get(r["id"], [])) for r in rows]
    return pg.wrap(items, total or 0)


@router.get("/documents/{document_id}")
def get_document(document_id: str, svc: Services = Depends(get_services),
                 _: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    return svc.review.document_detail(document_id, svc.sources.view)


@router.post("/documents/{document_id}/rollback")
def rollback(document_id: str, body: RollbackBody, svc: Services = Depends(get_services),
             user: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    return svc.review.rollback(document_id, body.version_id, user, body.note, svc.sources.view)


@router.post("/documents/{document_id}/cancel")
def cancel(document_id: str, body: ReasonBody, svc: Services = Depends(get_services),
           user: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    if get_one(svc.store, "source_documents", id=document_id) is None:
        raise NotFound("Document not found.")
    svc.review.cancel(document_id, user, body.reason)
    return svc.review.document_detail(document_id, svc.sources.view)


@router.get("/versions/{version_id}")
def get_version(version_id: str, svc: Services = Depends(get_services),
                _: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    return svc.review.get_version_view(version_id)


@router.get("/versions/{version_id}/chunks")
def version_chunks(version_id: str, svc: Services = Depends(get_services),
                   _: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    if get_one(svc.store, "document_versions", id=version_id) is None:
        raise NotFound("Version not found.")
    rows, _c = svc.store.select("document_chunks", DbQuery(
        eq={"version_id": version_id}, order=[("chunk_index", False)],
        cols="chunk_index,heading,content,page_start,embedding_model"))
    return {"items": [dict(chunk_index=r["chunk_index"], heading=r.get("heading"), content=r["content"],
                           page=r.get("page_start"), has_embedding=bool(r.get("embedding_model")),
                           embedding_model=r.get("embedding_model")) for r in rows]}


@router.post("/versions/{version_id}/approve")
def approve(version_id: str, body: NoteBody | None = None, svc: Services = Depends(get_services),
            user: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    return svc.review.approve(version_id, user, body.note if body else None)


@router.post("/versions/{version_id}/reject")
def reject(version_id: str, body: ReasonBody, svc: Services = Depends(get_services),
           user: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    return svc.review.reject(version_id, user, body.reason)


@router.post("/versions/{version_id}/reprocess")
def reprocess(version_id: str, svc: Services = Depends(get_services),
              _: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    return svc.review.reprocess(version_id)
