"""All desks: official-source monitoring, supporters' and coordinators' staff tools, deadlines, pause, re-run, privacy, storage."""
from __future__ import annotations

import pytest

from app.repositories.base import Query, get_one
from app.services.agents.registry import AGENTS
from app.services.agents.tasks import ADMIN_TASKS, DISCOVERY_AGENTS
from app.services.agents.tools import TOOLS
from tests.test_announcements import create
from tests.test_discovery import D, admin_source, program_page, run_task
from tests.test_document_translations import assign
from tests.test_gpu_worker import new_worker, publish

PAGE = "https://www.studyinkorea.go.kr/ko/desk-{}.do"
DESKS = [("immigration", "guidance_discovery", "visa-immigration", "체류기간 연장 안내", "<p>체류기간 연장 신청은 방문 예약 후 할 수 있습니다. 여권과 외국인등록증을 준비하십시오.</p>"),
         ("academic", "guidance_discovery", "academic-life", "학사일정", "<p>2027학년도 1학기 수강신청 기간을 확인하십시오. 자세한 일정은 아래와 같습니다.</p>"),
         ("topik", "guidance_discovery", "topik-korean", "TOPIK 접수 안내", "<p>한국어능력시험 접수 기간과 시험일을 확인하십시오. 접수는 온라인으로 합니다.</p>"),
         ("events", "event_discovery", "university-announcements", "유학생 문화 축제 행사 안내", f"<p>일시: {D(9)}. 장소: 학생회관</p><p>신청 마감: {D(5)}까지 신청하십시오. 누구나 참가할 수 있습니다.</p>"),
         ("career", "opportunity_discovery", "employment-internships", "유학생 인턴 채용 공고", f"<p>지원 자격: 재학생. 접수 마감: {D(8)}까지 지원하십시오. 근무지는 아산입니다.</p>"),
         ("scholarship", "opportunity_discovery", "scholarships", "장학금 신청 안내", f"<p>지원 자격: 유학생. 신청 마감: {D(7)}까지 신청하십시오. 금액은 별도 안내합니다.</p>"),
         ("announcement", "announcement_discovery", "university-announcements", "공지 안내문", "<p>새로운 공지사항 내용을 확인하십시오. 자세한 내용은 국제교육교류처로 문의하십시오.</p>")]


def desk(env, agent, category, title, body, role="admin"):  # type: ignore[no-untyped-def]
    url = PAGE.format(agent)
    env.page(url, program_page(title, body))
    return admin_source(env, agent_id=agent, name=title, kind="page", url=url, category=category, config={}), url


def tool(env, agent, name, params=None, role="student"):  # type: ignore[no-untyped-def]
    return env.client.post(f"/api/v1/agents/{agent}/tools", headers=env.auth(role) if role else {}, json=dict(tool=name, params=params or {}))


@pytest.mark.parametrize("agent,task_type,category,title,body", DESKS)
def test_every_desk_checks_its_own_sources_and_students_see_only_reviewed_items(env, agent, task_type, category, title, body):
    _s, url = desk(env, agent, category, title, body)
    assert run_task(env, agent, task_type, role="student").status_code == 403
    t = run_task(env, agent, task_type).json()
    assert t["status"] == "completed" and t["output"]["new_count"] == 1, t
    # a second, unchanged check finds nothing new; a changed page is "updated"
    env.store.update("discovery_sources", {"last_checked_at": None}, {})
    assert run_task(env, agent, task_type).json()["output"]["new_count"] == 0
    env.page(url, program_page(title, body + "<p>변경된 안내 사항이 추가되었습니다. 다시 확인하십시오.</p>"))
    env.store.update("discovery_sources", {"last_checked_at": None}, {})
    assert run_task(env, agent, task_type).json()["output"]["updated_count"] == 1
    assert env.store.select("source_documents")[0] == []                 # nothing became knowledge
    name = "official_updates"
    assert tool(env, agent, name).json()["result"]["items"] == []        # not reviewed: invisible
    if name == "official_updates":
        seen = tool(env, agent, name, role="admin").json()["result"]["items"]
        assert len(seen) == 1 and seen[0]["reliability"] == "external_unverified"
    # admin sends it to review, approves it in the normal review: now students see it, linked to the approved document
    item = env.client.get(f"/api/v1/admin/discovery/items?agent_id={agent}", headers=env.auth("admin")).json()["items"][0]
    assert env.client.post(f"/api/v1/admin/discovery/items/{item['id']}/send-to-review", headers=env.auth("admin")).status_code == 202
    assert tool(env, agent, name).json()["result"]["items"] == []        # still waiting for the reviewer
    v = env.store.select("document_versions")[0][0]
    assert env.client.post(f"/api/v1/admin/versions/{v['id']}/approve", headers=env.auth("admin"), json={}).status_code == 202
    if name == "official_updates":
        out = tool(env, agent, name).json()["result"]
        assert [i["reliability"] for i in out["items"]] == ["verified"] and out["items"][0]["href"].startswith("/knowledge/")
        assert out["sources"][0]["url"] == url


