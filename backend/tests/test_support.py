"""Language-based support, persistent AI conversations, consented handoff, routing and translation review."""
from __future__ import annotations

import uuid

import pytest

from app.repositories.base import Query
from tests.conftest import make_token


def add_user(env, name, role="student", lang="en"):
    uid = str(uuid.uuid4())
    env.store.insert("profiles", dict(id=uid, email=f"{name}@example.test", display_name=name.title(), role=role,
                                      preferred_language=lang, preferred_language_confirmed=True))
    env.users[name] = uid
    return uid


def h(env, name):
    return {"Authorization": f"Bearer {make_token(env.users[name])}"}


def team(env, name, *assignments):
    r = env.client.put(f"/api/v1/admin/users/{env.users[name]}/team", headers=env.auth("super_admin"),
                       json={"assignments": [dict(language=a[0], can_support=True, can_review_translations="review" in a,
                                                  is_team_lead="lead" in a) for a in assignments]})
    assert r.status_code == 200, r.text


@pytest.fixture
def world(env):
    add_user(env, "ayu", lang="id")           # Indonesian student
    add_user(env, "minh", lang="vi")          # Vietnamese student
    add_user(env, "sup_id", "supporter")      # Indonesian supporter
    add_user(env, "sup_id2", "supporter")     # second Indonesian supporter
    add_user(env, "sup_vi", "supporter")      # Vietnamese supporter
    add_user(env, "lead_id", "supporter")     # Indonesian team lead (language-scoped admin)
    team(env, "sup_id", ("id",))
    team(env, "sup_id2", ("id",))
    team(env, "sup_vi", ("vi",), ("en",))
    team(env, "lead_id", ("id", "lead"))
    # the lead should not take tickets automatically in these tests
    env.client.put("/api/v1/support/me/availability", headers=h(env, "lead_id"), json={"is_available": False})
    return env


def converse(env, who, text="Bagaimana cara memperpanjang visa D-2?"):
    c = env.client.post("/api/v1/conversations", headers=h(env, who), json={}).json()
    r = env.client.post(f"/api/v1/conversations/{c['id']}/messages", headers=h(env, who), json={"content": text})
    assert r.status_code == 201, r.text
    return c, r.json()


def handoff(env, who, conv, msg_ids, **kw):
    body = dict(subject="Perpanjangan visa D-2", summary="Saya perlu bantuan memperpanjang visa.", conversation_id=conv["id"],
                message_ids=msg_ids, consent=True)
    body.update(kw)
    return env.client.post("/api/v1/support/tickets", headers=h(env, who), json=body)


# ------------------------------------------------------------- A, B, H: profile language
def test_a_b_h_preferred_language_is_validated_and_changeable(world):
    env = world
    me = env.client.patch("/api/v1/me", headers=h(env, "ayu"), json={"preferred_language": "id"}).json()
    assert me["preferred_language"] == "id" and me["role"] == "student" and me["preferred_language_confirmed"]
    assert env.client.patch("/api/v1/me", headers=h(env, "ayu"), json={"preferred_language": "fr"}).status_code == 422
    # role cannot be set through the profile endpoint
    r = env.client.patch("/api/v1/me", headers=h(env, "ayu"), json={"preferred_language": "id", "role": "super_admin"})
    assert r.status_code == 200 and r.json()["role"] == "student"
    assert env.client.patch("/api/v1/me", headers=h(env, "minh"), json={"preferred_language": "vi"}).json()[
        "preferred_language"] == "vi"


