"""Archive / withdraw / restore, guarded permanent deletion, RAG exclusion and re-import suppression."""
from __future__ import annotations

import io
import json

import pytest

from app.core.errors import Forbidden
from app.repositories.base import Query
from tests.conftest import ARTICLE_HTML, ARTICLE_URL
from tests.test_phase2 import BOARD, NOTICES, make_board_source, make_pdf, paste, setup_board


def approve(env, vid):
    assert env.client.post(f"/api/v1/admin/versions/{vid}/approve", headers=env.auth("admin"), json={}).status_code == 202


def hits(env, q):
    return env.client.post("/api/v1/knowledge/search", json={"query": q, "top_k": 10}).json()["results"]


def website_doc(env):
    env.page(ARTICLE_URL, ARTICLE_HTML)
    src = env.client.post("/api/v1/admin/sources", headers=env.auth("admin"), json=dict(
        title="Study in Korea", original_url=ARTICLE_URL, organization="NIIED", source_type="website",
        authority_type="official_government", scope="national", category="visa-immigration", language="en")).json()
    r = env.client.post(f"/api/v1/admin/sources/{src['id']}/ingest", headers=env.auth("admin")).json()
    job = env.client.get(f"/api/v1/admin/ingestion-jobs/{r['job_id']}", headers=env.auth("admin")).json()
    approve(env, job["version_id"])
    return src, job


def delete(env, doc_id, role="super_admin", title=None, reason="Duplicate of an official source"):
    if title is None:
        title = env.store.select("source_documents", Query(eq={"id": doc_id}))[0][0]["title"]
    return env.client.post(f"/api/v1/admin/documents/{doc_id}/delete", headers=env.auth(role),
                           json={"reason": reason, "confirm_title": title})


def test_archive_and_withdraw_are_reversible_and_excluded_from_rag(env):
    src, job = website_doc(env)
    doc = job["document_id"]
    assert hits(env, "alien registration immigration office")
    r = env.client.post(f"/api/v1/admin/documents/{doc}/archive", headers=env.auth("admin"), json={"reason": "Outdated page"})
    assert r.status_code == 200 and r.json()["lifecycle"] == "archived"
    assert hits(env, "alien registration immigration office") == []
    assert env.client.get(f"/api/v1/knowledge/documents/{doc}").status_code == 404
    assert env.client.get("/api/v1/knowledge/documents").json()["total"] == 0
    # an archived document is not silently refreshed by syncs
    r = env.client.post(f"/api/v1/admin/sources/{src['id']}/ingest", headers=env.auth("admin")).json()
    j = env.client.get(f"/api/v1/admin/ingestion-jobs/{r['job_id']}", headers=env.auth("admin")).json()
    assert j["outcome"] == "unchanged"
    assert env.client.post(f"/api/v1/admin/documents/{doc}/restore", headers=env.auth("admin"), json={}).status_code == 200
    assert hits(env, "alien registration immigration office")
    # withdraw -> restore
    env.client.post(f"/api/v1/admin/documents/{doc}/cancel", headers=env.auth("admin"), json={"reason": "Wrong rule"})
    assert hits(env, "alien registration immigration office") == []
    d = env.client.get(f"/api/v1/admin/documents/{doc}", headers=env.auth("admin")).json()
    assert d["lifecycle"] == "withdrawn" and d["canceled_reason"] == "Wrong rule"
    env.client.post(f"/api/v1/admin/documents/{doc}/restore", headers=env.auth("admin"), json={"note": "checked"})
    assert hits(env, "alien registration immigration office")
    acts = [a["action"] for a in env.store.select("audit_log", Query(eq={"entity_id": doc}))[0]]
    assert {"document.archive", "document.restore", "document.cancel"} <= set(acts)
    # supporters / students cannot archive or restore
    for role in ("supporter", "student"):
        assert env.client.post(f"/api/v1/admin/documents/{doc}/archive", headers=env.auth(role),
                               json={"reason": "nope"}).status_code == 403


def test_delete_requires_super_admin_unpublished_state_and_exact_title(env):
    _src, job = website_doc(env)
    doc = job["document_id"]
    chk = env.client.get(f"/api/v1/admin/documents/{doc}/deletion-check", headers=env.auth("admin")).json()
    assert chk["eligible"] is False and any(b.startswith("published") for b in chk["blockers"])
    assert chk["recommended_action"] == "archive" and chk["approved_versions"] == 1
    for role in ("admin", "supporter", "student"):
        assert delete(env, doc, role=role).status_code == 403
    assert delete(env, doc).status_code == 409                     # still published: withdraw/archive first
    env.client.post(f"/api/v1/admin/documents/{doc}/archive", headers=env.auth("admin"), json={"reason": "Replaced"})
    assert delete(env, doc, title="wrong title").status_code == 422
    assert delete(env, doc, reason="no").status_code == 422
    assert env.store.select("source_documents", Query(eq={"id": doc}))[0]  # nothing happened so far


