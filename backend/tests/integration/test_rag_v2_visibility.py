"""RAG v2 source integrity on REAL PostgreSQL: only approved, current, valid, active content can reach an answer.

One document per state, each carrying a unique marker word. The search (every mode), the assistant's retrieve + select
step, and the chunk counts used by hub scaling must return the approved control and nothing else.
Skipped unless a scratch stack is running (see test_postgres_integration.py).
"""
from __future__ import annotations

import uuid

import pytest

from app.repositories.base import Query
from tests.integration.test_postgres_integration import IT, sql
from tests.integration.test_postgres_integration import pytestmark as _skip

pytestmark = _skip
STATES = ("control", "draft", "pending", "superseded", "cancelled", "archived", "expired", "future", "inactive")


def _ingest(it: IT, svc, admin: str, title: str, text: str, src: dict | None = None):  # type: ignore[no-untyped-def]
    src = src or it.store.insert("knowledge_sources", dict(
        title=title, organization="SCH", source_type="manual_text", authority_type="official_university",
        scope="university", category="daily-living", language="en", original_url=None))
    job = svc.ingestion.ingest_text(src, title=title, text=text, requested_by=admin)
    return src, job


def _approve(it: IT, svc, admin: str, job: dict) -> None:  # type: ignore[no-untyped-def]
    v = it.store.select("document_versions", Query(eq={"id": job["version_id"]}))[0][0]
    if v["verification_status"] == "draft":
        it.store.update("document_versions", {"verification_status": "pending_review"}, {"id": v["id"]})
        v["verification_status"] = "pending_review"
    act = svc.ingestion.request_activation(v, admin, "rag v2 visibility test")
    svc.ingestion.run_job(act["id"])


@pytest.fixture(scope="module")
def world():  # type: ignore[no-untyped-def]
    it = IT()
    svc = it.app.state.services
    admin = it.users["admin"]
    tag = uuid.uuid4().hex[:6]
    mark = {s: f"qvx{s}{tag}" for s in STATES}
    body = "Notice about the {m} programme. Students who need the {m} service should apply at the office."
    jobs = {}
    for s in STATES:
        if s == "superseded":
            continue
        src, job = _ingest(it, svc, admin, f"{s} notice {tag}", body.format(m=mark[s]))
        jobs[s] = (src, job)
        if s == "pending":
            it.store.update("document_versions", {"verification_status": "pending_review"}, {"id": job["version_id"]})
        elif s != "draft":
            _approve(it, svc, admin, job)
    # superseded: version 1 (old marker) approved, then version 2 of the SAME document approved
    src, j1 = _ingest(it, svc, admin, f"superseded notice {tag}", body.format(m=mark["superseded"]))
    _approve(it, svc, admin, j1)
    _src, j2 = _ingest(it, svc, admin, f"superseded notice {tag}", body.format(m=f"qvxcurrent{tag}"), src=src)
    _approve(it, svc, admin, j2)
    assert j2["document_id"] == j1["document_id"] and j2["version_id"] != j1["version_id"]
    jobs["superseded"] = (src, j1)
    sql(f"update public.source_documents set is_canceled = true where id = '{jobs['cancelled'][1]['document_id']}'")
    sql(f"update public.source_documents set archived_at = now() where id = '{jobs['archived'][1]['document_id']}'")
    sql(f"update public.document_versions set valid_until = now() - interval '1 day' where id = '{jobs['expired'][1]['version_id']}'")
    sql(f"update public.document_versions set valid_from = now() + interval '1 day' where id = '{jobs['future'][1]['version_id']}'")
    sql(f"update public.knowledge_sources set is_active = false where id = '{jobs['inactive'][0]['id']}'")
    # the hidden states are not trivially absent: their chunks exist and are embedded, only the view hides them
    for s in ("superseded", "cancelled", "archived", "expired", "future", "inactive"):
        n = int(sql(f"select count(*) from public.document_chunks where version_id = '{jobs[s][1]['version_id']}' "
                    f"and embedding is not null"))
        assert n > 0, f"{s}: no indexed chunks, the test would prove nothing"
    return dict(it=it, svc=svc, mark=mark, jobs=jobs, tag=tag)


@pytest.mark.parametrize("mode", ["hybrid", "keyword", "vector", "hybrid_legacy"])
def test_search_returns_only_the_approved_current_valid_document(world, mode: str) -> None:  # type: ignore[no-untyped-def]
    svc, mark, jobs = world["svc"], world["mark"], world["jobs"]
    svc.retrieval.settings.retrieval_min_similarity = 0.0
    for s in STATES:
        hits = svc.retrieval.search(f"{mark[s]} programme", top_k=20, mode=mode)["results"]
        found = {h["document_id"] for h in hits if mark[s] in (h.get("passage") or "")}
        if s == "control":
            if mode != "vector":                     # hash test vectors carry no meaning; lexical modes must find it
                assert jobs["control"][1]["document_id"] in found, "positive control not found"
        else:
            assert not found, f"{s} content reached the {mode} search"


def test_the_assistant_never_selects_hidden_content(world) -> None:  # type: ignore[no-untyped-def]
    svc, mark = world["svc"], world["mark"]
    engine = svc.conversations.engine
    for s in STATES:
        q = f"How do I apply for the {mark[s]} service?"
        sources = engine._select(engine._retrieve([q], top_k=10)["hits"], set(), q)
        texts = " ".join(p.get("passage") or "" for src in sources for p in src["passages"])
        assert (mark[s] in texts) == (s == "control"), s


def test_hub_scaling_counts_only_searchable_versions(world) -> None:  # type: ignore[no-untyped-def]
    svc, jobs = world["svc"], world["jobs"]
    svc.retrieval._sizes = None                       # drop the cache
    counts = svc.retrieval.chunk_counts()
    assert jobs["control"][1]["version_id"] in counts
    for s in STATES:
        if s != "control":
            assert jobs[s][1]["version_id"] not in counts, s
