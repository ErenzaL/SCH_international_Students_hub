"""Review & publishing: edit / submit / request changes / approve / reject / rollback / cancel / reprocess,
version views, diffs, history and review warnings."""
from __future__ import annotations

import difflib
from datetime import UTC, datetime
from typing import Any

from app.core.constants import OFFICIAL_AUTHORITIES
from app.core.errors import Conflict, Forbidden, InvalidState, NotFound
from app.repositories.base import FileStorage, Query, Store, get_many, get_one
from app.security.auth import AuthUser
from app.services.indexing import IndexingService
from app.services.ingestion.normalize import content_hash, normalize_text

OPEN_STATES = ("draft", "pending_review")


def diff_versions(old: str, new: str) -> dict[str, Any]:
    a, b = old.splitlines(), new.splitlines()
    added = [ln[2:] for ln in difflib.ndiff(a, b) if ln.startswith("+ ")]
    removed = [ln[2:] for ln in difflib.ndiff(a, b) if ln.startswith("- ")]
    unified = "\n".join(difflib.unified_diff(a, b, "current approved", "proposed", lineterm="", n=2))
    return dict(added_count=len(added), removed_count=len(removed), added_lines=added, removed_lines=removed,
                unified=unified)


def _field_value(v: dict[str, Any] | None, key: str) -> Any:
    f = ((v or {}).get("structured_data") or {}).get("fields", {}).get(key)
    return f.get("value") if isinstance(f, dict) else None