def test_delete_cleans_up_and_keeps_audit_history_and_blocks_reimport(env):
    src, job = website_doc(env)
    doc, vid = job["document_id"], job["version_id"]
    env.client.post(f"/api/v1/admin/documents/{doc}/cancel", headers=env.auth("admin"), json={"reason": "Incorrect"})
    r = delete(env, doc)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["deleted"] and out["versions"] == 1 and out["chunks"] >= 1 and out["reimport_blocked"]
    assert not env.store.select("source_documents", Query(eq={"id": doc}))[0]
    assert not env.store.select("document_versions", Query(eq={"id": vid}))[0]
    assert not env.store.select("document_chunks", Query(eq={"version_id": vid}))[0]
    jobs = env.store.select("ingestion_jobs", Query(eq={"source_id": src["id"]}))[0]
    assert jobs and all(j["document_id"] is None and j["version_id"] is None for j in jobs)  # job history kept
    tomb = env.store.select("audit_log", Query(eq={"action": "document.delete", "entity_id": doc}))[0][0]
    assert tomb["details"]["versions"][0]["content_hash"] and tomb["details"]["reason"]
    assert env.store.select("audit_log", Query(eq={"action": "version.approve"}))[0]  # earlier audit untouched
    # the next sync does NOT re-import the deleted page
    r = env.client.post(f"/api/v1/admin/sources/{src['id']}/ingest", headers=env.auth("admin")).json()
    j = env.client.get(f"/api/v1/admin/ingestion-jobs/{r['job_id']}", headers=env.auth("admin")).json()
    assert j["status"] == "succeeded" and j["outcome"] == "unchanged"
    assert not env.store.select("source_documents", Query(eq={"source_id": src["id"]}))[0]
    # an admin can explicitly allow it again
    sup = env.client.get(f"/api/v1/admin/sources/{src['id']}/suppressions", headers=env.auth("admin")).json()["items"]
    assert len(sup) == 1
    assert env.client.delete(f"/api/v1/admin/sources/{src['id']}/suppressions/{sup[0]['id']}",
                             headers=env.auth("admin")).status_code == 204
    r = env.client.post(f"/api/v1/admin/sources/{src['id']}/ingest", headers=env.auth("admin")).json()
    assert env.client.get(f"/api/v1/admin/ingestion-jobs/{r['job_id']}", headers=env.auth("admin")).json()["outcome"] == "new_version"


def test_deleted_board_notice_is_not_reimported(env):
    setup_board(env, NOTICES)
    src = make_board_source(env)
    r = env.client.post(f"/api/v1/admin/sources/{src['id']}/ingest", headers=env.auth("admin")).json()
    job = env.client.get(f"/api/v1/admin/ingestion-jobs/{r['job_id']}", headers=env.auth("admin")).json()
    target = job["statistics"]["notices"][0]
    assert delete(env, target["document_id"]).status_code == 200  # never approved -> deletable directly
    r = env.client.post(f"/api/v1/admin/sources/{src['id']}/ingest", headers=env.auth("admin")).json()
    j2 = env.client.get(f"/api/v1/admin/ingestion-jobs/{r['job_id']}", headers=env.auth("admin")).json()
    assert j2["statistics"].get("items_skipped") == 1 and j2["statistics"]["items_new"] == 0
    ids = {d["external_id"] for d in env.store.select("source_documents", Query(eq={"source_id": src["id"]}))[0]}
    assert f"noti_fore:{target['notice_no']}" not in ids and len(ids) == 2
    assert BOARD


def test_uploaded_file_delete_removes_private_storage(env):
    data = make_pdf([[("Temporary guide", 20), ("This draft was uploaded by mistake and should be removed.", 11)]])
    r = env.client.post("/api/v1/admin/intake/document", headers=env.auth("admin"),
                        files={"file": ("mistake.pdf", io.BytesIO(data), "application/pdf")},
                        data={"metadata": json.dumps(dict(title="Mistake", organization="SCH", category="academic-life",
                                                          scope="university", authority_type="official_university"))})
    job = env.client.get(f"/api/v1/admin/ingestion-jobs/{r.json()['job_id']}", headers=env.auth("admin")).json()
    storage = env.app.state.services.storage
    assert len(storage.files) == 1
    out = delete(env, job["document_id"]).json()
    assert out["files_removed"] == 1 and out["files_failed"] == [] and storage.files == {}


def test_announcement_documents_and_busy_documents_cannot_be_deleted(env):
    from tests.test_announcements import create

    a = create(env, submit=True)
    doc = env.store.select("announcements", Query(eq={"id": a["id"]}))[0][0]["document_id"]
    chk = env.client.get(f"/api/v1/admin/documents/{doc}/deletion-check", headers=env.auth("admin")).json()
    assert any(b.startswith("announcement") for b in chk["blockers"])
    assert delete(env, doc).status_code == 409
    # a queued indexing job blocks deletion
    vid = paste(env, role="admin").json()["version_id"]
    v = env.store.select("document_versions", Query(eq={"id": vid}))[0][0]
    env.app.state.services.ingestion.request_activation(v, env.users["admin"], None)
    assert delete(env, v["document_id"]).status_code == 409


def test_database_guard_blocks_direct_document_deletes(env):
    _src, job = website_doc(env)
    with pytest.raises(Forbidden):
        env.store.delete("source_documents", {"id": job["document_id"]})
    with pytest.raises(Forbidden):
        env.store.delete("document_versions", {"id": job["version_id"]})  # approved version = audit record