# ------------------------------------------------------------- C: persistent conversations
def test_c_conversation_history_persists_and_is_private(world):
    env = world
    c, out = converse(env, "ayu")
    from app.services.assistant.texts import t

    assert out["assistant_message"]["language"] == "id"
    assert out["assistant_message"]["content"] == t("none", "id")       # honest: nothing found, said in Indonesian
    assert out["assistant_message"]["metadata"]["offer_handoff"] is False   # no automatic offer for a general question
    # "sign out and back in" = a new token for the same user: history is still there
    fresh = {"Authorization": f"Bearer {make_token(env.users['ayu'])}"}
    lst = env.client.get("/api/v1/conversations", headers=fresh).json()
    assert lst["total"] == 1 and lst["items"][0]["message_count"] == 2
    detail = env.client.get(f"/api/v1/conversations/{c['id']}", headers=fresh).json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    # another user (even staff) cannot read it: same 404 as "does not exist"
    for who in ("minh", "sup_id", "lead_id"):
        assert env.client.get(f"/api/v1/conversations/{c['id']}", headers=h(env, who)).status_code == 404
    assert env.client.get(f"/api/v1/conversations/{c['id']}", headers=env.auth("super_admin")).status_code == 404
    # rename, per-message language, delete
    assert env.client.patch(f"/api/v1/conversations/{c['id']}", headers=fresh, json={"title": "Visa"}).json()["title"] == "Visa"
    r = env.client.post(f"/api/v1/conversations/{c['id']}/messages", headers=fresh,
                        json={"content": "How do I extend my visa?", "language": "en"}).json()
    assert r["assistant_message"]["language"] == "en"
    assert env.client.get("/api/v1/me", headers=fresh).json()["preferred_language"] == "id"  # profile unchanged
    # private conversations are never part of the shared RAG index
    assert not env.store.select("document_chunks", Query(or_ilike=[("content", "perpanjang")]))[0]
    assert env.client.delete(f"/api/v1/conversations/{c['id']}", headers=fresh).status_code == 204
    assert env.client.get("/api/v1/conversations", headers=fresh).json()["total"] == 0


# ------------------------------------------------------------- D, E, F, G: handoff + isolation
def test_d_e_f_g_consented_handoff_routing_isolation_and_reply(world):
    env = world
    c, out = converse(env, "ayu")
    um, am = out["user_message"]["id"], out["assistant_message"]["id"]
    assert handoff(env, "ayu", c, [um], consent=False).status_code == 422        # explicit consent required
    r = handoff(env, "ayu", c, [um], additional_message="Visa saya habis bulan depan.")
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["language"] == "id" and t["status"] == "assigned" and len(t["shared_context"]) == 1  # only what was selected
    assert t["shared_context"][0]["role"] == "user" and am not in str(t["shared_context"])
    tid = t["id"]
    ticket = env.store.select("support_tickets", Query(eq={"id": tid}))[0][0]
    assignee = ticket["assigned_to"]
    assert assignee in (env.users["sup_id"], env.users["sup_id2"])
    other_id = env.users["sup_id2"] if assignee == env.users["sup_id"] else env.users["sup_id"]
    name_of = {v: k for k, v in env.users.items()}

    # E: assigned Indonesian supporter can read; the other Indonesian supporter sees no content
    assert env.client.get(f"/api/v1/support/tickets/{tid}", headers=h(env, name_of[assignee])).status_code == 200
    assert env.client.get(f"/api/v1/support/tickets/{tid}", headers=h(env, name_of[other_id])).status_code == 404
    # ... and neither can read the student's AI conversation (handoff copies only the selected message)
    assert env.client.get(f"/api/v1/conversations/{c['id']}", headers=h(env, name_of[assignee])).status_code == 404
    # F: Vietnamese supporter guessing the id -> same 404 as a missing ticket; no queue visibility either
    assert env.client.get(f"/api/v1/support/tickets/{tid}", headers=h(env, "sup_vi")).status_code == 404
    assert env.client.post(f"/api/v1/support/tickets/{tid}/messages", headers=h(env, "sup_vi"),
                           json={"body": "hi"}).status_code == 404
    assert env.client.get("/api/v1/support/inbox?view=queue&language=id", headers=h(env, "sup_vi")).status_code == 403
    # plain admin without a language assignment has no access to private support content
    assert env.client.get(f"/api/v1/support/tickets/{tid}", headers=env.auth("admin")).status_code == 404
    # team lead of the language (triage role) can read; staff reads are audited
    assert env.client.get(f"/api/v1/support/tickets/{tid}", headers=h(env, "lead_id")).status_code == 200
    views = env.store.select("audit_log", Query(eq={"action": "ticket.view", "entity_id": tid}))[0]
    assert {v["actor_id"] for v in views} == {assignee, env.users["lead_id"]}

    # G: accept + reply -> student notified (no private body in the notification)
    acc = env.client.post(f"/api/v1/support/tickets/{tid}/accept", headers=h(env, name_of[assignee])).json()
    assert acc["status"] == "open"
    env.client.post(f"/api/v1/support/tickets/{tid}/messages", headers=h(env, name_of[assignee]),
                    json={"body": "Silakan siapkan paspor dan ARC Anda."})
    notes = env.client.get("/api/v1/me/notifications", headers=h(env, "ayu")).json()
    reply_note = next(n for n in notes["items"] if n["kind"] == "supporter_reply")
    assert "paspor" not in (reply_note["title"] + (reply_note["body"] or "")) and notes["unread"] >= 2
    thread = env.client.get(f"/api/v1/support/tickets/{tid}", headers=h(env, "ayu")).json()["messages"]
    assert any(m["author_role"] == "supporter" and "paspor" in m["body"] for m in thread)
    assert thread[-1]["author_name"] == name_of[assignee].title()
    # other users never see this notification
    assert all(n["kind"] != "supporter_reply" for n in env.client.get("/api/v1/me/notifications",
                                                                     headers=h(env, "minh")).json()["items"])
    assert env.client.post("/api/v1/me/notifications/read", headers=h(env, "ayu")).json()["marked"] >= 2
    assert env.client.get("/api/v1/me/notifications", headers=h(env, "ayu")).json()["unread"] == 0
    # nothing in the audit log contains the private message body
    assert "paspor" not in str(env.store.select("audit_log")[0])


