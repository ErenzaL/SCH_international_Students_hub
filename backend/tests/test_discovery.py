"""AI Office Phase 3: official-source discovery. Connectors (SCH board, listings, watched pages, PDFs), extraction,
change detection, deduplication, source validation, inaccessible sites, admin-only checks, review candidates,
send-to-review through the normal pipeline, schedules (disabled), worker recovery and student-visible results.

Fixtures copy the markup of the real sites (sgee.sch.ac.kr notice boards, studyinkorea.go.kr lists) with synthetic
text. The live check against the real sites is tests/integration/test_discovery_live.py (opt-in)."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from app.services.discovery.connectors import canonical, validate_config
from app.services.discovery.extract import analyse, application_links, classify, eligibility_lines
from tests.test_phase2 import BOARD, board_html, notice_html, notice_url

TODAY = date.today()
Y = TODAY.year
D = lambda days: (TODAY + timedelta(days=days)).isoformat()  # noqa: E731
SIK_LIST = "https://www.studyinkorea.go.kr/ko/notice/scholarshipsList.do?boardSort=3"
SIK_PAGE = "https://www.studyinkorea.go.kr/ko/plan/scholarship.do"
LINKED_LIST = "https://www.studyinkorea.go.kr/ko/notice/programs.do"


def sik_list_html(items: list[tuple[str, str]]) -> str:
    """Study in Korea list markup: items open through noticeRead(...) (no URL of their own)."""
    rows = "".join(
        f'<a class="board-text-item" href="javascript:void(0)" onclick="noticeRead(\'{4500 + i}\', \'BBS\')">'
        f'<span class="num">{90 - i}</span><div class="text-wrap"><div class="title-box"><p class="title">{t}</p></div>'
        f'<div class="info-box"><span class="writer">webmaster</span><span class="date">{d}</span></div></div></a>'
        for i, (t, d) in enumerate(items))
    return f"<html><body><div class='board-items'>{rows}</div></body></html>"


GKS_PAGE = (
    "<html><head><title>장학금 | Plan your studies | Study in Korea</title></head><body><main><h2>GKS 장학금</h2>"
    "<h3>지원 자격</h3><p>국적: 지원자와 부모 모두 대한민국 국적이 아닌 자</p><p>학력: 고등학교 졸업자 또는 졸업 예정자</p>"
    "<a href=\"javascript:showNotificationModal('접수 기간이 아닙니다.');\">GKS 학부장학금 신청하기</a>"
    "<a href='/public/v3/download/gks_undergraduate_user_guide.pdf'>지원자 가이드</a>"
    "<p>정부초청 외국인 장학생 프로그램은 대한민국 정부가 외국인 우수 인재를 초청하는 프로그램입니다. 학위과정 전체를 지원합니다.</p>"
    "</main></body></html>")


def linked_list_html(items: list[tuple[str, str, str]]) -> str:
    rows = "".join(f"<li class='item'><a href='{u}'>{t}</a> <span class='date'>{d}</span></li>" for t, u, d in items)
    return f"<html><body><ul class='list'>{rows}<li class='item'><a href='https://evil.example.com/x'>Off-site</a></li></ul></body></html>"


def program_page(title: str, body: str) -> str:
    return f"<html><head><title>{title}</title></head><body><article><h1>{title}</h1>{body}</article></body></html>"


def admin_source(env, **kw):  # type: ignore[no-untyped-def]
    body = dict(agent_id="announcement", name="SCH international notices", kind="sch_board",
                url="https://sgee.sch.ac.kr/notice/notice01.php?table_name=noti_fore&loc_mnu=3",
                config={"max_items": 3}) | kw
    r = env.client.post("/api/v1/admin/discovery/sources", headers=env.auth("admin"), json=body)
    assert r.status_code == 201, r.text
    return r.json()


def board(env, notices):  # type: ignore[no-untyped-def]
    url = "https://sgee.sch.ac.kr/notice/notice01.php?table_name=noti_fore&loc_mnu=3"
    env.page(url, board_html([(no, t, d, False) for no, (t, d, _b) in notices.items()]))
    env.page(BOARD, board_html([(no, t, d, False) for no, (t, d, _b) in notices.items()]))
    for no, (t, d, b) in notices.items():
        env.page(notice_url(no), notice_html(t, d.replace("-", "."), b))


NOTICES = {
    6801: ("[장학] 2027-1학기 외국인 유학생 성적우수 장학금 신청 안내", D(-2),
           f"<p>지원 자격: 직전 학기 평점 3.5 이상 외국인 유학생</p><p>신청 기간: {D(-1).replace('-', '. ')}. ~ {D(12).replace('-', '. ')}. 까지</p>"
           "<p><a href='https://forms.gle/abcd'>온라인 신청서 작성</a></p>"),
    6802: ("[공모전] 외국인 유학생 한국어 말하기 대회 참가자 모집", D(-1),
           "<p>대상: 국내 대학 재학 외국인 유학생</p><p>상금: 100만 원</p>"),
    6803: ("[생활관] 방학 중 짐 보관 안내", D(-3), "<p>방학 중 교내에 개인 짐을 보관할 수 없습니다.</p>"),
}


def run_task(env, agent, task_type, params=None, role="admin"):  # type: ignore[no-untyped-def]
    r = env.client.post(f"/api/v1/agents/{agent}/tasks", json=dict(task_type=task_type, params=params or {}),
                        headers=env.auth(role))
    if r.status_code != 201:
        return r
    return env.client.get(f"/api/v1/agent-tasks/{r.json()['id']}", headers=env.auth(role))


# =================================================================================== extraction
def test_extraction_quotes_deadlines_eligibility_and_application_links():
    text = (f"지원 자격\n직전 학기 평점 3.5 이상\n신청 기간: {Y}. 3. 2. ~ {Y + 1}. 1. 20. 까지\n"
            "자세한 내용은 첨부를 참고하세요.")
    f = analyse("[장학] 성적우수 장학금 신청 안내", text, published_on=f"{Y}-03-01",
                links=[{"text": "온라인 신청서", "href": "https://forms.gle/x"}, {"text": "홈", "href": "https://sch.ac.kr"},
                       {"text": "신청", "href": "javascript:alert(1)"}], today=date(Y, 3, 5))
    assert f["category"] == "scholarships" and f["opportunity_kind"] == "scholarship"
    assert f["next_deadline"] == f"{Y + 1}-01-20" and f["open_status"] == "open" and f["open_reason"] == "deadline_in_future"
    assert f["eligibility"] == ["지원 자격: 직전 학기 평점 3.5 이상"]
    assert [x["url"] for x in f["application_links"]] == ["https://forms.gle/x"]       # javascript: never kept
    assert f["flags"] == []


def test_open_only_when_the_source_supports_it():
    t = date(Y, 6, 1)
    passed = analyse("장학금 신청 안내", f"신청 마감: {Y}-05-20 까지", published_on=f"{Y}-05-01", today=t)
    assert passed["open_status"] == "closed" and passed["open_reason"] == "deadline_passed"
    says_closed = analyse("GKS 장학금", f"접수 기간이 아닙니다.\n마감 {Y}-12-01 까지", published_on=None, today=t)
    assert says_closed["open_status"] == "closed" and says_closed["open_reason"] == "source_says_closed"
    nothing = analyse("장학금 안내", "장학금 제도를 소개합니다.", published_on=f"{Y}-05-01", today=t)
    assert nothing["open_status"] == "unknown" and "missing_deadline" in nothing["flags"]
    # a date without a year: open is marked uncertain
    guessed = analyse("[모집] 글로벌 서포터즈 모집 (~12/6)", "많은 지원 바랍니다.", published_on=f"{Y}-06-01", today=t)
    assert guessed["open_status"] == "open" and {"year_assumed", "open_status_uncertain"} <= set(guessed["flags"])


def test_regressions_from_the_live_sch_boards():
    """Titles and phrasing seen on home.sch.ac.kr / sgee.sch.ac.kr on 2026-11-24."""
    t = date(Y, 11, 24)
    # "접수 마감: 11/27" states the deadline; it does not mean the application has closed
    f = analyse("[학점교류] 동계학기 학점교류 신청안내(~11/27)", f"접수 마감: {Y}. 11. 27.(목) 17:00", published_on=f"{Y}-11-23",
                today=t)
    assert f["open_status"] == "open" and f["next_deadline"] == f"{Y}-11-27"
    gone = analyse("근로장학생 모집", "신청이 마감되었습니다.", published_on=f"{Y}-11-01", today=t)
    assert gone["open_status"] == "closed" and gone["open_reason"] == "source_says_closed"
    # an office name in brackets is not what the notice offers
    assert classify("[대학일자리플러스센터] 산업체 특강 홍보 요청", "")["opportunity_kind"] is None
    assert classify("[국제교육교류처] 2027년 교환학생 선발 안내", "")["opportunity_kind"] == "program"
    assert classify("[채용공고] 사업단 행정직원(계약직) 모집 (~11/30)", "")["opportunity_kind"] == "job"
    assert classify("[(재)인천인재평생교육진흥원] 대학생 기업 탐방 모집", "")["opportunity_kind"] is None


def test_short_range_ends_inherit_year_and_month():
    from app.services.agents.tools import extract_dates

    ds = extract_dates(f"신청 기간: {Y}. 11. 23.(월) ~ 11. 29.(일) 17:00까지")
    assert [(d["date"], d["kind"], d["year_assumed"]) for d in ds] == [
        (f"{Y}-11-23", "period_start", False), (f"{Y}-11-29", "deadline", False)]
    ds = extract_dates("근로장학생 희망근로지 신청 안내 (11/23~29 신청)", default_year=Y)
    assert [(d["date"], d["kind"]) for d in ds] == [(f"{Y}-11-23", "period_start"), (f"{Y}-11-29", "deadline")]
    assert extract_dates("접수: 11/28~2", default_year=Y)[-1]["date"] == f"{Y}-12-02"         # into the next month
    assert extract_dates(f"모집 기간 {Y}.12.28 ~ {Y + 1}.1.5")[-1]["date"] == f"{Y + 1}-01-05"
    assert extract_dates("평점 3.5 이상, 1/2 학기 이수자") == []                                  # not dates
    f = analyse("[학생신청용] 동계방학 근로장학생 신청 안내 (11/23~29 신청)", "", published_on=f"{Y}-11-18",
                today=date(Y, 11, 24))
    assert f["open_status"] == "open" and f["next_deadline"] == f"{Y}-11-29"


def test_incorrect_and_missing_dates_are_flagged():
    t = date(Y, 6, 1)
    f = analyse("장학금 신청", f"신청 마감: {Y}-04-01 까지", published_on=f"{Y}-05-01", today=t)
    assert "deadline_before_published" in f["flags"]
    f = analyse("장학금 신청", "내용", published_on=f"{Y + 1}-01-01", today=t)
    assert "published_in_future" in f["flags"]
    f = analyse("장학금 신청", f"신청 마감: {Y}.02.30 까지", published_on=None, today=t)   # impossible date ignored
    assert f["deadlines"] == [] and "missing_published_date" in f["flags"]
    f = analyse("장학금", "", published_on=f"{Y}-05-01", today=t)
    assert "little_text" in f["flags"]


def test_classification_is_explainable_and_title_first():
    c = classify("[공모전] 한국어 말하기 대회", "비자 소지자 누구나")
    assert c["opportunity_kind"] == "competition" and c["kind_reason"] == "공모전" and c["category"] == "topik-korean"
    assert classify("[생활관] 동계방학 입사생 모집", "")["opportunity_kind"] is None    # an application, not an opportunity
    assert classify("Notice on GKS invitation letters", "")["category"] == "scholarships"
    assert classify("Campus festival", "")["category"] == "university-announcements"


def test_multilingual_eligibility_and_links():
    assert eligibility_lines("Eligibility: undergraduate international students\nOther") == [
        "Eligibility: undergraduate international students"]
    assert eligibility_lines("Đối tượng: sinh viên quốc tế") == ["Đối tượng: sinh viên quốc tế"]
    links = application_links([{"text": "Apply now", "href": "https://example.org/a"}],
                              [{"name": "신청서 양식.hwp", "url": "https://sgee.sch.ac.kr/lib/download.php?f=1"}])
    assert [x["kind"] for x in links] == ["link", "attachment"]


def test_canonical_urls_and_connector_config_validation():
    assert canonical("HTTPS://Example.ORG/a?b=1&utm_source=x#frag") == "https://example.org/a?b=1"
    with pytest.raises(Exception, match="item_selector"):
        validate_config("listing", SIK_LIST, {})
    with pytest.raises(Exception, match="Unknown connector settings"):
        validate_config("listing", SIK_LIST, {"item_selector": "a", "script": "x"})
    with pytest.raises(Exception, match="valid CSS"):
        validate_config("listing", SIK_LIST, {"item_selector": "a[[["})
    with pytest.raises(Exception, match="notice01"):
        validate_config("sch_board", SIK_LIST, {})
    assert validate_config("listing", SIK_LIST, {"item_selector": "a", "max_items": 999})["max_items"] == 30
    # per-source pace: never faster than 1 s, at most 10 s
    assert validate_config("listing", SIK_LIST, {"item_selector": "a", "delay_seconds": 0.1})["delay_seconds"] == 1.0
    assert validate_config("listing", SIK_LIST, {"item_selector": "a", "delay_seconds": 60})["delay_seconds"] == 10.0
    # the same article linked from page 1 and page 2 of a board is one item
    a = "https://home.sch.ac.kr/sch/06/010300.jsp?mode=view&article_no=1&pager.offset=0&board_no=9"
    b = "https://home.sch.ac.kr/sch/06/010300.jsp?mode=view&article_no=1&pager.offset=10&board_no=9"
    assert canonical(a) == canonical(b)


def test_home_sch_board_markup_with_pinned_rows(env):
    """home.sch.ac.kr board markup (2026-11-24): rows with td.subject / td.date; pinned rows carry span.notice."""
    url = "https://home.sch.ac.kr/sch/06/010300.jsp"
    def row(no, title, d, pinned=False):  # type: ignore[no-untyped-def]
        seq = '<span class="notice">공지</span>' if pinned else str(no)
        return (f'<tr><td class="seq">{seq}</td><td class="subject"><a href="?mode=view&amp;article_no={no}&amp;board_wrapper='
                f'%2Fsch%2F06%2F010300.jsp&amp;pager.offset=0&amp;board_no=9"> {title} </a></td>'
                f'<td class="writer"><span>작성자:</span> 학생지원팀</td><td class="date"><span>날짜:</span> {d}</td></tr>')
    env.page(url, "<table><tbody>" + row(1, "오래된 고정 공지", "2024-07-18", True) + row(2, f"[장학] 동계 근로장학생 신청 안내 (~{(TODAY + timedelta(days=5)).month}/{(TODAY + timedelta(days=5)).day})", D(-1))
             + row(3, "학자금 중복지원 방지 안내", D(-10)) + "</tbody></table>")
    article = ("<html><body><div class='layer'><ul><li><a href='/sch/promo.jsp'>홍보신청</a></li></ul></div>"
               "<div class='board_view'><div class='board_title'>작성자 : 학생지원팀 - 등록일 : 2026-11-18 - 조회수 : 1048</div>"
               "<div class='board_contents'><p>지원 자격: 재학생</p><p><a href='https://forms.gle/xyz'>온라인 신청</a></p></div>"
               "<div class='board_file'><a href='/download?f=1'>근로장학생 신청서.hwp</a></div></div></body></html>")
    for no in (2, 3):
        env.page(f"{url}?mode=view&article_no={no}&board_wrapper=%2Fsch%2F06%2F010300.jsp&pager.offset=0&board_no=9", article)
    admin_source(env, agent_id="scholarship", name="순천향대학교 장학공지", kind="listing", url=url,
                 config={"item_selector": "table tbody tr", "title_selector": "td.subject a", "date_selector": "td.date",
                         "link_selector": "td.subject a", "skip_selector": "span.notice",
                         "content_selector": "div.board_contents", "attachment_selector": "div.board_file"})
    t = run_task(env, "scholarship", "opportunity_discovery").json()
    titles = [i["title"] for i in t["output"]["items"]]
    assert "오래된 고정 공지" not in titles and len(titles) == 2
    first = next(i for i in t["output"]["items"] if "근로장학생" in i["title"])
    assert first["published_on"] == D(-1) and first["open_status"] == "open" and first["opportunity_kind"] == "scholarship"
    # only the article: the site menu's "홍보신청" and the author / view-count line are not part of the notice
    assert [x["text"] for x in first["application_links"]] == ["온라인 신청", "근로장학생 신청서.hwp"]
    assert "조회수" not in (first["excerpt"] or "") and first["eligibility"] == ["지원 자격: 재학생"]
    assert "pager.offset" not in [r for r in env.store.select("discovered_items")[0] if "근로" in r["title"]][0]["item_key"]


# =================================================================================== source validation
def test_sources_are_admin_only_and_must_be_allowlisted(env):
    body = dict(agent_id="scholarship", name="Somewhere", kind="page", url="https://evil.example.com/s")
    assert env.client.post("/api/v1/admin/discovery/sources", headers=env.auth("student"), json=body).status_code == 403
    r = env.client.post("/api/v1/admin/discovery/sources", headers=env.auth("admin"), json=body)
    assert r.status_code in (400, 422) and "allow" in r.text.lower()
    for bad in ("http://127.0.0.1/x", "http://localhost/x", "file:///etc/passwd", "https://user:pw@sch.ac.kr/x"):
        r = env.client.post("/api/v1/admin/discovery/sources", headers=env.auth("admin"), json=body | {"url": bad})
        assert r.status_code in (400, 422), bad
    s = admin_source(env)
    dup = env.client.post("/api/v1/admin/discovery/sources", headers=env.auth("admin"),
                          json=dict(agent_id="announcement", name="Again", kind="sch_board", url=s["url"]))
    assert dup.status_code == 409
    audit = [a for a in env.store.select("audit_log")[0] if a["action"] == "discovery_source.create"]
    assert len(audit) == 1


# =================================================================================== announcement agent
def test_announcement_agent_finds_new_and_changed_notices_as_review_candidates(env):
    board(env, NOTICES)
    admin_source(env)
    t = run_task(env, "announcement", "announcement_discovery").json()
    assert t["status"] == "completed", t
    out = t["output"]
    assert out["count"] == 3 and out["new_count"] == 3 and all(i["change"] == "new" for i in out["items"])
    sch = next(i for i in out["items"] if "장학금" in i["title"])
    assert sch["href"] == canonical(notice_url(6801)) and sch["published_on"] == D(-2)
    assert sch["next_deadline"] == D(12) and sch["open_status"] == "open" and sch["category"] == "scholarships"
    assert sch["application_links"][0]["url"] == "https://forms.gle/abcd"
    assert sch["reliability"] == "external_unverified" and sch["review_status"] == "candidate"
    assert t["progress"]["sources_done"] == 1 and t["progress"]["sources"][0]["status"] == "ok"
    assert "candidates_need_review" in out["notes"]
    # nothing became knowledge, and nothing is public
    assert env.store.select("source_documents")[0] == [] and env.store.select("announcements")[0] == []
    # the notice changes on the site: the next check reports it as updated (manual re-checks are throttled)
    changed = dict(NOTICES)
    changed[6803] = (NOTICES[6803][0], NOTICES[6803][1], "<p>방학 중 짐 보관 장소가 변경되었습니다.</p>")
    board(env, changed)
    env.store.update("discovery_sources", {"last_checked_at": None}, {})
    t2 = run_task(env, "announcement", "announcement_discovery").json()
    changes = {i["title"][:6]: i["change"] for i in t2["output"]["items"]}
    assert t2["output"]["updated_count"] == 1 and changes["[생활관] "] == "updated"
    assert t2["output"]["items"][0]["change"] == "updated"     # changed first


def test_manual_rechecks_are_throttled(env):
    board(env, NOTICES)
    admin_source(env)
    run_task(env, "announcement", "announcement_discovery")
    before = len(env.requests)
    t = run_task(env, "announcement", "announcement_discovery").json()
    assert len(env.requests) == before                      # no request to the site
    assert t["output"]["sources"][0]["status"] == "recently_checked" and "recently_checked" in t["output"]["notes"]


def test_only_admins_check_official_sources(env):
    board(env, NOTICES)
    admin_source(env)
    r = run_task(env, "announcement", "announcement_discovery", role="student")
    assert r.status_code == 403 and r.json()["error"]["code"] == "admin_only"
    r = env.client.post("/api/v1/agents/announcement/tools", headers=env.auth("student"),
                        json=dict(tool="review_candidates"))
    assert r.status_code == 403
    assert env.client.post("/api/v1/agents/announcement/tools", json=dict(tool="review_candidates")).status_code == 401
    # students do not see admin-only buttons
    items = {a["id"]: a for a in env.client.get("/api/v1/agents", headers=env.auth("student")).json()["items"]}
    assert "check_official_sources" not in {x["id"] for x in items["announcement"]["actions"]}
    admin = {a["id"]: a for a in env.client.get("/api/v1/agents", headers=env.auth("admin")).json()["items"]}
    assert "check_official_sources" in {x["id"] for x in admin["announcement"]["actions"]}
    assert env.client.get("/api/v1/agents", headers=env.auth("admin")).json()["is_admin"] is True


# =================================================================================== inaccessible sites
def test_inaccessible_and_blocked_sites_are_reported_not_hidden(env):
    src = admin_source(env)
    env.pages[src["url"]] = lambda req: httpx.Response(503, text="maintenance")
    t = run_task(env, "announcement", "announcement_discovery").json()
    assert t["status"] == "completed" and t["output"]["sources"][0]["status"] == "failed"
    assert "some_sources_failed" in t["output"]["notes"]
    s = env.client.get("/api/v1/admin/discovery/sources", headers=env.auth("admin")).json()["items"][0]
    assert s["last_status"] == "failed" and s["consecutive_failures"] == 1 and s["last_error"].startswith("http_503")
    # robots.txt disallows: blocked, never bypassed
    env.page("https://sgee.sch.ac.kr/robots.txt", "User-agent: *\nDisallow: /notice/", "text/plain")
    env.app.state.services.ingestion.fetcher._robots.clear()      # robots.txt is re-read (6-hour cache)
    env.store.update("discovery_sources", {"last_checked_at": None}, {})
    run_task(env, "announcement", "announcement_discovery")
    s = env.client.get("/api/v1/admin/discovery/sources", headers=env.auth("admin")).json()["items"][0]
    assert s["last_status"] == "blocked" and s["consecutive_failures"] == 2
    assert not any("notice01.php?admin_mode" in u for u in env.requests)


def test_board_structure_change_fails_loudly(env):
    src = admin_source(env)
    env.page(src["url"], "<html><body><table><tr><td>점검 중</td></tr></table></body></html>")
    t = run_task(env, "announcement", "announcement_discovery").json()
    assert t["output"]["sources"][0]["error"] == "board_structure_changed"


# =================================================================================== scholarship agent
def setup_scholarship_sources(env):  # type: ignore[no-untyped-def]
    env.page(SIK_LIST, sik_list_html([("2027 GKS Undergraduate Program 장학생 선발 안내", D(-20)),
                                      ("GKS Newsletter (October)", D(-40))]))
    env.page(SIK_PAGE, GKS_PAGE)
    env.page(LINKED_LIST, linked_list_html([
        ("2027 Global Korea Summer Camp for international students", "/ko/notice/camp.do", D(-3)),
        ("2027 Global Korea Summer Camp for international students", "/ko/notice/camp.do?utm_source=x", D(-3)),
        ("Startup competition guide (PDF)", "/ko/notice/contest.pdf", D(-5))]))
    env.page("https://www.studyinkorea.go.kr/ko/notice/camp.do", program_page(
        "2027 Global Korea Summer Camp for international students",
        f"<p>Eligibility: international undergraduate students in Korea</p><p>Application deadline: {D(30)}</p>"
        "<p><a href='https://www.studyinkorea.go.kr/apply/camp'>Apply online</a></p>"))
    from tests.test_phase2 import make_pdf

    env.page("https://www.studyinkorea.go.kr/ko/notice/contest.pdf",
             make_pdf([[("International startup competition", 18), (f"Deadline: {Y - 1}-01-10", 11)]]),
             content_type="application/pdf")
    for body in (dict(name="Study in Korea scholarship notices", kind="listing", url=SIK_LIST,
                      config={"item_selector": "a.board-text-item", "title_selector": "p.title", "date_selector": "span.date"}),
                 dict(name="GKS scholarship page", kind="page", url=SIK_PAGE),
                 dict(name="Study in Korea programs", kind="listing", url=LINKED_LIST,
                      config={"item_selector": "li.item", "date_selector": "span.date"})):
        admin_source(env, agent_id="scholarship", **body)


def test_scholarship_agent_discovers_opportunities_with_honest_status(env):
    setup_scholarship_sources(env)
    t = run_task(env, "scholarship", "opportunity_discovery").json()
    assert t["status"] == "completed", t
    items = {i["title"]: i for i in t["output"]["items"]}
    gks = items["2027 GKS Undergraduate Program 장학생 선발 안내"]
    assert gks["opportunity_kind"] == "scholarship" and gks["open_status"] == "unknown"
    assert "no_detail_page" in gks["flags"] and gks["href"] == SIK_LIST          # cites the list it came from
    page = items["GKS scholarship page"]
    assert page["open_status"] == "closed" and page["open_reason"] == "source_says_closed"
    assert page["eligibility"][0].startswith("지원 자격: 국적")
    camp = items["2027 Global Korea Summer Camp for international students"]
    assert camp["open_status"] == "open" and camp["next_deadline"] == D(30) and camp["opportunity_kind"] == "program"
    assert camp["application_links"][0]["url"] == "https://www.studyinkorea.go.kr/apply/camp"
    pdf = items["Startup competition guide (PDF)"]
    assert pdf["open_status"] == "closed" and pdf["opportunity_kind"] == "competition"   # read from the PDF
    # dedupe: the same camp page twice (tracking parameter) is one item; the off-site link was never followed
    assert sum(1 for i in t["output"]["items"] if "Summer Camp" in i["title"]) == 1
    assert not any("evil.example.com" in u for u in env.requests)
    assert t["progress"]["sources_total"] == 3 and t["progress"]["sources_done"] == 3


def test_students_see_only_reviewed_and_approved_discoveries(env):
    from tests.test_agents import publish

    setup_scholarship_sources(env)
    run_task(env, "scholarship", "opportunity_discovery")
    publish(env)                                                                    # a Hub-approved scholarship
    camp_title = "2027 Global Korea Summer Camp for international students"

    def search(role=None):  # type: ignore[no-untyped-def]
        return env.client.post("/api/v1/agents/scholarship/tools", json=dict(tool="opportunity_search"),
                               headers=env.auth(role) if role else {}).json()["result"]

    # admins see the unreviewed candidates, labelled unverified (closed ones hidden by default)
    staff = search("admin")
    titles = [i["title"] for i in staff["items"]]
    assert camp_title in titles
    assert "GKS scholarship page" not in titles and "Startup competition guide (PDF)" not in titles
    assert all(i["reliability"] == "external_unverified" for i in staff["items"])
    assert "open_only_when_stated" in staff["notes"]
    # visitors and students: nothing unreviewed at all
    for role in (None, "student", "supporter"):
        out = search(role)
        assert out["items"] == [] and out["notes"] == ["no_reviewed_discoveries"], role
    r = env.client.post("/api/v1/agents/scholarship/tasks", json=dict(task_type="scholarship_scan"),
                        headers=env.auth("student"))
    t = env.client.get(f"/api/v1/agent-tasks/{r.json()['id']}", headers=env.auth("student")).json()
    o = t["output"]
    assert o["verified_count"] == 1 and o["unverified_count"] == 0
    assert all(i["reliability"] == "verified" for i in o["items"])
    assert len(o["sources"]) == 3 and all(s["last_checked_at"] for s in o["sources"])
    assert t["events"] and not any(e["tool"] == "official_source_check" for e in t["events"])   # no crawling

    # sent to review: still hidden while the Knowledge Center version waits for approval
    camp = next(i for i in staff["items"] if i["title"] == camp_title)
    assert env.client.post(f"/api/v1/admin/discovery/items/{camp['id']}/send-to-review",
                           headers=env.auth("admin")).status_code == 202
    assert search("student")["items"] == []
    version = next(v for v in env.store.select("document_versions")[0] if v["verification_status"] == "pending_review")
    assert env.client.post(f"/api/v1/admin/versions/{version['id']}/approve", headers=env.auth("admin"),
                           json={}).status_code == 202
    # approved: shown to students as verified, linked to the approved Hub document and the official page
    out = search("student")
    assert [i["title"] for i in out["items"]] == [camp_title]
    item = out["items"][0]
    assert item["reliability"] == "verified" and item["href"].startswith("/knowledge/")
    assert item["official_url"].startswith("https://www.studyinkorea.go.kr/") and "review_status" not in item
    assert "imported_source_id" not in item and "review_note" not in item
    assert out["notes"][0] == "official_reviewed"
    # admins see the same approved item as verified too (and the other candidates as unverified)
    staff = {i["title"]: i for i in search("admin")["items"]}
    assert staff[camp_title]["reliability"] == "verified" and staff[camp_title]["href"] == item["href"]
    assert staff[camp_title]["review_status"] == "imported"
    # once it closes, students are told precisely why the list is empty (and can include closed ones)
    env.store.update("discovered_items", {"open_status": "closed"}, {"id": camp["id"]})
    hidden = search("student")
    assert hidden["items"] == [] and hidden["notes"] == ["reviewed_closed_hidden"]
    shown = env.client.post("/api/v1/agents/scholarship/tools", headers=env.auth("student"), json=dict(
        tool="opportunity_search", params={"include_closed": True})).json()["result"]
    assert [i["title"] for i in shown["items"]] == [camp_title]


def test_dismissed_and_duplicate_items_are_not_shown_to_students(env):
    setup_scholarship_sources(env)
    run_task(env, "scholarship", "opportunity_discovery")
    camp = next(i for i in env.client.get("/api/v1/admin/discovery/items?agent_id=scholarship",
                                          headers=env.auth("admin")).json()["items"] if "Camp" in i["title"])
    assert env.client.post(f"/api/v1/admin/discovery/items/{camp['id']}/dismiss", headers=env.auth("student"),
                           json={}).status_code == 403
    d = env.client.post(f"/api/v1/admin/discovery/items/{camp['id']}/dismiss", headers=env.auth("admin"),
                        json={"note": "not for SCH students"})
    assert d.status_code == 200 and d.json()["review_status"] == "dismissed"
    out = env.client.post("/api/v1/agents/scholarship/tools", json=dict(tool="opportunity_search"),
                          headers=env.auth("admin")).json()["result"]
    assert "Camp" not in " ".join(i["title"] for i in out["items"])


def test_cross_source_duplicates_are_linked(env):
    board(env, NOTICES)
    admin_source(env)
    env.page(LINKED_LIST, linked_list_html([(NOTICES[6802][0], "/ko/notice/speech.do", NOTICES[6802][1])]))
    env.page("https://www.studyinkorea.go.kr/ko/notice/speech.do", program_page(NOTICES[6802][0], "<p>대상: 유학생</p>"))
    admin_source(env, agent_id="scholarship", name="Programs", kind="listing", url=LINKED_LIST,
                 config={"item_selector": "li.item", "date_selector": "span.date"})
    run_task(env, "announcement", "announcement_discovery")
    run_task(env, "scholarship", "opportunity_discovery")
    rows = [r for r in env.store.select("discovered_items")[0] if "말하기" in r["title"]]
    assert len(rows) == 2 and sum(1 for r in rows if r["duplicate_of"]) == 1


# =================================================================================== review -> existing pipeline
def test_send_to_review_uses_the_normal_pipeline_and_publishes_nothing(env):
    board(env, NOTICES)
    admin_source(env)
    run_task(env, "announcement", "announcement_discovery")
    item = next(i for i in env.client.get("/api/v1/admin/discovery/items", headers=env.auth("admin")).json()["items"]
                if "장학금" in i["title"])
    env.page(canonical(notice_url(6801)), notice_html(NOTICES[6801][0], NOTICES[6801][1], NOTICES[6801][2]))
    r = env.client.post(f"/api/v1/admin/discovery/items/{item['id']}/send-to-review", headers=env.auth("admin"))
    assert r.status_code == 202, r.text
    ks = env.store.select("knowledge_sources", )[0]
    assert len(ks) == 1 and ks[0]["source_type"] == "website" and ks[0]["authority_type"] == "official_university"
    versions = env.store.select("document_versions")[0]
    assert versions and all(v["verification_status"] == "pending_review" for v in versions)
    assert env.client.get("/api/v1/knowledge/documents").json()["total"] == 0           # nothing public
    again = env.client.post(f"/api/v1/admin/discovery/items/{item['id']}/send-to-review", headers=env.auth("admin"))
    assert again.status_code == 409


def test_items_without_their_own_page_cannot_be_sent_to_review(env):
    setup_scholarship_sources(env)
    run_task(env, "scholarship", "opportunity_discovery")
    gks = next(i for i in env.client.get("/api/v1/admin/discovery/items", headers=env.auth("admin")).json()["items"]
               if "no_detail_page" in i["flags"])
    r = env.client.post(f"/api/v1/admin/discovery/items/{gks['id']}/send-to-review", headers=env.auth("admin"))
    assert r.status_code == 409 and "manually" in r.json()["error"]["message"]


# =================================================================================== schedules
def test_monitoring_schedules_are_off_and_configurable_by_admins(env):
    env.settings.cron_secret = "s3cret-value"
    board(env, NOTICES)
    src = admin_source(env)
    sched = next(s for s in env.client.get("/api/v1/admin/agent-schedules", headers=env.auth("admin")).json()["items"]
                 if s["task_type"] == "announcement_discovery")
    assert sched["enabled"] is False and sched["params"]["review"] == "admin"
    url = f"/api/v1/admin/agent-schedules/{sched['id']}"
    assert env.client.patch(url, json={"params": {"review": "none"}}, headers=env.auth("admin")).status_code == 422
    assert env.client.patch(url, json={"params": {"source_ids": ["nope"]}}, headers=env.auth("admin")).status_code == 422
    assert env.client.patch(url, json={"params": {"max_items_per_source": 99}}, headers=env.auth("admin")).status_code == 422
    assert env.client.patch(url, json={"params": {"evil": 1}}, headers=env.auth("admin")).status_code == 422
    assert env.client.patch(url, json={"enabled": True}, headers=env.auth("student")).status_code == 403
    r = env.client.patch(url, json={"enabled": True, "params": {"source_ids": [src["id"]], "max_items_per_source": 2}},
                         headers=env.auth("admin"))
    assert r.status_code == 200 and r.json()["params"]["max_items_per_source"] == 2
    cron = lambda: env.client.post("/api/v1/internal/sync/run-due", headers={"X-Cron-Secret": "s3cret-value"})  # noqa: E731
    assert cron().json()["agent_schedules"]["enabled"] is False        # the server switch is still off
    assert env.store.select("discovered_items")[0] == []
    env.settings.agent_schedules_enabled = True
    assert cron().json()["agent_schedules"]["queued"] == 1
    task = next(t for t in env.store.select("agent_tasks")[0] if t["task_type"] == "announcement_discovery")
    assert task["status"] == "completed" and task["requested_by"] is None
    assert len(env.store.select("discovered_items")[0]) == 2           # max_items_per_source from the schedule
    notes = [n for n in env.store.select("admin_notifications")[0] if n["kind"] == "discovery_candidates"]
    assert len(notes) == 1 and "Nothing is published" in notes[0]["message"]


def test_failing_sources_are_skipped_by_schedules_until_reset(env):
    src = admin_source(env)
    env.store.update("discovery_sources", {"consecutive_failures": 5}, {"id": src["id"]})
    svc = env.app.state.services
    out = svc.discovery.check_sources("announcement", scheduled=True)
    assert out["sources_total"] == 0
    env.client.patch(f"/api/v1/admin/discovery/sources/{src['id']}", json={"reset_failures": True},
                     headers=env.auth("admin"))
    assert svc.discovery.get_source(src["id"])["consecutive_failures"] == 0


# =================================================================================== worker recovery
def test_a_discovery_task_of_a_dead_worker_is_recovered(env):
    board(env, NOTICES)
    admin_source(env)
    env.settings.job_execution = "worker"
    svc = env.app.state.services
    svc.jobs.kick = lambda: None
    r = env.client.post("/api/v1/agents/announcement/tasks", json=dict(task_type="announcement_discovery"),
                        headers=env.auth("admin"))
    claimed = svc.agents.claim("dead", 300)
    old = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    env.store.update("agent_tasks", dict(heartbeat_at=old, started_at=old), {"id": claimed["id"]})
    assert svc.jobs.run_once() is True
    t = env.client.get(f"/api/v1/agent-tasks/{r.json()['id']}", headers=env.auth("admin")).json()
    assert t["status"] == "completed" and t["attempts"] == 2 and t["output"]["new_count"] == 3


# =================================================================================== scheduling readiness
def test_failing_sources_back_off_and_alert_admins(env):
    src = admin_source(env)
    env.pages[src["url"]] = lambda req: httpx.Response(503, text="maintenance")
    svc = env.app.state.services.discovery
    for expected in (1, 2):
        env.store.update("discovery_sources", {"last_checked_at": None}, {"id": src["id"]})
        svc.check_sources("announcement", scheduled=True)
        assert svc.get_source(src["id"])["consecutive_failures"] == expected
    # inside the back-off window (2 h after the 2nd failure) a scheduled run skips the source
    assert svc.check_sources("announcement", scheduled=True)["sources_total"] == 0
    s = svc.get_source(src["id"])
    later = (datetime.fromisoformat(s["last_checked_at"]) + timedelta(hours=3)).isoformat()
    assert svc._backing_off(s, datetime.fromisoformat(later)) is False
    env.store.update("discovery_sources", {"last_checked_at": (datetime.now(UTC) - timedelta(hours=3)).isoformat()},
                     {"id": src["id"]})
    svc.check_sources("announcement", scheduled=True)                       # 3rd failure: admins are alerted
    alerts = [n for n in env.store.select("admin_notifications")[0] if n["kind"] == "discovery_source_failing"]
    assert len(alerts) == 1 and alerts[0]["severity"] == "warning" and "3 time(s)" in alerts[0]["message"]
    # robots.txt refusal: alerted at once as an error
    env.page("https://sgee.sch.ac.kr/robots.txt", "User-agent: *\nDisallow: /", "text/plain")
    env.app.state.services.ingestion.fetcher._robots.clear()
    env.store.update("discovery_sources", {"last_checked_at": None, "consecutive_failures": 0}, {"id": src["id"]})
    svc.check_source(svc.get_source(src["id"]), scheduled=True)
    alerts = [n for n in env.store.select("admin_notifications")[0] if n["kind"] == "discovery_source_failing"]
    assert alerts[-1]["severity"] == "error" and "refused" in alerts[-1]["message"]


def test_scheduled_runs_never_duplicate_and_failures_alert(env):
    from app.services.agents import handlers

    env.settings.agent_schedules_enabled = True
    env.settings.job_execution = "worker"           # the first scheduled task stays queued (worker not running)
    env.app.state.services.jobs.kick = lambda: None
    agents = env.app.state.services.agents
    sched = next(s for s in env.store.select("agent_schedules")[0] if s["task_type"] == "announcement_discovery")
    env.store.update("agent_schedules", {"enabled": True}, {"id": sched["id"]})
    assert agents.run_due_schedules()["queued"] == 1
    env.store.update("agent_schedules", {"next_run_at": None}, {"id": sched["id"]})       # due again at once
    agents.run_due_schedules()
    tasks = [t for t in env.store.select("agent_tasks")[0] if t["schedule_id"] == sched["id"]]
    assert len(tasks) == 1                          # the still-queued run is reused, not duplicated
    original = handlers.HANDLERS["announcement_discovery"]
    handlers.HANDLERS["announcement_discovery"] = lambda svc, ctx, task: (_ for _ in ()).throw(ValueError("boom"))
    try:
        claimed = agents.claim("w1", 300)
        agents.execute(claimed)
    finally:
        handlers.HANDLERS["announcement_discovery"] = original
    alerts = [n for n in env.store.select("admin_notifications")[0] if n["kind"] == "agent_schedule_failed"]
    assert len(alerts) == 1 and alerts[0]["severity"] == "error"
    assert env.store.select("agent_schedules", )[0] and next(
        s for s in env.store.select("agent_schedules")[0] if s["id"] == sched["id"])["last_error"].startswith("internal_error")


PUBLIC_MONITORING_KEYS = {"agent_id", "supported", "sources", "schedules", "checking", "last_checked_at",
                          "last_success_at"}
PUBLIC_SCHEDULE_KEYS = {"task_type", "state", "interval_minutes", "last_run_at", "last_success_at", "next_run_at"}


def test_monitoring_status_is_public_but_sanitised(env):
    board(env, NOTICES)
    admin_source(env)
    sid = env.client.get("/api/v1/admin/discovery/sources", headers=env.auth("admin")).json()["items"][0]["id"]
    pub = env.client.get("/api/v1/agents/announcement/monitoring").json()
    assert pub["supported"] and pub["checking"] is False and pub["last_checked_at"] is None
    assert [s["health"] for s in pub["sources"]] == ["not_checked"]
    assert all(s["state"] == "disabled" and s["next_run_at"] is None for s in pub["schedules"])
    run_task(env, "announcement", "announcement_discovery")
    for role in (None, "student", "supporter"):
        out = env.client.get("/api/v1/agents/announcement/monitoring",
                             headers=env.auth(role) if role else {}).json()
        # exact allowlists: anything added later must be a deliberate decision
        assert set(out) == PUBLIC_MONITORING_KEYS, set(out) ^ PUBLIC_MONITORING_KEYS
        assert all(set(s) == PUBLIC_SCHEDULE_KEYS for s in out["schedules"])
        assert all(s["state"] in ("active", "disabled") for s in out["schedules"])
        src = out["sources"][0]
        assert set(src) == {"name", "url", "kind", "health", "last_checked_at", "last_success_at"}
        assert src["health"] == "ok" and out["last_checked_at"]
        assert "candidates_waiting" not in out
        assert all("id" not in s and "params" not in s and "last_error" not in s for s in out["schedules"])
    admin = env.client.get("/api/v1/agents/announcement/monitoring", headers=env.auth("admin")).json()
    assert admin["candidates_waiting"] >= 1 and admin["sources"][0]["consecutive_failures"] == 0
    assert admin["schedules_enabled_on_server"] is False
    # a schedule enabled while the server switch is off: admins see why it does not run, everyone else "disabled"
    sched = next(s for s in admin["schedules"] if s["task_type"] == "announcement_discovery")
    env.client.patch(f"/api/v1/admin/agent-schedules/{sched['id']}", headers=env.auth("admin"), json={"enabled": True})
    assert next(s for s in env.client.get("/api/v1/agents/announcement/monitoring", headers=env.auth("admin")).json()
                ["schedules"] if s["task_type"] == "announcement_discovery")["state"] == "off_on_server"
    assert next(s for s in env.client.get("/api/v1/agents/announcement/monitoring").json()["schedules"]
                if s["task_type"] == "announcement_discovery")["state"] == "disabled"
    assert all("id" in s and "enabled" in s for s in admin["schedules"])
    # a disabled source is not shown publicly; a failing one shows only "attention"
    env.client.patch(f"/api/v1/admin/discovery/sources/{sid}", headers=env.auth("admin"), json={"enabled": False})
    assert env.client.get("/api/v1/agents/announcement/monitoring").json()["sources"] == []
    assert len(env.client.get("/api/v1/agents/announcement/monitoring",
                              headers=env.auth("admin")).json()["sources"]) == 1
    assert env.client.get("/api/v1/agents/nobody/monitoring").status_code == 404
    visa = env.client.get("/api/v1/agents/immigration/monitoring").json()
    assert visa["supported"] is False and visa["sources"] == [] and visa["schedules"] == []


CALENDAR_URL = "https://home.sch.ac.kr/sch/05/010000.jsp"
# the structure of the live academic-calendar page (2026-11-24): the site menu in <header><nav id="gnb2"> contains a
# "홍보신청" (promotion request) link; the calendar is in div#sub_contents > div.schedule-board
CALENDAR_HTML = """<html><body id="item_body"><div id="wrap" class="sub">
<header><section><div id="gnb2"><nav><ul><li class="menu_depth1"><div class="menu_depth2"><ul>
  <li class="menu_depth3"><a href="/sch/01/040100.jsp">대학홍보</a><ul><li><a href="/sch/01/040900.jsp">홍보신청</a></li></ul></li>
