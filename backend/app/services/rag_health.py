"""Is every published document actually searchable? (post-activation verification + on-demand audit)

Activation already validates the index inside the switch transaction (``activate_document_version``). This module
checks the *result* the way students see it: the chunks of a document's current version must appear in the
``searchable_chunks`` view and carry an embedding from the current model (``search_knowledge_v2`` filters on it).

* ``check_version``  - one version: chunk / embedding / searchable counts, problems, or an expected hidden reason
                       (scheduled ``valid_from``, expired ``valid_until``, inactive source, archived, withdrawn).
* ``audit``          - every published document + lightweight corpus statistics, computed on demand (no cache table).
* ``alert``          - admin notification ``not_searchable`` (deduplicated per document for 24 h).

Read-only apart from notifications: it never re-indexes, activates or changes documents, and it never starts a
research benchmark, evaluation or snapshot.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from app.repositories.base import Query, Store, get_many, get_one

log = logging.getLogger("app.rag_health")
ALERT_KIND = "not_searchable"
ALERT_DEDUPE = timedelta(hours=24)


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=UTC)


class RagHealthService:
    def __init__(self, store: Store, model_id: str, notifications: Any | None = None):
        self.store = store
        self.model_id = model_id
        self.notifications = notifications

    # ---------------------------------------------------------------- counts
    def _count(self, table: str, **eq: Any) -> int:
        _rows, total = self.store.select(table, Query(eq=eq, limit=1, cols="version_id" if table == "searchable_chunks"
                                                      else "id"), count=True)
        return total or 0

    @staticmethod
    def hidden_reason(version: dict[str, Any], doc: dict[str, Any], source: dict[str, Any] | None,
                      now: datetime | None = None) -> str | None:
        """Why an approved current version is *intentionally* not searchable (None = it should be searchable)."""
        now = now or datetime.now(UTC)
        if doc.get("is_canceled"):
            return "withdrawn"
        if doc.get("archived_at"):
            return "archived"
        if source is not None and not source.get("is_active", True):
            return "source_inactive"
        vf, vu = _parse(version.get("valid_from")), _parse(version.get("valid_until"))
        if vf and vf > now:
            return "scheduled"
        if vu and vu <= now:
            return "expired"
        return None

    # ---------------------------------------------------------------- checks
    def check_version(self, version_id: str) -> dict[str, Any]:
        v = get_one(self.store, "document_versions", id=version_id)
        if v is None:
            return dict(version_id=version_id, ok=False, problems=["version_missing"])
        doc = get_one(self.store, "source_documents", id=v["document_id"]) or {}
        source = get_one(self.store, "knowledge_sources", id=doc.get("source_id")) if doc.get("source_id") else None
        return self._check(v, doc, source)

    def _check(self, v: dict[str, Any], doc: dict[str, Any], source: dict[str, Any] | None) -> dict[str, Any]:
        total = self._count("document_chunks", version_id=v["id"])
        embedded = self._count("document_chunks", version_id=v["id"], embedding_model=self.model_id)
        searchable = self._count("searchable_chunks", version_id=v["id"])
        active = v.get("verification_status") == "approved" and doc.get("current_version_id") == v["id"]
        hidden = self.hidden_reason(v, doc, source) if active else None
        problems: list[str] = []
        if not active:
            problems.append("not_active")
        elif total == 0:
            problems.append("no_chunks")
        else:
            if embedded < total:
                problems.append("embeddings_missing_or_outdated")   # search_knowledge_v2 only matches the current model
            if hidden is None and searchable < total:
                problems.append("not_searchable")
        return dict(document_id=v["document_id"], title=doc.get("title"), language=doc.get("language"),
                    category=(source or {}).get("category"), version_id=v["id"], version_number=v.get("version_number"),
                    indexing_status=v.get("indexing_status"), indexed_at=v.get("indexed_at"), chunks=total,
                    embedded_chunks=embedded, searchable_chunks=searchable, hidden_reason=hidden,
                    ok=not problems, problems=problems, checked_at=datetime.now(UTC).isoformat())

    def audit(self, *, notify: bool = False) -> dict[str, Any]:
        """Every published document (current version set, not withdrawn) + lightweight statistics, on demand."""
        docs, _ = self.store.select("source_documents", Query(is_null={"current_version_id": False}))
        docs = [d for d in docs if not d.get("is_canceled") and not d.get("archived_at")]
        versions = get_many(self.store, "document_versions", [d["current_version_id"] for d in docs])
        sources = get_many(self.store, "knowledge_sources", [d["source_id"] for d in docs])
        results = []
        for d in docs:
            v = versions.get(d["current_version_id"])
            if v is None:
                results.append(dict(document_id=d["id"], title=d.get("title"), version_id=d["current_version_id"],
                                    ok=False, problems=["version_missing"]))
                continue
            results.append(self._check(v, d, sources.get(d["source_id"])))
        problems = [r for r in results if not r["ok"]]
        if notify:
            for r in problems:
                self.alert(r)
        by_lang: dict[str, int] = {}
        by_cat: dict[str, int] = {}
        for r in results:
            by_lang[r.get("language") or "unknown"] = by_lang.get(r.get("language") or "unknown", 0) + (r.get("searchable_chunks") or 0)
            by_cat[r.get("category") or "unknown"] = by_cat.get(r.get("category") or "unknown", 0) + (r.get("searchable_chunks") or 0)
        return dict(
            checked_at=datetime.now(UTC).isoformat(), embedding_model=self.model_id,
            statistics=dict(published_documents=len(results),
                            searchable_documents=sum(1 for r in results if (r.get("searchable_chunks") or 0) > 0),
                            intentionally_hidden=sum(1 for r in results if r.get("hidden_reason")),
                            documents_with_problems=len(problems),
                            chunks=sum(r.get("chunks") or 0 for r in results),
                            embedded_chunks=sum(r.get("embedded_chunks") or 0 for r in results),
                            searchable_chunks=sum(r.get("searchable_chunks") or 0 for r in results),
                            searchable_chunks_by_language=by_lang, searchable_chunks_by_category=by_cat),
            problems=problems, documents=results)

    # ---------------------------------------------------------------- alerts
    def alert(self, report: dict[str, Any]) -> bool:
        """Notify admins that a published document is not (fully) searchable. Returns True if a notification was
        stored; at most one per document per 24 h so a recurring check does not flood the inbox."""
        if not self.notifications or report.get("ok"):
            return False
        doc_id = report.get("document_id")
        since = (datetime.now(UTC) - ALERT_DEDUPE).isoformat()
        try:
            recent, _ = self.store.select("admin_notifications", Query(eq={"kind": ALERT_KIND, "entity_id": doc_id},
                                                                       gte={"created_at": since}, limit=1))
            if recent:
                return False
        except Exception:  # noqa: BLE001 - dedupe is best effort; alerting matters more
            log.warning("could not check recent %s notifications", ALERT_KIND)
        title = (report.get("title") or "Unknown document")[:150]
        detail = ", ".join(report.get("problems") or [])
        self.notifications.notify(
            ALERT_KIND, f"Published but not searchable: {title}",
            f"v{report.get('version_number')}: {report.get('searchable_chunks', 0)}/{report.get('chunks', 0)} chunks "
            f"searchable, {report.get('embedded_chunks', 0)} embedded with {self.model_id} ({detail}). Students "
            "cannot find this document until it is re-indexed.", severity="error",
            entity_type="source_document", entity_id=doc_id, link=f"/admin/documents/{doc_id}")
        return True