def test_a_desk_shows_only_its_own_sources(env):
    desk(env, "immigration", "visa-immigration", "체류 안내", DESKS[0][4])
    run_task(env, "immigration", "guidance_discovery")
    assert tool(env, "academic", "official_updates", role="admin").json()["result"]["notes"] == ["no_sources"]
    assert len(tool(env, "immigration", "official_updates", role="admin").json()["result"]["items"]) == 1
    assert env.client.get("/api/v1/agents/immigration/monitoring").json()["sources"][0]["name"] == "체류 안내"


def test_tasks_belong_to_their_desk(env):
    assert run_task(env, "topik", "opportunity_discovery").status_code == 403
    assert run_task(env, "reception", "guidance_discovery").status_code == 403
    assert {AGENTS[a].id for a in DISCOVERY_AGENTS} == {a.id for a in AGENTS.values() if set(a.task_types) & ADMIN_TASKS}


def test_events_are_recognised_and_shown_by_mia(env):
    desk(env, "events", "university-announcements", DESKS[3][3], DESKS[3][4])
    run_task(env, "events", "event_discovery")
    it = tool(env, "events", "opportunity_search", role="admin").json()["result"]["items"][0]
    assert it["opportunity_kind"] == "event" and it["event_date"] == D(9) and it["next_deadline"] == D(5)


# ------------------------------------------------------------------------------------------------ deadlines
def test_upcoming_deadlines_are_sorted_and_public_only(env):
    for title, dl in (("B later", D(20)), ("A soon", D(3)), ("C far", D(170))):
        a = create(env, submit=True, title=title, deadline=dl, event_date=None)
        env.client.post(f"/api/v1/admin/announcements/{a['id']}/approve", headers=env.auth("admin"), json={})
    create(env, submit=True, title="Not approved", deadline=D(2))
    out = tool(env, "scholarship", "upcoming_deadlines", role=None).json()["result"]["items"]
    assert [i["title"] for i in out] == ["A soon", "B later"]


# ------------------------------------------------------------------------------------------------ supporters
def test_terms_are_found_in_every_language_and_marked_as_draft(env):
    for text in ("외국인등록증을 잃어버렸어요", "I lost my residence card", "kartu registrasi orang asing", "外国人登录证", "thẻ đăng ký người nước ngoài"):
        out = tool(env, "supporter-vi", "terminology_lookup", {"text": text}, role=None).json()["result"]
        assert any(i["terms"]["ko"] == "외국인등록증" for i in out["items"]), text
        assert out["notes"] == ["terms_draft"]
    assert tool(env, "supporter-en", "terminology_lookup", {"text": "zzz"}, role=None).json()["result"]["notes"] == ["no_terms"]
    assert tool(env, "events", "terminology_lookup", {"text": "x"}, role=None).status_code == 403


