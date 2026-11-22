"""Knowledge-source archive / restore and guarded permanent deletion (migration 0010 mirror)."""
from __future__ import annotations

import pytest

from app.core.errors import Forbidden
from app.repositories.base import Query
from tests.test_document_lifecycle import hits, website_doc
from tests.test_phase2 import make_pdf
from tests.test_rag_sync import upload

Q = "alien registration immigration office"


def new_source(env, title="Empty test source"):
    r = env.client.post("/api/v1/admin/sources", headers=env.auth("admin"), json=dict(
        title=title, organization="SCH", source_type="text_file", authority_type="official_university",
        scope="university", category="academic-life", language="en"))
    assert r.status_code == 201, r.text
    return r.json()


def check(env, sid, role="admin"):
    return env.client.get(f"/api/v1/admin/sources/{sid}/deletion-check", headers=env.auth(role))


def delete(env, sid, role="super_admin", title=None, reason="Registered by mistake", destructive=False):
    if title is None:
        rows = env.store.select("knowledge_sources", Query(eq={"id": sid}))[0]
        title = rows[0]["title"] if rows else "gone"
    return env.client.post(f"/api/v1/admin/sources/{sid}/delete", headers=env.auth(role),
                           json={"reason": reason, "confirm_title": title, "confirm_destructive": destructive})


def archive(env, sid, reason="Replaced by a newer source"):
    return env.client.post(f"/api/v1/admin/sources/{sid}/archive", headers=env.auth("admin"), json={"reason": reason})


def test_super_admin_deletes_an_unused_source(env):
    src = new_source(env)
    chk = check(env, src["id"]).json()
    assert chk["eligible"] and chk["documents"] == 0 and chk["recommended_action"] == "delete"
    assert chk["requires_destructive_confirmation"] is False and chk["is_searchable"] is False
    assert chk["title"] == src["title"] and chk["organization"] == "SCH"
    r = delete(env, src["id"])
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] and r.json()["documents"] == 0
    assert not env.store.select("knowledge_sources", Query(eq={"id": src["id"]}))[0]
    listed = env.client.get("/api/v1/admin/sources", headers=env.auth("admin")).json()["items"]
    assert all(s["id"] != src["id"] for s in listed)


@pytest.mark.parametrize("role", ["admin", "supporter", "student"])
def test_only_super_admin_can_delete(env, role):
    src = new_source(env)
    assert delete(env, src["id"], role=role).status_code == 403
    assert env.store.select("knowledge_sources", Query(eq={"id": src["id"]}))[0]
    # the database enforces it too, not only the API dependency
    with pytest.raises(Forbidden):
        env.store.rpc("delete_source", dict(p_source_id=src["id"], p_actor=env.users["admin"], p_reason="bypass try",
                                            p_confirm_title=src["title"], p_confirm_destructive=True))
    # and a raw row delete is refused once the source has history
    env.app.state.services.ingestion.create_job(env.store.select("knowledge_sources", Query(eq={"id": src["id"]}))[0][0])
    with pytest.raises(Forbidden):
        env.store.delete("knowledge_sources", {"id": src["id"]})


def test_title_confirmation_and_reason_are_required(env):
    src = new_source(env)
    assert delete(env, src["id"], title="Something else").status_code == 422
    assert delete(env, src["id"], reason="no").status_code == 422
    assert env.store.select("knowledge_sources", Query(eq={"id": src["id"]}))[0]


