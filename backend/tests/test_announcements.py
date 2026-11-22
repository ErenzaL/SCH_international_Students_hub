from datetime import date, timedelta

import pytest

TODAY = date.today()


def payload(**kw):
    base = dict(title="장학금 신청 안내", body="장학금 신청 기간 안내입니다. 신청서를 제출하세요.", category="scholarships",
                target_audience="All international students", source_type="manual_text",
                evidence_note="Posted on the official board (test data)", event_date=str(TODAY + timedelta(days=20)),
                deadline=str(TODAY + timedelta(days=10)))
    base.update(kw)
    return base


def create(env, role="admin", **kw):
    r = env.client.post("/api/v1/admin/announcements", headers=env.auth(role), json=payload(**kw))
    assert r.status_code == 201, r.text
    return r.json()


def pub_list(env, **params):
    return env.client.get("/api/v1/announcements", params=params).json()


def test_draft_is_private_until_approved(env):
    a = create(env)
    assert a["publication_status"] == "draft" and a["body"].startswith("장학금")
    assert pub_list(env)["total"] == 0
    assert env.client.get(f"/api/v1/announcements/{a['id']}").status_code == 404
    sub = env.client.post(f"/api/v1/admin/announcements/{a['id']}/submit", headers=env.auth("admin")).json()
    assert sub["publication_status"] == "pending_approval"
    assert pub_list(env)["total"] == 0  # pending is still private
    assert env.client.post("/api/v1/knowledge/search", json=dict(query="장학금")).json()["results"] == []


def test_full_workflow_publish_and_search_and_history(env):
    a = create(env, submit=True)
    assert a["publication_status"] == "pending_approval"
    r = env.client.post(f"/api/v1/admin/announcements/{a['id']}/approve", headers=env.auth("admin"), json={"note": "verified"})
    assert r.status_code == 200 and r.json()["publication_status"] == "published"
    listing = pub_list(env)
    assert listing["total"] == 1
    item = listing["items"][0]
    assert item["status"] == "active" and item["deadline"] == str(TODAY + timedelta(days=10))
    assert item["source"]["organization"].startswith("Soonchunhyang") and item["original_language"] == "ko"
    detail = env.client.get(f"/api/v1/announcements/{a['id']}").json()
    assert "신청서를 제출하세요" in detail["body"] and detail["verified_at"] and detail["translations"] == []
    res = env.client.post("/api/v1/knowledge/search", json=dict(query="장학금 신청")).json()["results"]
    assert res and res[0]["document_title"] == "장학금 신청 안내"
    hist = env.client.get(f"/api/v1/admin/announcements/{a['id']}/history", headers=env.auth("admin")).json()["items"]
    assert [h["action"] for h in hist][-3:] == ["announcement.create", "announcement.submit", "announcement.approve"] or \
        {"announcement.submit", "announcement.approve"} <= {h["action"] for h in hist}


def test_reject_edit_resubmit_preserves_rejected_version(env):
    a = create(env, submit=True)
    r = env.client.post(f"/api/v1/admin/announcements/{a['id']}/reject", headers=env.auth("admin"), json={"reason": "date unclear"})
    assert r.json()["publication_status"] == "rejected" and r.json()["rejection_reason"] == "date unclear"
    p = env.client.patch(f"/api/v1/admin/announcements/{a['id']}", headers=env.auth("admin"),
                         json={"body": "수정된 본문입니다. 마감일을 명확히 했습니다.", "deadline": None})
    assert p.status_code == 200, p.text
    assert p.json()["publication_status"] == "draft" and p.json()["deadline"] is None and "수정된" in p.json()["body"]
    sub = env.client.post(f"/api/v1/admin/announcements/{a['id']}/submit", headers=env.auth("admin"))
    assert sub.status_code == 200
    versions, _ = env.store.select("document_versions")
    assert sorted((v["version_number"], v["verification_status"]) for v in versions) == [(1, "rejected"), (2, "pending_review")]
    ok = env.client.post(f"/api/v1/admin/announcements/{a['id']}/approve", headers=env.auth("admin"), json={})
    assert ok.status_code == 200


def test_state_machine_guards(env):
    a = create(env)
    aid = a["id"]
    # cannot approve a draft
    assert env.client.post(f"/api/v1/admin/announcements/{aid}/approve", headers=env.auth("admin"), json={}).status_code == 409
    # reject requires a reason
    env.client.post(f"/api/v1/admin/announcements/{aid}/submit", headers=env.auth("admin"))
    assert env.client.post(f"/api/v1/admin/announcements/{aid}/reject", headers=env.auth("admin"), json={}).status_code == 422
    # cannot edit while pending
    assert env.client.patch(f"/api/v1/admin/announcements/{aid}", headers=env.auth("admin"), json={"title": "x"}).status_code == 409
    env.client.post(f"/api/v1/admin/announcements/{aid}/approve", headers=env.auth("admin"), json={})
    # double approve fails, edit published fails, cancel works and unpublishes
    assert env.client.post(f"/api/v1/admin/announcements/{aid}/approve", headers=env.auth("admin"), json={}).status_code == 409
    assert env.client.patch(f"/api/v1/admin/announcements/{aid}", headers=env.auth("admin"), json={"title": "x"}).status_code == 409
    c = env.client.post(f"/api/v1/admin/announcements/{aid}/cancel", headers=env.auth("admin"), json={"reason": "event canceled"})
    assert c.json()["publication_status"] == "canceled"
    assert pub_list(env)["total"] == 0
    assert env.client.post("/api/v1/knowledge/search", json=dict(query="장학금")).json()["results"] == []


