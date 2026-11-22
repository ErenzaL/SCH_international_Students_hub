"""Knowledge source registration and admin views."""
from __future__ import annotations

from typing import Any

from app.core.config import Settings
from app.core.errors import Conflict, DuplicateError, InvalidState, NotFound
from app.repositories.base import Query, Store, get_many, get_one
from app.security.url_guard import validate_url_syntax
from app.services.source_status import derive_source_status


class SourceService:
    def __init__(self, store: Store, settings: Settings):
        self.store = store
        self.settings = settings

    def view(self, s: dict[str, Any], doc_count: int | None = None, names: dict[str, str] | None = None) -> dict[str, Any]:
        if doc_count is None:
            _, doc_count = self.store.select("source_documents", Query(eq={"source_id": s["id"]}, limit=1), count=True)
        if names is None:
            names = {k: v.get("display_name") or v.get("email") or ""
                     for k, v in get_many(self.store, "profiles", [s.get("created_by")]).items()}
        return dict(
            id=s["id"], title=s["title"], original_url=s.get("original_url"), organization=s["organization"],
            source_type=s["source_type"], authority_type=s["authority_type"], scope=s["scope"],
            category=s["category"], language=s["language"], sync_frequency=s["sync_frequency"],
            is_active=s["is_active"], status=s["status"], created_by=s.get("created_by"),
            created_by_name=names.get(s.get("created_by") or ""), created_at=s["created_at"],
            updated_at=s.get("updated_at"), last_checked_at=s.get("last_checked_at"),
            last_ingestion_result=s.get("last_ingestion_result"), is_test_data=s.get("is_test_data", False),
            document_count=doc_count or 0)

    def list(self, *, status: str | None, source_type: str | None, q: str | None, page: int, size: int
             ) -> tuple[list[dict[str, Any]], int]:
        eq = {k: v for k, v in (("status", status), ("source_type", source_type)) if v}
        rows, total = self.store.select("knowledge_sources", Query(
            eq=eq, or_ilike=[("title", q), ("organization", q), ("original_url", q)] if q else [],
            order=[("created_at", True)], limit=size, offset=(page - 1) * size), count=True)
        names = {k: v.get("display_name") or v.get("email") or ""
                 for k, v in get_many(self.store, "profiles", [r.get("created_by") for r in rows]).items()}
        docs, _ = self.store.select("source_documents", Query(in_={"source_id": [r["id"] for r in rows]},
                                                               cols="id,source_id")) if rows else ([], None)
        counts: dict[str, int] = {}
        for d in docs:
            counts[d["source_id"]] = counts.get(d["source_id"], 0) + 1
        return [self.view(r, counts.get(r["id"], 0), names) for r in rows], total or 0

    def get(self, source_id: str) -> dict[str, Any]:
        s = get_one(self.store, "knowledge_sources", id=source_id)
        if s is None:
            raise NotFound("Source not found.")
        return s

    def detail(self, source_id: str) -> dict[str, Any]:
        s = self.get(source_id)
        docs, _ = self.store.select("source_documents", Query(eq={"source_id": source_id}, order=[("created_at", True)]))
        versions, _ = self.store.select("document_versions", Query(
            in_={"document_id": [d["id"] for d in docs]}, order=[("version_number", True)],
            cols="id,document_id,version_number,verification_status,created_at")) if docs else ([], None)
        latest: dict[str, dict[str, Any]] = {}
        for v in versions:
            latest.setdefault(v["document_id"], v)
        out = self.view(s, len(docs))
        out["documents"] = [dict(id=d["id"], title=d["title"], canonical_url=d.get("canonical_url"),
                                 current_version_id=d["current_version_id"],
                                 latest_version=latest.get(d["id"])) for d in docs]
        return out

    def create(self, data: dict[str, Any], created_by: str) -> dict[str, Any]:
        row = dict(data)
        if row["source_type"] == "website":
            row["original_url"] = validate_url_syntax(row["original_url"], self.settings.allowed_domains)
        elif row.get("original_url"):
            # optional reference URL for non-website sources: still must be http(s)
            if not row["original_url"].lower().startswith(("http://", "https://")):
                raise InvalidState("original_url must start with http:// or https://")
        row.update(created_by=created_by, status="registered" if row.get("is_active", True) else "inactive")
        try:
            return self.store.insert("knowledge_sources", row)
        except DuplicateError as exc:
            raise Conflict("A website source with this exact URL is already registered.") from exc

    def patch(self, source_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        s = self.get(source_id)
        fields = {k: v for k, v in patch.items() if v is not None}
        if fields.get("sync_frequency", "manual") != "manual" and s["source_type"] != "website":
            raise InvalidState("Only website sources can use daily/weekly sync.")
        if not fields:
            return s
        return self.store.update("knowledge_sources", fields, {"id": source_id})[0]

    def set_active(self, source_id: str, active: bool, actor_id: str) -> dict[str, Any]:
        s = self.get(source_id)
        updated = self.store.update("knowledge_sources", dict(
            is_active=active, status=("registered" if active else "inactive")), {"id": source_id})[0]
        self.store.insert("audit_log", dict(action="source.enable" if active else "source.disable",
                                            entity_type="knowledge_source", entity_id=source_id, actor_id=actor_id,
                                            details={"title": s["title"]}))
        if active:  # restore a meaningful status (pending_review / approved) instead of 'registered'
            status = derive_source_status(self.store, source_id)
            updated = self.store.update("knowledge_sources", {"status": status}, {"id": source_id})[0]
        return updated


