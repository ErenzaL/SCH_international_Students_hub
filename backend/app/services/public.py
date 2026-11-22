"""Read-only public views: only approved, published, non-private content is ever returned."""
from __future__ import annotations

from datetime import date
from typing import Any

from app.core.constants import CATEGORIES
from app.core.errors import NotFound
from app.repositories.base import Query, Store, get_many, get_one
from app.services.announcements import AnnouncementService, compute_status, excerpt, today_kst

PRIVATE_SOURCE_FILTER = {"authority_type": "supporter_submitted"}


class PublicService:
    def __init__(self, store: Store, announcements: AnnouncementService):
        self.store = store
        self.ann = announcements

    # ---------------------------------------------------------- categories
    def categories(self, with_counts: bool) -> list[dict[str, Any]]:
        counts_docs: dict[str, int] = {}
        counts_ann: dict[str, int] = {}
        if with_counts:
            anns, _ = self.store.select("announcements", Query(eq={"publication_status": "published"},
                                                                cols="id,category"))
            for a in anns:
                counts_ann[a["category"]] = counts_ann.get(a["category"], 0) + 1
            for d in self._public_documents_all():
                counts_docs[d["_category"]] = counts_docs.get(d["_category"], 0) + 1
        return [dict(slug=s, name=n, description=d, sort_order=o,
                     document_count=counts_docs.get(s, 0) if with_counts else None,
                     announcement_count=counts_ann.get(s, 0) if with_counts else None)
                for s, n, d, o in CATEGORIES]

    # -------------------------------------------------------- announcements
    def _source_ref(self, source: dict[str, Any] | None, doc: dict[str, Any] | None) -> dict[str, Any]:
        if not source:
            return dict(title=None, organization=None, url=None, authority_type=None, scope=None)
        return dict(title=source["title"], organization=source["organization"],
                    url=source.get("original_url") or (doc or {}).get("canonical_url"),
                    authority_type=source["authority_type"], scope=source["scope"])

    def _available_languages(self, announcement_ids: list[str]) -> dict[str, list[str]]:
        if not announcement_ids:
            return {}
        rows, _ = self.store.select("announcement_translations", Query(
            in_={"announcement_id": announcement_ids}, eq={"translation_status": "human_approved"},
            cols="announcement_id,language_code"))
        out: dict[str, list[str]] = {}
        for r in rows:
            out.setdefault(r["announcement_id"], []).append(r["language_code"])
        return out

    def _summaries(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        docs = get_many(self.store, "source_documents", [r["document_id"] for r in rows])
        sources = get_many(self.store, "knowledge_sources", [d["source_id"] for d in docs.values()])
        versions = get_many(self.store, "document_versions",
                            [d.get("current_version_id") for d in docs.values()])
        langs = self._available_languages([r["id"] for r in rows])
        today = today_kst()
        out = []
        for a in rows:
            doc = docs.get(a["document_id"]) or {}
            ver = versions.get(doc.get("current_version_id")) or {}
            src = sources.get(doc.get("source_id"))
            published = ver.get("source_published_at") or a.get("approved_at") or a["created_at"]
            out.append(dict(
                id=a["id"], title=a["title"], category=a["category"], target_audience=a.get("target_audience"),
                event_date=a.get("event_date"), deadline=a.get("deadline"), published_at=published,
                status=compute_status(a.get("valid_from"), a.get("deadline"), today),
                original_language=a["original_language"],
                available_languages=sorted({a["original_language"], *langs.get(a["id"], [])}),
                excerpt=excerpt(ver.get("extracted_text", "")), is_test_data=a["is_test_data"],
                source=self._source_ref(src, doc),
                _ver=ver, _doc=doc))
        return out

    def list_announcements(self, *, q: str | None, category: str | None, language: str | None, status: str | None,
                           page: int, size: int) -> tuple[list[dict[str, Any]], int]:
        today = today_kst().isoformat()
        eq: dict[str, Any] = {"publication_status": "published"}
        if category:
            eq["category"] = category
        gt: dict[str, Any] = {}
        lt: dict[str, Any] = {}
        gte: dict[str, Any] = {}
        in_: dict[str, list[Any]] = {}
        is_null: dict[str, bool] = {}
        # status filter -> date predicates (deadline is a date: "active" includes today)
        if status == "expired":
            lt["deadline"] = today
        elif status == "upcoming":
            gt["valid_from"] = today
        elif status == "active":
            gte["deadline"] = today  # NULL deadlines handled below
        or_eq: list[tuple[str, Any]] = []
        if language:
            ids = {r["announcement_id"] for r in self.store.select("announcement_translations", Query(
                eq={"language_code": language, "translation_status": "human_approved"}, cols="announcement_id"))[0]}
            if language == "ko":
                or_eq = [("original_language", "ko")]
            else:
                in_["id"] = list(ids) or ["00000000-0000-0000-0000-000000000000"]
        rows, total = self._query_announcements(eq, gt, lt, gte, in_, is_null, or_eq, q, status, page, size)
        return [{k: v for k, v in s.items() if not k.startswith("_")} for s in self._summaries(rows)], total

    def _query_announcements(self, eq, gt, lt, gte, in_, is_null, or_eq, q, status, page, size):  # type: ignore[no-untyped-def]
        # "active" must also admit announcements without a deadline, which a single AND filter cannot express,
        # so filter by status after fetching candidates (announcement volume is small) and paginate in memory.
        query = Query(eq=eq, gt=gt, lt=lt, in_=in_, is_null=is_null, or_eq=or_eq,
                      or_ilike=[("title", q), ("target_audience", q)] if q else [],
                      order=[("created_at", True)])
        rows, _ = self.store.select("announcements", query)
        if status:
            today = today_kst()
            rows = [r for r in rows if compute_status(r.get("valid_from"), r.get("deadline"), today) == status]
        total = len(rows)
        rows.sort(key=lambda r: (r.get("approved_at") or r["created_at"]), reverse=True)
        start = (page - 1) * size
        return rows[start : start + size], total

    def get_announcement(self, announcement_id: str) -> dict[str, Any]:
        a = get_one(self.store, "announcements", id=announcement_id)
        if a is None or a["publication_status"] != "published":
            raise NotFound("Announcement not found.")
        s = self._summaries([a])[0]
        ver = s.pop("_ver")
        s.pop("_doc")
        if not ver:
            raise NotFound("Announcement not found.")
        s.update(body=ver["extracted_text"], source_published_at=ver.get("source_published_at"),
                 verified_at=ver.get("approved_at"), version_id=ver["id"],
                 translations=[dict(language=t["language_code"], title=t["title"], body=t["body"],
                                    translation_status="human_approved", reviewed_at=t["reviewed_at"])
                               for t in self.ann._translations(a["id"], public=True)])
        return s

    # ------------------------------------------------------------ knowledge
    def _eligible_sources(self, category: str | None, scope: str | None) -> dict[str, dict[str, Any]]:
        eq: dict[str, Any] = {"is_active": True}
        if category:
            eq["category"] = category
        if scope:
            eq["scope"] = scope
        rows, _ = self.store.select("knowledge_sources", Query(eq=eq, neq=PRIVATE_SOURCE_FILTER))
        return {r["id"]: r for r in rows if r["source_type"] != "kakao_message"}

    def _public_documents_all(self) -> list[dict[str, Any]]:
        sources = self._eligible_sources(None, None)
        if not sources:
            return []
        docs, _ = self.store.select("source_documents", Query(
            in_={"source_id": list(sources)}, eq={"is_canceled": False}, neq={"document_type": "announcement"},
            is_null={"current_version_id": False}))
        return [{**d, "_category": sources[d["source_id"]]["category"]} for d in docs]

    def list_documents(self, *, q: str | None, category: str | None, scope: str | None, page: int, size: int
                       ) -> tuple[list[dict[str, Any]], int]:
        sources = self._eligible_sources(category, scope)
        if not sources:
            return [], 0
        docs, total = self.store.select("source_documents", Query(
            in_={"source_id": list(sources)}, eq={"is_canceled": False}, neq={"document_type": "announcement"},
            is_null={"current_version_id": False}, or_ilike=[("title", q)] if q else [],
            order=[("updated_at", True)], limit=size, offset=(page - 1) * size), count=True)
        versions = get_many(self.store, "document_versions", [d["current_version_id"] for d in docs])
        return [self._doc_summary(d, sources[d["source_id"]], versions.get(d["current_version_id"], {}))
                for d in docs], total or 0

    @staticmethod
    def _doc_summary(d: dict[str, Any], s: dict[str, Any], v: dict[str, Any]) -> dict[str, Any]:
        return dict(id=d["id"], title=d["title"], category=s["category"], organization=s["organization"],
                    scope=s["scope"], authority_type=s["authority_type"], language=d["language"],
                    source_url=s.get("original_url") or d.get("canonical_url"),
                    source_published_at=v.get("source_published_at"), verified_at=v.get("approved_at"),
                    excerpt=excerpt(v.get("extracted_text", "")))

    def get_document(self, document_id: str) -> dict[str, Any]:
        d = get_one(self.store, "source_documents", id=document_id)
        if d is None or d["is_canceled"] or not d["current_version_id"] or d["document_type"] == "announcement":
            raise NotFound("Document not found.")
        s = get_one(self.store, "knowledge_sources", id=d["source_id"])
        if s is None or not s["is_active"] or s["authority_type"] == "supporter_submitted" \
                or s["source_type"] == "kakao_message":
            raise NotFound("Document not found.")
        v = get_one(self.store, "document_versions", id=d["current_version_id"])
        if v is None or v["verification_status"] != "approved":
            raise NotFound("Document not found.")
        out = self._doc_summary(d, s, v)
        out.update(content=v["extracted_text"], version_id=v["id"], version_number=v["version_number"])
        return out


_ = date