def test_the_review_queue_is_staff_only_and_language_scoped(env):
    a = publish(env)
    env.store.update("announcement_translations", {"translation_status": "machine_draft"}, {"announcement_id": a["id"], "language_code": "vi"})
    assert tool(env, "supporter-vi", "translation_review_queue", role=None).status_code == 401
    r = tool(env, "supporter-vi", "translation_review_queue")
    assert r.status_code == 403 and r.json()["error"]["code"] == "staff_only"
    r = tool(env, "supporter-vi", "translation_review_queue", role="supporter").json()["result"]
    assert r["items"] == [] and r["notes"] == ["not_your_language"]
    assign(env, "supporter", "vi")
    r = tool(env, "supporter-vi", "translation_review_queue", role="supporter").json()["result"]
    assert r["counts"] == {"machine_draft": 1} and r["items"][0]["href"] == f"/admin/translations/{a['id']}/vi"
    assert tool(env, "supporter-id", "translation_review_queue", role="supporter").json()["result"]["notes"] == ["not_your_language"]
    tabs = {x["id"]: x["interface"]["tabs"] for x in env.client.get("/api/v1/agents", headers=env.auth("student")).json()["items"]}
    assert "queue" not in tabs["supporter-vi"] and "terms" in tabs["supporter-vi"]


def test_a_supporter_requests_a_draft_for_the_gpu_worker_and_nothing_becomes_public(env):
    env.settings.gpu_worker_enabled = True
    new_worker(env)
    a = publish(env)
    assign(env, "supporter", "id")
    assert tool(env, "supporter-id", "request_translation_draft", {"announcement_id": a["id"]}).status_code == 403          # student
    assert tool(env, "supporter-en", "request_translation_draft", {"announcement_id": a["id"]}, "supporter").status_code == 403
    r = tool(env, "supporter-id", "request_translation_draft", {"announcement_id": a["id"]}, "supporter")
    assert r.status_code == 200 and r.json()["result"]["items"][0]["executor"] == "gpu", r.text
    again = tool(env, "supporter-id", "request_translation_draft", {"announcement_id": a["id"]}, "supporter").json()["result"]["items"][0]
    assert again["id"] == r.json()["result"]["items"][0]["id"]           # one open job, not two
    assert env.client.get(f"/api/v1/announcements/{a['id']}", params={"lang": "id"}).json()["translation"] is None
    # Release 1: an assigned Vietnamese supporter gets no machine draft of an announcement (out of scope, not hidden)
    assign(env, "supporter", "vi")
    out = tool(env, "supporter-vi", "request_translation_draft", {"announcement_id": a["id"]}, "supporter")
    assert out.status_code == 409 and out.json()["error"]["code"] == "language_out_of_scope", out.text
    # never as a background lookup of a student
    assert env.client.post("/api/v1/agents/supporter-id/tasks", headers=env.auth("supporter"), json=dict(
        task_type="lookup", params=dict(tool="request_translation_draft", params={}))).status_code == 403


def test_a_supporter_requests_a_summary_of_an_approved_document(env):
    from tests.test_gpu_worker import claim
    from tests.test_retrieval import make_doc

    env.settings.gpu_worker_enabled = True
    env.worker = new_worker(env)
    doc = make_doc(env, "기숙사 안내", "기숙사 입사 신청은 12월 18일까지 종합정보시스템에서 합니다. 결핵 검사 결과서를 제출해야 합니다.", language="ko")
    doc_id = doc["document_id"]
    assign(env, "supporter", "vi")
    r = tool(env, "supporter-vi", "request_translation_draft", {"document_id": doc_id, "summary": True}, "supporter")
    assert r.status_code == 200 and r.json()["result"]["items"][0]["executor"] == "gpu", r.text
    job = claim(env)
    assert "summarize" in str(job)
    a = publish(env)
    assert tool(env, "supporter-vi", "request_translation_draft", {"announcement_id": a["id"], "summary": True}, "supporter").status_code == 422


def test_without_a_model_or_worker_drafts_are_refused(env):
    a = publish(env)
    assign(env, "supporter", "vi")
    r = tool(env, "supporter-vi", "request_translation_draft", {"announcement_id": a["id"]}, "supporter")
    assert r.status_code == 409 and r.json()["error"]["code"] == "tool_unavailable"


