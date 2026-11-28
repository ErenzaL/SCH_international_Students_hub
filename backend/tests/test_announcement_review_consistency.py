"""Production error `no pending version` (announcement shown as "Pending approval" but its text version is no longer
pending_review).

Cause: Admin → Review listed an announcement twice, as an announcement AND as the document holding its text. Approving,
rejecting or sending back the DOCUMENT moved only the text version; the announcement stayed `pending_approval` and its
approval then failed in `approve_announcement` ("no pending version").
"""
from __future__ import annotations

from app.repositories.base import Query
from tests.test_announcements import create

AUTH = "admin"


def submitted(env):  # type: ignore[no-untyped-def]
    a = create(env, submit=True)
    assert a["publication_status"] == "pending_approval"
    v = env.store.select("document_versions", Query(eq={"document_id": a["document_id"]}))[0][0]
    assert v["verification_status"] == "pending_review"
    return a, v


def ann(env, aid):  # type: ignore[no-untyped-def]
    return env.store.select("announcements", Query(eq={"id": aid}))[0][0]


def version(env, vid):  # type: ignore[no-untyped-def]
    return env.store.select("document_versions", Query(eq={"id": vid}))[0][0]


def approve(env, aid, note=None):  # type: ignore[no-untyped-def]
    return env.client.post(f"/api/v1/admin/announcements/{aid}/approve", headers=env.auth(AUTH), json={"note": note})


# ---------------------------------------------------------------- prevention: one review path per announcement
def test_review_queue_lists_an_announcement_once(env) -> None:  # type: ignore[no-untyped-def]
    a, _v = submitted(env)
    docs = env.client.get("/api/v1/admin/documents", headers=env.auth(AUTH), params={"review_status": "pending_review"}).json()
    assert a["document_id"] not in {d["id"] for d in docs["items"]}
    anns = env.client.get("/api/v1/admin/announcements", headers=env.auth(AUTH), params={"status": "pending_approval"}).json()
    assert a["id"] in {x["id"] for x in anns["items"]}


def test_document_review_actions_refuse_an_announcement_text(env) -> None:  # type: ignore[no-untyped-def]
    a, v = submitted(env)
    hd = env.auth(AUTH)
    for path, body in (("approve", {}), ("reject", {"reason": "wrong date"}), ("request-changes", {"note": "fix the date"})):
        r = env.client.post(f"/api/v1/admin/versions/{v['id']}/{path}", headers=hd, json=body)
        assert r.status_code == 409, (path, r.text)
        assert "Announcements" in r.json()["error"]["message"]
    assert version(env, v["id"])["verification_status"] == "pending_review"      # nothing moved
    assert approve(env, a["id"]).status_code == 200                               # the announcement path works
    assert ann(env, a["id"])["publication_status"] == "published"


# ---------------------------------------------------------------- recovery of records already in the stuck state
def stuck_with_text_approved_in_document_review(env):  # type: ignore[no-untyped-def]
    """The production state: the text version was approved through document review (before the fix)."""
    a, v = submitted(env)
    env.app.state.services.indexer.index_version(v["id"], embed=True)   # what the document approval job does first
    env.store.rpc("approve_document_version", dict(p_version_id=v["id"], p_actor=env.users["admin"], p_note="checked"))
    assert ann(env, a["id"])["publication_status"] == "pending_approval"
    assert version(env, v["id"])["verification_status"] == "approved"
    return a, v


def test_the_old_failure_is_reproduced_at_the_database_function(env) -> None:  # type: ignore[no-untyped-def]
    a, _v = stuck_with_text_approved_in_document_review(env)
    import pytest

    from app.core.errors import InvalidState
    with pytest.raises(InvalidState, match="no pending version"):
        env.store.rpc("approve_announcement", dict(p_announcement_id=a["id"], p_actor=env.users["admin"], p_note=None))


def test_stuck_announcement_whose_text_was_already_approved_can_be_published(env) -> None:  # type: ignore[no-untyped-def]
    a, v = stuck_with_text_approved_in_document_review(env)
    before = version(env, v["id"])
    r = approve(env, a["id"], note="published after the earlier text approval")
    assert r.status_code == 200, r.text
    assert r.json()["publication_status"] == "published"
    after = version(env, v["id"])
    # the original content and its approval history are untouched
    assert {k: after.get(k) for k in ("extracted_text", "verification_status", "approved_by", "approved_at")} == \
           {k: before.get(k) for k in ("extracted_text", "verification_status", "approved_by", "approved_at")}
    audit = [x for x in env.store.select("audit_log", Query(eq={"entity_id": a["id"]}))[0] if x["action"] == "announcement.approve"]
    assert len(audit) == 1 and audit[0]["details"]["text_version_id"] == v["id"]
    assert audit[0]["details"]["text_already_approved"] is True
    # and it is public now
    assert a["id"] in {x["id"] for x in env.client.get("/api/v1/announcements").json()["items"]}


