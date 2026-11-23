"""AI Support Office agents against the REAL database (PostgREST + PostgreSQL + migration 0014): tasks are stored and
claimed through claim_agent_task, the active-idempotency index works through the real store, approval creates a real
support ticket, owner-only reads, schedules stay disabled. Skipped unless the integration environment is configured."""
from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from tests.integration.test_postgres_integration import IT, PSQL, REST, sql

pytestmark = pytest.mark.skipif(not (REST and PSQL), reason="set SCH_IT_REST_URL and SCH_IT_PSQL to run")


@pytest.fixture(scope="module")
def it() -> IT:
    return IT()


def publish_event(it: IT, title: str) -> dict:  # type: ignore[type-arg]
    a = it.auth("admin")
    ann = it.client.post("/api/v1/admin/announcements", headers=a, json=dict(
        title=title, body=f"{title} 행사 안내", category="university-announcements", source_type="manual_text",
        submit=True, evidence_note="integration test", event_date=str(date.today() + timedelta(days=4)),
        deadline=str(date.today() + timedelta(days=3)))).json()
    r = it.client.post(f"/api/v1/admin/announcements/{ann['id']}/approve", headers=a, json={})
    assert r.status_code == 200, r.text
    return ann


def test_task_runs_through_the_real_store_with_events(it: IT):
    ann = publish_event(it, f"Orientation {uuid.uuid4().hex[:6]}")
    r = it.client.post("/api/v1/agents/events/tasks", json=dict(task_type="event_digest"), headers=it.auth("student"))
    assert r.status_code == 201, r.text
    t = it.client.get(f"/api/v1/agent-tasks/{r.json()['id']}", headers=it.auth("student")).json()
    assert t["status"] == "completed", t
    assert any(i["id"] == ann["id"] for i in t["output"]["items"])
    assert [e["step"] for e in t["events"]][:2] == ["queued", "start"]
    n = sql(f"select count(*) from agent_task_events where task_id = '{t['id']}'")
    assert int(n.splitlines()[-1]) == len(t["events"])


def test_worker_claim_rpc_and_idempotency_index(it: IT):
    svc = it.app.state.services
    it.settings.job_execution = "worker"
    svc.jobs.kick = lambda: None
    try:
        key = f"it-{uuid.uuid4().hex[:8]}"
        a = it.client.post("/api/v1/agents/events/tasks", json=dict(task_type="event_digest", idempotency_key=key),
                           headers=it.auth("student")).json()
        b = it.client.post("/api/v1/agents/events/tasks", json=dict(task_type="event_digest", idempotency_key=key),
                           headers=it.auth("student")).json()
        assert a["id"] == b["id"] and a["status"] == "queued"        # unique partial index -> the same task
        # the worker drains everything that is due (other tests' rows may be queued too)
        for _ in range(20):
            if not svc.jobs.run_once():
                break
        t = it.client.get(f"/api/v1/agent-tasks/{a['id']}", headers=it.auth("student")).json()
        assert t["status"] == "completed" and t["attempts"] == 1
    finally:
        it.settings.job_execution = "inline"


def test_approval_creates_a_real_ticket_and_tasks_are_private(it: IT):
    r = it.client.post("/api/v1/agents/support-coordinator/requests",
                       json=dict(message="I want to talk to a human supporter about housing"), headers=it.auth("student"))
    assert r.status_code == 200, r.text
    tid = r.json()["task"]["id"]
    before = int(sql(f"select count(*) from support_tickets where student_id = '{it.users['student']}'").splitlines()[-1])
    assert it.client.get(f"/api/v1/agent-tasks/{tid}", headers=it.auth("supporter")).status_code == 404
    d = it.client.post(f"/api/v1/agent-tasks/{tid}/decision", json={"approve": True}, headers=it.auth("student"))
    assert d.status_code == 200, d.text
    t = it.client.get(f"/api/v1/agent-tasks/{tid}", headers=it.auth("student")).json()
    assert t["status"] == "completed", t
    after = int(sql(f"select count(*) from support_tickets where student_id = '{it.users['student']}'").splitlines()[-1])
    assert after == before + 1


def test_schedules_are_seeded_disabled(it: IT):
    s = it.client.get("/api/v1/admin/agent-schedules", headers=it.auth("admin")).json()
    assert s["globally_enabled"] is False and {x["task_type"] for x in s["items"]} >= {"event_digest", "scholarship_scan"}
    assert not any(x["enabled"] for x in s["items"])
