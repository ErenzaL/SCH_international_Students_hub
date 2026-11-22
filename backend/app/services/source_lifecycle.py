"""Knowledge-source lifecycle: archive / restore (admin, reversible) and guarded permanent deletion (super_admin).

All state changes run inside database functions (migration 0010) so the role check, the blockers, the audit
tombstone and the row deletions are one transaction. Private files are removed afterwards - only the ones no other
source, document or job references - and any leftovers are reported and audited instead of failing the request.
"""
from __future__ import annotations

from typing import Any

from app.core.errors import NotFound
from app.repositories.base import FileStorage, Store, get_one
from app.security.auth import AuthUser


class SourceLifecycleService:
    def __init__(self, store: Store, storage: FileStorage | None):
        self.store = store
        self.storage = storage

    def _require(self, source_id: str) -> dict[str, Any]:
        s = get_one(self.store, "knowledge_sources", id=source_id)
        if s is None:
            raise NotFound("Source not found.")
        return s

    def check(self, source_id: str) -> dict[str, Any]:
        self._require(source_id)
        return self.store.rpc("source_delete_check", {"p_source_id": source_id}) or {}

    def archive(self, source_id: str, actor: AuthUser, reason: str) -> dict[str, Any]:
        self._require(source_id)
        return self.store.rpc("archive_source", dict(p_source_id=source_id, p_actor=actor.id, p_reason=reason))

    def restore(self, source_id: str, actor: AuthUser) -> dict[str, Any]:
        self._require(source_id)
        return self.store.rpc("restore_source", dict(p_source_id=source_id, p_actor=actor.id))

    def delete(self, source_id: str, actor: AuthUser, reason: str, confirm_title: str,
               confirm_destructive: bool) -> dict[str, Any]:
        self._require(source_id)   # a repeated request after a successful delete is a clean 404
        result = self.store.rpc("delete_source", dict(
            p_source_id=source_id, p_actor=actor.id, p_reason=reason, p_confirm_title=confirm_title,
            p_confirm_destructive=confirm_destructive)) or {}
        removed, failed = [], []
        for path in result.get("storage_files") or []:
            try:
                if self.storage is None:
                    raise RuntimeError("storage not configured")
                self.storage.remove(path)
                removed.append(path)
            except Exception:  # noqa: BLE001 - the source is gone; report leftovers instead of failing
                failed.append(path)
        if removed or failed:
            self.store.insert("audit_log", dict(action="source.storage_cleanup", entity_type="knowledge_source",
                                                entity_id=source_id, actor_id=actor.id,
                                                details={"removed": len(removed), "failed": failed}))
        return dict(deleted=True, title=result.get("title"), documents=result.get("documents", 0),
                    versions=result.get("versions", 0), chunks=result.get("chunks", 0),
                    jobs_kept=result.get("jobs", 0), queued_jobs_canceled=result.get("queued_jobs_canceled", 0),
                    files_removed=len(removed), files_failed=failed)
