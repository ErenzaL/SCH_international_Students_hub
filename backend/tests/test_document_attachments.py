"""Public attachments belong to the approved version: import, approval, rejection, send-back, repeated imports, rollback."""
from __future__ import annotations

import pytest

from app.core.errors import UpstreamError
from app.repositories.base import get_one
from app.services.document_attachments import KEYS
from tests.test_ingestion_versioning import approve
from tests.test_phase2 import BOARD, board_html, ingest, make_board_source, notice_html, notice_url

NO, TITLE, BODY = 6708, "[생활관] 짐 보관 안내", "<p>방학 중 교내에 개인 짐을 보관할 수 없습니다. 첨부 안내문을 참고하세요.</p>"
A, B, C = "승인된 안내문.pdf", "미승인 새 양식.pdf", "또 다른 파일.hwp"


def setup(env, *files, body=BODY, title=TITLE, pinned=False):  # type: ignore[no-untyped-def]
    rows = "".join(f"<a href='../lib/download.php?file={i}-{abs(hash(f)) % 999}' class='down_file'><span>{f}</span></a>" for i, f in enumerate(files))
    env.page(BOARD, board_html([(NO, title, "2026-11-17", pinned)]))
    html = notice_html(title, "2026.11.17", body, attachment="PLACEHOLDER" if files else None)
    if files:
        start = html.index("<a href='../lib/download.php")
        html = html[:start] + rows + html[html.index("</a>", start) + 4:]
    env.page(notice_url(NO), html)


def sync(env, *files, **kw):  # type: ignore[no-untyped-def]
    setup(env, *files, **kw)
    job = ingest(env, env.src["id"])
    return job


@pytest.fixture
def notice(env):  # type: ignore[no-untyped-def]
    """A published notice with the attachment A."""
    setup(env, A)
    env.src = make_board_source(env)
    job = ingest(env, env.src["id"])
    assert approve(env, job["version_id"]).status_code == 202
    env.doc_id, env.v1 = job["document_id"], job["version_id"]
    assert public(env) == [A]
    return env


def doc(env):  # type: ignore[no-untyped-def]
    return get_one(env.store, "source_documents", id=env.doc_id)


def public(env):  # type: ignore[no-untyped-def]
    """Attachment names students get, checked in the API and in the row that the public key can read."""
    r = env.client.get(f"/api/v1/knowledge/documents/{env.doc_id}")
    assert r.status_code == 200, r.text
    api = [a["name"] for a in r.json()["attachments"]]
    assert [a["name"] for a in doc(env)["metadata"]["attachments"]] == api
    return api


def admin(env):  # type: ignore[no-untyped-def]
    return env.client.get(f"/api/v1/admin/documents/{env.doc_id}", headers=env.auth("admin")).json()


def act(env, vid, action, **body):  # type: ignore[no-untyped-def]
    r = env.client.post(f"/api/v1/admin/versions/{vid}/{action}", headers=env.auth("admin"), json=body)
    assert r.status_code in (200, 202), r.text


# ------------------------------------------------------------------------- import and approval
@pytest.mark.parametrize("files", [(A, B), (B,), ()], ids=["added", "replaced", "removed"])
def test_unapproved_attachments_are_not_public_until_approval(notice, files):
    job = sync(notice, *files)
    assert job["outcome"] == "new_version" and public(notice) == [A]
    approve(notice, job["version_id"])
    assert public(notice) == list(files)


def test_every_public_place_keeps_the_approved_attachment(notice):
    sync(notice, B)
    body = notice.client.get(f"/api/v1/knowledge/documents/{notice.doc_id}").text
    hits = notice.client.post("/api/v1/knowledge/search", json=dict(query="짐 보관 안내 첨부파일")).text
    chat = notice.client.post("/api/v1/assistant/chat", json=dict(message="짐 보관 첨부파일", language="ko")).text
    tool = notice.client.post("/api/v1/agents/academic/tools", json=dict(tool="knowledge_document_lookup", params={"document_id": notice.doc_id})).text
    listed = notice.client.get("/api/v1/knowledge/documents").text
    assert A in body and all(B not in x for x in (body, hits, chat, tool, listed))