</ul></div></li></ul></nav></div></section></header>
<div id="sub_contents"><div id="board_wrap"><div class="jwxe_root schedule-board">
  <a href="?year=2025">이전년도 보기</a><a href="?month=1">1월</a>
  <div class="info"><div class="section month_1 active"><div class="list"><dl><dt>01.05(월) ~ 01.09(금)</dt>
  <dd>2027학년도 1학기 수강신청 기간</dd></dl></div></div></div>
</div></div></div>
<footer><a href="/sch/apply.jsp">입학 신청</a></footer></div></body></html>"""


def test_navigation_and_promotional_links_are_never_application_links(env):
    from app.services.discovery.connectors import anchors
    from app.services.discovery.extract import application_links

    # no selector: the known content region is used and menus / footers are skipped
    links = anchors(CALENDAR_HTML, CALENDAR_URL)
    texts = [x["text"] for x in links]
    assert "홍보신청" not in texts and "대학홍보" not in texts and "입학 신청" not in texts
    assert "1월" in texts
    # even when a page has no content region at all, links inside nav / header / footer / menus are skipped
    bare = CALENDAR_HTML.replace('id="sub_contents"', 'id="x"').replace('schedule-board', 'x')
    assert {x["text"] for x in anchors(bare, CALENDAR_URL)} >= {"1월"}
    assert not {"홍보신청", "입학 신청"} & {x["text"] for x in anchors(bare, CALENDAR_URL)}
    # site services that contain an "apply" word are not applications even inside content
    assert application_links([{"text": "홍보신청", "href": "https://home.sch.ac.kr/a"},
                              {"text": "로그인", "href": "https://home.sch.ac.kr/login"},
                              {"text": "온라인 신청", "href": "https://forms.gle/x"}]) == [
        dict(url="https://forms.gle/x", text="온라인 신청", kind="link")]


def test_watched_page_uses_its_content_selector(env):
    env.page(CALENDAR_URL, CALENDAR_HTML)
    admin_source(env, name="순천향대학교 학사일정", kind="page", url=CALENDAR_URL,
                 config={"content_selector": "div.schedule-board", "max_items": 10})
    run_task(env, "announcement", "announcement_discovery")
    items = env.client.get("/api/v1/admin/discovery/items", headers=env.auth("admin")).json()["items"]
    cal = next(i for i in items if i["url"] == CALENDAR_URL)
    assert cal["application_links"] == []
    assert "수강신청 기간" in cal["excerpt"] and "대학홍보" not in cal["excerpt"]