def test_private_conversation_cannot_be_shared(world):
    env = world
    c, out = converse(env, "ayu")
    env.client.patch(f"/api/v1/conversations/{c['id']}", headers=h(env, "ayu"), json={"is_private": True})
    assert handoff(env, "ayu", c, [out["user_message"]["id"]]).status_code == 403
    # messages from someone else's conversation cannot be attached
    c2, out2 = converse(env, "minh", "Visa D-2 là gì?")
    assert handoff(env, "ayu", c2, [out2["user_message"]["id"]]).status_code == 404


# ------------------------------------------------------------- H: preference change routing
def test_h_new_preference_routes_new_tickets_only(world):
    env = world
    c, out = converse(env, "ayu")
    t1 = handoff(env, "ayu", c, [out["user_message"]["id"]]).json()
    env.client.patch("/api/v1/me", headers=h(env, "ayu"), json={"preferred_language": "vi"})
    t2 = env.client.post("/api/v1/support/tickets", headers=h(env, "ayu"),
                         json=dict(subject="Ký túc xá", summary="Tôi cần hỏi về ký túc xá.", consent=True)).json()
    assert t2["language"] == "vi"
    assert env.store.select("support_tickets", Query(eq={"id": t2["id"]}))[0][0]["assigned_to"] == env.users["sup_vi"]
    assert env.client.get(f"/api/v1/support/tickets/{t1['id']}", headers=h(env, "ayu")).json()["language"] == "id"
    assert env.client.get(f"/api/v1/support/tickets/{t1['id']}", headers=h(env, "sup_vi")).status_code == 404


# ------------------------------------------------------------- I: nobody available
def test_i_no_supporter_available_ticket_waits_and_student_is_told(world):
    env = world
    add_user(env, "chen", lang="zh-CN")
    r = env.client.post("/api/v1/support/tickets", headers=h(env, "chen"),
                        json=dict(subject="宿舍问题", summary="我想问宿舍的问题。", consent=True)).json()
    assert r["status"] == "waiting" and "Waiting for an available Global Supporter" in r["status_message"]
    assert r["assigned_supporter"] is None
    kinds = [n["kind"] for n in env.client.get("/api/v1/me/notifications", headers=h(env, "chen")).json()["items"]]
    assert "ticket_waiting" in kinds
    # escalated to a designated administrator (no zh-CN lead exists -> super admins)
    assert any(n["kind"] == "ticket_unassigned" for n in
               env.client.get("/api/v1/me/notifications", headers=env.auth("super_admin")).json()["items"])
    # never routed to another language's supporters
    assert env.store.select("support_tickets", Query(eq={"id": r["id"]}))[0][0]["assigned_to"] is None