def test_reviewers_see_exactly_what_changes(notice):
    sync(notice, B, C)
    d = admin(notice)
    assert [a["name"] for a in d["metadata"]["attachments"]] == [A]                      # what students see now
    w = {(x["code"], x["message"].split(": ", 1)[1].split(" (")[0]) for x in d["review_warnings"] if x["code"].startswith("attachments")}
    assert w == {("attachments_added", B), ("attachments_added", C), ("attachments_removed", A)}
    assert [a["name"] for a in d["pending_version"]["extraction_meta"]["attachments"]] == [B, C]
    assert any(B in line for line in d["diff"]["added_lines"]) and any(A in line for line in d["diff"]["removed_lines"])


def test_no_attachment_warning_without_a_change(notice):
    sync(notice, A, body="<p>본문만 변경되었습니다. 첨부 안내문을 참고하세요. 새로운 내용입니다.</p>")
    assert not [w for w in admin(notice)["review_warnings"] if w["code"].startswith("attachments")]


# ------------------------------------------------------------------- rejection and send-back
def test_rejected_attachments_never_become_public(notice):
    job = sync(notice, B)
    act(notice, job["version_id"], "reject", reason="Wrong form")
    assert public(notice) == [A]
    assert sync(notice, B)["outcome"] == "unchanged" and public(notice) == [A]           # the same content again
    job = sync(notice, C)
    assert public(notice) == [A]
    approve(notice, job["version_id"])
    assert public(notice) == [C]


def test_sent_back_edited_and_resubmitted_version(notice):
    job = sync(notice, B)
    vid = job["version_id"]
    act(notice, vid, "request-changes", note="Please check the form")
    assert public(notice) == [A] and admin(notice)["pending_version"]["verification_status"] == "draft"
    r = notice.client.patch(f"/api/v1/admin/versions/{vid}", headers=notice.auth("admin"),
                            json=dict(extracted_text=get_one(notice.store, "document_versions", id=vid)["extracted_text"] + "\n\n확인했습니다."))
    assert r.status_code == 200 and public(notice) == [A]
    act(notice, vid, "submit")
    assert public(notice) == [A]
    approve(notice, vid)
    assert public(notice) == [B]


def test_import_after_send_back_replaces_the_draft_and_changes_nothing_public(notice):
    job = sync(notice, B)
    act(notice, job["version_id"], "request-changes", note="Please check the form")
    job2 = sync(notice, C)
    assert job2["version_id"] != job["version_id"] and public(notice) == [A]
    approve(notice, job2["version_id"])
    assert public(notice) == [C]


# ----------------------------------------------------------------------------- repeated imports
def test_repeated_imports_never_change_the_public_list(notice):
    for files in ((B,), (B,), (B, C), (), (C,), (A,), (B,)):
        sync(notice, *files)
        assert public(notice) == [A], files


def test_source_goes_back_to_the_approved_state(notice):
    sync(notice, B)
    assert sync(notice, A)["outcome"] == "unchanged" and public(notice) == [A]


def test_several_replacements_before_one_approval(notice):
    for files in ((B,), (C,)):
        sync(notice, *files)
    job = sync(notice, B, C)
    approve(notice, job["version_id"])
    assert public(notice) == [B, C]


def test_only_the_place_in_the_list_follows_the_board_at_once(notice):
    assert sync(notice, A, pinned=True)["outcome"] == "unchanged"
    assert doc(notice)["metadata"]["pinned"] is True and public(notice) == [A]


def test_unpublished_notices_follow_the_latest_import(env):
    setup(env, A)
    env.src = make_board_source(env)
    env.doc_id = ingest(env, env.src["id"])["document_id"]
    sync(env, B)
    assert [a["name"] for a in doc(env)["metadata"]["attachments"]] == [B]
    assert [a["name"] for a in admin(env)["metadata"]["attachments"]] == [B]


def test_withdrawn_and_archived_notices_keep_their_attachments(notice):
    for action, body in (("archive", dict(reason="Outdated page")), ("cancel", dict(reason="Wrong rule"))):
        notice.client.post(f"/api/v1/admin/documents/{notice.doc_id}/{action}", headers=notice.auth("admin"), json=body)
        sync(notice, B)
        assert [a["name"] for a in doc(notice)["metadata"]["attachments"]] == [A]
        notice.client.post(f"/api/v1/admin/documents/{notice.doc_id}/restore", headers=notice.auth("admin"), json={})
        assert public(notice) == [A]


# ---------------------------------------------------------------------- rollback, crash, old data
def rollback(env, vid):  # type: ignore[no-untyped-def]
    r = env.client.post(f"/api/v1/admin/documents/{env.doc_id}/rollback", headers=env.auth("admin"), json=dict(version_id=vid))
    assert r.status_code == 200, r.text


