"""`no pending version` (production, 2026-11) on the REAL database: the stuck state, its recovery, and the guard.

Runs on every schema from 0015 (production) onwards: the fix is application code only. Skipped unless configured.
"""
from __future__ import annotations

import uuid

import pytest

from tests.integration.test_postgres_integration import IT, PSQL, REST, sql

pytestmark = pytest.mark.skipif(not (REST and PSQL), reason="set SCH_IT_REST_URL and SCH_IT_PSQL to run")


@pytest.fixture(scope="module")
def it() -> IT:
    return IT()


def submitted(it: IT) -> tuple[dict, str]:  # type: ignore[type-arg]
    tag = uuid.uuid4().hex[:8]
    a = it.client.post("/api/v1/admin/announcements", headers=it.auth("admin"), json=dict(
        title=f"장학금 안내 {tag}", body=f"장학금 신청 기간은 2026-12-01부터 12-10까지입니다. {tag}", category="scholarships",
        source_type="manual_text", submit=True, evidence_note="integration test")).json()
    assert a["publication_status"] == "pending_approval", a
    vid = sql(f"select id from public.document_versions where document_id = '{a['document_id']}'")
    assert sql(f"select verification_status from public.document_versions where id = '{vid}'") == "pending_review"
    return a, vid


def status(aid: str) -> str:
    return sql(f"select publication_status from public.announcements where id = '{aid}'")


def test_document_review_no_longer_touches_an_unpublished_announcements_text(it: IT):
    a, vid = submitted(it)
    h = it.auth("admin")
    queue = it.client.get("/api/v1/admin/documents", headers=h, params={"review_status": "pending_review",
                                                                         "page_size": 100}).json()["items"]
    assert a["document_id"] not in {d["id"] for d in queue}
    for path, body in (("approve", {}), ("reject", {"reason": "wrong date"}), ("request-changes", {"note": "fix the date"})):
        assert it.client.post(f"/api/v1/admin/versions/{vid}/{path}", headers=h, json=body).status_code == 409, path
    assert sql(f"select verification_status from public.document_versions where id = '{vid}'") == "pending_review"
    assert it.client.post(f"/api/v1/admin/announcements/{a['id']}/approve", headers=h, json={}).status_code == 200
    assert status(a["id"]) == "published"


def test_the_production_state_is_reproduced_and_recovered(it: IT):
    """Text approved through document review before the fix: the database function refuses, the API publishes."""
    a, vid = submitted(it)
    svc = it.app.state.services
    svc.indexer.index_version(vid, embed=True)
    svc.store.rpc("approve_document_version", dict(p_version_id=vid, p_actor=it.users["admin"], p_note="checked"))
    assert status(a["id"]) == "pending_approval"
    before = sql(f"select concat_ws('|', verification_status, approved_by, approved_at, content_hash) "
                 f"from public.document_versions where id = '{vid}'")
    # the exact production error, from the database function itself
    with pytest.raises(Exception, match="no pending version"):
        svc.store.rpc("approve_announcement", dict(p_announcement_id=a["id"], p_actor=it.users["admin"], p_note=None))
    r = it.client.post(f"/api/v1/admin/announcements/{a['id']}/approve", headers=it.auth("admin"), json={"note": "ok"})
    assert r.status_code == 200, r.text
    assert status(a["id"]) == "published"
    assert sql(f"select concat_ws('|', verification_status, approved_by, approved_at, content_hash) "
               f"from public.document_versions where id = '{vid}'") == before          # history untouched
    assert sql(f"select count(*) from public.audit_log where entity_id = '{a['id']}' and action = 'announcement.approve' "
               f"and details->>'text_already_approved' = 'true'") == "1"
    assert a["id"] in {x["id"] for x in it.client.get("/api/v1/announcements").json()["items"]}


def test_a_sent_back_text_is_explained_and_nothing_changes(it: IT):
    a, vid = submitted(it)
    it.app.state.services.store.rpc("request_version_changes", dict(p_version_id=vid, p_actor=it.users["admin"],
                                                                    p_note="check the date"))
    r = it.client.post(f"/api/v1/admin/announcements/{a['id']}/approve", headers=it.auth("admin"), json={})
    assert r.status_code == 409 and "check the date" in r.json()["error"]["message"]
    assert status(a["id"]) == "pending_approval"
    assert it.client.post(f"/api/v1/admin/announcements/{a['id']}/reject", headers=it.auth("admin"),
                          json={"reason": "check the date"}).status_code == 200
    assert status(a["id"]) == "rejected"


def test_a_live_stuck_text_is_withdrawn_by_cancel_not_hidden_by_reject(it: IT):
    a, vid = submitted(it)
    svc, h = it.app.state.services, it.auth("admin")
    svc.indexer.index_version(vid, embed=True)
    svc.store.rpc("approve_document_version", dict(p_version_id=vid, p_actor=it.users["admin"], p_note="checked"))
    live = f"select count(*) from public.searchable_chunks where document_id = '{a['document_id']}'"
    assert int(sql(live)) > 0                                     # the production consequence: searchable while "pending"
    assert it.client.post(f"/api/v1/admin/announcements/{a['id']}/reject", headers=h,
                          json={"reason": "not now"}).status_code == 409
    assert status(a["id"]) == "pending_approval"
    assert it.client.post(f"/api/v1/admin/announcements/{a['id']}/cancel", headers=h,
                          json={"reason": "withdrawn"}).status_code == 200
    assert status(a["id"]) == "canceled" and int(sql(live)) == 0
    assert sql(f"select verification_status from public.document_versions where id = '{vid}'") == "approved"