def test_supporters_can_submit_but_not_approve_and_only_see_their_own(env):
    mine = create(env, role="supporter", submit=True)
    other = create(env, role="admin")
    assert env.client.post(f"/api/v1/admin/announcements/{mine['id']}/approve", headers=env.auth("supporter"), json={}).status_code == 403
    assert env.client.post(f"/api/v1/admin/announcements/{mine['id']}/reject", headers=env.auth("supporter"), json={"reason": "abc"}).status_code == 403
    ids = [x["id"] for x in env.client.get("/api/v1/admin/announcements", headers=env.auth("supporter")).json()["items"]]
    assert ids == [mine["id"]]
    assert env.client.get(f"/api/v1/admin/announcements/{other['id']}", headers=env.auth("supporter")).status_code == 403
    assert env.client.post(f"/api/v1/admin/announcements/{other['id']}/submit", headers=env.auth("supporter")).status_code == 403
    assert len(env.client.get("/api/v1/admin/announcements", headers=env.auth("admin")).json()["items"]) == 2


def test_kakao_submission_needs_authorization_privacy_redaction_and_review(env):
    raw = "[홍길동] [오후 3:21] 장학금 설명회 안내. 문의 010-1234-5678"
    r = env.client.post("/api/v1/admin/announcements", headers=env.auth("supporter"),
                        json=payload(body=raw, source_type="kakao_message"))
    assert r.status_code == 422
    r = env.client.post("/api/v1/admin/announcements", headers=env.auth("supporter"),
                        json=payload(body=raw, source_type="kakao_message", authorized_by_supporter=True, submit=True))
    assert r.status_code == 201
    body = r.json()["body"]
    assert "홍길동" not in body and "010-1234-5678" not in body and "장학금 설명회" in body
    assert r.json()["publication_status"] == "pending_approval"  # never auto-published
    src, _ = env.store.select("knowledge_sources")
    assert src[0]["authority_type"] == "supporter_submitted" and src[0]["source_type"] == "kakao_message"


@pytest.mark.parametrize("kw,code", [
    (dict(category="nope"), 422), (dict(body="short"), 422), (dict(title=""), 422),
    (dict(valid_from=str(TODAY + timedelta(days=5)), deadline=str(TODAY)), 422),
    (dict(evidence_url="javascript:alert(1)"), 422), (dict(source_type="website"), 422),
])
def test_announcement_validation(env, kw, code):
    r = env.client.post("/api/v1/admin/announcements", headers=env.auth("admin"), json=payload(**kw))
    assert r.status_code == code


def test_status_computation_and_filters(env):
    specs = [
        ("active one", dict(deadline=str(TODAY + timedelta(days=3)))),
        ("no deadline", dict(deadline=None)),
        ("expired one", dict(deadline=str(TODAY - timedelta(days=2)), event_date=None)),
        ("upcoming one", dict(valid_from=str(TODAY + timedelta(days=5)), deadline=str(TODAY + timedelta(days=9)))),
    ]
    for i, (title, kw) in enumerate(specs):
        a = create(env, title=title, body=f"본문 내용입니다 번호 {i} 가나다라마바사", category="scholarships" if i % 2 else "academic-life", **kw)
        env.client.post(f"/api/v1/admin/announcements/{a['id']}/submit", headers=env.auth("admin"))
        assert env.client.post(f"/api/v1/admin/announcements/{a['id']}/approve", headers=env.auth("admin"), json={}).status_code == 200
    by_title = {i["title"]: i for i in pub_list(env)["items"]}
    assert {t: i["status"] for t, i in by_title.items()} == {
        "active one": "active", "no deadline": "active", "expired one": "expired", "upcoming one": "upcoming"}
    assert {i["title"] for i in pub_list(env, status="active")["items"]} == {"active one", "no deadline"}
    assert [i["title"] for i in pub_list(env, status="expired")["items"]] == ["expired one"]
    assert [i["title"] for i in pub_list(env, status="upcoming")["items"]] == ["upcoming one"]
    assert {i["title"] for i in pub_list(env, category="scholarships")["items"]} == {"no deadline", "upcoming one"}
    assert [i["title"] for i in pub_list(env, q="expired")["items"]] == ["expired one"]
    assert pub_list(env, page_size=2)["total"] == 4 and len(pub_list(env, page_size=2)["items"]) == 2
    assert env.client.get("/api/v1/announcements", params={"page_size": 101}).status_code == 422
    # expired announcements are visible in the list but no longer searchable evidence
    titles = [r["document_title"] for r in env.client.post("/api/v1/knowledge/search", json=dict(query="본문 내용입니다", top_k=20)).json()["results"]]
    assert "expired one" not in titles and "upcoming one" not in titles and "active one" in titles


