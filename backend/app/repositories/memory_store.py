"""In-memory Store that mirrors the SQL schema/semantics (constraints + RPC functions).

Used by unit tests and scripts/demo_pipeline.py. It is a *test double*: the API never
falls back to it when Supabase is unconfigured (that returns 503 instead).
Keep behaviour in sync with supabase/migrations/*.sql.
"""
from __future__ import annotations

import copy
import math
import threading
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.errors import DuplicateError, Forbidden, InvalidState, NotFound, ValidationFailed
from app.repositories.base import FileStorage, Query, Row

TABLES = (
    "categories", "profiles", "supporter_languages", "knowledge_sources", "source_documents",
    "document_versions", "document_chunks", "ingestion_jobs", "audit_log", "announcements",
    "announcement_translations", "ingestion_events", "allowed_source_domains",
)
NO_ID = {"categories", "profiles", "supporter_languages", "audit_log", "ingestion_events", "allowed_source_domains"}
HAS_UPDATED_AT = {"knowledge_sources", "source_documents", "announcements", "announcement_translations"}


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


class MemoryStore:
    def __init__(self) -> None:
        self.t: dict[str, list[Row]] = {name: [] for name in TABLES}
        self._lock = threading.RLock()
        self._audit_seq = 0

    # ------------------------------------------------------------------ utils
    def _defaults(self, table: str, row: Row) -> Row:
        r = copy.deepcopy(row)
        if table not in NO_ID:
            r.setdefault("id", str(uuid.uuid4()))
        elif table in ("audit_log", "ingestion_events") and "id" not in r:
            self._audit_seq += 1
            r["id"] = self._audit_seq
        d: dict[str, Any] = {
            "knowledge_sources": dict(status="registered", sync_frequency="manual", is_active=True, is_test_data=False,
                                      language="ko", original_url=None, last_checked_at=None, last_ingestion_result=None,
                                      created_by=None, config={}, stale_after_days=None, last_success_at=None,
                                      last_change_at=None),
            "source_documents": dict(is_canceled=False, document_type="webpage", language="ko", current_version_id=None,
                                     canonical_url=None, external_id=None, canceled_at=None, canceled_reason=None,
                                     metadata={}),
            "document_versions": dict(verification_status="pending_review", was_approved=False, fetched_at=now_iso(),
                                      source_published_at=None, valid_from=None, valid_until=None, approved_by=None,
                                      approved_at=None, rejected_by=None, rejected_at=None, rejected_reason=None,
                                      created_by=None, raw_text=None, structured_data={}, extraction_meta={},
                                      original_file=None, edited_by=None, edited_at=None, review_note=None,
                                      submitted_at=None, indexing_status="not_indexed", indexed_at=None,
                                      indexing_error=None),
            "document_chunks": dict(chunk_strategy="v1", embedding=None, embedding_model=None, heading=None,
                                    token_count=None, page_start=None, page_end=None),
            "ingestion_jobs": dict(status="queued", trigger="manual", outcome=None, document_id=None, version_id=None,
                                   payload={}, error_code=None, error_message=None, statistics={}, requested_by=None,
                                   started_at=None, completed_at=None, job_type="ingest", attempts=0, max_attempts=3,
                                   run_after=now_iso(), heartbeat_at=None, locked_by=None),
            "announcements": dict(publication_status="draft", original_language="ko", source_type="manual_text",
                                  is_test_data=False, target_audience=None, event_date=None, deadline=None,
                                  valid_from=None, evidence_note=None, evidence_url=None, created_by=None,
                                  submitted_at=None, approved_by=None, approved_at=None, rejection_reason=None,
                                  canceled_at=None),
            "announcement_translations": dict(translation_status="machine_draft", reviewed_by=None, reviewed_at=None),
            "profiles": dict(role="student", preferred_language="en", display_name=None, email=None),
            "audit_log": dict(details={}, actor_id=None, entity_id=None),
            "ingestion_events": dict(level="info", data={}),
            "allowed_source_domains": dict(note=None, added_by=None),
        }.get(table, {})
        for k, v in d.items():
            r.setdefault(k, v)
        if table not in ("categories", "profiles", "supporter_languages"):
            r.setdefault("created_at", now_iso())
        if table in HAS_UPDATED_AT:
            r.setdefault("updated_at", now_iso())
        if table == "profiles":
            r.setdefault("created_at", now_iso())
        return r

    def _check_unique(self, table: str, row: Row, ignore_id: Any = None) -> None:
        rows = [x for x in self.t[table] if x.get("id") != ignore_id or ignore_id is None]

        def dup(pred) -> None:  # type: ignore[no-untyped-def]
            if any(pred(x) for x in rows):
                raise DuplicateError(f"duplicate key on {table}")

        if table == "profiles":
            dup(lambda x: x["id"] == row["id"])
        elif table == "knowledge_sources" and row.get("source_type") in ("website", "sch_board") and row.get("original_url"):
            dup(lambda x: x.get("source_type") == row["source_type"] and x.get("original_url") == row["original_url"])
        elif table == "allowed_source_domains":
            dup(lambda x: x["domain"] == row["domain"])
        elif table == "source_documents":
            if row.get("canonical_url"):
                dup(lambda x: x["source_id"] == row["source_id"] and x.get("canonical_url") == row["canonical_url"])
            if row.get("external_id"):
                dup(lambda x: x["source_id"] == row["source_id"] and x.get("external_id") == row["external_id"])
        elif table == "document_versions":
            dup(lambda x: x["document_id"] == row["document_id"] and x["version_number"] == row["version_number"])
            dup(lambda x: x["document_id"] == row["document_id"] and x["content_hash"] == row["content_hash"])
            if row["verification_status"] in ("draft", "pending_review"):
                dup(lambda x: x["document_id"] == row["document_id"]
                    and x["verification_status"] in ("draft", "pending_review"))
        elif table == "document_chunks":
            dup(lambda x: x["version_id"] == row["version_id"] and x["chunk_index"] == row["chunk_index"])
        elif table == "announcements":
            dup(lambda x: x["document_id"] == row["document_id"])
        elif table == "announcement_translations":
            dup(lambda x: x["announcement_id"] == row["announcement_id"] and x["language_code"] == row["language_code"])

    @staticmethod
    def _get(r: Row, c: str) -> Any:
        if "->>" in c:  # PostgREST JSON path filter, e.g. original_file->>sha256
            col, key = c.split("->>", 1)
            val = (r.get(col) or {}).get(key)
            return None if val is None else str(val)
        return r.get(c)

    @classmethod
    def _match(cls, r: Row, q: Query) -> bool:
        for c, v in q.eq.items():
            if cls._get(r, c) != v:
                return False
        for c, v in q.neq.items():
            if r.get(c) == v:
                return False
        for c, vals in q.in_.items():
            if r.get(c) not in vals:
                return False
        for c, v in q.gte.items():
            if r.get(c) is None or r[c] < v:
                return False
        for c, v in q.lte.items():
            if r.get(c) is None or r[c] > v:
                return False
        for c, v in q.gt.items():
            if r.get(c) is None or r[c] <= v:
                return False
        for c, v in q.lt.items():
            if r.get(c) is None or r[c] >= v:
                return False
        for c, isn in q.is_null.items():
            if (r.get(c) is None) != isn:
                return False
        if q.or_ilike and not any(t.lower() in str(r.get(c) or "").lower() for c, t in q.or_ilike):
            return False
        return not (q.or_eq and not any(r.get(c) == v for c, v in q.or_eq))

    # ------------------------------------------------------------- primitives
    def select(self, table: str, query: Query | None = None, *, count: bool = False):  # type: ignore[no-untyped-def]
        query = query or Query()
        with self._lock:
            rows = [r for r in self.t[table] if self._match(r, query)]
            for col, desc in reversed(query.order):
                rows.sort(key=lambda r, c=col: (r.get(c) is None, r.get(c)), reverse=desc)
            total = len(rows)
            rows = rows[query.offset :]
            if query.limit is not None:
                rows = rows[: query.limit]
            return copy.deepcopy(rows), (total if count else None)

    def insert(self, table: str, row: Row) -> Row:
        with self._lock:
            r = self._defaults(table, row)
            self._check_unique(table, r)
            self.t[table].append(r)
            return copy.deepcopy(r)

    def insert_many(self, table: str, rows: list[Row]) -> list[Row]:
        return [self.insert(table, r) for r in rows]

    def update(self, table: str, patch: Row, eq: dict[str, Any]) -> list[Row]:
        with self._lock:
            out = []
            for r in self.t[table]:
                if all(r.get(c) == v for c, v in eq.items()):
                    if table == "document_versions" and r["verification_status"] in ("approved", "superseded", "rejected"):
                        for k in ("extracted_text", "content_hash", "document_id", "version_number", "structured_data"):
                            if k in patch and patch[k] != r.get(k):
                                raise InvalidState("version content is immutable once reviewed")
                    if table == "document_versions":
                        for k in ("raw_text", "original_file"):
                            if r.get(k) is not None and k in patch and patch[k] != r[k]:
                                raise InvalidState(f"version {k} is immutable")
                    if table == "source_documents" and patch.get("current_version_id") not in (None, r.get("current_version_id")):
                        v = self._ver(patch["current_version_id"])
                        if not v or v["document_id"] != r["id"] or v["verification_status"] != "approved":
                            raise ValidationFailed("current_version_id must reference an approved version")
                    candidate = {**r, **copy.deepcopy(patch)}
                    if table in HAS_UPDATED_AT:
                        candidate["updated_at"] = now_iso()
                    if table == "document_versions" and candidate["verification_status"] in ("draft", "pending_review"):
                        if any(x is not r and x["document_id"] == r["document_id"]
                               and x["verification_status"] in ("draft", "pending_review") for x in self.t[table]):
                            raise DuplicateError("one open version per document")
                    r.update(candidate)
                    out.append(copy.deepcopy(r))
            return out

    def delete(self, table: str, eq: dict[str, Any]) -> None:
        with self._lock:
            self.t[table] = [r for r in self.t[table] if not all(r.get(c) == v for c, v in eq.items())]
            if table == "document_versions":
                ids = {r["id"] for r in self.t[table]}
                self.t["document_chunks"] = [c for c in self.t["document_chunks"] if c["version_id"] in ids]

    # ------------------------------------------------------------ RPC mirror
    def rpc(self, name: str, params: dict[str, Any]) -> Any:
        fn = getattr(self, f"_rpc_{name}", None)
        if fn is None:
            raise NotFound(f"unknown rpc {name}")
        with self._lock:
            return copy.deepcopy(fn(**params))

    def _ver(self, vid: str) -> Row | None:
        return next((v for v in self.t["document_versions"] if v["id"] == vid), None)

    def _doc(self, did: str) -> Row | None:
        return next((d for d in self.t["source_documents"] if d["id"] == did), None)

    def _ann(self, aid: str) -> Row | None:
        return next((a for a in self.t["announcements"] if a["id"] == aid), None)

    def _assert_admin(self, actor: str | None) -> None:
        p = next((p for p in self.t["profiles"] if p["id"] == actor), None)
        if not p or p["role"] not in ("super_admin", "admin"):
            raise Forbidden("forbidden: admin role required")

    def _audit(self, action: str, entity_type: str, entity_id: str | None, actor: str | None, details: Row) -> None:
        self._audit_seq += 1
        self.t["audit_log"].append(self._defaults("audit_log", dict(
            id=self._audit_seq, action=action, entity_type=entity_type, entity_id=entity_id, actor_id=actor,
            details=details)))

    def _refresh_source(self, source_id: str) -> None:
        s = next((s for s in self.t["knowledge_sources"] if s["id"] == source_id), None)
        if not s:
            return
        docs = [d for d in self.t["source_documents"] if d["source_id"] == source_id]
        dids = {d["id"] for d in docs}
        if not s["is_active"]:
            new = "inactive"
        elif any(v["verification_status"] == "pending_review" and v["document_id"] in dids
                 for v in self.t["document_versions"]):
            new = "pending_review"
        elif any(d["current_version_id"] for d in docs):
            new = "approved"
        else:
            new = "registered"
        if s["status"] not in ("fetching", "processing"):
            s["status"] = new

    def _rpc_approve_document_version(self, p_version_id: str, p_actor: str, p_note: str | None = None) -> Row:
        self._assert_admin(p_actor)
        v = self._ver(p_version_id)
        if not v:
            raise NotFound("version not found")
        if v["verification_status"] != "pending_review":
            raise InvalidState(f"only pending_review versions can be approved (is {v['verification_status']})")
        d = self._doc(v["document_id"])
        assert d is not None
        if d["is_canceled"]:
            raise InvalidState("document is canceled")
        if (v.get("extraction_meta") or {}).get("requires_field_confirmation") and \
                not (v.get("structured_data") or {}).get("fields_confirmed"):
            raise InvalidState("OCR-derived content needs the reviewer to confirm key fields first")
        chunks = [c for c in self.t["document_chunks"] if c["version_id"] == v["id"]]
        if not chunks or any(c["embedding"] is None for c in chunks):
            raise InvalidState("version has no complete embeddings", code="not_indexed")
        prev_id = d["current_version_id"]
        if d["current_version_id"] and d["current_version_id"] != v["id"]:
            prev = self._ver(d["current_version_id"])
            if prev and prev["verification_status"] == "approved":
                prev["verification_status"] = "superseded"
        v.update(verification_status="approved", was_approved=True, approved_by=p_actor, approved_at=now_iso(),
                 rejected_by=None, rejected_at=None, rejected_reason=None, indexing_status="indexed",
                 indexed_at=v.get("indexed_at") or now_iso(), indexing_error=None)
        d["current_version_id"] = v["id"]
        self._refresh_source(d["source_id"])
        self._audit("version.approve", "document_version", v["id"], p_actor,
                    {"document_id": d["id"], "version_number": v["version_number"], "note": p_note,
                     "content_hash": v["content_hash"], "previous_status": "pending_review", "new_status": "approved",
                     "superseded_version": prev_id})
        return v

    def _rpc_reject_document_version(self, p_version_id: str, p_actor: str, p_reason: str) -> Row:
        self._assert_admin(p_actor)
        if not p_reason or not p_reason.strip():
            raise ValidationFailed("a rejection reason is required")
        v = self._ver(p_version_id)
        if not v:
            raise NotFound("version not found")
        if v["verification_status"] not in ("pending_review", "draft"):
            raise InvalidState(f"only draft/pending versions can be rejected (is {v['verification_status']})")
        v.update(verification_status="rejected", rejected_by=p_actor, rejected_at=now_iso(), rejected_reason=p_reason)
        d = self._doc(v["document_id"])
        assert d is not None
        self._refresh_source(d["source_id"])
        self._audit("version.reject", "document_version", v["id"], p_actor,
                    {"document_id": d["id"], "version_number": v["version_number"], "reason": p_reason})
        return v

    def _rpc_rollback_document_version(self, p_document_id: str, p_version_id: str, p_actor: str,
                                       p_note: str | None = None) -> Row:
        self._assert_admin(p_actor)
        d = self._doc(p_document_id)
        if not d:
            raise NotFound("document not found")
        if d["is_canceled"]:
            raise InvalidState("document is canceled")
        v = self._ver(p_version_id)
        if not v or v["document_id"] != d["id"]:
            raise NotFound("version not found for document")
        if not v["was_approved"]:
            raise InvalidState("only previously approved versions can be restored")
        if d["current_version_id"] == v["id"]:
            raise InvalidState("version is already current")
        chunks = [c for c in self.t["document_chunks"] if c["version_id"] == v["id"]]
        if not chunks or any(c["embedding"] is None for c in chunks):
            raise InvalidState("restored version has no complete embeddings", code="not_indexed")
        prev = d["current_version_id"]
        if prev:
            self._ver(prev)["verification_status"] = "superseded"  # type: ignore[index]
        v.update(verification_status="approved", approved_by=p_actor, approved_at=now_iso())
        d["current_version_id"] = v["id"]
        self._refresh_source(d["source_id"])
        self._audit("document.rollback", "source_document", d["id"], p_actor,
                    {"from_version": prev, "to_version": v["id"], "note": p_note})
        return d

    def _rpc_cancel_document(self, p_document_id: str, p_actor: str, p_reason: str) -> Row:
        self._assert_admin(p_actor)
        if not p_reason or not p_reason.strip():
            raise ValidationFailed("a reason is required")
        d = self._doc(p_document_id)
        if not d:
            raise NotFound("document not found")
        d.update(is_canceled=True, canceled_at=now_iso(), canceled_reason=p_reason)
        for a in self.t["announcements"]:
            if a["document_id"] == d["id"] and a["publication_status"] == "published":
                a.update(publication_status="canceled", canceled_at=now_iso())
        self._audit("document.cancel", "source_document", d["id"], p_actor, {"reason": p_reason})
        return d

    def _rpc_submit_announcement(self, p_announcement_id: str, p_actor: str) -> Row:
        p = next((p for p in self.t["profiles"] if p["id"] == p_actor), None)
        if not p or p["role"] == "student":
            raise Forbidden("forbidden: staff role required")
        a = self._ann(p_announcement_id)
        if not a:
            raise NotFound("announcement not found")
        if p["role"] == "supporter" and a["created_by"] != p_actor:
            raise Forbidden("forbidden: supporters may only submit their own announcements")
        if a["publication_status"] not in ("draft", "rejected"):
            raise InvalidState(f"announcement is {a['publication_status']}")
        drafts = [v for v in self.t["document_versions"]
                  if v["document_id"] == a["document_id"] and v["verification_status"] == "draft"]
        if not drafts:
            raise InvalidState("no draft version to submit")
        drafts[0]["verification_status"] = "pending_review"
        a.update(publication_status="pending_approval", submitted_at=now_iso(), rejection_reason=None)
        self._audit("announcement.submit", "announcement", a["id"], p_actor, {})
        return a

    def _pending_version_of(self, a: Row) -> Row | None:
        return next((v for v in self.t["document_versions"]
                     if v["document_id"] == a["document_id"] and v["verification_status"] == "pending_review"), None)

    def _rpc_approve_announcement(self, p_announcement_id: str, p_actor: str, p_note: str | None = None) -> Row:
        self._assert_admin(p_actor)
        a = self._ann(p_announcement_id)
        if not a:
            raise NotFound("announcement not found")
        if a["publication_status"] != "pending_approval":
            raise InvalidState(f"announcement is {a['publication_status']}")
        v = self._pending_version_of(a)
        if not v:
            raise InvalidState("no pending version")
        # atomic in SQL; here: validate first so a failure leaves state untouched
        self._rpc_approve_document_version(v["id"], p_actor, p_note)
        a.update(publication_status="published", approved_by=p_actor, approved_at=now_iso())
        self._audit("announcement.approve", "announcement", a["id"], p_actor, {"note": p_note})
        return a

    def _rpc_reject_announcement(self, p_announcement_id: str, p_actor: str, p_reason: str) -> Row:
        self._assert_admin(p_actor)
        if not p_reason or not p_reason.strip():
            raise ValidationFailed("a rejection reason is required")
        a = self._ann(p_announcement_id)
        if not a:
            raise NotFound("announcement not found")
        if a["publication_status"] != "pending_approval":
            raise InvalidState(f"announcement is {a['publication_status']}")
        v = self._pending_version_of(a)
        if v:
            self._rpc_reject_document_version(v["id"], p_actor, p_reason)
        a.update(publication_status="rejected", rejection_reason=p_reason)
        self._audit("announcement.reject", "announcement", a["id"], p_actor, {"reason": p_reason})
        return a

    def _rpc_cancel_announcement(self, p_announcement_id: str, p_actor: str, p_reason: str) -> Row:
        self._assert_admin(p_actor)
        if not p_reason or not p_reason.strip():
            raise ValidationFailed("a reason is required")
        a = self._ann(p_announcement_id)
        if not a:
            raise NotFound("announcement not found")
        if a["publication_status"] == "canceled":
            raise InvalidState("already canceled")
        d = self._doc(a["document_id"])
        assert d is not None
        d.update(is_canceled=True, canceled_at=now_iso(), canceled_reason=p_reason)
        a.update(publication_status="canceled", canceled_at=now_iso())
        self._audit("announcement.cancel", "announcement", a["id"], p_actor, {"reason": p_reason})
        return a

    def _rpc_search_knowledge(self, p_query_embedding: list[float] | None, p_query_tokens: list[str] | None,
                              p_model: str, p_category: str | None = None, p_match_count: int = 5,
                              p_mode: str = "hybrid") -> list[Row]:
        if p_mode not in ("hybrid", "vector", "keyword"):
            raise ValidationFailed("invalid mode")
        limit = min(max(p_match_count or 5, 1), 50)
        pool = limit * 4
        now = datetime.now(UTC)
        cand: list[tuple[Row, Row, Row, Row]] = []
        for c in self.t["document_chunks"]:
            v = self._ver(c["version_id"])
            if not v or v["verification_status"] != "approved":
                continue
            d = self._doc(v["document_id"])
            if not d or d["current_version_id"] != v["id"] or d["is_canceled"]:
                continue
            s = next((s for s in self.t["knowledge_sources"] if s["id"] == d["source_id"]), None)
            if not s or not s["is_active"]:
                continue
            if v["valid_from"] and datetime.fromisoformat(v["valid_from"]) > now:
                continue
            if v["valid_until"] and datetime.fromisoformat(v["valid_until"]) <= now:
                continue
            if p_category and s["category"] != p_category:
                continue
            cand.append((c, v, d, s))

        vec: dict[str, tuple[int, float]] = {}
        if p_mode != "keyword" and p_query_embedding is not None:
            scored = [(c["id"], _cos(p_query_embedding, c["embedding"])) for c, *_ in cand
                      if c["embedding"] is not None and c["embedding_model"] == p_model]
            scored.sort(key=lambda x: -x[1])
            vec = {cid: (i + 1, sim) for i, (cid, sim) in enumerate(scored[:pool])}
        kw: dict[str, tuple[int, float]] = {}
        toks = [t.lower() for t in (p_query_tokens or []) if t]
        if p_mode != "vector" and toks:
            scored2 = []
            for c, *_ in cand:
                hay = ((c["heading"] or "") + " " + c["content"]).lower()
                hits = sum(1 for t in toks if t in hay)
                if hits:
                    scored2.append((c["id"], hits / len(toks)))
            scored2.sort(key=lambda x: -x[1])
            kw = {cid: (i + 1, r) for i, (cid, r) in enumerate(scored2[:pool])}

        fused = []
        for c, v, d, s in cand:
            cid = c["id"]
            if cid not in vec and cid not in kw:
                continue
            rrf = (1.0 / (60 + vec[cid][0]) if cid in vec else 0) + (1.0 / (60 + kw[cid][0]) if cid in kw else 0)
            fused.append((rrf, cid, c, v, d, s))
        fused.sort(key=lambda x: (-x[0], x[1]))
        out = []
        for rrf, cid, c, v, d, s in fused[:limit]:
            out.append(dict(
                chunk_id=cid, document_id=d["id"], version_id=v["id"], document_title=d["title"], heading=c["heading"],
                passage=c["content"], page=c["page_start"], similarity=vec[cid][1] if cid in vec else None,
                keyword_rank=kw[cid][1] if cid in kw else None, score=rrf,
                source_url=s["original_url"] or d["canonical_url"], organization=s["organization"],
                authority_type=s["authority_type"], scope=s["scope"], category=s["category"],
                source_published_at=v["source_published_at"], verified_at=v["approved_at"], language=d["language"]))
        return out

    # ------------------------------------------------------------- Phase 2
    def _rpc_claim_ingestion_job(self, p_worker: str, p_stale_seconds: int = 900) -> list[Row]:
        now = datetime.now(UTC)
        for j in self.t["ingestion_jobs"]:
            if j["status"] != "running":
                continue
            beat = j.get("heartbeat_at") or j.get("started_at") or j["created_at"]
            if (now - datetime.fromisoformat(beat)).total_seconds() > max(p_stale_seconds, 60):
                if j["attempts"] < j["max_attempts"]:
                    j.update(status="queued", locked_by=None, run_after=now_iso())
                else:
                    j.update(status="failed", locked_by=None, error_code="interrupted", completed_at=now_iso(),
                             error_message="The worker stopped while this job was running and the retry limit was reached.")
        queued = sorted((j for j in self.t["ingestion_jobs"] if j["status"] == "queued"
                         and datetime.fromisoformat(j["run_after"]) <= now), key=lambda j: j["created_at"])
        if not queued:
            return []
        j = queued[0]
        j.update(status="running", attempts=j["attempts"] + 1, started_at=now_iso(), heartbeat_at=now_iso(),
                 locked_by=p_worker)
        return [j]

    def _rpc_request_version_changes(self, p_version_id: str, p_actor: str, p_note: str) -> Row:
        self._assert_admin(p_actor)
        if not p_note or len(p_note.strip()) < 3:
            raise ValidationFailed("a note explaining the requested changes is required")
        v = self._ver(p_version_id)
        if not v:
            raise NotFound("version not found")
        if v["verification_status"] != "pending_review":
            raise InvalidState(f"only pending_review versions can be sent back (is {v['verification_status']})")
        v.update(verification_status="draft", review_note=p_note)
        d = self._doc(v["document_id"])
        assert d is not None
        self._refresh_source(d["source_id"])
        self._audit("version.request_changes", "document_version", v["id"], p_actor,
                    {"document_id": d["id"], "version_number": v["version_number"], "note": p_note,
                     "previous_status": "pending_review", "new_status": "draft"})
        return v

    def _rpc_submit_version_for_review(self, p_version_id: str, p_actor: str) -> Row:
        p = next((p for p in self.t["profiles"] if p["id"] == p_actor), None)
        if not p or p["role"] == "student":
            raise Forbidden("forbidden: staff role required")
        v = self._ver(p_version_id)
        if not v:
            raise NotFound("version not found")
        if p["role"] == "supporter" and v.get("created_by") != p_actor:
            raise Forbidden("forbidden: supporters may only submit their own submissions")
        if v["verification_status"] != "draft":
            raise InvalidState(f"only draft versions can be submitted (is {v['verification_status']})")
        v.update(verification_status="pending_review", submitted_at=now_iso())
        d = self._doc(v["document_id"])
        assert d is not None
        self._refresh_source(d["source_id"])
        self._audit("version.submit", "document_version", v["id"], p_actor,
                    {"document_id": d["id"], "version_number": v["version_number"],
                     "previous_status": "draft", "new_status": "pending_review"})
        return v

    def _searchable(self) -> list[tuple[Row, Row, Row, Row]]:
        now = datetime.now(UTC)
        out = []
        for c in self.t["document_chunks"]:
            v = self._ver(c["version_id"])
            if not v or v["verification_status"] != "approved":
                continue
            d = self._doc(v["document_id"])
            if not d or d["current_version_id"] != v["id"] or d["is_canceled"]:
                continue
            s = next((s for s in self.t["knowledge_sources"] if s["id"] == d["source_id"]), None)
            if not s or not s["is_active"]:
                continue
            if v["valid_from"] and datetime.fromisoformat(v["valid_from"]) > now:
                continue
            if v["valid_until"] and datetime.fromisoformat(v["valid_until"]) <= now:
                continue
            out.append((c, v, d, s))
        return out

    def _rpc_search_knowledge_v2(self, p_query_embedding: list[float] | None, p_query_tokens: list[str] | None,
                                 p_exact_terms: list[str] | None, p_model: str, p_category: str | None = None,
                                 p_scope: str | None = None, p_authority: list[str] | None = None,
                                 p_match_count: int = 5, p_mode: str = "hybrid") -> list[Row]:
        import re as _re

        if p_mode not in ("hybrid", "vector", "keyword"):
            raise ValidationFailed("invalid mode")
        limit = min(max(p_match_count or 5, 1), 50)
        pool = limit * 4
        cand = [(c, v, d, s) for c, v, d, s in self._searchable()
                if (not p_category or s["category"] == p_category) and (not p_scope or s["scope"] == p_scope)
                and (not p_authority or s["authority_type"] in p_authority)]
        exact = [t for t in (p_exact_terms or []) if _re.fullmatch(r"[A-Za-z0-9]+([ -][A-Za-z0-9]+)*", t)
                 and 2 <= len(t) <= 40] if p_mode != "vector" else []
        pats = [_re.compile(r"(^|[^0-9A-Za-z])" + _re.escape(t) + r"($|[^0-9A-Za-z])", _re.I) for t in exact]
        vec: dict[str, tuple[int, float]] = {}
        if p_mode != "keyword" and p_query_embedding is not None:
            scored = [(c["id"], _cos(p_query_embedding, c["embedding"])) for c, *_ in cand
                      if c["embedding"] is not None and c["embedding_model"] == p_model]
            scored.sort(key=lambda x: -x[1])
            vec = {cid: (i + 1, sim) for i, (cid, sim) in enumerate(scored[:pool])}
        kw: dict[str, tuple[int, float, bool]] = {}
        toks = [t.lower() for t in (p_query_tokens or []) if t] if p_mode != "vector" else []
        if toks or pats:
            scored2 = []
            for c, *_ in cand:
                hay = (c["heading"] or "") + " " + c["content"]
                hits = sum(1 for t in toks if t in hay.lower())
                ex = any(p.search(hay) for p in pats)
                if hits or ex:
                    scored2.append((c["id"], (hits / len(toks) if toks else 0) + (1.0 if ex else 0), ex))
            scored2.sort(key=lambda x: (-x[1], x[0]))
            kw = {cid: (i + 1, r, ex) for i, (cid, r, ex) in enumerate(scored2[:pool])}
        fused = []
        for c, v, d, s in cand:
            cid = c["id"]
            if cid not in vec and cid not in kw:
                continue
            rrf = (1.0 / (60 + vec[cid][0]) if cid in vec else 0) + (1.0 / (60 + kw[cid][0]) if cid in kw else 0)
            rrf += 0.001 if s["authority_type"] in ("official_government", "official_university") else 0
            fused.append((rrf, cid, c, v, d, s))
        fused.sort(key=lambda x: (-x[0], x[1]))
        return [dict(
            chunk_id=cid, document_id=d["id"], version_id=v["id"], source_id=s["id"], document_title=d["title"],
            heading=c["heading"], passage=c["content"], page=c["page_start"],
            similarity=vec[cid][1] if cid in vec else None, keyword_rank=kw[cid][1] if cid in kw else None,
            exact_match=kw[cid][2] if cid in kw else False, score=rrf,
            source_url=d["canonical_url"] or s["original_url"], organization=s["organization"],
            authority_type=s["authority_type"], scope=s["scope"], category=s["category"], source_type=s["source_type"],
            source_published_at=v["source_published_at"], verified_at=v["approved_at"], valid_until=v["valid_until"],
            stale_after_days=s.get("stale_after_days"), language=d["language"])
            for rrf, cid, c, v, d, s in fused[:limit]]

    def _rpc_knowledge_stats(self) -> Row:
        src = self.t["knowledge_sources"]
        vers = self.t["document_versions"]
        succ = [s["last_success_at"] for s in src if s.get("last_success_at")]
        return dict(
            sources_total=len(src), sources_active=sum(1 for s in src if s["is_active"]),
            sources_failed=sum(1 for s in src if s["status"] in ("failed", "blocked")),
            versions_pending=sum(1 for v in vers if v["verification_status"] == "pending_review"),
            versions_draft=sum(1 for v in vers if v["verification_status"] == "draft"),
            documents_approved=sum(1 for d in self.t["source_documents"] if d["current_version_id"] and not d["is_canceled"]),
            jobs_failed=sum(1 for j in self.t["ingestion_jobs"] if j["status"] == "failed"),
            jobs_queued=sum(1 for j in self.t["ingestion_jobs"] if j["status"] in ("queued", "running")),
            searchable_chunks=len(self._searchable()), latest_success_at=max(succ) if succ else None)


class MemoryFileStorage(FileStorage):
    def __init__(self) -> None:
        self.files: dict[str, tuple[bytes, str]] = {}

    def upload(self, path: str, data: bytes, content_type: str) -> None:
        self.files[path] = (data, content_type)

    def download(self, path: str) -> bytes:
        if path not in self.files:
            raise NotFound("stored file not found")
        return self.files[path][0]

    def remove(self, path: str) -> None:
        self.files.pop(path, None)


def seed_categories(store: MemoryStore) -> None:
    from app.core.constants import CATEGORIES

    for slug, name, desc, order in CATEGORIES:
        store.insert("categories", dict(slug=slug, name=name, description=desc, sort_order=order))


_ = timedelta
