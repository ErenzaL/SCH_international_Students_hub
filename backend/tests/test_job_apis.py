"""Official recruitment APIs: fixtures of the documented answers (no real key), keys never leak, nothing is published."""
from __future__ import annotations

import httpx
import pytest

from app.repositories.base import get_one
from app.services.agents.tools import ToolContext  # noqa: F401 - the registry must import cleanly
from tests.test_discovery import D, run_task

KEY = "SECRET-API-KEY-123"
SARAMIN = {"jobs": {"count": 3, "start": 0, "total": "3", "job": [
    {"id": "101", "url": "https://www.saramin.co.kr/zf_user/jobs/relay/view?rec_idx=101", "active": 1, "posting-date": f"{D(-3)}T00:00:00+0900", "expiration-date": f"{D(9)}T23:59:59+0900",
     "company": {"detail": {"name": "(주)테스트"}}, "position": {"title": "외국인 유학생 인턴 채용", "location": {"name": "충남 &gt; 아산시"}, "job-type": {"name": "인턴직"}, "required-education-level": {"name": "대학교"}}},
    {"id": "102", "url": "https://evil.example/x", "active": 1, "company": {"detail": {"name": "Global Co"}}, "position": {"title": "글로벌 마케팅 <script>alert(1)</script> 신입"}},
    {"id": "103", "url": "https://www.saramin.co.kr/3", "active": 0, "company": {"detail": {"name": "X"}}, "position": {"title": "외국인 채용 (마감)"}},
    {"id": "104", "url": "https://www.saramin.co.kr/4", "active": 1, "company": {"detail": {"name": "Y"}}, "position": {"title": "국내 영업 사원"}}]}}
PUBLIC = {"resultCode": 200, "totalCount": 1, "result": [{"recrutPblntSn": 55, "instNm": "한국테스트공단", "recrutPbancTtl": "통역 계약직 채용", "hireTypeNmLst": "비정규직", "workRgnNmLst": "충남",
          "pbancBgngYmd": D(-2).replace("-", ""), "pbancEndYmd": D(6).replace("-", ""), "srcUrl": "https://job.alio.go.kr/recruitview.do?idx=55", "ongoingYn": "Y", "acbgCondNmLst": "학력무관"}]}


def source(env, kind, **cfg):  # type: ignore[no-untyped-def]
    r = env.client.post("/api/v1/admin/discovery/sources", headers=env.auth("admin"), json=dict(
        agent_id="career", name=f"API {kind}", kind=kind, url="https://ignored.example/", config=cfg))
    assert r.status_code == 201, r.text
    return r.json()


