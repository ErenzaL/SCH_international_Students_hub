"""Automatic RAG synchronization scenarios A–H (approval -> durable index job -> atomic activation)."""
from __future__ import annotations

import io
import json

from app.repositories.base import Query
from tests.test_phase2 import make_pdf, paste

ART = "https://www.studyinkorea.go.kr/en_US/plan/visaAndStay.do"


def search(env, q, **kw):
    r = env.client.post("/api/v1/knowledge/search", json={"query": q, "top_k": 10, **kw})
    assert r.status_code == 200, r.text
    return r.json()["results"]


def approve(env, vid):
    r = env.client.post(f"/api/v1/admin/versions/{vid}/approve", headers=env.auth("admin"), json={"note": "checked"})
    assert r.status_code == 202, r.text
    return r.json()


def upload(env, data, name="guide.pdf", source_id=None):
    form = {"source_id": source_id} if source_id else {"metadata": json.dumps(dict(
        title="Health insurance guide", organization="NHIS", category="health-insurance", scope="national",
        authority_type="official_government", language="en"))}
    r = env.client.post("/api/v1/admin/intake/document", headers=env.auth("admin"),
                        files={"file": (name, io.BytesIO(data), "application/pdf")}, data=form)
    assert r.status_code == 202, r.text
    return env.client.get(f"/api/v1/admin/ingestion-jobs/{r.json()['job_id']}", headers=env.auth("admin")).json(), r.json()


def chunks(env, vid):
    return env.store.select("document_chunks", Query(eq={"version_id": vid}))[0]


def test_a_b_pdf_upload_approve_searchable_then_replace_supersedes(env):
    pdf1 = make_pdf([[("Health insurance enrollment", 20), ("Students are enrolled in national health insurance "
                                                            "six months after arrival. Premium is about 70,000 won.", 11)]])
    job, out = upload(env, pdf1)
    v1 = job["version_id"]
    assert all(c["embedding"] is None for c in chunks(env, v1))  # pending: chunked, not embedded
    assert search(env, "health insurance premium") == []
    res = approve(env, v1)
    assert res["verification_status"] == "approved" and res["is_current"] and res["indexing_job_status"] == "succeeded"
    assert all(c["embedding"] is not None for c in chunks(env, v1))
    assert any(r["version_id"] == v1 for r in search(env, "health insurance premium"))

    # B: replace the file -> new pending version; public answers unchanged until approval
    pdf2 = make_pdf([[("Health insurance enrollment", 20), ("Students are enrolled in national health insurance "
                                                            "six months after arrival. Premium is about 75,000 won.", 11)]])
    job2, _ = upload(env, pdf2, "guide-v2.pdf", source_id=out["source"]["id"])
    v2 = job2["version_id"]
    assert v2 != v1 and job2["outcome"] == "new_version"
    hits = search(env, "health insurance premium")
    assert hits and all(h["version_id"] == v1 for h in hits)
    approve(env, v2)
    hits = search(env, "health insurance premium")
    assert hits and all(h["version_id"] == v2 for h in hits) and "75,000" in hits[0]["passage"]
    old = env.store.select("document_versions", Query(eq={"id": v1}))[0][0]
    assert old["verification_status"] == "superseded" and chunks(env, v1)  # kept for audit/rollback


def test_c_d_webpage_fetch_approve_then_update_creates_pending_without_changing_answers(env):
    page = lambda txt: f"<html><head><title>Visa</title></head><body><article><h1>D-2 visa</h1><p>{txt}</p></article></body></html>"  # noqa: E731
    env.page(ART, page("D-2 student visa holders must report a change of address within 15 days. " * 3))
    src = env.client.post("/api/v1/admin/sources", headers=env.auth("admin"), json=dict(
        title="Study in Korea", original_url=ART, organization="NIIED", source_type="website",
        authority_type="official_government", scope="national", category="visa-immigration", language="en",
        sync_frequency="weekly")).json()
    r = env.client.post(f"/api/v1/admin/sources/{src['id']}/ingest", headers=env.auth("admin"))
    job = env.client.get(f"/api/v1/admin/ingestion-jobs/{r.json()['job_id']}", headers=env.auth("admin")).json()
    approve(env, job["version_id"])
    assert "15 days" in search(env, "D-2 change of address")[0]["passage"]

    # D: the official page changes -> pending version + admin notification; students still get the approved text
    env.page(ART, page("D-2 student visa holders must report a change of address within 14 days. " * 3))
    r = env.client.post(f"/api/v1/admin/sources/{src['id']}/ingest", headers=env.auth("admin"))
    job2 = env.client.get(f"/api/v1/admin/ingestion-jobs/{r.json()['job_id']}", headers=env.auth("admin")).json()
    assert job2["outcome"] == "new_version"
    top = search(env, "D-2 change of address")[0]
    assert "15 days" in top["passage"] and top["version_id"] == job["version_id"]
    notes = env.client.get("/api/v1/admin/notifications", headers=env.auth("admin")).json()["items"]
    assert any(n["kind"] == "review_needed" for n in notes)
    status = env.client.get("/api/v1/admin/rag/status", headers=env.auth("admin")).json()
    assert status["counts"]["pending_review"] == 1 and status["counts"]["active_versions"] == 1
    approve(env, job2["version_id"])
    assert "14 days" in search(env, "D-2 change of address")[0]["passage"]


