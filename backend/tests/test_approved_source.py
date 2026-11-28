"""Translations are made from the approved public text only - and administrators can still review pending edits."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.repositories.base import get_one
from app.services.ingestion.normalize import content_hash
from app.services.llm.base import ScriptedLLMProvider
from tests.test_announcements import create
from tests.test_document_translations import assign
from tests.test_retrieval import make_doc

TITLE, TEXT = "장학금 신청 안내", "신청 기간은 2026-12-01부터입니다. 문의: intl@example.ac.kr"
EDIT = "수정된 공지입니다. 신청 기간은 2026-12-20부터입니다. SECRET-EDIT 문의: intl@example.ac.kr"


def model(env):  # type: ignore[no-untyped-def]
    """The server's own model (the path Gemini uses), recording every prompt."""
    p = ScriptedLLMProvider(lambda s, x: "Scholarship guide 2026-12-01 intl@example.ac.kr")
    svc = env.app.state.services
    svc.announcement_translator.llm = svc.doc_translations.llm = p
    env.settings.translation_fallback_to_gemini = True    # the server's own model is used for announcements: opt-in
    return p


def publish(env, title=TITLE, body=TEXT):  # type: ignore[no-untyped-def]
    a = create(env, submit=True, title=title, body=body)
    assert env.client.post(f"/api/v1/admin/announcements/{a['id']}/approve", headers=env.auth("admin"), json={}).status_code == 200
    return get_one(env.store, "announcements", id=a["id"])


def pending_edit(env, a, text=EDIT):  # type: ignore[no-untyped-def]
    v = env.store.insert("document_versions", dict(document_id=a["document_id"], version_number=2, extracted_text=text,
                                                   content_hash=content_hash(text), verification_status="pending_review"))
    env.app.state.services.indexer.index_version(v["id"])
    return v


def request(env, aid, lang="en"):  # type: ignore[no-untyped-def]
    r = env.client.post(f"/api/v1/admin/announcements/{aid}/translations/{lang}/machine-translate", headers=env.auth("super_admin"))
    assert r.status_code == 202, r.text
    return get_one(env.store, "ingestion_jobs", id=r.json()["job_id"])


def row(env, aid, lang="en"):  # type: ignore[no-untyped-def]
    return get_one(env.store, "announcement_translations", announcement_id=aid, language_code=lang)


def detail(env, aid, lang="en"):  # type: ignore[no-untyped-def]
    return env.client.get(f"/api/v1/admin/announcements/{aid}/translations/{lang}", headers=env.auth("super_admin")).json()


def public(env, aid, lang="en"):  # type: ignore[no-untyped-def]
    return env.client.get(f"/api/v1/announcements/{aid}", params={"lang": lang}).json()


# ------------------------------------------------------------------------------- generation
def test_model_never_sees_an_unapproved_edit(env):
    p, a = model(env), publish(env)
    pending_edit(env, a)
    assert request(env, a["id"])["status"] == "succeeded" and p.calls
    assert all("SECRET-EDIT" not in prompt for _s, prompt in p.calls)
    assert row(env, a["id"])["source_content_hash"] == content_hash(f"{TITLE}\n\n{TEXT}")


def test_result_is_discarded_when_the_source_stops_being_public_meanwhile(env):
    p, a = model(env), publish(env)
    p.responder = lambda s, x: (env.store.update("announcements", {"publication_status": "canceled"}, {"id": a["id"]}), "text")[1]
    assert request(env, a["id"])["error_code"] in ("source_not_public", "source_changed")
    assert row(env, a["id"])["translation_status"] == "todo"


@pytest.mark.parametrize("change", [dict(archived_at="2026-11-24T00:00:00+00:00"), dict(is_canceled=True)])
@pytest.mark.parametrize("when", ["before", "during"])
def test_documents_must_be_public_before_and_after(env, change, when):
    p = model(env)
    d = make_doc(env, "기숙사 안내", "입사일은 2027-02-24입니다. 학생증을 가져오세요.", language="ko")
    tr = env.app.state.services.doc_translations
    tr.sync(d["document_id"])
    job = tr._queue(*tr._context(d["document_id"]), "en", None, force=False)

    def hide(*_a):  # type: ignore[no-untyped-def]
        env.store.update("source_documents", change, {"id": d["document_id"]})
        return "Dormitory"

    if when == "before":
        hide()
    else:
        p.responder = hide
    out = env.app.state.services.ingestion.run_job(job["id"])
    assert (out["status"], out["error_code"]) == ("failed", "source_not_public") and bool(p.calls) is (when == "during")
    assert all(t["translation_status"] == "todo" for t in env.store.t["document_translations"])


def test_document_draft_is_discarded_when_the_title_changes_meanwhile(env):
    p = model(env)
    d = make_doc(env, "기숙사 안내", "입사일은 2027-02-24입니다. 학생증을 가져오세요.", language="ko")
    tr = env.app.state.services.doc_translations
    tr.sync(d["document_id"])
    job = tr._queue(*tr._context(d["document_id"]), "en", None, force=False)
    p.responder = lambda s, x: (env.store.update("source_documents", {"title": "새 제목"}, {"id": d["document_id"]}), "Dorm")[1]
    assert env.app.state.services.ingestion.run_job(job["id"])["error_code"] == "source_changed"


def test_force_never_replaces_later_human_work(env):
    model(env)
    a = publish(env)
    request(env, a["id"])
    svc = env.app.state.services
    job = svc.announcement_translator.queue(a["id"], "en", None, force=True, enqueue=False)
    later = (datetime.now(UTC) + timedelta(seconds=1)).isoformat()
    env.store.update("announcement_translations", dict(title="Human", last_edited_at=later, last_edited_by=env.users["supporter"]),
                     {"id": row(env, a["id"])["id"]})
    assert svc.ingestion.run_job(job["id"])["error_code"] == "human_draft_exists" and row(env, a["id"])["title"] == "Human"


