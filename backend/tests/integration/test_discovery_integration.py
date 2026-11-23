"""Official-source discovery against the REAL database (PostgREST + PostgreSQL + migration 0015): sources and items are
stored through the real store, the item_key unique index deduplicates, change detection survives a round trip,
task progress is stored, send-to-review creates a pending_review version only. Skipped unless the integration
environment is configured. Pages come from a mock transport (no network)."""
from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from tests.integration.test_postgres_integration import IT, PSQL, REST, sql
from tests.test_phase2 import board_html, notice_html

pytestmark = pytest.mark.skipif(not (REST and PSQL), reason="set SCH_IT_REST_URL and SCH_IT_PSQL to run")
TAG = uuid.uuid4().hex[:6]
TABLE = f"noti_it{TAG}"
LIST = f"https://sgee.sch.ac.kr/notice/notice01.php?table_name={TABLE}"
TODAY = date.today()


def notice(no: int) -> str:
    return f"https://sgee.sch.ac.kr/notice/notice01.php?admin_mode=read&no={no}&table_name={TABLE}"


@pytest.fixture(scope="module")
def it() -> IT:
    it = IT()
    it.settings.board_request_delay_seconds = 0
    it.app.state.services.discovery.connectors.delay = 0
    return it


def publish_pages(it: IT, body_suffix: str = "") -> None:
    posted = (TODAY - timedelta(days=1)).isoformat()
    rows = [(9001, f"[장학] 통합테스트 장학금 신청 안내 {TAG}", posted, False), (9002, f"[생활관] 통합테스트 안내 {TAG}", posted, False)]
    it.pages[LIST] = board_html(rows).replace("table_name=noti_fore", f"table_name={TABLE}").encode()
    deadline = (TODAY + timedelta(days=10)).isoformat().replace("-", ". ")
    it.pages[notice(9001)] = notice_html(rows[0][1], posted.replace("-", "."),
                                         f"<p>지원 자격: 외국인 유학생</p><p>신청 마감: {deadline}. 까지</p>").encode()
    it.pages[notice(9002)] = notice_html(rows[1][1], posted.replace("-", "."), f"<p>생활관 안내입니다.{body_suffix}</p>").encode()


def test_discovery_round_trip_through_the_real_store(it: IT):
    publish_pages(it)
    r = it.client.post("/api/v1/admin/discovery/sources", headers=it.auth("admin"), json=dict(
        agent_id="announcement", name=f"IT board {TAG}", kind="sch_board", url=LIST, config={"max_items": 5}))
    assert r.status_code == 201, r.text
    src = r.json()
    t = it.client.post("/api/v1/agents/announcement/tasks", json=dict(task_type="announcement_discovery",
                                                                    params={"source_ids": [src["id"]]}),
                       headers=it.auth("admin"))
    assert t.status_code == 201, t.text
    task = it.client.get(f"/api/v1/agent-tasks/{t.json()['id']}", headers=it.auth("admin")).json()
    assert task["status"] == "completed", task
    assert task["output"]["new_count"] == 2 and task["progress"]["sources_done"] == 1
    rows = sql(f"select count(*) from discovered_items where source_id = '{src['id']}'")
    assert rows.splitlines()[-1] == "2"
    sch = next(i for i in task["output"]["items"] if "장학금" in i["title"])
    assert sch["open_status"] == "open" and sch["eligibility"]

    # changed notice -> updated; the unique item_key keeps one row per notice
    publish_pages(it, body_suffix=" 장소가 변경되었습니다.")
    sql(f"update discovery_sources set last_checked_at = null where id = '{src['id']}'")
    t2 = it.client.post("/api/v1/agents/announcement/tasks", json=dict(task_type="announcement_discovery",
                                                                     params={"source_ids": [src["id"]]}),
                        headers=it.auth("admin")).json()
    task2 = it.client.get(f"/api/v1/agent-tasks/{t2['id']}", headers=it.auth("admin")).json()
    assert task2["output"]["updated_count"] == 1 and task2["output"]["new_count"] == 0
    assert sql(f"select count(*) from discovered_items where source_id = '{src['id']}'").splitlines()[-1] == "2"

    # students: not allowed to crawl, and never see the admin review queue
    s = it.client.post("/api/v1/agents/announcement/tasks", json=dict(task_type="announcement_discovery"),
                       headers=it.auth("student"))
    assert s.status_code == 403

    # send to review: a website knowledge source + a pending_review version, nothing approved
    it.pages[f"https://sgee.sch.ac.kr/notice/notice01.php?admin_mode=read&no=9001&table_name={TABLE}"] = \
        it.pages[notice(9001)]
    r = it.client.post(f"/api/v1/admin/discovery/items/{sch['id']}/send-to-review", headers=it.auth("admin"))
    assert r.status_code == 202, r.text
    ks = r.json()["knowledge_source_id"]
    statuses = sql("select string_agg(v.verification_status, ',') from document_versions v join source_documents d "
                   f"on d.id = v.document_id where d.source_id = '{ks}'").splitlines()[-1]
    assert statuses == "pending_review"
    assert sql(f"select status from discovered_items where id = '{sch['id']}'").splitlines()[-1] == "imported"
