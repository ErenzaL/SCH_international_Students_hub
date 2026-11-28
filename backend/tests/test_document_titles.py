"""A published title belongs to the approved version: whatever an unapproved change proposes, students keep the old title
everywhere until the replacement is approved."""
from __future__ import annotations

import pytest

from app.core.errors import UpstreamError
from app.repositories.base import get_one
from app.services.document_titles import KEY
from tests.test_ingestion_versioning import approve, ingest, website_source
from tests.test_phase2 import ingest as board_ingest
from tests.test_phase2 import make_board_source, setup_board

URL = "https://www.studyinkorea.go.kr/en_US/plan/titles.do"
OLD, NEW = "Visa guide", "Visa guide with UNAPPROVED claims"
BODY = "International students should keep their residence status valid. Registration happens at the immigration office."


def html(title, body=BODY):  # type: ignore[no-untyped-def]
    return f"<html><head><title>{title}</title></head><body><div id='content'><p>{body}</p></div></body></html>"


@pytest.fixture
def doc(env):  # type: ignore[no-untyped-def]
    """A published document with the title OLD."""
    env.page(URL, html(OLD))
    env.src = website_source(env, url=URL)
    job = ingest(env, env.src["id"])
    assert approve(env, job["version_id"]).status_code == 202
    env.doc_id, env.v1 = job["document_id"], job["version_id"]
    assert row(env)["title"] == OLD
    return env


def row(env):  # type: ignore[no-untyped-def]
    return get_one(env.store, "source_documents", id=env.doc_id)


def ver(env, vid):  # type: ignore[no-untyped-def]
    return get_one(env.store, "document_versions", id=vid)


def public_titles(env):  # type: ignore[no-untyped-def]
    """Every place a student can see a title."""
    d = env.client.get(f"/api/v1/knowledge/documents/{env.doc_id}").json()
    listed = env.client.get("/api/v1/knowledge/documents").json()["items"]
    hits = env.client.post("/api/v1/knowledge/search", json=dict(query="immigration office registration")).json()["results"]
    chat = env.client.post("/api/v1/assistant/chat", json=dict(message="Where does registration happen?", language="en")).json()
    return {d["title"], *(x["title"] for x in listed), *(h["document_title"] for h in hits),
            *(c["document_title"] for c in chat["citations"])}


def change(env, title=NEW, body="A completely different second edition of the text, waiting for the review of an administrator."):  # type: ignore[no-untyped-def]
    env.page(URL, html(title, body))
    return ingest(env, env.src["id"])


# ---------------------------------------------------------------------------- re-ingestion
def test_unapproved_title_is_not_public_until_the_version_is_approved(doc):
    job = change(doc)
    assert job["outcome"] == "new_version" and public_titles(doc) == {OLD}
    d = doc.client.get(f"/api/v1/admin/documents/{doc.doc_id}", headers=doc.auth("admin")).json()
    assert d["title"] == OLD and d["proposed_title"] == NEW and d["pending_version"]["document_title"] == NEW
    assert any(w["code"] == "title_changed" and NEW in w["message"] for w in d["review_warnings"])
    assert approve(doc, job["version_id"]).status_code == 202
    assert public_titles(doc) == {NEW}


def test_rejected_title_never_becomes_public(doc):
    job = change(doc)
    r = doc.client.post(f"/api/v1/admin/versions/{job['version_id']}/reject", headers=doc.auth("admin"), json=dict(reason="Not true"))
    assert r.status_code == 200 and public_titles(doc) == {OLD}
    change(doc, "Third title", "A third edition of the text that also needs the review of an administrator first.")
    assert public_titles(doc) == {OLD}


def test_board_notice_keeps_its_title_until_approval(env):
    setup_board(env, {101: ("기숙사 안내", "2026-11-20", "입사일은 2월 24일입니다. 학생증을 가져오세요.")})
    src = make_board_source(env)
    job = board_ingest(env, src["id"])
    env.doc_id = job["document_id"]
    approve(env, job["version_id"])
    setup_board(env, {101: ("기숙사 안내 (변경)", "2026-11-20", "입사일은 2월 25일로 변경되었습니다. 학생증을 가져오세요.")})
    job = board_ingest(env, src["id"])
    assert job["outcome"] == "new_version" and row(env)["title"] == "기숙사 안내"
    approve(env, job["version_id"])
    assert row(env)["title"] == "기숙사 안내 (변경)"


def test_withdrawn_and_archived_documents_keep_their_title(doc):
    for action, body in (("archive", dict(reason="Outdated page")), ("cancel", dict(reason="Wrong rule"))):
        doc.client.post(f"/api/v1/admin/documents/{doc.doc_id}/{action}", headers=doc.auth("admin"), json=body)
        change(doc)
        assert row(doc)["title"] == OLD
        doc.client.post(f"/api/v1/admin/documents/{doc.doc_id}/restore", headers=doc.auth("admin"), json={})


def test_unpublished_documents_follow_the_latest_extraction(env):
    env.page(URL, html(OLD))
    env.src = website_source(env, url=URL)
    env.doc_id = ingest(env, env.src["id"])["document_id"]
    change(env)
    assert row(env)["title"] == NEW


# ------------------------------------------------------------------------------- editing
def test_editing_the_title_of_an_open_version_changes_nothing_public(doc):
    job = change(doc, OLD)
    for role in ("admin",):
        r = doc.client.patch(f"/api/v1/admin/versions/{job['version_id']}", headers=doc.auth(role), json=dict(title="Edited title"))
        assert r.status_code == 200 and r.json()["document_title"] == "Edited title"
    assert public_titles(doc) == {OLD}
    approve(doc, job["version_id"])
    assert public_titles(doc) == {"Edited title"}