def test_concurrent_claims_assign_once(world):
    env = world
    env.client.put("/api/v1/support/me/availability", headers=h(env, "sup_id"), json={"is_available": False})
    env.client.put("/api/v1/support/me/availability", headers=h(env, "sup_id2"), json={"is_available": False})
    c, out = converse(env, "ayu")
    tid = handoff(env, "ayu", c, [out["user_message"]["id"]]).json()["id"]
    q = env.client.get("/api/v1/support/inbox?view=queue", headers=h(env, "sup_id")).json()
    item = next(i for i in q["items"] if i["id"] == tid)
    assert "summary" not in item and "shared_context" not in item and item["can_open"] is False  # metadata only
    assert env.client.post(f"/api/v1/support/tickets/{tid}/accept", headers=h(env, "sup_id")).status_code == 200
    assert env.client.post(f"/api/v1/support/tickets/{tid}/accept", headers=h(env, "sup_id2")).status_code == 409


# ------------------------------------------------------------- J: reassignment revokes access
def test_j_reassignment_and_role_change_revoke_access(world):
    env = world
    c, out = converse(env, "ayu")
    tid = handoff(env, "ayu", c, [out["user_message"]["id"]]).json()["id"]
    first = env.store.select("support_tickets", Query(eq={"id": tid}))[0][0]["assigned_to"]
    name_of = {v: k for k, v in env.users.items()}
    second = env.users["sup_id2"] if first == env.users["sup_id"] else env.users["sup_id"]
    # cross-language transfer is refused by the database invariant
    r = env.client.post(f"/api/v1/support/tickets/{tid}/transfer", headers=h(env, "lead_id"),
                        json={"to_supporter_id": env.users["sup_vi"]})
    assert r.status_code == 403
    r = env.client.post(f"/api/v1/support/tickets/{tid}/transfer", headers=h(env, "lead_id"),
                        json={"to_supporter_id": second, "reason": "workload"})
    assert r.status_code == 200, r.text
    assert env.client.get(f"/api/v1/support/tickets/{tid}", headers=h(env, name_of[first])).status_code == 404
    assert env.client.get(f"/api/v1/support/tickets/{tid}", headers=h(env, name_of[second])).status_code == 200
    hist = env.store.select("support_ticket_assignments", Query(eq={"ticket_id": tid}, order=[("id", False)]))[0]
    assert len(hist) == 2 and hist[0]["ended_at"] and hist[1]["ended_at"] is None
    # demoting the new assignee revokes access immediately and returns the ticket to the queue
    env.client.patch(f"/api/v1/admin/users/{second}/role", headers=env.auth("super_admin"), json={"role": "student"})
    assert env.client.get(f"/api/v1/support/tickets/{tid}", headers=h(env, name_of[second])).status_code == 404
    t = env.store.select("support_tickets", Query(eq={"id": tid}))[0][0]
    assert t["assigned_to"] != second


# ------------------------------------------------------------- K: resolution, feedback, retention
def test_k_resolve_feedback_reopen_and_retention(world):
    env = world
    c, out = converse(env, "ayu")
    tid = handoff(env, "ayu", c, [out["user_message"]["id"]]).json()["id"]
    assignee = {v: k for k, v in env.users.items()}[env.store.select("support_tickets", Query(eq={"id": tid}))[0][0]["assigned_to"]]
    assert env.client.post(f"/api/v1/support/tickets/{tid}/feedback", headers=h(env, "ayu"),
                           json={"rating": 5}).status_code == 409   # only after resolution
    env.client.post(f"/api/v1/support/tickets/{tid}/accept", headers=h(env, assignee))
    assert env.client.post(f"/api/v1/support/tickets/{tid}/resolve", headers=h(env, assignee)).json()["status"] == "resolved"
    assert env.client.post(f"/api/v1/support/tickets/{tid}/feedback", headers=h(env, "ayu"),
                           json={"rating": 4, "comment": "Terima kasih"}).json()["satisfaction"] == 4
    assert env.client.get("/api/v1/support/tickets", headers=h(env, "ayu")).json()["items"][0]["status"] == "resolved"
    env.client.post(f"/api/v1/support/tickets/{tid}/withdraw-context", headers=h(env, "ayu"))
    assert env.client.get(f"/api/v1/support/tickets/{tid}", headers=h(env, "ayu")).json()["shared_context"] == []
    assert env.client.post(f"/api/v1/support/tickets/{tid}/reopen", headers=h(env, "ayu")).json()["status"] == "open"
    env.client.post(f"/api/v1/support/tickets/{tid}/resolve", headers=h(env, "ayu"))
    # retention: still available now, purged after the retention period
    svc = env.app.state.services
    assert svc.support.purge_expired()["tickets"] == 0
    env.store.update("support_tickets", {"resolved_at": "2000-01-01T00:00:00+00:00"}, {"id": tid})
    assert svc.support.purge_expired()["tickets"] == 1
    assert env.client.get(f"/api/v1/support/tickets/{tid}", headers=h(env, "ayu")).status_code == 404


