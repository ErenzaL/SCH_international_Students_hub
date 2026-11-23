"""AI Support Office Phase 2: agent registry, tool permissions, real tools on seeded data, durable tasks,
approval, cancellation, retries, delegation limits, schedules (disabled by default) and ownership."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from app.services.agents.registry import AGENTS, CHARACTER_TO_AGENT
from app.services.agents.router import plan_request
from app.services.agents.tools import TOOLS, extract_dates
from app.services.llm.base import LLMError, ScriptedLLMProvider
from tests.test_announcements import create

TODAY = date.today()


def publish(env, **kw):  # type: ignore[no-untyped-def]
    a = create(env, submit=True, **kw)
    r = env.client.post(f"/api/v1/admin/announcements/{a['id']}/approve", headers=env.auth("admin"), json={})
    assert r.status_code == 200, r.text
    return a


def tool(env, agent, name, params=None, role=None):  # type: ignore[no-untyped-def]
    return env.client.post(f"/api/v1/agents/{agent}/tools", json=dict(tool=name, params=params or {}),
                           headers=env.auth(role) if role else {})


def ask(env, agent, message, role="student", language=None):  # type: ignore[no-untyped-def]
    body = dict(message=message) | ({"language": language} if language else {})
    return env.client.post(f"/api/v1/agents/{agent}/requests", json=body, headers=env.auth(role) if role else {})


def task(env, agent, task_type, params=None, role="student", **kw):  # type: ignore[no-untyped-def]
    return env.client.post(f"/api/v1/agents/{agent}/tasks", json=dict(task_type=task_type, params=params or {}, **kw),
                           headers=env.auth(role))


def get_task(env, task_id, role="student"):  # type: ignore[no-untyped-def]
    return env.client.get(f"/api/v1/agent-tasks/{task_id}", headers=env.auth(role))


# ------------------------------------------------------------------ registry
def test_every_office_character_maps_to_one_registered_agent():
    chars = {"reception", "guide-bot", "supporter-ko", "supporter-en", "supporter-id", "supporter-vi", "supporter-zh",
             "supporter-lead", "visa", "academic", "topik", "opportunities", "events", "career"}
    assert set(CHARACTER_TO_AGENT) == chars
    assert len(set(CHARACTER_TO_AGENT.values())) == len(chars)
    for a in AGENTS.values():
        assert a.allowed_tools <= set(TOOLS), a.id                 # no agent lists a tool that does not exist
        assert set(a.can_delegate_to) <= set(AGENTS) and a.id not in a.can_delegate_to
        for action in a.actions:                                   # every button maps to something it may do
            assert action.target in (a.allowed_tools if action.kind == "tool" else a.task_types), (a.id, action.id)
    assert AGENTS["supporter-vi"].fixed_language == "vi" and AGENTS["supporter-zh"].fixed_language == "zh-CN"
    # specialists cannot write; only the coordinator can create (approved) support requests
    writers = [a.id for a in AGENTS.values() if any(TOOLS[t].writes for t in a.allowed_tools)]
    assert writers == ["support-coordinator"]


def test_directory_lists_agents_tools_and_honest_availability(env):
    r = env.client.get("/api/v1/agents")
    assert r.status_code == 200
    items = {a["id"]: a for a in r.json()["items"]}
    assert len(items) == len(AGENTS) and items["scholarship"]["character_id"] == "opportunities"
    tools = {t["name"]: t for t in items["scholarship"]["tools"]}
    assert tools["official_web_search"]["available"] is False and "No web search" in tools["official_web_search"]["unavailable_reason"]
    assert tools["scholarship_search"]["available"] is True
    # no model configured in tests: AI tools say so instead of pretending
    assert {t["name"]: t for t in items["announcement"]["tools"]}["summarize_document"]["available"] is False
    assert all(a["state"] == "idle" for a in items.values()) and items["events"]["monitoring"] is False


# ------------------------------------------------------------------ tool permissions
def test_agents_can_only_use_their_own_tools(env):
    r = tool(env, "events", "scholarship_search")
    assert r.status_code == 403 and r.json()["error"]["code"] == "tool_not_allowed"
    assert tool(env, "reception", "career_opportunity_search").status_code == 403
    assert tool(env, "nobody", "rag_search", {"query": "visa"}).status_code == 404
    # unknown parameters are rejected (no free-form input reaches a service)
    r = tool(env, "scholarship", "scholarship_search", {"q": "x", "sql": "drop table"})
    assert r.status_code == 422


def test_background_and_private_tools_never_run_in_a_request(env):
    r = tool(env, "scholarship", "official_page_fetch", {"url": "https://www.hikorea.go.kr/"}, role="student")
    assert r.status_code == 403 and r.json()["error"]["code"] == "background_only"
    assert tool(env, "support-coordinator", "get_support_request_status").status_code == 401   # needs sign-in
    r = tool(env, "support-coordinator", "create_support_request", {"subject": "Help me", "summary": "x"}, role="student")
    assert r.status_code == 403 and r.json()["error"]["code"] == "approval_required"
    assert env.store.select("support_tickets")[0] == []


def test_unavailable_tool_never_pretends_to_work(env):
    r = tool(env, "scholarship", "official_web_search", {"query": "scholarship"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "tool_unavailable"


# ------------------------------------------------------------------ real tools on seeded data
def test_scholarship_search_returns_published_items_dedupes_and_flags_nothing_private(env):
    a = publish(env)                                                   # 장학금 신청 안내, deadline in 10 days
    twin = publish(env, title="장학금  신청 안내!")                       # the same notice posted twice
    draft = create(env, title="장학금 비공개 초안")                           # never published
    publish(env, title="Campus festival", body="Festival on campus.", category="university-announcements")
    out = tool(env, "scholarship", "scholarship_search").json()["result"]
    ids = [i.get("id") for i in out["items"]]
    assert out["count"] == 1 and ids[0] in (a["id"], twin["id"]) and draft["id"] not in ids
    item = out["items"][0]
    assert item["href"] == f"/announcements/{ids[0]}" and item["reliability"] == "verified"
    assert "eligibility_office" in out["notes"]


def test_expired_scholarships_are_flagged_or_hidden(env):
    publish(env, title="Old scholarship", deadline=str(TODAY - timedelta(days=3)), event_date=str(TODAY - timedelta(days=5)),
            valid_from=str(TODAY - timedelta(days=30)))
    assert tool(env, "scholarship", "scholarship_search").json()["result"]["count"] == 0
    out = tool(env, "scholarship", "scholarship_search", {"include_expired": True}).json()["result"]
    assert out["items"][0]["reliability"] == "expired"


def test_empty_results_are_explained(env):
    out = tool(env, "career", "career_opportunity_search").json()["result"]
    assert out["count"] == 0 and out["notes"][0] == "nothing_published"
    out = tool(env, "events", "event_search").json()["result"]
    assert out["count"] == 0 and out["notes"]


def test_event_search_lists_upcoming_events_soonest_first(env):
    later = publish(env, title="Culture night", category="university-announcements", event_date=str(TODAY + timedelta(days=30)),
                    deadline=str(TODAY + timedelta(days=25)))
    sooner = publish(env, title="Orientation", category="university-announcements", event_date=str(TODAY + timedelta(days=3)),
                     deadline=str(TODAY + timedelta(days=2)))
    out = tool(env, "events", "event_search").json()["result"]
    assert [i["id"] for i in out["items"]] == [sooner["id"], later["id"]]


def test_deadline_extraction_quotes_the_source_and_prefers_reviewed_fields(env):
    y = TODAY.year + 1
    a = publish(env, body=f"장학금 신청 안내\n신청 기간: {y}. 3. 2. ~ {y}. 3. 20. 까지\n설명회 일시: {y}년 3월 5일")
    out = tool(env, "announcement", "deadline_extraction", {"announcement_id": a["id"]}).json()["result"]
    reviewed = [d for d in out["items"] if d["reviewed"]]
    assert {d["kind"] for d in reviewed} == {"deadline", "event"}
    quoted = [d for d in out["items"] if not d["reviewed"]]
    assert {"date": f"{y}-03-20", "kind": "deadline"}.items() <= quoted[1].items()
    assert quoted[0]["kind"] == "period_start" and "신청 기간" in quoted[0]["quote"]
    assert any(d["kind"] == "event" and d["date"] == f"{y}-03-05" for d in quoted)
    with_text = tool(env, "announcement", "deadline_extraction", {"text": "x", "announcement_id": a["id"]})
    assert with_text.status_code == 422


def test_extract_dates_is_pattern_based():
    assert extract_dates("Apply by 2027-04-01")[0] == dict(date="2027-04-01", kind="deadline", quote="Apply by 2027-04-01",
                                                           year_assumed=False)
    assert extract_dates("4월 1일까지 제출", default_year=2027)[0]["year_assumed"] is True
    assert extract_dates("2027.02.30 invalid") == []
    assert extract_dates("no dates here") == []


def test_source_verification(env):
    a = publish(env)
    out = tool(env, "scholarship", "source_verification", {"announcement_id": a["id"]}).json()["result"]
    assert out["items"][0]["verdict"] == "hub_verified"
    draft = create(env)
    assert tool(env, "scholarship", "source_verification", {"announcement_id": draft["id"]}).json()["result"]["items"][0][
        "verdict"] == "not_published"
    out = tool(env, "scholarship", "source_verification", {"url": "https://evil.example.com/x"}).json()["result"]
    assert out["items"][0]["verdict"] == "unknown_source"
    assert tool(env, "scholarship", "source_verification", {"url": "file:///etc/passwd"}).status_code == 422


def test_visa_checklist_quotes_approved_guides_only(env):
    out = tool(env, "immigration", "visa_checklist", {"topic": "extension"}).json()["result"]
    assert out["count"] == 0 and out["notes"][0] == "no_guide"
    assert tool(env, "immigration", "visa_checklist", {"topic": "registration"}).status_code == 422   # another desk


# ------------------------------------------------------------------ router
@pytest.mark.parametrize("message,route,agent,target", [
    ("장학금 알려줘", "tool", "scholarship", "scholarship_search"),
    ("Are there any scholarships?", "tool", "scholarship", "scholarship_search"),
    ("Có học bổng nào không?", "tool", "scholarship", "scholarship_search"),
    ("Ada beasiswa?", "tool", "scholarship", "scholarship_search"),
    ("有奖学金吗", "tool", "scholarship", "scholarship_search"),
    ("How do I extend my visa?", "tool", "immigration", "visa_checklist"),
    ("주소 변경 신고", "tool", "immigration", "visa_checklist"),
    ("I want to talk to a human supporter", "approval", "support-coordinator", "support_request"),
    ("What is the status of my request?", "tool", "support-coordinator", "get_support_request_status"),
    ("upcoming events", "tool", "events", "event_search"),
    ("When is TOPIK?", "tool", "topik", "topik_dates"),
    ("Can I find an internship?", "tool", "career", "career_opportunity_search"),
    ("수강신청 방법", "tool", "academic", "academic_checklist"),
    ("How does the dormitory laundry work?", "answer", "reception", None),
    ("hi", "clarify", "reception", None),
])
def test_router_decisions(message, route, agent, target):  # type: ignore[no-untyped-def]
    p = plan_request(AGENTS["reception"], message, signed_in=True)
    assert (p.route, p.agent_id, p.target) == (route, agent, target)


def test_reception_delegates_and_specialists_redirect(env):
    publish(env)
    r = ask(env, "reception", "Are there any scholarships?").json()
    assert r["route"] == "tool" and r["handled_by"] == "scholarship" and r["delegated_from"] == "reception"
    assert r["result"]["count"] == 1
    r = ask(env, "events", "Are there any scholarships?").json()
    assert r["route"] == "redirect" and r["suggested_character"] == "opportunities"
    r = ask(env, "supporter-vi", "Bạn có thể giải thích thủ tục ký túc xá không?").json()
    assert r["route"] == "answer" and r["language"] == "vi"          # the supporter's own language


def test_anonymous_visitors_get_lookups_but_not_tasks(env):
    publish(env)
    assert ask(env, "reception", "scholarships", role=None).json()["result"]["count"] == 1
    r = ask(env, "reception", "I want to talk to a human supporter", role=None)
    assert r.status_code == 401
    assert task(env, "events", "event_digest", role="student").status_code == 201
    assert env.client.post("/api/v1/agents/events/tasks", json=dict(task_type="event_digest")).status_code == 401


# ------------------------------------------------------------------ tasks
def test_task_lifecycle_with_provenance_and_change_detection(env):
    a = publish(env, title="Orientation", category="university-announcements", event_date=str(TODAY + timedelta(days=3)))
    r = task(env, "events", "event_digest")
    assert r.status_code == 201, r.text
    t = get_task(env, r.json()["id"]).json()
    assert t["status"] == "completed" and t["output"]["first_run"] is True and t["attempts"] == 1
    assert [c["href"] for c in t["citations"]] == [f"/announcements/{a['id']}"]
    steps = [e["step"] for e in t["events"]]
    assert steps[:2] == ["queued", "start"] and "tool" in steps and steps[-1] == "result"
    assert t["output"]["provenance"]["generated_by"] == "deterministic"
    # second run: the new announcement is marked new, the old one is unchanged
    b = publish(env, title="Culture night", category="university-announcements", event_date=str(TODAY + timedelta(days=9)))
    t2 = get_task(env, task(env, "events", "event_digest").json()["id"]).json()
    changes = {i["id"]: i["change"] for i in t2["output"]["items"]}
    assert changes == {a["id"]: None, b["id"]: "new"} and t2["output"]["new_count"] == 1
    states = {x["id"]: x for x in env.client.get("/api/v1/agents", headers=env.auth("student")).json()["items"]}
    assert states["events"]["state"] == "completed" and states["career"]["state"] == "idle"


def test_task_types_are_restricted_per_agent(env):
    r = task(env, "events", "scholarship_scan")
    assert r.status_code == 403 and r.json()["error"]["code"] == "task_not_allowed"
    r = task(env, "events", "lookup", {"tool": "create_support_request", "params": {}})
    assert r.status_code == 403
    assert task(env, "events", "event_digest", {"evil": 1}).status_code == 422


def test_support_request_waits_for_approval_and_only_then_creates_a_ticket(env):
    r = ask(env, "reception", "I want to talk to a human supporter about my visa").json()
    assert r["route"] == "approval" and r["handled_by"] == "support-coordinator"
    tid = r["task"]["id"]
    assert r["task"]["status"] == "awaiting_approval" and env.store.select("support_tickets")[0] == []
    # another student cannot see or approve it
    assert get_task(env, tid, role="supporter").status_code == 404
    assert env.client.post(f"/api/v1/agent-tasks/{tid}/decision", json={"approve": True},
                           headers=env.auth("supporter")).status_code == 404
    d = env.client.post(f"/api/v1/agent-tasks/{tid}/decision", json={"approve": True}, headers=env.auth("student"))
    assert d.status_code == 200
    t = get_task(env, tid).json()
    assert t["status"] == "completed", t
    tickets = env.store.select("support_tickets")[0]
    assert len(tickets) == 1 and tickets[0]["student_id"] == env.users["student"]
    assert t["output"]["items"][0]["href"] == f"/support/requests/{tickets[0]['id']}"
    assert env.client.post(f"/api/v1/agent-tasks/{tid}/decision", json={"approve": True},
                           headers=env.auth("student")).status_code == 409   # never twice


def test_declined_request_sends_nothing(env):
    tid = ask(env, "support-coordinator", "Please connect me with a staff member").json()["task"]["id"]
    d = env.client.post(f"/api/v1/agent-tasks/{tid}/decision", json={"approve": False}, headers=env.auth("student")).json()
    assert d["status"] == "cancelled" and env.store.select("support_tickets")[0] == []


def test_cancel_queued_and_running_tasks(env):
    env.settings.job_execution = "worker"         # nothing runs until the worker claims it
    env.app.state.services.jobs.kick = lambda: None
    t = task(env, "events", "event_digest").json()
    assert t["status"] == "queued"
    c = env.client.post(f"/api/v1/agent-tasks/{t['id']}/cancel", headers=env.auth("student")).json()
    assert c["status"] == "cancelled"
    assert env.client.post(f"/api/v1/agent-tasks/{t['id']}/cancel", headers=env.auth("student")).status_code == 409
    # running: cancellation is requested; the worker stops at its next step
    t2 = task(env, "events", "event_digest").json()
    svc = env.app.state.services
    claimed = svc.agents.claim("w1", 300)
    assert claimed["id"] == t2["id"] and claimed["status"] == "running"
    env.client.post(f"/api/v1/agent-tasks/{t2['id']}/cancel", headers=env.auth("student"))
    svc.agents.execute(claimed)
    assert get_task(env, t2["id"]).json()["status"] == "cancelled"


def test_worker_claims_agent_tasks_after_ingestion_jobs_and_recovers_dead_workers(env):
    env.settings.job_execution = "worker"
    svc = env.app.state.services
    svc.jobs.kick = lambda: None
    t = task(env, "events", "event_digest").json()
    assert svc.jobs.run_once() is True                   # no ingestion job: the agent task is claimed and run
    assert get_task(env, t["id"]).json()["status"] == "completed"
    t2 = task(env, "events", "event_digest").json()
    claimed = svc.agents.claim("dead-worker", 300)
    old = (datetime.now(UTC) - timedelta(minutes=30)).isoformat()
    env.store.update("agent_tasks", dict(heartbeat_at=old, started_at=old), {"id": claimed["id"]})
    again = svc.agents.claim("w2", 300)                  # the dead worker's task is re-queued and claimed again
    assert again["id"] == t2["id"] and again["attempts"] == 2 and again["locked_by"] == "w2"


def test_transient_failures_retry_and_permanent_ones_fail(env):
    from app.services.agents import handlers

    publish(env, title="Orientation", category="university-announcements", event_date=str(TODAY + timedelta(days=3)))
    original = handlers.HANDLERS["event_digest"]
    calls = {"n": 0}

    def flaky(svc, ctx, t):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        raise LLMError("llm_unavailable", "busy", transient=True)

    handlers.HANDLERS["event_digest"] = flaky
    try:
        t = task(env, "events", "event_digest").json()
        cur = get_task(env, t["id"]).json()
        assert cur["status"] == "queued" and cur["stage"] == "retry_wait" and cur["error_code"] == "llm_unavailable"
        svc = env.app.state.services
        for _ in range(2):   # make it due and run it again until the retry limit
            env.store.update("agent_tasks", dict(run_after=datetime.now(UTC).isoformat()), {"id": t["id"]})
            svc.agents.run_inline(t["id"])
        cur = get_task(env, t["id"]).json()
        assert cur["status"] == "failed" and cur["attempts"] == 3 and calls["n"] == 3
    finally:
        handlers.HANDLERS["event_digest"] = original


def test_idempotency_and_quotas(env):
    env.settings.job_execution = "worker"
    env.app.state.services.jobs.kick = lambda: None
    a = task(env, "events", "event_digest", idempotency_key="digest-key-1").json()
    b = task(env, "events", "event_digest", idempotency_key="digest-key-1").json()
    assert a["id"] == b["id"]
    env.settings.agent_max_active_tasks_per_user = 2
    task(env, "career", "career_scan")
    r = task(env, "scholarship", "scholarship_scan")
    assert r.status_code == 429 and r.json()["error"]["code"] == "task_quota"


def test_tasks_are_private_to_their_owner(env):
    t = task(env, "events", "event_digest").json()
    assert get_task(env, t["id"], role="admin").status_code == 404
    assert env.client.get("/api/v1/agent-tasks", headers=env.auth("admin")).json()["total"] == 0
    assert env.client.get("/api/v1/agent-tasks", headers=env.auth("student")).json()["total"] == 1
    assert env.client.get(f"/api/v1/agent-tasks/{t['id']}").status_code == 401


# ------------------------------------------------------------------ delegation
def test_delegation_runs_inside_the_task_with_provenance(env):
    publish(env)
    t = task(env, "reception", "delegated_search", {"agent_id": "scholarship", "tool": "scholarship_search"}).json()
    full = get_task(env, t["id"]).json()
    assert full["status"] == "completed" and full["output"]["handled_by"] == "scholarship"
    assert full["output"]["count"] == 1
    child = full["children"][0]
    assert child["agent_id"] == "scholarship" and child["depth"] == 1 and child["parent_task_id"] == t["id"]
    assert any(e["step"] == "delegate" for e in full["events"])
    assert {e["agent_id"] for e in child["events"]} >= {"scholarship", "reception"}


def test_delegation_limits(env):
    svc = env.app.state.services
    # an agent may only delegate to agents listed for it
    r = task(env, "reception", "delegated_search", {"agent_id": "reception", "tool": "announcement_search"}).json()
    assert get_task(env, r["id"]).json()["status"] == "failed"
    # depth limit and loops
    from app.security.auth import AuthUser
    from app.services.agents.tasks import MAX_DEPTH
    from app.services.agents.tools import ToolContext

    user = AuthUser(id=env.users["student"], email=None, role="student")
    parent = dict(id="00000000-0000-0000-0000-000000000001", depth=MAX_DEPTH, agent_id="reception", parent_task_id=None,
                  params={})
    ctx = ToolContext(svc=svc, agent=AGENTS["reception"], user=user, language="en", in_task=True, task=parent)
    with pytest.raises(Exception, match="two levels"):
        svc.agents.delegate(ctx, "scholarship", "lookup", {"tool": "scholarship_search"})
    parent2 = dict(parent, depth=0, params={"delegated_from": "scholarship"})
    ctx2 = ToolContext(svc=svc, agent=AGENTS["supporter-en"], user=user, language="en", in_task=True, task=parent2)
    with pytest.raises(Exception, match="already working"):
        svc.agents.delegate(ctx2, "scholarship", "lookup", {"tool": "scholarship_search"})


# ------------------------------------------------------------------ AI tasks
def test_summary_task_uses_the_shared_model_and_is_labelled(env):
    a = publish(env)
    svc = env.app.state.services
    svc.doc_translations.llm = ScriptedLLMProvider(lambda system, prompt: "Scholarship notice" if "title" in prompt.lower()
                                                   and "summar" not in system.lower() else "- Apply before the deadline.")
    t = task(env, "announcement", "summarize_announcement", {"ref": a["id"], "language": "en"})
    assert t.status_code == 201, t.text
    full = get_task(env, t.json()["id"]).json()
    assert full["status"] == "completed", full
    item = full["output"]["items"][0]
    assert item["reliability"] == "ai_generated" and item["href"] == f"/announcements/{a['id']}"
    assert full["output"]["provenance"]["generated_by"] == "scripted-1"


def test_summary_task_is_refused_without_a_model(env):
    a = publish(env)
    r = task(env, "announcement", "summarize_announcement", {"ref": a["id"]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "tool_unavailable"


# ------------------------------------------------------------------ schedules
def cron(env):  # type: ignore[no-untyped-def]
    return env.client.post("/api/v1/internal/sync/run-due", headers={"X-Cron-Secret": "s3cret-value"})


def test_schedules_are_disabled_by_default_and_need_both_switches(env):
    env.settings.cron_secret = "s3cret-value"
    s = env.client.get("/api/v1/admin/agent-schedules", headers=env.auth("admin")).json()
    assert s["globally_enabled"] is False and len(s["items"]) == 4 and not any(x["enabled"] for x in s["items"])
    assert env.client.get("/api/v1/admin/agent-schedules", headers=env.auth("student")).status_code == 403
    assert cron(env).json()["agent_schedules"] == dict(enabled=False, queued=0)
    events = next(x for x in s["items"] if x["agent_id"] == "events")
    r = env.client.patch(f"/api/v1/admin/agent-schedules/{events['id']}", json={"enabled": True}, headers=env.auth("admin"))
    assert r.status_code == 200 and r.json()["enabled"] is True
    assert cron(env).json()["agent_schedules"]["enabled"] is False         # the server switch is still off
    env.settings.agent_schedules_enabled = True
    out = cron(env).json()["agent_schedules"]
    assert out == dict(enabled=True, queued=1)
    sys_tasks = [t for t in env.store.select("agent_tasks")[0] if t["schedule_id"] == events["id"]]
    assert len(sys_tasks) == 1 and sys_tasks[0]["requested_by"] is None and sys_tasks[0]["status"] == "completed"
    assert cron(env).json()["agent_schedules"]["queued"] == 0               # not due again yet
    audit = [x for x in env.store.select("audit_log")[0] if x["action"] == "agent_schedule.update"]
    assert len(audit) == 1


def test_schedule_urls_must_be_allowlisted(env):
    s = env.client.get("/api/v1/admin/agent-schedules", headers=env.auth("admin")).json()["items"][0]
    r = env.client.patch(f"/api/v1/admin/agent-schedules/{s['id']}", json={"urls": ["https://evil.example.com/"]},
                         headers=env.auth("admin"))
    assert r.status_code == 422


def test_finished_tasks_are_purged_after_retention(env):
    t = task(env, "events", "event_digest").json()
    old = (datetime.now(UTC) - timedelta(days=60)).isoformat()
    env.store.update("agent_tasks", dict(created_at=old), {"id": t["id"]})
    assert env.app.state.services.agents.purge_expired() == 1
    assert env.store.select("agent_tasks")[0] == [] and env.store.select("agent_task_events")[0] == []