class ReviewService:
    def __init__(self, store: Store, indexer: IndexingService, storage: FileStorage | None = None):
        self.store = store
        self.indexer = indexer
        self.storage = storage

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
            "valid_until", "verification_status", "approved_by", "approved_at", "rejected_reason", "created_at",
            "created_by", "edited_by", "edited_at", "review_note", "submitted_at", "indexing_status", "indexed_at",
            "indexing_error", "activation_requested_by", "activation_requested_at")}
        meta = v.get("extraction_meta") or {}
        f = v.get("original_file") or None
        out.update(content_length=len(v["extracted_text"]), is_current=(v["id"] == current_id), **stats,
                   extraction_meta=meta, warnings=meta.get("warnings", []),
                   requires_field_confirmation=bool(meta.get("requires_field_confirmation")),
                   structured_data=v.get("structured_data") or {},
                   original_file=({k: f.get(k) for k in ("filename", "mime_type", "size", "sha256")} if f else None),
                   has_raw_text=bool(v.get("raw_text")))
        if include_text:
            out["extracted_text"] = v["extracted_text"]
            out["raw_text"] = v.get("raw_text")
        return out

    def get_version_view(self, version_id: str) -> dict[str, Any]:
        v = get_one(self.store, "document_versions", id=version_id)
        if v is None:
            raise NotFound("Version not found.")
        doc = get_one(self.store, "source_documents", id=v["document_id"]) or {}
        return self.version_view(v, doc.get("current_version_id"))

    def review_warnings(self, doc: dict[str, Any], source: dict[str, Any] | None, current: dict[str, Any] | None,
                        pending: dict[str, Any] | None) -> list[dict[str, str]]:
        """Facts the reviewer must look at. Conflicts are surfaced, never merged silently."""
        out: list[dict[str, str]] = []
        if pending is None:
            return out
        if source and source["authority_type"] not in OFFICIAL_AUTHORITIES and source["category"] == "visa-immigration":
            out.append(dict(code="non_official_immigration",
                            message="Immigration rules must follow current official government sources. This content "
                                    "is not from an official authority: check it against Hi Korea / the immigration "
                                    "office before approving, and do not let it override official guidance."))
        for key, label in (("deadline", "Deadline"), ("event_date", "Event date"), ("fee", "Fee"),
                           ("location", "Location")):
            old, new = _field_value(current, key), _field_value(pending, key)
            if current is not None and old and new and old != new:
                out.append(dict(code=f"{key}_changed", message=f"{label} changed from '{old}' to '{new}'. Confirm "
                                                               "which is correct; both versions are kept."))
        meta = pending.get("extraction_meta") or {}
        sd = pending.get("structured_data") or {}
        if meta.get("requires_field_confirmation") and not sd.get("fields_confirmed"):
            out.append(dict(code="confirm_fields", message="OCR-derived text: verify dates, times, places, fees, "
                                                           "contacts and eligibility against the original, then confirm."))
        for w in meta.get("warnings", []):
            out.append(dict(code="extraction_warning", message=str(w)))
        return out

    def document_detail(self, document_id: str, source_view) -> dict[str, Any]:  # type: ignore[no-untyped-def]
        doc = get_one(self.store, "source_documents", id=document_id)
        if doc is None:
            raise NotFound("Document not found.")
        versions, _ = self.store.select("document_versions", Query(eq={"document_id": document_id},
                                                                    order=[("version_number", True)]))
        stats = self.chunk_stats([v["id"] for v in versions])
        by_id = {v["id"]: v for v in versions}
        current = by_id.get(doc["current_version_id"]) if doc["current_version_id"] else None
        pending = next((v for v in versions if v["verification_status"] in OPEN_STATES), None)
        source = get_one(self.store, "knowledge_sources", id=doc["source_id"])
        item = self.document_item(doc, source, versions)
        return dict(
            **item, source=source_view(source), metadata=doc.get("metadata") or {},
            current_version=self.version_view(current, doc["current_version_id"], stats[current["id"]]) if current else None,
            pending_version=self.version_view(pending, doc["current_version_id"], stats[pending["id"]]) if pending else None,
            versions=[self.version_view(v, doc["current_version_id"], stats[v["id"]], include_text=False) for v in versions],
            diff=diff_versions(current["extracted_text"], pending["extracted_text"]) if current and pending else None,
            review_warnings=self.review_warnings(doc, source, current, pending),
        )

    def document_item(self, doc: dict[str, Any], source: dict[str, Any] | None, versions: list[dict[str, Any]]
                      ) -> dict[str, Any]:
        pending = next((v for v in versions if v["verification_status"] in OPEN_STATES), None)
        return dict(
            id=doc["id"], source_id=doc["source_id"], source_title=source["title"] if source else None,
            source_type=source["source_type"] if source else None,
            authority_type=source["authority_type"] if source else None,
            title=doc["title"], canonical_url=doc.get("canonical_url"), language=doc["language"],
            document_type=doc["document_type"], organization=source["organization"] if source else None,
            category=source["category"] if source else None, current_version_id=doc["current_version_id"],
            pending_version_id=pending["id"] if pending else None,
            pending_status=pending["verification_status"] if pending else None,
            latest_version_number=max((v["version_number"] for v in versions), default=0),
            is_canceled=doc["is_canceled"], created_at=doc["created_at"], updated_at=doc.get("updated_at"),
            canceled_at=doc.get("canceled_at"), canceled_reason=doc.get("canceled_reason"),
            archived_at=doc.get("archived_at"), archive_reason=doc.get("archive_reason"),
            lifecycle="withdrawn" if doc["is_canceled"] else "archived" if doc.get("archived_at") else
            ("published" if doc["current_version_id"] else "unpublished"),
        )

    def history(self, document_id: str) -> list[dict[str, Any]]:
        doc = get_one(self.store, "source_documents", id=document_id)
        if doc is None:
            raise NotFound("Document not found.")
        versions, _ = self.store.select("document_versions", Query(eq={"document_id": document_id}, cols="id"))
        ids = [document_id] + [v["id"] for v in versions]
        rows, _ = self.store.select("audit_log", Query(in_={"entity_id": ids}, order=[("created_at", True)], limit=200))
        names = {k: v.get("display_name") or v.get("email") or ""
                 for k, v in get_many(self.store, "profiles", [r.get("actor_id") for r in rows]).items()}
        return [dict(id=r["id"], action=r["action"], entity_type=r["entity_type"], entity_id=r.get("entity_id"),
                     actor_id=r.get("actor_id"), actor_name=names.get(r.get("actor_id") or ""),
                     details=r.get("details") or {}, created_at=r["created_at"]) for r in rows]

    # ------------------------------------------------------------- guards
    def _open_version(self, version_id: str, actor: AuthUser) -> dict[str, Any]:
        v = get_one(self.store, "document_versions", id=version_id)
        if v is None:
            raise NotFound("Version not found.")
        if v["verification_status"] not in OPEN_STATES:
            raise InvalidState(f"Only draft or pending versions can be changed (this one is '{v['verification_status']}'). "
                               "Approved content is never edited in place; a new version is created instead.")
        if actor.role == "supporter":
            if v.get("created_by") != actor.id:
                raise Forbidden("Supporters can only edit their own submissions.")
            if v["verification_status"] != "draft":
                raise InvalidState("This submission is waiting for review; an admin can send it back for changes.")
        return v

    def can_view(self, version: dict[str, Any], actor: AuthUser) -> None:
        if actor.role == "supporter" and version.get("created_by") != actor.id:
            raise Forbidden("Supporters can only view their own submissions.")

    # ------------------------------------------------------------- actions
    def edit(self, version_id: str, patch: dict[str, Any], actor: AuthUser) -> dict[str, Any]:
        """Correct extracted text / structured fields / validity window of an open version (re-indexes on text change)."""
        v = self._open_version(version_id, actor)
        upd: dict[str, Any] = {}
        changed: list[str] = []
        if patch.get("extracted_text") is not None:
            text = normalize_text(patch["extracted_text"])
            if len(text) < 10:
                raise InvalidState("The corrected text is empty or too short.")
            h = content_hash(text)
            if h != v["content_hash"]:
                clash = get_one(self.store, "document_versions", document_id=v["document_id"], content_hash=h)
                if clash:
                    raise Conflict(f"This text is identical to version v{clash['version_number']} "
                                   f"({clash['verification_status']}).")
                upd.update(extracted_text=text, content_hash=h, indexing_status="indexing")
                changed.append("extracted_text")
        sd = dict(v.get("structured_data") or {})
        if patch.get("fields") is not None:
            fields = dict(sd.get("fields") or {})
            for k, val in patch["fields"].items():
                if val is None or val == "":
                    fields.pop(k, None)
                else:
                    fields[k] = {"value": val, "evidence": (fields.get(k) or {}).get("evidence"), "confirmed": True,
                                 "source": "reviewer", "by": actor.id}
            sd["fields"] = fields
            changed.append("fields")
        if patch.get("fields_confirmed") is not None:
            if actor.role not in ("admin", "super_admin") and patch["fields_confirmed"]:
                raise Forbidden("Only an admin reviewer can confirm OCR-derived fields.")
            sd["fields_confirmed"] = bool(patch["fields_confirmed"])
            sd["fields_confirmed_by"] = actor.id if patch["fields_confirmed"] else None
            changed.append("fields_confirmed")
        if "fields" in changed or "fields_confirmed" in changed:
            upd["structured_data"] = sd
        for k in ("valid_from", "valid_until", "source_published_at"):
            if k in patch:
                val = patch[k]
                upd[k] = val.isoformat() if hasattr(val, "isoformat") else val
                changed.append(k)
        if upd.get("valid_from") and upd.get("valid_until") and upd["valid_until"] <= upd["valid_from"]:
            raise InvalidState("valid_until must be after valid_from.")
        if patch.get("title"):
            doc = get_one(self.store, "source_documents", id=v["document_id"])
            if doc and doc["title"] != patch["title"]:
                self.store.update("source_documents", {"title": patch["title"][:500]}, {"id": v["document_id"]})
                changed.append("title")
        if not changed:
            return self.get_version_view(version_id)
        upd.update(edited_by=actor.id, edited_at=datetime.now(UTC).isoformat())
        self.store.update("document_versions", upd, {"id": version_id})
        if "extracted_text" in changed:
            self.indexer.index_version(version_id)  # chunks + embeddings for the corrected text
        self.store.insert("audit_log", dict(action="version.edit", entity_type="document_version", entity_id=version_id,
                                            actor_id=actor.id, details={"changed": changed, "previous_hash": v["content_hash"],
                                                                        "new_hash": upd.get("content_hash", v["content_hash"])}))
        return self.get_version_view(version_id)

    def submit(self, version_id: str, actor: AuthUser) -> dict[str, Any]:
        self.store.rpc("submit_version_for_review", dict(p_version_id=version_id, p_actor=actor.id))
        return self.get_version_view(version_id)

    def request_changes(self, version_id: str, actor: AuthUser, note: str) -> dict[str, Any]:
        self.store.rpc("request_version_changes", dict(p_version_id=version_id, p_actor=actor.id, p_note=note))
        return self.get_version_view(version_id)

    def check_approvable(self, version_id: str) -> dict[str, Any]:
        """Approval preconditions (the activation itself happens in the index job, atomically)."""
        v = get_one(self.store, "document_versions", id=version_id)
        if v is None:
            raise NotFound("Version not found.")
        if v["verification_status"] != "pending_review":
            raise InvalidState(f"Only versions in 'pending_review' can be approved (this one is '{v['verification_status']}').")
        meta, sd = v.get("extraction_meta") or {}, v.get("structured_data") or {}
        if meta.get("requires_field_confirmation") and not sd.get("fields_confirmed"):
            raise InvalidState("OCR-derived content: confirm the dates, times, places, fees and contacts against the "
                               "original first (set fields_confirmed).", code="fields_not_confirmed")
        doc = get_one(self.store, "source_documents", id=v["document_id"]) or {}
        if doc.get("is_canceled"):
            raise InvalidState("This document was withdrawn; restore it before approving new content.")
        return v

    def reject(self, version_id: str, actor: AuthUser, reason: str) -> dict[str, Any]:
        self.store.rpc("reject_document_version", dict(p_version_id=version_id, p_actor=actor.id, p_reason=reason))
        return self.get_version_view(version_id)

    def reprocess(self, version_id: str) -> dict[str, Any]:
        if get_one(self.store, "document_versions", id=version_id) is None:
            raise NotFound("Version not found.")
        self.indexer.index_version(version_id, raise_on_embedding_error=True, embed=True)  # "retry indexing"
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

    def original_file(self, version_id: str, actor: AuthUser) -> tuple[bytes, str, str]:
        v = get_one(self.store, "document_versions", id=version_id)
        if v is None:
            raise NotFound("Version not found.")
        self.can_view(v, actor)
        f = v.get("original_file") or {}
        if not f.get("storage_path"):
            raise NotFound("This version has no stored original file.")
        if self.storage is None:
            raise InvalidState("Private file storage is not configured.")
        return self.storage.download(f["storage_path"]), f.get("mime_type") or "application/octet-stream", \
            f.get("filename") or "original"


