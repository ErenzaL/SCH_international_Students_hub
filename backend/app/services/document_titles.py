"""The title of a document belongs to its approved version.

``source_documents.title`` is what students see (Knowledge Center, search, citations, translations). It only changes
together with the approved version: when a version is activated or restored. The title an unapproved version proposes is
kept with that version (``extraction_meta.document_title``) and shown to reviewers. A document without an approved version
is not public, so its title follows the latest extraction as before.
"""
from __future__ import annotations

from typing import Any

from app.repositories.base import Store, get_one

KEY = "document_title"          # the version's own title
MAX_TITLE = 500


def version_title(version: dict[str, Any], doc: dict[str, Any]) -> str:
    """The title of this version (versions made before titles were recorded: the document's title)."""
    return (version.get("extraction_meta") or {}).get(KEY) or doc.get("title") or ""


def set_meta(store: Store, version: dict[str, Any], title: str) -> None:
    store.update("document_versions", {"extraction_meta": dict(version.get("extraction_meta") or {}) | {KEY: title}},
                 {"id": version["id"]})


def remember_current_title(store: Store, document_id: str) -> None:
    """Before another version becomes current: write the public title down with the version it belongs to, so that a
    rollback can restore it (versions made before titles were recorded)."""
    doc = get_one(store, "source_documents", id=document_id)
    cur = get_one(store, "document_versions", id=doc["current_version_id"]) if doc and doc.get("current_version_id") else None
    if doc and cur and not (cur.get("extraction_meta") or {}).get(KEY):
        set_meta(store, cur, doc["title"])


def apply_title(store: Store, version_id: str) -> str | None:
    """Make the title of the CURRENT approved version the public one (idempotent). Returns the new title if it changed."""
    v = get_one(store, "document_versions", id=version_id)
    doc = get_one(store, "source_documents", id=v["document_id"]) if v else None
    if not v or not doc or doc.get("current_version_id") != v["id"] or v["verification_status"] != "approved":
        return None
    title = version_title(v, doc)[:MAX_TITLE]
    if not title or title == doc["title"]:
        return None
    store.update("source_documents", {"title": title}, {"id": doc["id"], "current_version_id": v["id"]})
    return title