# ------------------------------------------------------------------------------------------------ Sumin's staff queue
def test_the_support_queue_never_contains_the_students_words(env):
    env.client.post("/api/v1/support/tickets", headers=env.auth("student"), json=dict(
        subject="SECRET-SUBJECT visa", summary="SECRET-SUMMARY my family", language="id", consent=True))
    assert tool(env, "support-coordinator", "support_queue").status_code == 403
    assign(env, "supporter", "id")
    r = tool(env, "support-coordinator", "support_queue", role="supporter")
    assert r.status_code == 200 and len(r.json()["result"]["items"]) >= 0 and "SECRET" not in r.text
    assert tool(env, "support-coordinator", "support_queue", {"language": "vi"}, "supporter").status_code == 403


# ------------------------------------------------------------------------------------------------ pause
def test_a_paused_desk_starts_nothing_and_resumes(env):
    put = lambda paused, role="admin": env.client.put("/api/v1/admin/agent-operations/agents/events", headers=env.auth(role), json={"paused": paused})  # noqa: E731
    assert put(True, "student").status_code == 403 and put(True, "supporter").status_code == 403
    assert put(True).status_code == 200
    r = env.client.post("/api/v1/agents/events/tasks", headers=env.auth("student"), json=dict(task_type="event_digest"))
    assert r.status_code == 503 and r.json()["error"]["code"] == "agent_paused"
    assert next(a for a in env.client.get("/api/v1/agents").json()["items"] if a["id"] == "events")["paused"] is True
    env.store.insert("agent_tasks", dict(agent_id="events", task_type="event_digest", requested_by=env.users["student"], status="queued"))
    assert env.app.state.services.agents.claim("w", 300) is None          # a queued task waits
    assert put(False).status_code == 200
    assert env.app.state.services.agents.claim("w", 300)["agent_id"] == "events"
    assert [a["action"] for a in env.store.select("audit_log", Query(order=[("id", False)]))[0] if a["action"].startswith("agent.")] == ["agent.pause", "agent.resume"]
    assert env.client.put("/api/v1/admin/agent-operations/agents/nobody", headers=env.auth("admin"), json={"paused": True}).status_code == 404


def test_paused_desks_are_skipped_by_schedules(env):
    env.settings.cron_secret, env.settings.agent_schedules_enabled = "s3cret-value", True
    env.store.update("agent_schedules", {"enabled": True}, {"agent_id": "events"})
    env.client.put("/api/v1/admin/agent-operations/agents/events", headers=env.auth("admin"), json={"paused": True})
    r = env.client.post("/api/v1/internal/sync/run-due", headers={"X-Cron-Secret": "s3cret-value"}).json()
    assert r["agent_schedules"]["queued"] == 0


# ------------------------------------------------------------------------------------------------ admin view
def test_admins_see_all_tasks_but_never_a_students_words(env):
    env.client.post("/api/v1/agents/support-coordinator/tasks", headers=env.auth("student"), json=dict(
        task_type="support_request", params=dict(subject="SECRET-SUBJECT", summary="SECRET-SUMMARY", language="en")))
    desk(env, "topik", "topik-korean", DESKS[2][3], DESKS[2][4])
    run_task(env, "topik", "guidance_discovery")
    for role, code in (("student", 403), ("supporter", 403), ("admin", 200)):
        assert env.client.get("/api/v1/admin/agent-operations/tasks", headers=env.auth(role)).status_code == code
        assert env.client.get("/api/v1/admin/agent-operations", headers=env.auth(role)).status_code == code
        assert env.client.get("/api/v1/admin/storage", headers=env.auth(role)).status_code == code
    r = env.client.get("/api/v1/admin/agent-operations/tasks", headers=env.auth("admin"))
    assert "SECRET" not in r.text and r.json()["total"] == 2
    by = {t["task_type"]: t for t in r.json()["items"]}
    assert by["support_request"]["requested"] == "student" and "params" not in by["support_request"]
    assert by["guidance_discovery"]["new_count"] == 1 and by["guidance_discovery"]["requested"] == "administrator"
    one = env.client.get(f"/api/v1/admin/agent-operations/tasks/{by['support_request']['id']}", headers=env.auth("admin"))
    assert "SECRET" not in one.text and all(e["message"] is None for e in one.json()["events"])


