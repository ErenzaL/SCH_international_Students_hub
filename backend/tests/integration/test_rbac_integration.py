"""Roles and privacy against the REAL database (PostgREST + PostgreSQL + migrations 0001-0015), for the AI Office
agents, tasks, support-request confirmation and official-source discovery. Tokens are verified by the API exactly as
in production (HS256 secret of this stack); RLS is also exercised directly through PostgREST with each user's JWT.
Skipped unless the integration environment is configured."""
from __future__ import annotations

import time
import uuid

import httpx
import jwt
import pytest

from tests.integration.test_postgres_integration import ANON_KEY, IT, PSQL, REST, SECRET, sql

pytestmark = pytest.mark.skipif(not (REST and PSQL), reason="set SCH_IT_REST_URL and SCH_IT_PSQL to run")


@pytest.fixture(scope="module")
def it() -> IT:
    it = IT()
    # a second student, and the supporter gets the English team (support requests route by language)
    uid = str(uuid.uuid4())
    sql(f"insert into auth.users (id, email) values ('{uid}', 'student2-{uid[:6]}@example.test')")
    it.users["student2"] = uid
    sql(f"insert into supporter_languages (supporter_id, language_code, can_support) values ('{it.users['supporter']}', 'en', true)")
    return it


def rest(token: str | None, path: str) -> httpx.Response:
    headers = {"apikey": ANON_KEY} | ({"Authorization": f"Bearer {token}"} if token else {})
    return httpx.get(f"{REST}/rest/v1/{path}", headers=headers, timeout=10)


def user_jwt(it: IT, role: str, **extra) -> str:  # type: ignore[no-untyped-def]
    claims = {"sub": it.users[role], "aud": "authenticated", "role": "authenticated", "exp": int(time.time()) + 600} | extra
    return jwt.encode(claims, SECRET, algorithm="HS256")


def task(it: IT, role: str, agent: str, task_type: str, params: dict | None = None) -> httpx.Response:  # type: ignore[type-arg]
    return it.client.post(f"/api/v1/agents/{agent}/tasks", json=dict(task_type=task_type, params=params or {}),
                          headers=it.auth(role))


# ------------------------------------------------------------------ tokens
def test_tokens_are_verified_and_roles_come_from_the_database(it: IT):
    expired = jwt.encode({"sub": it.users["student"], "aud": "authenticated", "exp": int(time.time()) - 10}, SECRET,
                         algorithm="HS256")
    forged = jwt.encode({"sub": it.users["student"], "aud": "authenticated", "exp": int(time.time()) + 600},
                        "not-the-secret-not-the-secret-not-the-secret", algorithm="HS256")
    for bad in (expired, forged):
        r = it.client.get("/api/v1/agent-tasks", headers={"Authorization": f"Bearer {bad}"})
        assert r.status_code == 401
    # a student who claims to be an admin in the token is still a student
    spoof = jwt.encode({"sub": it.users["student"], "aud": "authenticated", "exp": int(time.time()) + 600,
                        "role": "admin", "app_metadata": {"role": "super_admin"}}, SECRET, algorithm="HS256")
    r = it.client.get("/api/v1/admin/discovery/sources", headers={"Authorization": f"Bearer {spoof}"})
    assert r.status_code == 403
    assert it.client.get("/api/v1/agents", headers={"Authorization": f"Bearer {spoof}"}).json()["is_admin"] is False


# ------------------------------------------------------------------ role matrix
@pytest.mark.parametrize("role,expect", [("student", 403), ("supporter", 403), ("admin", 200), ("super_admin", 200)])
def test_discovery_and_schedule_admin_endpoints(it: IT, role: str, expect: int):
    assert it.client.get("/api/v1/admin/discovery/sources", headers=it.auth(role)).status_code == expect
    assert it.client.get("/api/v1/admin/discovery/items", headers=it.auth(role)).status_code == expect
    assert it.client.get("/api/v1/admin/agent-schedules", headers=it.auth(role)).status_code == expect
    # scoped to a source that does not exist: the permission is what is tested, and the real sources a shared
    # database may hold are never checked through this test's mock network
    r = task(it, role, "announcement", "announcement_discovery", {"source_ids": ["00000000-0000-0000-0000-000000000000"]})
    assert r.status_code == (201 if expect == 200 else 403)
    r = it.client.post("/api/v1/agents/scholarship/tools", headers=it.auth(role), json=dict(tool="review_candidates"))
    assert r.status_code == expect


