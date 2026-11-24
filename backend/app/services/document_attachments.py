"""The public details of a board notice (attachments, notice number, author) belong to its approved version.

Every version records what its import found (``extraction_meta``, also versions made before this module existed). Two layers:

* the API shows the attachments recorded with the APPROVED version, whatever ``source_documents.metadata`` says;
* ``source_documents.metadata`` (readable with the public key, like the title) is only changed together with the approved
  version. A document without an approved version is not public and follows the latest import as before.
"""
from __future__ import annotations

from typing import Any

from app.repositories.base import Store, get_one

#: what a version decides about; everything else in the metadata (``pinned``: its place in the list) follows the board
KEYS = ("notice_no", "board_table", "author", "attachments")


def recorded(version: dict[str, Any] | None) -> dict[str, Any] | None:
    """The details recorded with this version, or None (not a board notice)."""
    meta = (version or {}).get("extraction_meta") or {}
    if meta.get("extractor") != "sch_board" or "attachments" not in meta:
        return None
    return {k: meta[k] for k in KEYS if k in meta}


def public_details(version: dict[str, Any], doc: dict[str, Any]) -> dict[str, Any]:
    """What students see for an approved version."""
    return (doc.get("metadata") or {}) | (recorded(version) or {})


def imported(doc: dict[str, Any], found: dict[str, Any]) -> dict[str, Any]:
    """``source_documents.metadata`` after an import: a published document keeps the details of its approved version."""
    old = doc.get("metadata") or {}
    if not doc.get("current_version_id"):
        return found
    return found | {k: old[k] for k in KEYS if k in old} if old else {k: v for k, v in found.items() if k not in KEYS}


def apply_details(store: Store, version_id: str) -> bool:
    """Make the details of the CURRENT approved version the stored ones (idempotent)."""
    v = get_one(store, "document_versions", id=version_id)
    doc = get_one(store, "source_documents", id=v["document_id"]) if v else None
    details = recorded(v)
    if not v or not doc or details is None or doc.get("current_version_id") != v["id"] or v["verification_status"] != "approved":
        return False
    new = (doc.get("metadata") or {}) | details
    if new == (doc.get("metadata") or {}):
        return False
    store.update("source_documents", {"metadata": new}, {"id": doc["id"], "current_version_id": v["id"]})
    return True


def changes(current: dict[str, Any] | None, pending: dict[str, Any] | None) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """(added, removed) attachments of a pending version, for the reviewer."""
    old, new = recorded(current), recorded(pending)
    if old is None or new is None:
        return [], []
    a, b = old.get("attachments") or [], new.get("attachments") or []
    return [x for x in b if x not in a], [x for x in a if x not in b]