def test_stuck_announcement_whose_text_is_live_cannot_be_rejected_but_can_be_canceled(env) -> None:  # type: ignore[no-untyped-def]
    """Rejecting would leave its (already approved, searchable) text in the chat under a 'rejected' announcement."""
    a, v = stuck_with_text_approved_in_document_review(env)
    hd = env.auth(AUTH)
    r = env.client.post(f"/api/v1/admin/announcements/{a['id']}/reject", headers=hd, json={"reason": "not now"})
    assert r.status_code == 409 and "Cancel" in r.json()["error"]["message"]
    assert ann(env, a["id"])["publication_status"] == "pending_approval"
    before = version(env, v["id"])
    r = env.client.post(f"/api/v1/admin/announcements/{a['id']}/cancel", headers=hd, json={"reason": "withdrawn"})
    assert r.status_code == 200, r.text
    assert ann(env, a["id"])["publication_status"] == "canceled"
    assert version(env, v["id"]) == before                                        # approval history kept
    doc = env.store.select("source_documents", Query(eq={"id": a["document_id"]}))[0][0]
    assert doc["is_canceled"]                                                     # out of search


def test_stuck_announcement_whose_text_was_sent_back_explains_what_to_do(env) -> None:  # type: ignore[no-untyped-def]
    a, v = submitted(env)
    env.store.rpc("request_version_changes", dict(p_version_id=v["id"], p_actor=env.users["admin"], p_note="fix the date"))
    r = approve(env, a["id"])
    assert r.status_code == 409
    msg = r.json()["error"]["message"]
    assert "sent back for changes" in msg and "fix the date" in msg and "Reject" in msg
    assert ann(env, a["id"])["publication_status"] == "pending_approval"          # nothing changed by the refusal
    # the documented way out works end to end: reject -> edit -> resubmit -> approve
    hd = env.auth(AUTH)
    assert env.client.post(f"/api/v1/admin/announcements/{a['id']}/reject", headers=hd, json={"reason": "fix the date"}).status_code == 200
    assert env.client.patch(f"/api/v1/admin/announcements/{a['id']}", headers=hd,
                            json={"body": "장학금 신청 기간은 12월 10일까지입니다. 신청서를 제출하세요."}).status_code == 200
    assert env.client.post(f"/api/v1/admin/announcements/{a['id']}/submit", headers=hd).status_code == 200
    assert approve(env, a["id"]).status_code == 200


def test_stuck_announcement_whose_text_was_rejected_explains_what_to_do(env) -> None:  # type: ignore[no-untyped-def]
    a, v = submitted(env)
    env.store.rpc("reject_document_version", dict(p_version_id=v["id"], p_actor=env.users["admin"], p_reason="not official"))
    r = approve(env, a["id"])
    assert r.status_code == 409
    assert "rejected" in r.json()["error"]["message"] and "not official" in r.json()["error"]["message"]
    assert ann(env, a["id"])["publication_status"] == "pending_approval"


def test_normal_workflow_is_unchanged(env) -> None:  # type: ignore[no-untyped-def]
    a, v = submitted(env)
    assert approve(env, a["id"], note="ok").status_code == 200
    assert version(env, v["id"])["verification_status"] == "approved"
    audit = [x for x in env.store.select("audit_log", Query(eq={"entity_id": a["id"]}))[0] if x["action"] == "announcement.approve"]
    assert len(audit) == 1


def test_a_published_announcements_pending_edit_stays_in_document_review(env) -> None:  # type: ignore[no-untyped-def]
    """The boundary: Release A reviews edits of PUBLISHED announcements in document review; that must keep working."""
    from app.services.ingestion.normalize import content_hash
    a, _v = submitted(env)
    assert approve(env, a["id"]).status_code == 200
    text = "수정된 공지입니다. 신청 기간은 2026-12-20부터입니다."
    edit = env.store.insert("document_versions", dict(document_id=a["document_id"], version_number=2, extracted_text=text,
                                                      content_hash=content_hash(text), verification_status="pending_review"))
    docs = env.client.get("/api/v1/admin/documents", headers=env.auth(AUTH), params={"review_status": "pending_review"}).json()
    assert a["document_id"] in {d["id"] for d in docs["items"]}
    r = env.client.post(f"/api/v1/admin/versions/{edit['id']}/request-changes", headers=env.auth(AUTH), json={"note": "date?"})
    assert r.status_code == 200, r.text
