"""Migration 0017 on the REAL database: pause and claim, sizes, the new desks' sources. Skipped unless configured."""
from __future__ import annotations

import uuid

import pytest

from tests.integration.test_postgres_integration import IT, PSQL, REST, sql

pytestmark = [pytest.mark.skipif(not (REST and PSQL), reason="set SCH_IT_REST_URL and SCH_IT_PSQL to run")]


@pytest.fixture(scope="module")
def it() -> IT:
    if sql("select count(*) from information_schema.tables where table_name = 'agent_controls'") == "0":
        pytest.skip("migration 0017 is not applied")
    return IT()


def test_pause_claim_and_resume(it: IT):
    a, agents = it.auth("admin"), it.app.state.services.agents
    sql("update public.agent_tasks set status = 'cancelled' where status = 'queued'")
    assert it.client.put("/api/v1/admin/agent-operations/agents/topik", headers=a, json={"paused": True, "note": "test"}).status_code == 200
    r = it.client.post("/api/v1/agents/topik/tasks", headers=it.auth("student"), json=dict(task_type="topik_dates"))
    assert r.status_code == 503 and r.json()["error"]["code"] == "agent_paused"
    sql(f"insert into public.agent_tasks (agent_id, task_type, requested_by) values ('topik', 'topik_dates', '{it.users['student']}')")
    assert agents.claim("w-it", 300) is None
    assert it.client.put("/api/v1/admin/agent-operations/agents/topik", headers=a, json={"paused": False}).status_code == 200
    t = agents.claim("w-it", 300)
    assert t is not None and t["agent_id"] == "topik" and agents.claim("w-it", 300) is None
    agents.execute(t)
    assert sql(f"select status from public.agent_tasks where id = '{t['id']}'") == "completed"


def test_health_storage_and_new_desk_sources(it: IT):
    a = it.auth("admin")
    h = it.client.get("/api/v1/admin/agent-operations", headers=a).json()
    assert len(h["agents"]) == 14 and not any(s["enabled"] for x in h["agents"] for s in x["schedules"])
    assert h["queues"]["gpu_jobs"] is None or h["queues"]["gpu_jobs"]["queued"] >= 0
    st = it.client.get("/api/v1/admin/storage", headers=a).json()
    assert st["available"] and st["database_bytes"] > 5_000_000 and {"document_chunks"} <= {t["table_name"] for t in st["tables"]}
    url = f"https://www.studyinkorea.go.kr/ko/it-{uuid.uuid4().hex[:8]}.do"
    r = it.client.post("/api/v1/admin/discovery/sources", headers=a, json=dict(agent_id="immigration", name="Integration test", kind="page", url=url))
    assert r.status_code == 201, r.text
    assert it.client.get("/api/v1/agents/immigration/monitoring").json()["supported"] is True
    assert it.client.delete(f"/api/v1/admin/discovery/sources/{r.json()['id']}", headers=a).status_code == 204
    for path in ("/api/v1/admin/agent-operations", "/api/v1/admin/storage"):
        assert it.client.get(path, headers=it.auth("student")).status_code == 403