def test_anonymous_and_unknown_profiles(it: IT):
    assert it.client.get("/api/v1/agents").status_code == 200                       # public directory
    assert it.client.get("/api/v1/agent-tasks").status_code == 401
    ghost = jwt.encode({"sub": str(uuid.uuid4()), "aud": "authenticated", "exp": int(time.time()) + 600}, SECRET,
                       algorithm="HS256")
    r = it.client.get("/api/v1/agent-tasks", headers={"Authorization": f"Bearer {ghost}"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "no_profile"


# ------------------------------------------------------------------ private task histories
def test_task_histories_are_private_through_the_api_and_rls(it: IT):
    mine = task(it, "student", "events", "event_digest").json()
    assert mine["id"]
    for other in ("student2", "supporter", "admin", "super_admin"):
        assert it.client.get(f"/api/v1/agent-tasks/{mine['id']}", headers=it.auth(other)).status_code == 404
        listed = it.client.get("/api/v1/agent-tasks", headers=it.auth(other)).json()["items"]
        assert all(t["id"] != mine["id"] for t in listed)
    # directly through PostgREST with the users' own JWTs (what a Supabase client could do)
    own = rest(user_jwt(it, "student"), f"agent_tasks?id=eq.{mine['id']}&select=id,status").json()
    assert [t["id"] for t in own] == [mine["id"]]
    assert rest(user_jwt(it, "student2"), f"agent_tasks?id=eq.{mine['id']}&select=id").json() == []
    assert rest(user_jwt(it, "student2"), f"agent_task_events?task_id=eq.{mine['id']}&select=id").json() == []
    anon = rest(None, "agent_tasks?select=id")
    assert anon.status_code in (401, 403)
    # students cannot write tasks directly or read schedules / discovery data
    w = httpx.post(f"{REST}/rest/v1/agent_tasks", headers={"apikey": ANON_KEY, "Authorization": f"Bearer {user_jwt(it, 'student')}"},
                   json={"agent_id": "events", "task_type": "event_digest"}, timeout=10)
    assert w.status_code in (401, 403)
    for table in ("agent_schedules", "discovery_sources", "discovered_items"):
        assert rest(user_jwt(it, "student"), f"{table}?select=id").status_code in (401, 403), table


# ------------------------------------------------------------------ support request confirmation
def test_support_request_needs_the_students_confirmation_and_routes_by_language(it: IT):
    before = int(sql(f"select count(*) from support_tickets where student_id = '{it.users['student']}'").splitlines()[-1])
    r = it.client.post("/api/v1/agents/supporter-en/requests", headers=it.auth("student"),
                       json=dict(message="I want to talk to a human supporter about my dormitory contract"))
    out = r.json()
    assert out["route"] == "approval" and out["handled_by"] == "support-coordinator" and out["delegated_from"] == "supporter-en"
    tid = out["task"]["id"]
    assert int(sql(f"select count(*) from support_tickets where student_id = '{it.users['student']}'").splitlines()[-1]) == before
    # nobody else can confirm it
    for other in ("student2", "supporter", "admin"):
        assert it.client.post(f"/api/v1/agent-tasks/{tid}/decision", json={"approve": True},
                              headers=it.auth(other)).status_code == 404
    d = it.client.post(f"/api/v1/agent-tasks/{tid}/decision", json={"approve": True}, headers=it.auth("student"))
    assert d.status_code == 200
    t = it.client.get(f"/api/v1/agent-tasks/{tid}", headers=it.auth("student")).json()
    assert t["status"] == "completed", t
    ticket = t["output"]["items"][0]
    assert int(sql(f"select count(*) from support_tickets where student_id = '{it.users['student']}'").splitlines()[-1]) == before + 1
    # the English supporter now sees it; the student sees their own ticket; another student does not
    inbox = it.client.get("/api/v1/support/inbox", headers=it.auth("supporter"))
    assert inbox.status_code == 200 and any(x["id"] == ticket["id"] for x in inbox.json()["items"])
    assert it.client.get(f"/api/v1/support/tickets/{ticket['id']}", headers=it.auth("student")).status_code == 200
    assert it.client.get(f"/api/v1/support/tickets/{ticket['id']}", headers=it.auth("student2")).status_code in (403, 404)


# ------------------------------------------------------------------ agent tool permissions
def test_agent_tool_permissions_hold_for_every_role(it: IT):
    for role in ("student", "supporter", "admin"):
        r = it.client.post("/api/v1/agents/events/tools", headers=it.auth(role), json=dict(tool="scholarship_search"))
        assert r.status_code == 403 and r.json()["error"]["code"] == "tool_not_allowed"
        r = it.client.post("/api/v1/agents/scholarship/tools", headers=it.auth(role),
                           json=dict(tool="official_page_fetch", params={"url": "https://www.hikorea.go.kr/"}))
        assert r.status_code == 403 and r.json()["error"]["code"] == "background_only"
    # admins also cannot crawl through a student-facing instant tool, and nobody can pass URLs to discovery
    r = it.client.post("/api/v1/agents/scholarship/tools", headers=it.auth("admin"),
                       json=dict(tool="official_source_check"))
    assert r.status_code == 403 and r.json()["error"]["code"] == "background_only"
    r = task(it, "admin", "scholarship", "opportunity_discovery", {"url": "https://evil.example.com"})
    assert r.status_code == 422


# ------------------------------------------------------------------ workspaces (presentation) and monitoring status
@pytest.mark.parametrize("role,admin", [(None, False), ("student", False), ("supporter", False), ("admin", True),
                                        ("super_admin", True)])
def test_workspace_interfaces_monitoring_and_discoveries_respect_roles(it: IT, role: str | None, admin: bool):
    headers = it.auth(role) if role else {}
    items = {a["id"]: a for a in it.client.get("/api/v1/agents", headers=headers).json()["items"]}
    for agent_id in ("scholarship", "announcement"):
        ui = items[agent_id]["interface"]
        assert ({"review", "sources"} <= set(ui["tabs"])) is admin
        assert ("check_official_sources" in ui["task_actions"]) is admin
    assert items["support-coordinator"]["interface"]["type"] == "TASK_WORKSPACE"
    mon = it.client.get("/api/v1/agents/announcement/monitoring", headers=headers)
    assert mon.status_code == 200
    body = mon.json()
    assert ("candidates_waiting" in body) is admin and ("schedules_enabled_on_server" in body) is admin
    if not admin:
        assert set(body) == {"agent_id", "supported", "sources", "schedules", "checking", "last_checked_at",
                             "last_success_at"}
        assert all(s["state"] in ("active", "disabled") for s in body["schedules"])
    assert all(("last_error" in s and "id" in s) is admin for s in body["sources"])
    assert all(("params" in s) is admin for s in body["schedules"])
    # unreviewed discoveries never reach non-admins (whatever the database holds)
    out = it.client.post("/api/v1/agents/scholarship/tools", headers=headers,
                         json=dict(tool="opportunity_search", params={"include_closed": True, "limit": 30})).json()["result"]
    if not admin:
        assert all(i["reliability"] == "verified" and "review_status" not in i and i["href"].startswith("/knowledge/")
                   for i in out["items"])
        candidates = {t for t in sql("select title from discovered_items where status = 'candidate'").splitlines() if t}
        assert not candidates & {i["title"] for i in out["items"]}