# ------------------------------------------------------------- L: team management scope
def test_l_super_admin_manages_teams_language_admins_stay_scoped(world):
    env = world
    teams = env.client.get("/api/v1/admin/language-teams", headers=env.auth("super_admin")).json()
    assert {t["language"] for t in teams["items"]} == {"ko", "en", "id", "vi", "zh-CN"} and teams["can_manage_members"]
    lead = env.client.get("/api/v1/admin/language-teams", headers=h(env, "lead_id")).json()
    assert [t["language"] for t in lead["items"]] == ["id"] and lead["can_manage_members"] is False
    # language-scoped admin cannot change memberships, roles, or see other languages
    assert env.client.put(f"/api/v1/admin/users/{env.users['sup_vi']}/team", headers=h(env, "lead_id"),
                          json={"assignments": []}).status_code == 403
    assert env.client.patch(f"/api/v1/admin/users/{env.users['lead_id']}/role", headers=h(env, "lead_id"),
                            json={"role": "super_admin"}).status_code == 403
    assert env.client.get("/api/v1/support/inbox?view=team&language=vi", headers=h(env, "lead_id")).status_code == 403
    assert env.client.get("/api/v1/admin/language-teams", headers=h(env, "sup_vi")).status_code == 404
    assert env.client.get("/api/v1/admin/language-teams", headers=env.auth("admin")).status_code == 404
    audits = env.store.select("audit_log", Query(eq={"action": "team.update"}))[0]
    assert len(audits) >= 4 and all(a["actor_id"] == env.users["super_admin"] for a in audits)


# ------------------------------------------------------------- translation review
def _published_announcement(env):
    from tests.test_announcements import create

    a = create(env, submit=True)
    assert env.client.post(f"/api/v1/admin/announcements/{a['id']}/approve", headers=env.auth("admin"),
                           json={}).status_code == 200
    return a["id"]


def test_translation_review_is_language_scoped(world):
    env = world
    team(env, "sup_id", ("id", "review"))   # Indonesian reviewer
    team(env, "sup_vi", ("vi",))            # Vietnamese translator, not a reviewer
    aid = _published_announcement(env)
    # tasks were created per language and the language teams were notified
    kinds = [n["kind"] for n in env.client.get("/api/v1/me/notifications", headers=h(env, "sup_id")).json()["items"]]
    assert "translation_task" in kinds
    tasks = env.client.get("/api/v1/admin/translations", headers=h(env, "sup_id")).json()
    assert {t["language_code"] for t in tasks["items"]} == {"id"} and tasks["items"][0]["translation_status"] == "todo"
    draft = dict(title="Bản dịch", body="Nội dung bản dịch.", translation_status="in_review")
    assert env.client.put(f"/api/v1/admin/announcements/{aid}/translations/vi", headers=h(env, "sup_vi"),
                          json=draft).status_code == 200
    # the Indonesian supporter cannot approve (or even open) the Vietnamese translation
    for path in ("approve", "reject", "request-changes"):
        r = env.client.post(f"/api/v1/admin/announcements/{aid}/translations/vi/{path}", headers=h(env, "sup_id"),
                            json={"original_verified": True, "reason": "nope nope"})
        assert r.status_code == 403, (path, r.text)
    assert env.client.get(f"/api/v1/admin/announcements/{aid}/translations/vi", headers=h(env, "sup_id")).status_code == 403
    # the Vietnamese translator is not a reviewer either
    assert env.client.post(f"/api/v1/admin/announcements/{aid}/translations/vi/approve", headers=h(env, "sup_vi"),
                           json={"original_verified": True}).status_code == 403
    # once Vietnamese review is explicitly assigned, it works
    team(env, "sup_id", ("id", "review"), ("vi", "review"))
    ok = env.client.post(f"/api/v1/admin/announcements/{aid}/translations/vi/approve", headers=h(env, "sup_id"),
                         json={"original_verified": True})
    assert ok.status_code == 200 and ok.json()["translation_status"] == "human_approved"
    pub = env.client.get(f"/api/v1/announcements/{aid}").json()
    assert [t["language"] for t in pub["translations"]] == ["vi"]            # independent per-language publication
    share = env.client.get(f"/api/v1/admin/announcements/{aid}/translations/vi/share-text", headers=h(env, "sup_vi")).json()
    assert share["text"].startswith("Bản dịch")
    detail = env.client.get(f"/api/v1/admin/announcements/{aid}/translations/vi", headers=h(env, "sup_vi")).json()
    assert [r["action"] for r in detail["revisions"]][:2] == ["approve", "submit"]
    assert detail["original"]["language"] == "ko" and detail["permissions"] == {"can_edit": True, "can_review": False}


