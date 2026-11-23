"""RAG document lifecycle: publication, updates (embedding reuse), failed indexing, validated activation and the
post-activation searchability check / admin alerts."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.errors import AppError
from app.repositories.base import Query
from app.services.embeddings.base import EmbeddingError
from app.services.ingestion.normalize import content_hash
from tests.test_phase2 import paste
from tests.test_rag_sync import approve, chunks, search

SECTIONS = [f"## Section {i}\n" + " ".join(f"Topic{i} sentence {j} about dormitory rules and visa step {i}." for j in range(40))
            for i in range(6)]


def svc(env):
    return env.app.state.services


def one(env, table, **eq):
    return env.store.select(table, Query(eq=eq))[0][0]


def notes(env, kind=None):
    items = env.client.get("/api/v1/admin/notifications", headers=env.auth("admin")).json()["items"]
    return [n for n in items if kind is None or n["kind"] == kind]


def published_doc(env):
    """A published (approved, current, searchable) document; returns (document_id, version_id)."""
    vid = paste(env, role="admin").json()["version_id"]
    approve(env, vid)
    return one(env, "document_versions", id=vid)["document_id"], vid


def new_version(env, document_id, text, **extra):
    prev = env.store.select("document_versions", Query(eq={"document_id": document_id},
                                                       order=[("version_number", True)]))[0][0]
    return env.store.insert("document_versions", dict(
        document_id=document_id, version_number=prev["version_number"] + 1, extracted_text=text,
        content_hash=content_hash(text), verification_status="pending_review", **extra))


def activate(env, version):
    job = svc(env).ingestion.request_activation(version, env.users["admin"], "test")
    while svc(env).jobs.run_once():
        pass
    return one(env, "ingestion_jobs", id=job["id"])


def count_embeddings(env):
    emb = svc(env).embedder
    calls = {"texts": 0}
    orig = emb.embed_passages

    def counting(texts):
        calls["texts"] += len(texts)
        return orig(texts)
    emb.embed_passages = counting
    return calls, lambda: setattr(emb, "embed_passages", orig)


# ------------------------------------------------------------------------------------------------ publication
def test_publication_records_index_stats_and_verifies_searchability(env):
    doc_id, vid = published_doc(env)
    v = one(env, "document_versions", id=vid)
    assert v["verification_status"] == "approved" and v["indexing_status"] == "indexed" and v["indexed_at"]
    job = env.store.select("ingestion_jobs", Query(eq={"job_type": "index_version"}))[0][0]
    st = job["statistics"]
    assert job["status"] == "succeeded" and job["outcome"] == "activated" and job["completed_at"]
    assert st["chunk_count"] == st["embedded_chunks"] == st["searchable_chunks"] >= 1
    assert st["searchability_ok"] is True and st["embedding_model"] == svc(env).embedder.model_id
    events = env.store.select("ingestion_events", Query(eq={"job_id": job["id"]}))[0]
    assert any(e["step"] == "verify" and "searchable" in e["message"] for e in events)
    assert any(a["action"] == "version.activate" for a in env.store.select("audit_log", Query())[0])
    assert notes(env, "version_activated") and not notes(env, "not_searchable")
    health = env.client.get("/api/v1/admin/rag/health", headers=env.auth("admin")).json()
    assert health["statistics"]["published_documents"] == 1 and health["problems"] == []
    assert health["statistics"]["searchable_chunks"] == st["chunk_count"]
    assert env.client.get("/api/v1/admin/rag/health", headers=env.auth("supporter")).status_code == 403


def test_scheduled_document_is_activated_but_reported_as_intentionally_hidden(env):
    doc_id, _ = published_doc(env)
    later = (datetime.now(UTC) + timedelta(days=3)).isoformat()
    job = activate(env, new_version(env, doc_id, SECTIONS[0], valid_from=later))
    assert job["status"] == "succeeded"
    assert job["statistics"]["hidden_reason"] == "scheduled" and job["statistics"]["searchability_ok"] is True
    assert not notes(env, "not_searchable")


# ------------------------------------------------------------------------------------------------ updates
def test_update_reuses_unchanged_chunk_embeddings_and_keeps_old_version_until_activation(env):
    doc_id, _ = published_doc(env)
    v2 = new_version(env, doc_id, "\n\n".join(SECTIONS))
    job2 = activate(env, v2)
    n = job2["statistics"]["chunk_count"]
    assert n >= 3 and job2["statistics"]["reused_from_other_versions"] == 0

    changed = SECTIONS[:-1] + ["## Section 5\nThe dormitory office moved to building B; apply online before Friday."]
    v3 = new_version(env, doc_id, "\n\n".join(changed))
    svc(env).indexer.index_version(v3["id"])   # ingestion-time chunking for review: no vectors are copied
    assert all(c["embedding"] is None for c in chunks(env, v3["id"]))
    assert all(h["version_id"] == v2["id"] for h in search(env, "Topic1 dormitory rules"))
    calls, restore = count_embeddings(env)
    try:
        job3 = activate(env, v3)
    finally:
        restore()
    st = job3["statistics"]
    assert job3["status"] == "succeeded" and st["chunk_count"] == len(chunks(env, v3["id"]))
    assert st["reused_from_other_versions"] >= 1 and calls["texts"] == st["chunk_count"] - st["reused_embeddings"]
    assert calls["texts"] < st["chunk_count"]          # only changed chunks were embedded
    assert all(c["embedding"] is not None for c in chunks(env, v3["id"]))
    assert one(env, "document_versions", id=v2["id"])["verification_status"] == "superseded"
    assert chunks(env, v2["id"])                        # old chunks are kept (reuse never modifies them)
    assert any(h["version_id"] == v3["id"] for h in search(env, "dormitory office building B"))


def test_reindex_parses_text_vectors_instead_of_dropping_them(env):
    """PostgREST returns pgvector values as text; reusing them must keep the embedding, not store NULL."""
    _doc, vid = published_doc(env)
    for c in chunks(env, vid):
        env.store.update("document_chunks", {"embedding": "[" + ",".join(f"{x:.6f}" for x in c["embedding"]) + "]"},
                         {"id": c["id"]})
    calls, restore = count_embeddings(env)
    try:
        st = svc(env).indexer.index_version(vid, embed=True)
    finally:
        restore()
    assert calls["texts"] == 0 and st["reused_embeddings"] == st["chunk_count"]
    assert all(isinstance(c["embedding"], list) for c in chunks(env, vid))


# ------------------------------------------------------------------------------------------------ failures
def test_failed_indexing_alerts_admins_and_previous_version_stays_searchable(env):
    doc_id, v1 = published_doc(env)
    v2 = new_version(env, doc_id, "\n\n".join(SECTIONS))
    emb = svc(env).embedder
    orig = emb.embed_passages

    def broken(_texts):
        raise EmbeddingError("model crashed")
    emb.embed_passages = broken
    try:
        job = svc(env).ingestion.request_activation(v2, env.users["admin"], None)
        svc(env).jobs.run_once()                      # attempt 1: transient -> re-queued with backoff
        assert one(env, "ingestion_jobs", id=job["id"])["status"] == "queued"
        env.store.update("ingestion_jobs", {"run_after": datetime.now(UTC).isoformat(), "max_attempts": 2}, {"id": job["id"]})
        svc(env).jobs.run_once()                      # attempt 2 (last): failed
    finally:
        emb.embed_passages = orig
    j = one(env, "ingestion_jobs", id=job["id"])
    assert j["status"] == "failed" and j["error_code"] == "embedding_unavailable" and j["completed_at"]
    v = one(env, "document_versions", id=v2["id"])
    assert v["verification_status"] == "pending_review" and v["indexing_status"] == "failed" and v["indexing_error"]
    assert one(env, "source_documents", id=doc_id)["current_version_id"] == v1
    assert any(h["version_id"] == v1 for h in search(env, "겨울방학 기숙사 신청"))
    assert notes(env, "indexing_failed")
    status = env.client.get("/api/v1/admin/rag/status", headers=env.auth("admin")).json()
    assert status["counts"]["indexing_failed"] == 1


def test_activated_but_unsearchable_document_raises_one_alert(env):
    doc_id, vid = published_doc(env)
    for c in chunks(env, vid):                        # e.g. vectors from a previous embedding model
        env.store.update("document_chunks", {"embedding_model": "old-model"}, {"id": c["id"]})
    health = svc(env).rag_health
    report = health.audit(notify=True)
    assert report["statistics"]["documents_with_problems"] == 1
    assert report["problems"][0]["problems"] == ["embeddings_missing_or_outdated"]
    health.audit(notify=True)                         # recurring check: deduplicated
    alerts = notes(env, "not_searchable")
    assert len(alerts) == 1 and alerts[0]["severity"] == "error" and doc_id in alerts[0]["link"]

    from app.cli import check_rag
    assert check_rag(svc(env), notify=False) == 1
    svc(env).indexer.ensure_indexed(vid)              # repair: re-embed with the current model
    assert check_rag(svc(env), notify=False) == 0


def test_inactive_source_is_hidden_not_alerted(env):
    doc_id, _ = published_doc(env)
    src = one(env, "source_documents", id=doc_id)["source_id"]
    env.store.update("knowledge_sources", {"is_active": False}, {"id": src})
    report = svc(env).rag_health.audit(notify=True)
    assert report["problems"] == [] and report["documents"][0]["hidden_reason"] == "source_inactive"
    assert not notes(env, "not_searchable")


# ------------------------------------------------------------------------------------------------ activation
def test_activation_rejects_incomplete_or_wrong_model_index(env):
    doc_id, v1 = published_doc(env)
    v2 = new_version(env, doc_id, "\n\n".join(SECTIONS))
    svc(env).indexer.index_version(v2["id"], embed=True)
    total = len(chunks(env, v2["id"]))
    model = svc(env).embedder.model_id
    for kwargs in (dict(p_expected_chunks=total + 1, p_model=model),        # chunk count mismatch
                   dict(p_expected_chunks=total, p_model="another-model")):  # vectors from a different model
        with pytest.raises(AppError):
            env.store.rpc("activate_document_version", dict(p_version_id=v2["id"], p_actor=env.users["admin"],
                                                            p_note=None, **kwargs))
        assert one(env, "source_documents", id=doc_id)["current_version_id"] == v1
    env.store.rpc("activate_document_version", dict(p_version_id=v2["id"], p_actor=env.users["admin"], p_note=None,
                                                    p_expected_chunks=total, p_model=model))
    assert one(env, "source_documents", id=doc_id)["current_version_id"] == v2["id"]
    assert one(env, "document_versions", id=v1)["verification_status"] == "superseded"


def test_index_job_for_already_active_or_withdrawn_version_publishes_nothing(env):
    doc_id, v1 = published_doc(env)
    again = activate(env, one(env, "document_versions", id=v1))
    assert again["status"] == "succeeded" and again["statistics"].get("chunk_count") is None   # no re-index
    v2 = new_version(env, doc_id, SECTIONS[1])
    env.store.update("source_documents", {"is_canceled": True}, {"id": doc_id})
    job = activate(env, v2)
    assert job["status"] == "failed" and job["error_code"] == "invalid_state"
    assert one(env, "source_documents", id=doc_id)["current_version_id"] == v1


def test_announcement_publication_is_verified(env):
    from tests.test_announcements import create

    a = create(env, submit=True)
    r = env.client.post(f"/api/v1/admin/announcements/{a['id']}/approve", headers=env.auth("admin"), json={})
    assert r.status_code == 200 and r.json()["publication_status"] == "published"
    report = svc(env).rag_health.audit()
    doc = next(d for d in report["documents"] if d["document_id"] == a["document_id"])
    assert doc["ok"] and doc["searchable_chunks"] == doc["chunks"] >= 1
    assert not notes(env, "not_searchable")
