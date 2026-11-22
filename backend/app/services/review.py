"""Review & publishing: approve / reject / rollback / cancel / reprocess + version views and diffs."""
from __future__ import annotations

import difflib
from typing import Any

from app.core.errors import InvalidState, NotFound
from app.repositories.base import Query, Store, get_many, get_one
from app.security.auth import AuthUser
from app.services.indexing import IndexingService


def diff_versions(old: str, new: str) -> dict[str, Any]:
    a, b = old.splitlines(), new.splitlines()
    added = [ln[1:] for ln in difflib.ndiff(a, b) if ln.startswith("+ ")]
    removed = [ln[1:] for ln in difflib.ndiff(a, b) if ln.startswith("- ")]
    unified = "\n".join(difflib.unified_diff(a, b, "current approved", "proposed", lineterm="", n=2))
    return dict(added_count=len(added), removed_count=len(removed), added_lines=added, removed_lines=removed,
                unified=unified)


class ReviewService:
    def __init__(self, store: Store, indexer: IndexingService):
        self.store = store
        self.indexer = indexer

    # --------------------------------------------------------------- views
    def chunk_stats(self, version_ids: list[str]) -> dict[str, dict[str, Any]]:
        if not version_ids:
            return {}
        rows, _ = self.store.select("document_chunks", Query(in_={"version_id": version_ids},
                                                             cols="id,version_id,embedding_model"))
        stats: dict[str, dict[str, Any]] = {v: dict(chunk_count=0, embedded_chunk_count=0, embedding_model=None)
                                            for v in version_ids}
        for r in rows:
            s = stats[r["version_id"]]
            s["chunk_count"] += 1
            if r.get("embedding_model"):
                s["embedded_chunk_count"] += 1
                s["embedding_model"] = r["embedding_model"]
        return stats

    def version_view(self, v: dict[str, Any], current_id: str | None, stats: dict[str, Any] | None = None,
                     include_text: bool = True) -> dict[str, Any]:
        stats = stats if stats is not None else self.chunk_stats([v["id"]])[v["id"]]
        out = {k: v.get(k) for k in (
            "id", "document_id", "version_number", "content_hash", "source_published_at", "fetched_at", "valid_from",
            "valid_until", "verification_status", "approved_by", "approved_at", "rejected_reason", "created_at")}
        out.update(content_length=len(v["extracted_text"]), is_current=(v["id"] == current_id), **stats)
        if include_text:
            out["extracted_text"] = v["extracted_text"]
        return out

    def get_version_view(self, version_id: str) -> dict[str, Any]:
        v = get_one(self.store, "document_versions", id=version_id)
        if v is None:
            raise NotFound("Version not found.")
        doc = get_one(self.store, "source_documents", id=v["document_id"]) or {}
        return self.version_view(v, doc.get("current_version_id"))

    def document_detail(self, document_id: str, source_view) -> dict[str, Any]:  # type: ignore[no-untyped-def]
        doc = get_one(self.store, "source_documents", id=document_id)
        if doc is None:
            raise NotFound("Document not found.")
        versions, _ = self.store.select("document_versions", Query(eq={"document_id": document_id},
                                                                    order=[("version_number", True)]))
        stats = self.chunk_stats([v["id"] for v in versions])
        by_id = {v["id"]: v for v in versions}
        current = by_id.get(doc["current_version_id"]) if doc["current_version_id"] else None
        pending = next((v for v in versions if v["verification_status"] in ("pending_review", "draft")), None)
        source = get_one(self.store, "knowledge_sources", id=doc["source_id"])
        item = self.document_item(doc, source, versions)
        return dict(
            **item, source=source_view(source),
            current_version=self.version_view(current, doc["current_version_id"], stats[current["id"]]) if current else None,
            pending_version=self.version_view(pending, doc["current_version_id"], stats[pending["id"]]) if pending else None,
            versions=[self.version_view(v, doc["current_version_id"], stats[v["id"]], include_text=False) for v in versions],
            diff=diff_versions(current["extracted_text"], pending["extracted_text"]) if current and pending else None,
        )

    def document_item(self, doc: dict[str, Any], source: dict[str, Any] | None, versions: list[dict[str, Any]]
                      ) -> dict[str, Any]:
        pending = next((v for v in versions if v["verification_status"] in ("pending_review", "draft")), None)
        return dict(
            id=doc["id"], source_id=doc["source_id"], source_title=source["title"] if source else None,
            title=doc["title"], canonical_url=doc.get("canonical_url"), language=doc["language"],
            document_type=doc["document_type"], organization=source["organization"] if source else None,
            category=source["category"] if source else None, current_version_id=doc["current_version_id"],
            pending_version_id=pending["id"] if pending else None,
            latest_version_number=max((v["version_number"] for v in versions), default=0),
            is_canceled=doc["is_canceled"], created_at=doc["created_at"],
        )

    # ------------------------------------------------------------- actions
    def approve(self, version_id: str, actor: AuthUser, note: str | None) -> dict[str, Any]:
        v = get_one(self.store, "document_versions", id=version_id)
        if v is None:
            raise NotFound("Version not found.")
        if v["verification_status"] != "pending_review":
            raise InvalidState(f"Only versions in 'pending_review' can be approved (this one is '{v['verification_status']}').")
        self.indexer.ensure_indexed(version_id)  # embeddings must exist before anything becomes searchable
        self.store.rpc("approve_document_version", dict(p_version_id=version_id, p_actor=actor.id, p_note=note))
        return self.get_version_view(version_id)

    def reject(self, version_id: str, actor: AuthUser, reason: str) -> dict[str, Any]:
        self.store.rpc("reject_document_version", dict(p_version_id=version_id, p_actor=actor.id, p_reason=reason))
        return self.get_version_view(version_id)

    def reprocess(self, version_id: str) -> dict[str, Any]:
        if get_one(self.store, "document_versions", id=version_id) is None:
            raise NotFound("Version not found.")
        self.indexer.index_version(version_id, raise_on_embedding_error=True)
        return self.get_version_view(version_id)

    def rollback(self, document_id: str, version_id: str, actor: AuthUser, note: str | None, source_view) -> dict[str, Any]:  # type: ignore[no-untyped-def]
        v = get_one(self.store, "document_versions", id=version_id)
        if v is None or v["document_id"] != document_id:
            raise NotFound("Version not found for this document.")
        self.indexer.ensure_indexed(version_id)
        self.store.rpc("rollback_document_version", dict(
            p_document_id=document_id, p_version_id=version_id, p_actor=actor.id, p_note=note))
        return self.document_detail(document_id, source_view)

    def cancel(self, document_id: str, actor: AuthUser, reason: str) -> None:
        self.store.rpc("cancel_document", dict(p_document_id=document_id, p_actor=actor.id, p_reason=reason))


_ = get_many