def test_e_h_staff_announcement_approve_then_withdraw_disappears(env):
    vid = paste(env, role="supporter").json()["version_id"]
    assert search(env, "겨울방학 기숙사 신청") == []
    approve(env, vid)
    hits = search(env, "겨울방학 기숙사 신청")
    assert hits and hits[0]["authority_type"] == "staff_communication"
    doc_id = hits[0]["document_id"]
    w = env.client.post(f"/api/v1/admin/documents/{doc_id}/cancel", headers=env.auth("admin"),
                        json={"reason": "Wrong dates announced"})
    assert w.status_code == 200
    assert search(env, "겨울방학 기숙사 신청") == []  # gone from the very next query
    assert env.client.get(f"/api/v1/knowledge/documents/{doc_id}").status_code == 404
    assert any(n["kind"] == "withdrawn" for n in
               env.client.get("/api/v1/admin/notifications", headers=env.auth("admin")).json()["items"])


def test_g_retry_and_duplicate_approval_create_no_duplicate_chunks_or_jobs(env):
    vid = paste(env, role="admin").json()["version_id"]
    svc = env.app.state.services
    v = env.store.select("document_versions", Query(eq={"id": vid}))[0][0]
    j1 = svc.ingestion.request_activation(v, env.users["admin"], None)  # queued, not yet run
    j2 = svc.ingestion.request_activation(v, env.users["admin"], None)
    assert j1["id"] == j2["id"]  # idempotent: one open index job per version
    svc.jobs.run_once()
    assert env.store.select("document_versions", Query(eq={"id": vid}))[0][0]["verification_status"] == "approved"
    n = len(chunks(env, vid))
    svc.indexer.index_version(vid, embed=True)  # re-index the active version
    svc.indexer.index_version(vid, embed=True)
    cs = chunks(env, vid)
    assert len(cs) == n and len({c["chunk_index"] for c in cs}) == n  # replaced, never duplicated


def test_partial_embedding_result_is_never_activated(env):
    vid = paste(env, role="admin").json()["version_id"]
    embedder = env.app.state.services.embedder
    orig = embedder.embed_passages
    embedder.embed_passages = lambda texts: orig(texts)[:-1] if len(texts) > 0 else []  # one vector short
    try:
        r = approve(env, vid)
        assert r["verification_status"] == "pending_review" and r["indexing_job_status"] == "queued"
        assert all(c["embedding"] is None for c in chunks(env, vid))  # no partial set stored
    finally:
        embedder.embed_passages = orig


def test_rag_status_reports_real_counts_and_queue(env):
    vid = paste(env, role="admin").json()["version_id"]
    approve(env, vid)
    st = env.client.get("/api/v1/admin/rag/status", headers=env.auth("admin")).json()
    c = st["counts"]
    assert c["active_versions"] == 1 and c["searchable_chunks"] >= 1 and c["chunks_with_current_model"] >= 1
    assert c["waiting_for_indexing"] == 0 and c["indexing_now"] == 0
    assert st["embedding"]["dimensions"] == 384 and st["embedding"]["model"] == "hash-dev-384"
    assert st["queue"][0]["status"] == "succeeded" and st["queue"][0]["version_id"] == vid
    assert st["recent_activations"][0]["document_title"] == "겨울방학 기숙사 신청"
    assert env.client.get("/api/v1/admin/rag/status", headers=env.auth("supporter")).status_code == 403
    env.client.post("/api/v1/admin/notifications/read", headers=env.auth("admin"))
    assert env.client.get("/api/v1/admin/notifications", headers=env.auth("admin")).json()["unread"] == 0