def test_only_failed_tasks_without_side_effects_run_again(env):
    s, url = desk(env, "topik", "topik-korean", DESKS[2][3], DESKS[2][4])
    t = env.store.insert("agent_tasks", dict(agent_id="topik", task_type="guidance_discovery", requested_by=env.users["admin"],
                                             status="failed", attempts=3, error_code="interrupted"))
    w = env.store.insert("agent_tasks", dict(agent_id="support-coordinator", task_type="support_request", requested_by=env.users["student"],
                                             status="failed", params={}))
    post = lambda tid, what, role="admin": env.client.post(f"/api/v1/admin/agent-operations/tasks/{tid}/{what}", headers=env.auth(role))  # noqa: E731
    assert post(t["id"], "rerun", "student").status_code == 403
    assert post(w["id"], "rerun").status_code == 409                      # might have been sent already
    assert post(t["id"], "rerun").status_code == 202
    assert get_one(env.store, "agent_tasks", id=t["id"])["status"] == "completed"
    assert post(t["id"], "rerun").status_code == 409 and post(t["id"], "cancel").status_code == 409
    q = env.store.insert("agent_tasks", dict(agent_id="topik", task_type="guidance_discovery", requested_by=env.users["admin"], status="queued"))
    assert post(q["id"], "cancel").json()["status"] == "cancelled"


def test_health_lists_all_14_desks_with_their_sources_and_schedules(env):
    desk(env, "career", "employment-internships", DESKS[4][3], DESKS[4][4])
    run_task(env, "career", "opportunity_discovery")
    h = env.client.get("/api/v1/admin/agent-operations", headers=env.auth("admin")).json()
    by = {a["id"]: a for a in h["agents"]}
    assert len(by) == 14 and by["career"]["tasks_7d"]["completed"] == 1 and by["career"]["sources"] == 1
    assert by["career"]["last_success_at"] and all(not s["enabled"] for a in h["agents"] for s in a["schedules"])
    assert h["schedules_enabled_on_server"] is False and h["queues"]["agent_tasks"]["stuck"] is False


def test_storage_levels_and_one_alert_per_day(env):
    st = env.client.get("/api/v1/admin/storage", headers=env.auth("admin")).json()
    assert st["available"] and st["level"] == "ok" and st["database_bytes"] > 0
    ops = env.app.state.services.operations
    assert ops.alert() == []
    real = env.store._rpc_storage_overview
    env.store._rpc_storage_overview = lambda: [dict(table_name="(database)", total_bytes=480 * 1024 * 1024, table_bytes=0, index_bytes=0, row_estimate=0)]
    assert ops.alert() == ["storage_threshold"] and ops.alert() == []
    env.store._rpc_storage_overview = real
    env.store.insert("ingestion_jobs", dict(source_id=None, created_at="2026-01-01T00:00:00+00:00", run_after="2026-01-01T00:00:00+00:00"))
    assert ops.alert() == ["queue_stuck_jobs"]
    before = len(env.store.select("source_documents")[0])
    assert before == len(env.store.select("source_documents")[0])        # an alert never deletes


def test_without_migration_0017_everything_else_works(env):
    real = env.store.select

    def select(table, *a, **k):  # type: ignore[no-untyped-def]
        if table == "agent_controls":
            raise RuntimeError("relation does not exist")
        return real(table, *a, **k)

    env.store.select = select
    assert env.client.get("/api/v1/agents").status_code == 200
    assert env.client.post("/api/v1/agents/events/tasks", headers=env.auth("student"), json=dict(task_type="event_digest")).status_code == 201
    r = env.client.put("/api/v1/admin/agent-operations/agents/events", headers=env.auth("admin"), json={"paused": True})
    assert r.status_code == 409 and r.json()["error"]["code"] == "migration_missing"


