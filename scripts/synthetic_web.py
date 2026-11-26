"""A synthetic copy of the official websites the agents read, for local staging and browser journeys without real data.

    from synthetic_web import transport
    GuardedFetcher(settings, transport=transport(), resolver=lambda host: ["93.184.216.34"])

Same markup as the real sites (the fixtures of backend/tests/test_phase2.py and test_discovery.py: sgee.sch.ac.kr notice boards,
home.sch.ac.kr boards, studyinkorea.go.kr pages); every text is invented and says so ("합성 시험 데이터"). Dates are relative to today,
so deadlines stay open. Anything else answers 404: nothing leaves the computer.
"""
from __future__ import annotations

from datetime import date, timedelta
from urllib.parse import parse_qs, urlsplit

import httpx

MARK = "※ 이 공지는 시험용 합성 데이터입니다. 실제 순천향대학교 공지가 아닙니다."


def _d(days: int) -> date:
    return date.today() + timedelta(days=days)


def _md(days: int) -> str:
    x = _d(days)
    return f"{x.month}/{x.day}"


def _ko(days: int) -> str:
    x = _d(days)
    return f"{x.year}. {x.month}. {x.day}."


#: sgee.sch.ac.kr boards by table_name: (no, title, published offset in days, body html)
SGEE = {
    "noti_fore": [
        (9101, "[생활관] (합성) 동계방학 생활관 입사생 모집 안내", -2,
         f"<p>거주 생활관: 글로벌빌리지</p><p>신청 기간: {_ko(-1)} ~ {_ko(9)} 까지 포털에서 신청</p>"
         "<p>생활관비: 1일 12,000원, 최소 10일 이상 신청</p><p>입사일: 방학 시작일</p>"),
        (9102, "[중요] (합성) 외국인 유학생 시간제 취업 허가 안내", -5,
         "<p>시간제 취업은 허가를 받은 뒤에만 할 수 있습니다. 허가 없이 일하면 불법 취업입니다.</p>"),
        (9103, "[행사] (합성) 유학생 문화 체험 프로그램 참가자 모집", -8,
         f"<p>대상: 본교 외국인 유학생</p><p>신청 마감: {_ko(6)} 까지</p><p>참가비: 무료</p>"),
    ],
    "over_sea": [
        (9201, f"[채용] (합성) 외국인 유학생 통역 보조 아르바이트 채용 (~{_md(7)})", -1,
         f"<p>근무: 주 2회 오후, 시간제 취업 허가 필요</p><p>시급: 11,000원</p><p>지원 마감: {_ko(7)} 까지 이메일 접수</p>"),
        (9202, "[안내] (합성) 시간제 취업 신청 서류 안내", -6, "<p>신청서, 재학증명서, 성적증명서를 제출합니다.</p>"),
    ],
    "noti_school": [(9301, "[입학] (합성) 외국인 신입생 서류 제출 안내", -3, f"<p>제출 마감: {_ko(10)} 까지</p>")],
    "noti_sflec": [(9401, "[강좌] (합성) TOPIK 대비 특강 수강생 모집", -4, f"<p>모집 기간: {_ko(-1)} ~ {_ko(8)}</p><p>수강료: 무료</p>")],
    "": [(9501, "[일반] (합성) 국제교육교류처 행사 안내", -2, f"<p>일시: {_ko(12)} 14:00</p><p>장소: 학생회관</p>")],
}
#: home.sch.ac.kr boards by page: (article_no, title, offset, body)
HOME = {
    "/sch/06/010100.jsp": [(501, "(합성) 대학 공지: 겨울방학 도서관 운영 안내", -2, "<p>방학 중 도서관은 09:00~18:00 운영합니다.</p>")],
    "/sch/06/010200.jsp": [(601, "(합성) 동계 계절학기 수강신청 안내", -3,
                            f"<p>수강신청 기간: {_ko(2)} ~ {_ko(4)}</p><p>수강료: 학점당 80,000원</p>")],
    "/sch/06/010300.jsp": [(701, f"[장학] (합성) 동계 근로장학생 신청 안내 (~{_md(5)})", -1,
                            f"<p>지원 자격: 직전 학기 평점 2.5 이상 재학생</p><p>신청 기간: {_ko(-1)} ~ {_ko(5)} 까지</p>"
                            "<p><a href='https://forms.gle/synthetic'>온라인 신청</a></p>"),
                           (702, "(합성) 학자금 중복지원 방지 안내", -10, "<p>등록금을 넘는 장학금은 반환해야 합니다.</p>")],
    "/sch/06/020000.jsp": [(801, f"[채용] (합성) 교내 행정 인턴 채용 (~{_md(9)})", -2, f"<p>지원 마감: {_ko(9)}</p>")],
}
SIK_PAGES = {
    "/ko/plan/visaAndStay.do": "<h2>(합성) 학생비자 및 체류자격</h2><p>D-2 체류기간 연장은 만료 전에 신청합니다. 수수료와 서류는 출입국 안내를 따릅니다.</p>",
    "/ko/life/residenceAndStayInfo.do": "<h2>(합성) 거주 자격</h2><p>체류지를 옮기면 신고해야 합니다.</p>",
    "/ko/plan/examAndKoreanStudy.do": "<h2>(합성) TOPIK</h2><p>TOPIK 시험은 연 여러 차례 시행됩니다.</p>",
    "/ko/plan/scholarship.do": "<h2>(합성) GKS 장학금</h2><h3>지원 자격</h3><p>국적: 대한민국 국적이 아닌 자</p>",
    "/ko/work/aboutForeignerEmploymentSystem.do": "<h2>(합성) 외국인 유학생 취업제도</h2><p>졸업 후 구직 비자를 신청할 수 있습니다.</p>",
}


