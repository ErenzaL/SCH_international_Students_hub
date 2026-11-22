from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from app.api.deps import Pagination, get_services
from app.core.errors import NotFound
from app.repositories.base import Query as DbQuery
from app.repositories.base import get_many, get_one
from app.schemas.api import DocumentDelete, NoteBody, NoteRequired, ReasonBody, RollbackBody, VersionPatch
from app.security.auth import AuthUser, require_admin, require_staff, require_super_admin
from app.services.container import Services

router = APIRouter(prefix="/api/v1/admin", tags=["admin: documents & review"])


@router.get("/documents")
def list_documents(source_id: str | None = None, has_pending: bool = False,
                   review_status: Literal["pending_review", "draft", "open"] | None = None,
                   lifecycle: Literal["active", "archived", "withdrawn"] | None = None,
                   q: str | None = Query(None, max_length=200),
                   pg: Pagination = Depends(), svc: Services = Depends(get_services),
                   _: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    """``has_pending`` / ``review_status=pending_review`` = the review queue; ``draft`` = changes requested / unsubmitted."""
    eq = {"source_id": source_id} if source_id else {}
    in_: dict[str, list] = {}  # type: ignore[type-arg]
    statuses = {"pending_review": ["pending_review"], "draft": ["draft"], "open": ["pending_review", "draft"]}.get(
        review_status or ("pending_review" if has_pending else ""), None)
    if statuses:
        pend, _c = svc.store.select("document_versions", DbQuery(in_={"verification_status": statuses},
                                                                cols="id,document_id"))
        in_["id"] = list({p["document_id"] for p in pend}) or ["00000000-0000-0000-0000-000000000000"]
    is_null: dict[str, bool] = {}
    if lifecycle == "archived":
        is_null["archived_at"] = False
    elif lifecycle == "withdrawn":
        eq["is_canceled"] = True
    elif lifecycle == "active":
        eq["is_canceled"] = False
        is_null["archived_at"] = True
    rows, total = svc.store.select("source_documents", DbQuery(
        eq=eq, in_=in_, is_null=is_null, or_ilike=[("title", q)] if q else [], order=[("created_at", True)], limit=pg.page_size,
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


@router.get("/documents/{document_id}/history")
def document_history(document_id: str, svc: Services = Depends(get_services),
                     _: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    return {"items": svc.review.history(document_id)}


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
    doc = get_one(svc.store, "source_documents", id=document_id) or {}
    svc.notifications.notify("withdrawn", f"Withdrawn: {doc.get('title', '')[:150]}",
                             f"Removed from search and the Knowledge Center: {body.reason}", severity="warning",
                             entity_type="source_document", entity_id=document_id, link=f"/admin/documents/{document_id}")
    return svc.review.document_detail(document_id, svc.sources.view)


@router.post("/documents/{document_id}/archive")
def archive(document_id: str, body: ReasonBody, svc: Services = Depends(get_services),
            user: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    """Reversible: removed from search and the Knowledge Center, kept with full history."""
    if get_one(svc.store, "source_documents", id=document_id) is None:
        raise NotFound("Document not found.")
    svc.lifecycle.archive(document_id, user, body.reason)
    return svc.review.document_detail(document_id, svc.sources.view)


@router.post("/documents/{document_id}/restore")
def restore(document_id: str, body: NoteBody | None = None, svc: Services = Depends(get_services),
            user: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    """Undo archive / withdrawal: the last approved version becomes searchable again."""
    if get_one(svc.store, "source_documents", id=document_id) is None:
        raise NotFound("Document not found.")
    svc.lifecycle.restore(document_id, user, body.note if body else None)
    return svc.review.document_detail(document_id, svc.sources.view)


@router.get("/documents/{document_id}/deletion-check")
def deletion_check(document_id: str, svc: Services = Depends(get_services),
                   _: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    """What a permanent deletion would remove, what blocks it, and the recommended (reversible) alternative."""
    return svc.lifecycle.check(document_id)


@router.post("/documents/{document_id}/delete")
def delete_document(document_id: str, body: DocumentDelete, svc: Services = Depends(get_services),
                    user: AuthUser = Depends(require_super_admin)) -> dict:  # type: ignore[type-arg]
    """Permanent deletion (super_admin; DB-enforced eligibility; audited tombstone; re-import blocked)."""
    return svc.lifecycle.delete(document_id, user, body.reason, body.confirm_title)


@router.get("/sources/{source_id}/suppressions")
def suppressions(source_id: str, svc: Services = Depends(get_services),
                 _: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    return {"items": svc.lifecycle.suppressions(source_id)}


@router.delete("/sources/{source_id}/suppressions/{suppression_id}", status_code=204)
def lift_suppression(source_id: str, suppression_id: int, svc: Services = Depends(get_services),
                     user: AuthUser = Depends(require_admin)) -> None:
    """Allow a deliberately deleted document to be imported again by future syncs."""
    svc.lifecycle.lift_suppression(source_id, suppression_id, user)


@router.get("/versions/{version_id}")
def get_version(version_id: str, svc: Services = Depends(get_services),
                user: AuthUser = Depends(require_staff)) -> dict:  # type: ignore[type-arg]
    v = get_one(svc.store, "document_versions", id=version_id)
    if v is None:
        raise NotFound("Version not found.")
    svc.review.can_view(v, user)
    return svc.review.get_version_view(version_id)


@router.patch("/versions/{version_id}")
def edit_version(version_id: str, body: VersionPatch, svc: Services = Depends(get_services),
                 user: AuthUser = Depends(require_staff)) -> dict:  # type: ignore[type-arg]
    """Correct extracted text / structured fields of a draft or pending version (never an approved one)."""
    return svc.review.edit(version_id, body.model_dump(exclude_unset=True), user)


@router.post("/versions/{version_id}/submit")
def submit_version(version_id: str, svc: Services = Depends(get_services),
                   user: AuthUser = Depends(require_staff)) -> dict:  # type: ignore[type-arg]
    return svc.review.submit(version_id, user)


@router.post("/versions/{version_id}/request-changes")
def request_changes(version_id: str, body: NoteRequired, svc: Services = Depends(get_services),
                    user: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    return svc.review.request_changes(version_id, user, body.note)


@router.get("/versions/{version_id}/original")
def original_file(version_id: str, svc: Services = Depends(get_services),
                  user: AuthUser = Depends(require_staff)) -> Response:
    """Original uploaded file/screenshot, streamed through the API (the bucket stays private)."""
    data, mime, name = svc.review.original_file(version_id, user)
    disposition = "inline" if mime.startswith(("image/", "application/pdf", "text/")) else "attachment"
    return Response(data, media_type=mime, headers={"Content-Disposition": f'{disposition}; filename="{name}"',
                                                     "X-Content-Type-Options": "nosniff",
                                                     "Cache-Control": "private, no-store"})


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


@router.post("/versions/{version_id}/approve", status_code=202)
def approve(version_id: str, body: NoteBody | None = None,
            svc: Services = Depends(get_services), user: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    """Approve -> queue a durable indexing job. The version becomes active (searchable) only after every chunk
    is embedded and validated; until then the previously approved version stays live. Idempotent."""
    v = svc.review.check_approvable(version_id)
    job = svc.ingestion.request_activation(v, user.id, body.note if body else None)
    svc.jobs.enqueue(job)  # inline mode: indexed + activated before responding; worker mode: queued, returns now
    job = get_one(svc.store, "ingestion_jobs", id=job["id"]) or job
    out = svc.review.get_version_view(version_id)
    return {**out, "indexing_job_id": job["id"], "indexing_job_status": job["status"]}


@router.post("/versions/{version_id}/reject")
def reject(version_id: str, body: ReasonBody, svc: Services = Depends(get_services),
           user: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    return svc.review.reject(version_id, user, body.reason)


@router.post("/versions/{version_id}/reprocess")
def reprocess(version_id: str, svc: Services = Depends(get_services),
              _: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    return svc.review.reprocess(version_id)