def test_source_with_pending_jobs(env):
    src = new_source(env)
    row = env.store.select("knowledge_sources", Query(eq={"id": src["id"]}))[0][0]
    ingestion = env.app.state.services.ingestion
    job = ingestion.create_job(row, payload={"storage_path": "sources/x/never-uploaded.pdf"})
    # a RUNNING job blocks deletion
    env.store.update("ingestion_jobs", {"status": "running"}, {"id": job["id"]})
    chk = check(env, src["id"]).json()
    assert not chk["eligible"] and any(b.startswith("busy") for b in chk["blockers"]) and chk["running_jobs"] == 1
    assert delete(env, src["id"]).status_code == 409
    # a QUEUED job is canceled by the delete; its history row survives without the source
    env.store.update("ingestion_jobs", {"status": "queued"}, {"id": job["id"]})
    r = delete(env, src["id"])
    assert r.status_code == 200, r.text
    assert r.json()["queued_jobs_canceled"] == 1
    kept = env.store.select("ingestion_jobs", Query(eq={"id": job["id"]}))[0][0]
    assert kept["status"] == "failed" and kept["error_code"] == "source_deleted" and kept["source_id"] is None
    # the worker never recreates anything for it, and the job API still renders it
    assert ingestion.run_job(job["id"])["status"] == "failed"
    view = env.client.get(f"/api/v1/admin/ingestion-jobs/{job['id']}", headers=env.auth("admin")).json()
    assert view["source_title"] == src["title"] and view["source_deleted"] is True
    listed = env.client.get("/api/v1/admin/ingestion-jobs", headers=env.auth("admin")).json()["items"]
    assert any(j["id"] == job["id"] for j in listed)
    assert env.client.post(f"/api/v1/admin/ingestion-jobs/{job['id']}/retry", headers=env.auth("admin")).status_code == 409
    assert not env.store.select("knowledge_sources", Query(eq={"id": src["id"]}))[0]


def test_archiving_a_source_with_approved_documents(env):
    src, job = website_doc(env)
    assert hits(env, Q)
    chk = check(env, src["id"]).json()
    assert chk["recommended_action"] == "archive" and chk["approved_versions"] == 1 and chk["is_searchable"]
    assert chk["published_documents"] == 1 and any(b.startswith("published") for b in chk["blockers"])
    assert chk["indexed_chunks"] >= 1 and chk["requires_destructive_confirmation"]
    assert delete(env, src["id"], destructive=True).status_code == 409     # live content: withdraw/archive first
    # admins may archive (reversible); supporters may not
    assert env.client.post(f"/api/v1/admin/sources/{src['id']}/archive", headers=env.auth("supporter"),
                           json={"reason": "nope nope"}).status_code == 403
    r = archive(env, src["id"])
    assert r.status_code == 200 and r.json()["archived_at"] and r.json()["is_active"] is False
    assert hits(env, Q) == []                                               # never in RAG results
    doc = env.store.select("source_documents", Query(eq={"id": job["document_id"]}))[0][0]
    assert doc["archived_at"]
    # an archived source cannot be re-enabled or synced behind the archive's back
    assert env.client.post(f"/api/v1/admin/sources/{src['id']}/enable", headers=env.auth("admin")).status_code == 409
    assert env.client.post(f"/api/v1/admin/sources/{src['id']}/ingest", headers=env.auth("admin")).status_code == 409
    assert archive(env, src["id"]).status_code == 409                       # already archived
    # restore brings back exactly what the archive took away
    r = env.client.post(f"/api/v1/admin/sources/{src['id']}/restore", headers=env.auth("admin"))
    assert r.status_code == 200 and r.json()["archived_at"] is None and r.json()["is_active"]
    assert hits(env, Q)
    acts = [a["action"] for a in env.store.select("audit_log", Query(eq={"entity_id": src["id"]}))[0]]
    assert {"source.archive", "source.restore"} <= set(acts)


def test_restore_keeps_documents_archived_individually_before(env):
    src, job = website_doc(env)
    doc = job["document_id"]
    env.client.post(f"/api/v1/admin/documents/{doc}/archive", headers=env.auth("admin"), json={"reason": "Outdated page"})
    archive(env, src["id"])
    env.client.post(f"/api/v1/admin/sources/{src['id']}/restore", headers=env.auth("admin"))
    assert env.store.select("source_documents", Query(eq={"id": doc}))[0][0]["archived_at"]
    assert hits(env, Q) == []