def _sgee_board(table: str, loc: str) -> str:
    rows = "".join(
        f'<tr><td class="w_cell">{no}</td><td class="subject"><a href="/notice/notice01.php?admin_mode=read&no={no}&make=&search=&type='
        f'&loc_mnu={loc}&table_name={table}&page=1"> {title}</a></td><td class="w_cell">국제교육교류처</td><td>{_d(off).isoformat()}</td>'
        '<td class="w_cell">10</td></tr>' for no, title, off, _b in SGEE.get(table, []))
    return f"<html><body><table><thead><tr><th>번호</th></tr></thead><tbody>{rows}</tbody></table></body></html>"


def _sgee_notice(title: str, off: int, body: str) -> str:
    return (f"<html><body><div class='view_tit'><h3 class='v_tit'>{title}</h3></div><p class='click_count'>조회수 : 7</p>"
            f"<table class='board-view'><tbody><tr><th>작성일</th><td>{_d(off).strftime('%Y.%m.%d')}</td><th>작성자</th><td>국제교육교류처</td></tr>"
            f"<tr><td class='view_td' colspan='4'>{body}<p>{MARK}</p></td></tr></tbody></table></body></html>")


def _home_board(path: str) -> str:
    rows = "".join(
        f'<tr><td class="seq">{no}</td><td class="subject"><a href="?mode=view&amp;article_no={no}&amp;board_wrapper='
        f'{path.replace("/", "%2F")}&amp;pager.offset=0&amp;board_no=9"> {title} </a></td><td class="writer"><span>작성자:</span> 학생지원팀</td>'
        f'<td class="date"><span>날짜:</span> {_d(off).isoformat()}</td></tr>' for no, title, off, _b in HOME[path])
    return f"<html><body><table><tbody>{rows}</tbody></table></body></html>"


def _home_article(title: str, off: int, body: str) -> str:
    return (f"<html><head><title>{title}</title></head><body><div class='board_view'><div class='board_title'>작성자 : 학생지원팀 - 등록일 : "
            f"{_d(off).isoformat()} - 조회수 : 3</div><div class='board_contents'><h3>{title}</h3>{body}<p>{MARK}</p></div></div></body></html>")


def respond(request: httpx.Request) -> httpx.Response:
    u = urlsplit(str(request.url))
    q = {k: v[0] for k, v in parse_qs(u.query).items()}
    html = None
    if u.path.endswith("/robots.txt"):
        return httpx.Response(404)
    if u.hostname == "sgee.sch.ac.kr" and u.path == "/notice/notice01.php":
        table = q.get("table_name", "")
        if q.get("admin_mode") == "read":
            hit = next((n for n in SGEE.get(table, []) if str(n[0]) == q.get("no")), None)
            html = _sgee_notice(hit[1], hit[2], hit[3]) if hit else None
        elif table in SGEE:
            html = _sgee_board(table, q.get("loc_mnu", "1"))
    elif u.hostname == "sgee.sch.ac.kr":
        html = f"<html><body><main id='contents'><h2>(합성) {u.path}</h2><p>{MARK}</p></main></body></html>"
    elif u.hostname == "home.sch.ac.kr" and u.path in HOME:
        if q.get("mode") == "view":
            hit = next((n for n in HOME[u.path] if str(n[0]) == q.get("article_no")), None)
            html = _home_article(hit[1], hit[2], hit[3]) if hit else None
        else:
            html = _home_board(u.path)
    elif u.hostname == "home.sch.ac.kr" and u.path == "/sch/05/010000.jsp":
        html = f"<html><body><div class='board_contents'><h2>(합성) 학사일정</h2><p>기말고사: {_ko(14)} ~ {_ko(18)}</p><p>{MARK}</p></div></body></html>"
    elif u.hostname == "www.studyinkorea.go.kr" and u.path in SIK_PAGES:
        html = f"<html><head><title>(합성) Study in Korea</title></head><body><main id='contents'>{SIK_PAGES[u.path]}<p>{MARK}</p></main></body></html>"
    if html is None:
        return httpx.Response(404, text="synthetic web: not found")
    return httpx.Response(200, content=html.encode(), headers={"content-type": "text/html; charset=utf-8"})


def transport() -> httpx.MockTransport:
    return httpx.MockTransport(respond)