def test_translations_are_private_until_human_approved(env):
    env.client.put(f"/api/v1/admin/users/{env.users['supporter']}/languages", headers=env.auth("admin"), json={"languages": ["id"]})
    a = create(env, submit=True)
    env.client.post(f"/api/v1/admin/announcements/{a['id']}/approve", headers=env.auth("admin"), json={})
    aid = a["id"]
    tr = dict(title="Pengumuman beasiswa", body="Terjemahan.", translation_status="machine_draft")
    # a supporter not assigned to 'vi' is rejected, assigned to 'id' is fine
    assert env.client.put(f"/api/v1/admin/announcements/{aid}/translations/vi", headers=env.auth("supporter"), json=tr).status_code == 403
    r = env.client.put(f"/api/v1/admin/announcements/{aid}/translations/id", headers=env.auth("supporter"), json=tr)
    assert r.status_code == 200 and r.json()["is_machine_translated"] is True
    assert env.client.get(f"/api/v1/announcements/{aid}").json()["translations"] == []  # machine draft never public
    assert pub_list(env, language="id")["total"] == 0
    r = env.client.post(f"/api/v1/admin/announcements/{aid}/translations/id/approve", headers=env.auth("supporter"))
    assert r.status_code == 200 and r.json()["translation_status"] == "human_approved" and r.json()["reviewed_by_name"] == "Supporter"
    d = env.client.get(f"/api/v1/announcements/{aid}").json()
    assert d["translations"][0]["language"] == "id" and d["translations"][0]["translation_status"] == "human_approved"
    assert "id" in d["available_languages"] and pub_list(env, language="id")["total"] == 1
    assert pub_list(env, language="ko")["total"] == 1 and pub_list(env, language="vi")["total"] == 0
    # editing an approved translation voids the approval
    env.client.put(f"/api/v1/admin/announcements/{aid}/translations/id", headers=env.auth("supporter"),
                   json=dict(title="Revisi", body="Teks baru", translation_status="in_review"))
    assert env.client.get(f"/api/v1/announcements/{aid}").json()["translations"] == []
    q = env.client.get("/api/v1/admin/translations", headers=env.auth("supporter")).json()
    assert q["total"] == 1 and q["items"][0]["announcement_title"] == "장학금 신청 안내"
    assert env.client.put(f"/api/v1/admin/announcements/{aid}/translations/ko", headers=env.auth("admin"), json=tr).status_code == 422


def test_public_knowledge_hides_private_and_announcement_documents(env):
    from tests.test_retrieval import make_doc

    make_doc(env, "Public guide", "Public guide text about banking accounts for students.", category="banking-taxes")
    make_doc(env, "Pending guide", "Pending text should stay private.", category="banking-taxes", approve=False)
    make_doc(env, "Kakao private", "Kakao chat sourced material should not be a public article.", category="daily-living",
             source_type="kakao_message", authority="supporter_submitted")
    a = create(env, submit=True)
    env.client.post(f"/api/v1/admin/announcements/{a['id']}/approve", headers=env.auth("admin"), json={})
    docs = env.client.get("/api/v1/knowledge/documents").json()
    assert [d["title"] for d in docs["items"]] == ["Public guide"]
    assert env.client.get("/api/v1/knowledge/documents", params={"category": "banking-taxes", "q": "guide"}).json()["total"] == 1
    assert env.client.get("/api/v1/knowledge/documents", params={"scope": "university"}).json()["total"] == 0
    assert env.client.get("/api/v1/knowledge/documents", params={"category": "bad"}).status_code == 422
    cats = {c["slug"]: c for c in env.client.get("/api/v1/categories").json()["items"]}
    assert cats["banking-taxes"]["document_count"] == 1 and cats["scholarships"]["announcement_count"] == 1
    detail_id = docs["items"][0]["id"]
    d = env.client.get(f"/api/v1/knowledge/documents/{detail_id}").json()
    assert d["scope"] == "national" and d["verified_at"] and "banking accounts" in d["content"]
    kakao_doc = [x for x in env.store.t["source_documents"] if x["title"] == "Kakao private"][0]
    assert env.client.get(f"/api/v1/knowledge/documents/{kakao_doc['id']}").status_code == 404
    ann_doc = [x for x in env.store.t["source_documents"] if x["document_type"] == "announcement"][0]
    assert env.client.get(f"/api/v1/knowledge/documents/{ann_doc['id']}").status_code == 404