def test_deleting_an_archived_source_needs_second_confirmation_and_cleans_up(env):
    data = make_pdf([[("Health insurance guide", 20), ("Every international student must enroll in the national "
                                                       "health insurance after six months of stay.", 11)]])
    job, _ = upload(env, data)
    sid, vid = job["source_id"], job["version_id"]
    assert env.client.post(f"/api/v1/admin/versions/{vid}/approve", headers=env.auth("admin"),
                           json={}).status_code == 202
    assert hits(env, "national health insurance enroll")
    chunks = env.store.select("document_chunks", Query(eq={"version_id": vid}))[0]
    assert chunks and all(c["embedding"] is not None for c in chunks)
    storage = env.app.state.services.storage
    assert len(storage.files) == 1
    archive(env, sid)
    assert hits(env, "national health insurance enroll") == []
    chk = check(env, sid).json()
    assert chk["eligible"] and chk["is_searchable"] is False and len(chk["storage_files"]) == 1
    r = delete(env, sid)                                                    # no second confirmation
    assert r.status_code == 422 and "confirm" in r.text
    r = delete(env, sid, destructive=True)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["documents"] == 1 and out["versions"] == 1 and out["chunks"] == len(chunks)
    assert out["files_removed"] == 1 and out["files_failed"] == [] and storage.files == {}
    # embedding cleanup: no chunk / vector rows left for the deleted version
    assert not env.store.select("document_chunks", Query(eq={"version_id": vid}))[0]
    assert not env.store.select("document_versions", Query(eq={"id": vid}))[0]
    assert not env.store.select("source_documents", Query(eq={"source_id": sid}))[0]
    assert hits(env, "national health insurance enroll") == []
    # audit preservation: earlier entries stay, plus a tombstone with the content hashes
    tomb = env.store.select("audit_log", Query(eq={"action": "source.delete", "entity_id": sid}))[0][0]
    assert tomb["details"]["documents"][0]["versions"][0]["content_hash"] and tomb["details"]["reason"]
    assert env.store.select("audit_log", Query(eq={"action": "source.archive", "entity_id": sid}))[0]
    assert env.store.select("audit_log", Query(eq={"action": "version.approve", "entity_id": vid}))[0]
    assert env.store.select("audit_log", Query(eq={"action": "source.storage_cleanup", "entity_id": sid}))[0]
    stats = env.client.get("/api/v1/admin/knowledge/stats", headers=env.auth("admin"))
    assert stats.status_code == 200


def test_withdrawn_documents_are_excluded_and_source_then_deletable(env):
    src, job = website_doc(env)
    env.client.post(f"/api/v1/admin/documents/{job['document_id']}/cancel", headers=env.auth("admin"),
                    json={"reason": "Wrong rule"})
    assert hits(env, Q) == []
    chk = check(env, src["id"]).json()
    assert chk["eligible"] and chk["published_documents"] == 0 and chk["approved_versions"] == 1
    assert delete(env, src["id"], destructive=True).status_code == 200
    assert hits(env, Q) == []


def test_files_shared_with_another_source_are_kept(env):
    data = make_pdf([[("Shared guide", 20), ("Text that two sources both reference for this test case.", 11)]])
    job, _ = upload(env, data)
    path = env.store.select("document_versions", Query(eq={"id": job["version_id"]}))[0][0]["original_file"]["storage_path"]
    other = new_source(env, "Other source")
    other_row = env.store.select("knowledge_sources", Query(eq={"id": other["id"]}))[0][0]
    shared = env.app.state.services.ingestion.create_job(other_row, payload={"storage_path": path})
    env.store.update("ingestion_jobs", {"status": "failed"}, {"id": shared["id"]})
    chk = check(env, job["source_id"]).json()
    assert chk["storage_files"] == []
    r = delete(env, job["source_id"], destructive=True)
    assert r.status_code == 200 and r.json()["files_removed"] == 0
    assert path in env.app.state.services.storage.files


def test_repeated_deletion_requests(env):
    src = new_source(env)
    assert delete(env, src["id"], title=src["title"]).status_code == 200
    again = delete(env, src["id"], title=src["title"])
    assert again.status_code == 404
    assert check(env, src["id"]).status_code == 404
    assert len(env.store.select("audit_log", Query(eq={"action": "source.delete", "entity_id": src["id"]}))[0]) == 1


def test_announcement_sources_cannot_be_deleted(env):
    from tests.test_announcements import create

    a = create(env, submit=True)
    doc_id = env.store.select("announcements", Query(eq={"id": a["id"]}))[0][0]["document_id"]
    sid = env.store.select("source_documents", Query(eq={"id": doc_id}))[0][0]["source_id"]
    chk = check(env, sid).json()
    assert any(b.startswith("announcement") for b in chk["blockers"])
    assert delete(env, sid, destructive=True).status_code == 409