def test_rollback_restores_the_attachments_of_the_restored_version(notice):
    v2 = sync(notice, B)["version_id"]
    approve(notice, v2)
    v3 = sync(notice)["version_id"]
    approve(notice, v3)
    assert public(notice) == []
    for vid, files in ((notice.v1, [A]), (v2, [B]), (v3, [])):
        rollback(notice, vid)
        assert public(notice) == files


def test_rollback_while_a_version_waits(notice):
    approve(notice, sync(notice, B)["version_id"])
    waiting = sync(notice, C)["version_id"]
    rollback(notice, notice.v1)
    assert public(notice) == [A]
    approve(notice, waiting)
    assert public(notice) == [C]


def test_title_and_attachments_change_together(notice):
    job = sync(notice, B, title="[생활관] 변경된 안내")
    assert (doc(notice)["title"], public(notice)) == (TITLE, [A])
    approve(notice, job["version_id"])
    assert (doc(notice)["title"], public(notice)) == ("[생활관] 변경된 안내", [B])


def test_failed_activation_leaves_everything_as_it_was(notice):
    job = sync(notice, B)
    emb = notice.app.state.services.indexer.embedder
    real, emb.embed_passages = emb.embed_passages, lambda *_a: (_ for _ in ()).throw(MemoryError())
    approve(notice, job["version_id"])
    emb.embed_passages = real
    assert public(notice) == [A]


def test_crash_right_after_the_switch_is_safe_and_healed(notice):
    job = sync(notice, B)
    svc, real = notice.app.state.services, notice.store.update

    def broken(table, patch, eq):  # type: ignore[no-untyped-def]
        if table == "source_documents" and "metadata" in patch:
            raise UpstreamError("database unreachable")
        return real(table, patch, eq)

    notice.store.update = broken
    approve(notice, job["version_id"])
    notice.store.update = real
    api = notice.client.get(f"/api/v1/knowledge/documents/{notice.doc_id}").json()["attachments"]
    assert [a["name"] for a in api] == [B]                       # approved text and approved attachments, never mixed
    j = [x for x in notice.store.t["ingestion_jobs"] if x["job_type"] == "index_version"][-1]
    notice.store.update("ingestion_jobs", {"run_after": "2020-01-01T00:00:00+00:00"}, {"id": j["id"]})
    assert svc.ingestion.run_job(j["id"])["status"] == "succeeded" and public(notice) == [B]


def test_a_list_that_is_already_wrong_is_not_shown_any_more(notice):
    """Before this fix an import overwrote the row. Nothing is corrected in the database; the API shows the approved list."""
    wrong = dict(doc(notice)["metadata"], attachments=[{"name": B, "url": "https://x"}])
    notice.store.update("source_documents", {"metadata": wrong}, {"id": notice.doc_id})
    r = notice.client.get(f"/api/v1/knowledge/documents/{notice.doc_id}").json()
    assert [a["name"] for a in r["attachments"]] == [A] == [a["name"] for a in admin(notice)["metadata"]["attachments"]]
    assert doc(notice)["metadata"]["attachments"][0]["name"] == B                        # data untouched
    approve(notice, sync(notice, C)["version_id"])
    assert public(notice) == [C]                                                         # corrected by the next approval


def test_versions_without_recorded_details_keep_what_is_stored(notice):
    notice.store.update("document_versions", {"extraction_meta": {}}, {"id": notice.v1})
    assert public(notice) == [A]
    job = sync(notice, B)
    assert public(notice) == [A]
    approve(notice, job["version_id"])
    assert public(notice) == [B]


def test_other_documents_are_not_affected(env):
    from tests.test_retrieval import make_doc

    d = make_doc(env, "Guide", "The library opens at nine in the morning. Bring your card.", language="en")
    r = env.client.get(f"/api/v1/knowledge/documents/{d['document_id']}").json()
    assert r["attachments"] == [] and r["notice_no"] is None
    assert get_one(env.store, "source_documents", id=d["document_id"])["metadata"] == {}


def test_public_notice_number_and_keys(notice):
    assert notice.client.get(f"/api/v1/knowledge/documents/{notice.doc_id}").json()["notice_no"] == str(NO)
    assert set(doc(notice)["metadata"]) == {*KEYS, "pinned"}