class DocumentLifecycleService:
    """Archive / withdraw / restore (reversible) and guarded permanent deletion (super_admin, DB-enforced)."""

    def __init__(self, store: Store, storage: FileStorage | None):
        self.store = store
        self.storage = storage

    def archive(self, document_id: str, actor: AuthUser, reason: str) -> None:
        self.store.rpc("archive_document", dict(p_document_id=document_id, p_actor=actor.id, p_reason=reason))

    def restore(self, document_id: str, actor: AuthUser, note: str | None) -> None:
        self.store.rpc("restore_document", dict(p_document_id=document_id, p_actor=actor.id, p_note=note))

    def check(self, document_id: str) -> dict[str, Any]:
        if get_one(self.store, "source_documents", id=document_id) is None:
            raise NotFound("Document not found.")
        out = self.store.rpc("document_delete_check", {"p_document_id": document_id}) or {}
        out["recommended_action"] = "archive" if out.get("approved_versions") else "delete"
        return out

    def delete(self, document_id: str, actor: AuthUser, reason: str, confirm_title: str) -> dict[str, Any]:
        """Database deletion is atomic and audited; private files are removed afterwards (best effort, reported)."""
        if get_one(self.store, "source_documents", id=document_id) is None:
            raise NotFound("Document not found.")
        result = self.store.rpc("delete_document", dict(p_document_id=document_id, p_actor=actor.id, p_reason=reason,
                                                        p_confirm_title=confirm_title)) or {}
        removed, failed = [], []
        for path in result.get("storage_files") or []:
            try:
                if self.storage is None:
                    raise RuntimeError("storage not configured")
                self.storage.remove(path)
                removed.append(path)
            except Exception:  # noqa: BLE001 - the document is gone; report leftovers instead of failing
                failed.append(path)
        if removed or failed:
            self.store.insert("audit_log", dict(action="document.storage_cleanup", entity_type="source_document",
                                                entity_id=document_id, actor_id=actor.id,
                                                details={"removed": len(removed), "failed": failed}))
        return dict(deleted=True, title=result.get("title"), versions=result.get("versions", 0),
                    chunks=result.get("chunks", 0), files_removed=len(removed), files_failed=failed,
                    reimport_blocked=bool(result.get("suppress_reimport")))

    def suppressions(self, source_id: str) -> list[dict[str, Any]]:
        rows, _ = self.store.select("document_suppressions", Query(eq={"source_id": source_id}, order=[("created_at", True)]))
        return rows

    def lift_suppression(self, source_id: str, suppression_id: int, actor: AuthUser) -> None:
        row = get_one(self.store, "document_suppressions", id=suppression_id)
        if row is None or row["source_id"] != source_id:
            raise NotFound("Suppression not found.")
        self.store.delete("document_suppressions", {"id": suppression_id})
        self.store.insert("audit_log", dict(action="document.reimport_allowed", entity_type="knowledge_source",
                                            entity_id=source_id, actor_id=actor.id,
                                            details={k: row.get(k) for k in ("canonical_url", "external_id", "title")}))
