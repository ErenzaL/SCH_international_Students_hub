"""Human-facing source status derived from its documents/versions (mirrors SQL refresh_source_status)."""
from __future__ import annotations

from app.repositories.base import Query, Store, get_one


def derive_source_status(store: Store, source_id: str) -> str:
    src = get_one(store, "knowledge_sources", id=source_id)
    if src is None:
        return "registered"
    if not src["is_active"]:
        return "inactive"
    docs, _ = store.select("source_documents", Query(eq={"source_id": source_id}))
    if docs:
        pending, _ = store.select("document_versions", Query(
            in_={"document_id": [d["id"] for d in docs]}, eq={"verification_status": "pending_review"}, limit=1))
        if pending:
            return "pending_review"
    return "approved" if any(d["current_version_id"] for d in docs) else "registered"