def test_a_supporters_draft_cannot_change_a_published_title(doc):
    doc.store.insert("document_versions", dict(document_id=doc.doc_id, version_number=9, extracted_text="draft " * 10, content_hash="d" * 64,
                                               verification_status="draft", created_by=doc.users["supporter"]))
    vid = doc.store.t["document_versions"][-1]["id"]
    r = doc.client.patch(f"/api/v1/admin/versions/{vid}", headers=doc.auth("supporter"), json=dict(title="Supporter title"))
    assert r.status_code == 200 and public_titles(doc) == {OLD}


# ---------------------------------------------------------------- rollback, retry, old data
def test_rollback_restores_the_title_of_the_restored_version(doc):
    job = change(doc)
    approve(doc, job["version_id"])
    r = doc.client.post(f"/api/v1/admin/documents/{doc.doc_id}/rollback", headers=doc.auth("admin"), json=dict(version_id=doc.v1))
    assert r.status_code == 200, r.text
    assert public_titles(doc) == {OLD}


def test_versions_from_before_this_change_get_their_title_recorded(doc):
    """No data migration: a version without a recorded title keeps the document's title, also across a rollback."""
    meta = dict(ver(doc, doc.v1)["extraction_meta"])
    meta.pop(KEY)
    doc.store.update("document_versions", {"extraction_meta": meta}, {"id": doc.v1})
    job = change(doc)
    assert public_titles(doc) == {OLD}
    approve(doc, job["version_id"])
    assert public_titles(doc) == {NEW} and ver(doc, doc.v1)["extraction_meta"][KEY] == OLD
    doc.client.post(f"/api/v1/admin/documents/{doc.doc_id}/rollback", headers=doc.auth("admin"), json=dict(version_id=doc.v1))
    assert public_titles(doc) == {OLD}


def test_an_old_pending_version_without_a_title_keeps_the_published_one(doc):
    job = change(doc)
    doc.store.update("document_versions", {"extraction_meta": {}}, {"id": job["version_id"]})
    approve(doc, job["version_id"])
    assert public_titles(doc) == {OLD}


def test_a_crash_between_activation_and_title_is_healed_by_the_job_retry(doc):
    job = change(doc)
    svc, real = doc.app.state.services, doc.store.update

    def broken(table, patch, eq):  # type: ignore[no-untyped-def]
        if table == "source_documents" and "title" in patch:
            raise UpstreamError("database unreachable")
        return real(table, patch, eq)

    doc.store.update = broken
    approve(doc, job["version_id"])
    doc.store.update = real
    assert row(doc)["current_version_id"] == job["version_id"] and row(doc)["title"] == OLD     # old title, never an unapproved one
    j = [x for x in doc.store.t["ingestion_jobs"] if x["job_type"] == "index_version"][-1]
    assert j["status"] == "queued"
    doc.store.update("ingestion_jobs", {"run_after": "2020-01-01T00:00:00+00:00"}, {"id": j["id"]})
    assert svc.ingestion.run_job(j["id"])["status"] == "succeeded" and public_titles(doc) == {NEW}


def test_failed_indexing_leaves_the_title_alone(doc):
    job = change(doc)
    emb = doc.app.state.services.indexer.embedder
    real, emb.embed_passages = emb.embed_passages, lambda *_a: (_ for _ in ()).throw(MemoryError())
    approve(doc, job["version_id"])
    emb.embed_passages = real
    assert row(doc)["title"] == OLD and row(doc)["current_version_id"] == doc.v1


def test_the_search_index_uses_the_title_the_version_is_published_with(doc):
    seen = []
    emb = doc.app.state.services.indexer.embedder
    real = emb.embed_passages
    emb.embed_passages = lambda texts: (seen.extend(texts), real(texts))[1]
    job = change(doc)
    approve(doc, job["version_id"])
    emb.embed_passages = real
    assert seen and all(NEW in t for t in seen)


# --------------------------------------------------------------------------- title-only changes
def submit(env, title, text):  # type: ignore[no-untyped-def]
    source = get_one(env.store, "knowledge_sources", id=env.src["id"])
    return env.app.state.services.ingestion.ingest_text(source, title=title, text=text, requested_by=env.users["admin"], external_id="same-id")


@pytest.fixture
def manual(env):  # type: ignore[no-untyped-def]
    env.src = env.client.post("/api/v1/admin/sources", headers=env.auth("admin"), json=dict(
        title="Manual", organization="SCH", source_type="manual_text", authority_type="official_university", scope="university",
        category="academic-life", language="en")).json()
    job = submit(env, OLD, BODY)
    env.doc_id, env.v1 = job["document_id"], job["version_id"]
    return env


def test_title_only_change_never_replaces_a_published_title(manual):
    approve(manual, manual.v1)
    assert submit(manual, NEW, BODY)["outcome"] == "unchanged" and public_titles(manual) == {OLD}
    assert any("published title was kept" in e["message"] for e in manual.store.t["ingestion_events"])


def test_title_only_change_of_a_waiting_version_is_taken_over_for_review(manual):
    submit(manual, "Corrected title", BODY)
    assert ver(manual, manual.v1)["extraction_meta"][KEY] == "Corrected title"
    approve(manual, manual.v1)
    assert public_titles(manual) == {"Corrected title"}