# ----------------------------------------------------- administrators review pending edits
def test_administrators_see_and_compare_the_pending_edit(env):
    a = publish(env)
    v = pending_edit(env, a)
    view = env.client.get(f"/api/v1/admin/announcements/{a['id']}", headers=env.auth("admin")).json()
    assert view["body"] == EDIT                                             # the announcement editor shows the edit
    d = env.client.get(f"/api/v1/admin/documents/{a['document_id']}", headers=env.auth("admin")).json()
    assert d["current_version"]["extracted_text"] == TEXT and d["pending_version"]["extracted_text"] == EDIT
    assert any("SECRET-EDIT" in x for x in d["diff"]["added_lines"])
    queue = env.client.get("/api/v1/admin/documents", params={"has_pending": True}, headers=env.auth("admin")).json()["items"]
    assert [x["pending_version_id"] for x in queue] == [v["id"]]
    assert public(env, a["id"])["body"] == TEXT and detail(env, a["id"])["original"]["body"] == TEXT


def test_administrators_edit_send_back_and_reject_the_pending_edit(env):
    a = publish(env)
    v = pending_edit(env, a)
    h, url = env.auth("admin"), f"/api/v1/admin/versions/{v['id']}"
    assert env.client.patch(url, headers=h, json=dict(extracted_text=EDIT + " corrected")).status_code == 200
    assert env.client.post(url + "/request-changes", headers=h, json=dict(note="Check the date")).status_code == 200
    assert env.client.post(url + "/submit", headers=h).status_code == 200
    assert public(env, a["id"])["body"] == TEXT == detail(env, a["id"])["original"]["body"]
    assert env.client.post(url + "/reject", headers=h, json=dict(reason="Not correct")).status_code == 200
    assert public(env, a["id"])["body"] == TEXT == detail(env, a["id"])["original"]["body"]


def test_approving_the_edit_publishes_it_and_the_translation_follows(env):
    p, a = model(env), publish(env)
    assign(env, "supporter", "en")
    request(env, a["id"])
    assert env.client.post(f"/api/v1/admin/announcements/{a['id']}/translations/en/approve", headers=env.auth("super_admin"),
                           json=dict(original_verified=True)).status_code == 200
    v = pending_edit(env, a)
    # while the edit waits: the approved translation stays valid and public
    assert public(env, a["id"])["translation"]["status"] == "verified" and not detail(env, a["id"])["translation"]["is_outdated"]
    assert env.client.post(f"/api/v1/admin/versions/{v['id']}/approve", headers=env.auth("admin"), json={}).status_code == 202
    assert public(env, a["id"])["body"] == EDIT and public(env, a["id"])["translation"] is None    # never the old translation
    d = detail(env, a["id"])
    assert d["original"]["body"] == EDIT and d["translation"]["is_outdated"]
    assert row(env, a["id"])["is_outdated"] and any(
        n["kind"] == "translation_outdated" for n in env.store.t["user_notifications"])            # the team is told
    p.calls.clear()
    env.client.post(f"/api/v1/admin/announcements/{a['id']}/translations/en/machine-translate", headers=env.auth("super_admin"),
                    params={"force": True})
    assert any("SECRET-EDIT" in prompt for _s, prompt in p.calls)                                   # now it is approved


def test_a_reviewer_can_approve_a_translation_while_an_edit_waits(env):
    model(env)
    a = publish(env)
    pending_edit(env, a)
    request(env, a["id"])
    r = env.client.post(f"/api/v1/admin/announcements/{a['id']}/translations/en/approve", headers=env.auth("super_admin"),
                        json=dict(original_verified=True))
    assert r.status_code == 200 and public(env, a["id"])["translation"]["status"] == "verified"


def test_unpublished_announcements_are_prepared_from_their_draft_as_before(env):
    a = create(env, title=TITLE, body=TEXT)
    assert detail(env, a["id"])["original"]["body"] == TEXT
    env.client.patch(f"/api/v1/admin/announcements/{a['id']}", headers=env.auth("admin"), json=dict(body=EDIT))
    assert detail(env, a["id"])["original"]["body"] == EDIT


def test_pending_document_version_is_reviewed_and_then_translated(env):
    p = model(env)
    d = make_doc(env, "기숙사 안내", "입사일은 2027-02-24입니다. 학생증을 가져오세요.", language="ko")
    new = "입사일은 2027-02-25로 변경되었습니다. SECRET-EDIT 학생증을 가져오세요."
    v = env.store.insert("document_versions", dict(document_id=d["document_id"], version_number=2, extracted_text=new,
                                                   content_hash=content_hash(new), verification_status="pending_review"))
    url = f"/api/v1/admin/documents/{d['document_id']}"
    h = env.auth("super_admin")
    assert env.client.post(url + "/translations/drafts", headers=h, json=dict(languages=["en"])).status_code == 202
    assert p.calls and all("SECRET-EDIT" not in x for _s, x in p.calls)
    shown = env.client.get(url, headers=h).json()
    assert shown["pending_version"]["extracted_text"] == new and shown["diff"]["added_count"] == 1
    assert env.client.post(f"/api/v1/admin/versions/{v['id']}/approve", headers=h, json={}).status_code == 202
    p.calls.clear()
    assert env.client.post(url + "/translations/drafts", headers=h, json=dict(languages=["en"])).status_code == 202
    assert any("SECRET-EDIT" in x for _s, x in p.calls)