def test_translation_outdated_when_original_changes_and_needs_verification(world):
    env = world
    team(env, "sup_id", ("id", "review"))
    from tests.test_announcements import create

    a = create(env, submit=True)
    aid = a["id"]
    draft = dict(title="Pengumuman", body="Isi terjemahan.", translation_status="in_review")
    env.client.put(f"/api/v1/admin/announcements/{aid}/translations/id", headers=h(env, "sup_id"), json=draft)
    # original not published yet -> cannot approve a translation
    r = env.client.post(f"/api/v1/admin/announcements/{aid}/translations/id/approve", headers=h(env, "sup_id"),
                        json={"original_verified": True})
    assert r.status_code == 409
    env.client.post(f"/api/v1/admin/announcements/{aid}/approve", headers=env.auth("admin"), json={})
    assert env.client.post(f"/api/v1/admin/announcements/{aid}/translations/id/approve", headers=h(env, "sup_id"),
                           json={}).status_code == 422                     # reviewer must verify the original
    assert env.client.post(f"/api/v1/admin/announcements/{aid}/translations/id/approve", headers=h(env, "sup_id"),
                           json={"original_verified": True}).status_code == 200
    # the original changes -> the approved translation becomes outdated
    svc = env.app.state.services
    env.store.update("announcements", {"title": "장학금 신청 안내 (수정)"}, {"id": aid})
    assert svc.translations.mark_outdated(aid, None) == 1
    d = env.client.get(f"/api/v1/admin/announcements/{aid}/translations/id", headers=h(env, "sup_id")).json()
    assert d["translation"]["is_outdated"] and d["translation"]["published"] is False
    assert env.client.get(f"/api/v1/announcements/{aid}").json()["translations"] == []   # hidden publicly
    r = env.client.post(f"/api/v1/admin/announcements/{aid}/translations/id/approve", headers=h(env, "sup_id"),
                        json={"original_verified": True})
    assert r.status_code == 409 and r.json()["error"]["code"] == "translation_outdated"
    env.client.put(f"/api/v1/admin/announcements/{aid}/translations/id", headers=h(env, "sup_id"),
                   json=dict(title="Pengumuman (revisi)", body="Isi terjemahan baru.", translation_status="in_review"))
    assert env.client.post(f"/api/v1/admin/announcements/{aid}/translations/id/approve", headers=h(env, "sup_id"),
                           json={"original_verified": True}).status_code == 200
    assert env.client.get(f"/api/v1/announcements/{aid}").json()["translations"][0]["title"] == "Pengumuman (revisi)"
    rc = env.client.post(f"/api/v1/admin/announcements/{aid}/translations/id/request-changes", headers=h(env, "sup_id"),
                         json={"reason": "Please check the deadline"})
    assert rc.status_code == 200 and rc.json()["translation_status"] == "changes_requested"


def test_translation_dashboard_never_exposes_support_data(world):
    env = world
    team(env, "sup_id", ("id", "review"))
    c, out = converse(env, "ayu")
    handoff(env, "ayu", c, [out["user_message"]["id"]])
    _published_announcement(env)
    body = str(env.client.get("/api/v1/admin/translations", headers=h(env, "sup_id")).json())
    assert "Perpanjangan" not in body and "perpanjang" not in body