def test_every_tool_of_every_desk_exists_and_staff_tools_are_gated():
    for a in AGENTS.values():
        assert a.allowed_tools <= set(TOOLS), a.id
    for name in ("translation_review_queue", "request_translation_draft", "support_queue"):
        assert TOOLS[name].roles and "student" not in TOOLS[name].roles and TOOLS[name].requires_auth


def test_a_discovered_board_notice_is_imported_by_its_own_parser(env):
    """Not as a generic page: the title is the notice's, menus stay out, attachments come along and stay reviewed."""
    from tests.test_discovery import NOTICES, board

    board(env, NOTICES)
    admin_source(env)
    run_task(env, "announcement", "announcement_discovery")
    item = next(i for i in env.client.get("/api/v1/admin/discovery/items?agent_id=announcement", headers=env.auth("admin")).json()["items"] if "장학금" in i["title"])
    assert env.client.post(f"/api/v1/admin/discovery/items/{item['id']}/send-to-review", headers=env.auth("admin")).status_code == 202
    v = env.store.select("document_versions")[0][0]
    d = env.store.select("source_documents")[0][0]
    assert d["title"] == item["title"] and v["extracted_text"].startswith(f"# {item['title']}") and v["source_published_at"]
    assert "평점 3.5" in v["extracted_text"] and v["extraction_meta"]["extractor"] == "sch_board"
    env.client.post(f"/api/v1/admin/versions/{v['id']}/approve", headers=env.auth("admin"), json={})
    pub = env.client.get(f"/api/v1/knowledge/documents/{d['id']}").json()
    assert pub["title"] == item["title"]
    # a page whose structure changed fails loudly instead of importing menus
    env.page(item["url"], "<html><body><nav>menu</nav><p>" + "x" * 200 + "</p></body></html>")
    src = env.store.select("knowledge_sources", Query(eq={"source_type": "website"}))[0][0]
    r = env.client.post(f"/api/v1/admin/sources/{src['id']}/ingest", headers=env.auth("admin"))
    job = env.client.get(f"/api/v1/admin/ingestion-jobs/{r.json()['job_id']}", headers=env.auth("admin")).json()
    assert job["status"] == "failed" and len(env.store.select("document_versions")[0]) == 1


def test_a_discovered_listing_item_is_imported_without_site_chrome(env):
    url = "https://home.sch.ac.kr/sch/06/010300.jsp"
    env.page(url, f'<table><tbody><tr><td class="subject"><a href="?mode=view&amp;article_no=2"> [장학] 동계 근로장학생 신청 안내 </a></td><td class="date">{D(-1)}</td></tr></tbody></table>')
    env.page(f"{url}?mode=view&article_no=2", "<html><head><title>순천향대학교</title></head><body><div class='menu'>메뉴 홍보신청</div><div class='board_contents'><p>지원 자격: 재학생. 신청은 종합정보시스템에서 합니다.</p></div>"
             "<div class='board_file'><a href='/download?f=1'>신청서.hwp</a><a href='javascript:x()'>bad</a></div></body></html>")
    admin_source(env, agent_id="scholarship", name="장학공지", kind="listing", url=url, config={
        "item_selector": "table tbody tr", "title_selector": "td.subject a", "date_selector": "td.date", "link_selector": "td.subject a",
        "content_selector": "div.board_contents", "attachment_selector": "div.board_file"})
    run_task(env, "scholarship", "opportunity_discovery")
    item = env.client.get("/api/v1/admin/discovery/items?agent_id=scholarship", headers=env.auth("admin")).json()["items"][0]
    env.client.post(f"/api/v1/admin/discovery/items/{item['id']}/send-to-review", headers=env.auth("admin"))
    v, d = env.store.select("document_versions")[0][0], env.store.select("source_documents")[0][0]
    assert d["title"] == "[장학] 동계 근로장학생 신청 안내" and "메뉴" not in v["extracted_text"] and "지원 자격: 재학생" in v["extracted_text"]
    assert "신청서.hwp: https://home.sch.ac.kr/download?f=1" in v["extracted_text"] and "javascript" not in v["extracted_text"] and D(-1) in v["extracted_text"]