def answer(env, data, status=200):  # type: ignore[no-untyped-def]
    seen: list[httpx.Request] = []

    def h(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(status, json=data) if not isinstance(data, Exception) else (_ for _ in ()).throw(data)

    c = env.app.state.services.discovery.connectors
    c.api_http = httpx.Client(transport=httpx.MockTransport(h))
    env.settings.saramin_access_key = env.settings.data_go_kr_service_key = KEY
    return seen


@pytest.mark.parametrize("kind", ["saramin_api", "data_go_kr_jobs"])
def test_without_a_key_the_source_is_blocked_and_nothing_is_requested(env, kind):
    source(env, kind)
    seen = answer(env, {})
    env.settings.saramin_access_key = env.settings.data_go_kr_service_key = ""
    t = run_task(env, "career", "opportunity_discovery").json()
    assert t["output"]["sources"][0]["status"] == "blocked" and t["output"]["sources"][0]["error"] == "api_key_missing" and seen == []


def test_saramin_items_are_candidates_with_safe_links(env, caplog):
    s = source(env, "saramin_api", keywords="외국인")
    assert s["url"] == "https://www.saramin.co.kr/"                      # fixed, not what the caller sent
    seen = answer(env, SARAMIN)
    t = run_task(env, "career", "opportunity_discovery").json()
    items = t["output"]["items"]
    assert [i["title"] for i in items] == ["[채용] (주)테스트 외국인 유학생 인턴 채용", "[채용] Global Co 글로벌 마케팅 alert(1) 신입"]
    assert items[0]["opportunity_kind"] == "job" and items[0]["next_deadline"] == D(9) and items[0]["published_on"] == D(-3)
    assert items[1]["href"] == "https://www.saramin.co.kr/"              # a link to another site is never shown
    assert seen[0].url.host == "oapi.saramin.co.kr" and seen[0].url.scheme == "https" and len(seen) == 1
    stored = str(env.store.select("discovered_items")[0]) + str(env.store.select("discovery_sources")[0]) + str(env.store.select("agent_task_events")[0])
    assert KEY not in stored and KEY not in t.__repr__() and KEY not in caplog.text
    assert env.client.post("/api/v1/agents/career/tools", headers=env.auth("student"), json=dict(tool="opportunity_search", params={"kind": "job"})).json()["result"]["items"] == []


def test_review_approval_and_expiry_of_a_public_posting(env):
    source(env, "data_go_kr_jobs")
    answer(env, PUBLIC)
    run_task(env, "career", "opportunity_discovery")
    before = len(env.requests)
    item = env.client.get("/api/v1/admin/discovery/items?agent_id=career", headers=env.auth("admin")).json()["items"][0]
    r = env.client.post(f"/api/v1/admin/discovery/items/{item['id']}/send-to-review", headers=env.auth("admin"))
    assert r.status_code == 202 and len(env.requests) == before          # the posting page itself is never fetched
    v = env.store.select("document_versions")[0][0]
    assert v["verification_status"] == "pending_review" and v["valid_until"].startswith(D(6))
    tool = lambda: env.client.post("/api/v1/agents/career/tools", headers=env.auth("student"), json=dict(tool="opportunity_search", params={"kind": "job"})).json()["result"]["items"]  # noqa: E731
    assert tool() == []
    assert env.client.post(f"/api/v1/admin/versions/{v['id']}/approve", headers=env.auth("admin"), json={}).status_code == 202
    assert [i["reliability"] for i in tool()] == ["verified"]
    assert "job.alio.go.kr" in v["extracted_text"] and "출입국에서 확인" in v["extracted_text"]
    env.store.update("document_versions", {"valid_until": "2026-01-01T00:00:00+00:00"}, {"id": v["id"]})
    assert env.client.post("/api/v1/knowledge/search", json=dict(query="통역 계약직 채용")).json()["results"] == []


@pytest.mark.parametrize("data,status,code", [({"code": 2, "message": "x"}, 200, "api_key_invalid"), ({"code": 4}, 200, "http_429"), ({"unknown": 1}, 200, "structure_changed"),
                                              ({}, 503, "http_503"), (httpx.ConnectError(f"https://oapi.saramin.co.kr/?access-key={KEY}"), 200, "connect_error")])
def test_api_failures_are_reported_without_the_key(env, data, status, code):
    s = source(env, "saramin_api")
    answer(env, data, status)
    t = run_task(env, "career", "opportunity_discovery").json()
    assert t["output"]["sources"][0]["error"] == code
    row = get_one(env.store, "discovery_sources", id=s["id"])
    assert code in row["last_error"] and KEY not in str(row) and KEY not in str(env.store.select("admin_notifications")[0])


def test_apis_belong_to_the_career_desk_and_settings_are_checked(env):
    for body, code in ((dict(agent_id="events"), 422), (dict(config={"access-key": "x"}), 422)):
        r = env.client.post("/api/v1/admin/discovery/sources", headers=env.auth("admin"), json=dict(agent_id="career", name="API x", kind="saramin_api", url="https://x.example/") | body)
        assert r.status_code == code, r.text


def test_the_catalogue_is_valid_allowlisted_and_added_by_an_administrator(env):
    from app.core.constants import CATEGORY_SLUGS
    from app.services.agents.tasks import DISCOVERY_AGENTS

    assert env.client.get("/api/v1/admin/discovery/catalog", headers=env.auth("student")).status_code == 403
    items = env.client.get("/api/v1/admin/discovery/catalog", headers=env.auth("admin")).json()["items"]
    assert len(items) >= 23 and {i["agent_id"] for i in items} == set(DISCOVERY_AGENTS) and not any(i["added"] for i in items)
    assert all(i["category"] in CATEGORY_SLUGS and (i["validated"]["status"] == "ok" or i["needs"]) for i in items)
    for i in items:
        r = env.client.post("/api/v1/admin/discovery/sources", headers=env.auth("admin"), json={k: i[k] for k in ("agent_id", "name", "kind", "url", "category", "language", "config")})
        assert r.status_code == 201, (i["name"], r.text)
    again = env.client.get("/api/v1/admin/discovery/catalog", headers=env.auth("admin")).json()["items"]
    assert all(i["added"] for i in again) and [i["ready"] for i in again if i["needs"]] == [False, False, False]   # 3 keys


# ------------------------------------------------------------------ 고용24 (Work24) OPEN-API: XML, field names from the official page
def work24_xml(*wanted: str) -> bytes:
    return ("<?xml version='1.0' encoding='UTF-8'?><wantedRoot><total>3</total><startPage>1</startPage><display>50</display>"
            + "".join(wanted) + "</wantedRoot>").encode()


def wanted(no: str, title: str, close: str, url: str = "https://www.work24.go.kr/wk/a/b/1500/empDetailAuthView.do?wantedAuthNo=K1") -> str:
    return (f"<wanted><wantedAuthNo>{no}</wantedAuthNo><company>(주)아산글로벌</company><title>{title}</title>"
            f"<salTpNm>시급</salTpNm><sal>10,320원</sal><region>충남 아산시</region><holidayTpNm>주5일근무</holidayTpNm>"
            f"<minEdubg>학력무관</minEdubg><career>신입</career><regDt>{D(-2)[2:]}</regDt><closeDt>{close}</closeDt>"
            f"<wantedInfoUrl>{url}</wantedInfoUrl></wanted>")


def work24(env, body: bytes, status: int = 200) -> list[httpx.Request]:  # type: ignore[no-untyped-def]
    seen: list[httpx.Request] = []

    def h(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(status, content=body, headers={"content-type": "application/xml"})

    env.app.state.services.discovery.connectors.api_http = httpx.Client(transport=httpx.MockTransport(h))
    env.settings.work24_auth_key = KEY
    return seen


def test_work24_without_a_key_is_blocked_and_sends_nothing(env):
    source(env, "work24_api")
    seen = work24(env, work24_xml())
    env.settings.work24_auth_key = ""
    t = run_task(env, "career", "opportunity_discovery").json()
    assert t["output"]["sources"][0]["error"] == "api_key_missing" and seen == []


def test_work24_postings_become_private_candidates_with_honest_deadlines(env, caplog):
    s = source(env, "work24_api", keywords="외국인")
    assert s["url"] == "https://www.work24.go.kr/"
    seen = work24(env, work24_xml(
        wanted("K1", "외국인 유학생 통역 아르바이트", D(10)[2:]),                      # yy-mm-dd, as Work24 writes it
        wanted("K2", "영어 가능 글로벌 마케팅 인턴", "채용시까지"),                      # no date: deadline unknown
        wanted("K3", "중국어 상담원", D(5), url="https://evil.example/x"),
        wanted("K4", "생산직 사원", D(5))))                                            # not relevant to international students
    t = run_task(env, "career", "opportunity_discovery").json()
    items = {i["title"]: i for i in t["output"]["items"]}
    assert set(items) == {"[채용] (주)아산글로벌 외국인 유학생 통역 아르바이트", "[채용] (주)아산글로벌 영어 가능 글로벌 마케팅 인턴",
                          "[채용] (주)아산글로벌 중국어 상담원"}
    assert items["[채용] (주)아산글로벌 외국인 유학생 통역 아르바이트"]["next_deadline"] == D(10)
    assert items["[채용] (주)아산글로벌 영어 가능 글로벌 마케팅 인턴"]["next_deadline"] is None     # never "open until" a guessed date
    assert items["[채용] (주)아산글로벌 중국어 상담원"]["href"] == "https://www.work24.go.kr/"        # foreign links are not shown
    q = seen[0].url
    assert q.host == "www.work24.go.kr" and q.scheme == "https" and q.params["callTp"] == "L" and q.params["regDate"] == "W-1"
    assert q.params["keyword"] == "외국인" and len(seen) == 1
    row = next(r for r in env.store.select("discovered_items")[0] if "마케팅" in r["title"])
    assert "채용 시까지" in (row["text_excerpt"] or "") and row["open_status"] != "open"   # labelled, not "open"
    stored = str(env.store.select("discovered_items")[0]) + str(env.store.select("agent_task_events")[0])
    assert KEY not in stored and KEY not in caplog.text
    # nothing is visible to students before an administrator approves it
    assert env.client.post("/api/v1/agents/career/tools", headers=env.auth("student"),
                           json=dict(tool="opportunity_search", params={"kind": "job"})).json()["result"]["items"] == []


@pytest.mark.parametrize("body,code", [
    (b"<?xml version='1.0'?><!DOCTYPE x [<!ENTITY a 'aaaa'>]><wantedRoot>&a;</wantedRoot>", "invalid_answer"),
    (b"<error><message>\xec\x9d\xb8\xec\xa6\x9d\xed\x82\xa4 \xec\x98\xa4\xeb\xa5\x98</message></error>", "api_key_invalid"),
    (b"<result><code>x</code></result>", "structure_changed"),
    (b"not xml at all", "invalid_answer")])
def test_work24_bad_answers_are_refused_without_leaking_the_key(env, body, code):
    s = source(env, "work24_api")
    work24(env, body)
    t = run_task(env, "career", "opportunity_discovery").json()
    assert t["output"]["sources"][0]["error"] == code
    assert KEY not in str(get_one(env.store, "discovery_sources", id=s["id"]))
