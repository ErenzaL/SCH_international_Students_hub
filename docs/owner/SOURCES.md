# Official sources

Generated from `backend/app/services/discovery/catalog.json` by `scripts/env_inventory.py`. 26 prepared sources; **none is active** until an
administrator adds it. "works" = read on the live website with the Hub's own fetcher (allowlist, robots.txt, at least one second between requests).

| Desk | Source | Type | Category | State | Suggested interval |
|---|---|---|---|---|---|
| Robo | [SCH 국제교육교류처 유학생 공지사항](https://sgee.sch.ac.kr/notice/notice01.php?table_name=noti_fore&loc_mnu=3) | sch_board | university-announcements | works (2026-11-25, 3 read) | 168 h |
| Robo | [순천향대학교 공지사항](https://home.sch.ac.kr/sch/06/010100.jsp) | listing | university-announcements | works (2026-11-25, 3 read) | 168 h |
| Robo | [SCH 국제교육교류처 외국인입학 공지사항](https://sgee.sch.ac.kr/notice/notice01.php?table_name=noti_school&loc_mnu=2) | sch_board | university-announcements | works (2026-11-25, 3 read) | 168 h |
| Joon | [순천향대학교 학사공지](https://home.sch.ac.kr/sch/06/010200.jsp) | listing | academic-life | works (2026-11-25, 3 read) | 168 h |
| Joon | [순천향대학교 학사일정](https://home.sch.ac.kr/sch/05/010000.jsp) | page | academic-life | works (2026-11-25, 1 read) | 168 h |
| Joon | [SCH 국제교육교류처 학사/장학 안내](https://sgee.sch.ac.kr/usupport/degree01.php) | page | academic-life | works (2026-11-25, 1 read) | 168 h |
| Leo | [순천향대학교 장학공지](https://home.sch.ac.kr/sch/06/010300.jsp) | listing | scholarships | works (2026-11-25, 3 read) | 168 h |
| Leo | [Study in Korea 장학금 공지](https://www.studyinkorea.go.kr/ko/notice/scholarshipsList.do?boardSort=3) | listing | scholarships | works (2026-11-25, 3 read) | 168 h |
| Leo | [Study in Korea GKS 장학금 안내](https://www.studyinkorea.go.kr/ko/plan/scholarship.do) | page | scholarships | works (2026-11-25, 1 read) | 168 h |
| Daniel | [순천향대학교 취업정보](https://home.sch.ac.kr/sch/06/020000.jsp) | listing | employment-internships | works (2026-11-25, 3 read) | 168 h |
| Daniel | [SCH 국제교육교류처 취업·아르바이트 공지](https://sgee.sch.ac.kr/notice/notice01.php?table_name=over_sea&loc_mnu=5) | sch_board | part-time-employment | works (2026-11-25, 3 read) | 168 h |
| Daniel | [Study in Korea 외국인 유학생 취업제도](https://www.studyinkorea.go.kr/ko/work/aboutForeignerEmploymentSystem.do) | page | employment-internships | works (2026-11-25, 1 read) | 168 h |
| Yuna | [SCH 국제교육교류처 비자 및 체류](https://sgee.sch.ac.kr/usupport/visa01.php) | page | visa-immigration | works (2026-11-25, 1 read) | 168 h |
| Yuna | [SCH 국제교육교류처 시간제 취업](https://sgee.sch.ac.kr/usupport/job01.php) | page | part-time-employment | works (2026-11-25, 1 read) | 168 h |
| Yuna | [SCH 국제교육교류처 의료보험](https://sgee.sch.ac.kr/usupport/insur01.php) | page | health-insurance | works (2026-11-25, 1 read) | 168 h |
| Yuna | [Study in Korea 학생비자 및 체류자격](https://www.studyinkorea.go.kr/ko/plan/visaAndStay.do) | page | visa-immigration | works (2026-11-25, 1 read) | 168 h |
| Yuna | [Study in Korea 거주 자격 및 체류 기간](https://www.studyinkorea.go.kr/ko/life/residenceAndStayInfo.do) | page | visa-immigration | works (2026-11-25, 1 read) | 168 h |
| Yuna | [하이코리아 공지사항](https://www.hikorea.go.kr/board/BoardNtcListR.pt) | page | visa-immigration | works (2026-11-25, 1 read) | 168 h |
| Seo | [Study in Korea 언어 능력 기준 및 TOPIK](https://www.studyinkorea.go.kr/ko/plan/examAndKoreanStudy.do) | page | topik-korean | works (2026-11-25, 1 read) | 168 h |
| Seo | [SCH 한국어교육원 교육과정](https://sgee.sch.ac.kr/edukor/edukor02.php) | page | topik-korean | works (2026-11-25, 1 read) | 168 h |
| Seo | [SCH 외국어강좌 공지사항](https://sgee.sch.ac.kr/notice/notice01.php?table_name=noti_sflec&loc_mnu=4) | sch_board | topik-korean | works (2026-11-25, 3 read) | 168 h |
| Mia | [Study in Korea 소식](https://www.studyinkorea.go.kr/ko/notice/newsList.do?boardSort=1) | listing | university-announcements | works (2026-11-25, 3 read) | 168 h |
| Mia | [SCH 국제교육교류처 일반 공지사항](https://sgee.sch.ac.kr/notice/notice01.php?loc_mnu=1) | sch_board | university-announcements | works (2026-11-25, 3 read) | 168 h |
| Daniel | [공공기관 채용정보 (재정경제부 API)](https://job.alio.go.kr/) | data_go_kr_jobs | employment-internships | **needs DATA_GO_KR_SERVICE_KEY** | 168 h |
| Daniel | [사람인 채용정보 (공식 API)](https://www.saramin.co.kr/) | saramin_api | employment-internships | **needs SARAMIN_ACCESS_KEY** | 168 h |
| Daniel | [고용24 채용정보 (공식 Open API)](https://www.work24.go.kr/) | work24_api | employment-internships | **needs WORK24_AUTH_KEY** | 168 h |

## How to

| Task | Where |
|---|---|
| Add | Admin → Agents → Sources → *Prepared official sources* → Add (or the form below it) |
| Check now | AI Office → the desk → Sources → *Check official sources now* (administrators) |
| Pause one | Admin → Agents → Sources → Turn off. A whole desk: Admin → Agents → Desks → Pause |
| Recognise failures | red "failing" count in Sources; a notification after 3 failures; after 5 the source is skipped until *Reset failures* |
| Review what was found | AI Office → the desk → Review → *Send to review* or *Dismiss*; then Admin → Review Queue → Approve. Only then students and the chat see it |
| Validate again | `cd backend && .venv/bin/python ../scripts/validate_sources.py app/services/discovery/catalog.json --items 2` |
| Switch on a schedule | 1. `AGENT_SCHEDULES_ENABLED=true` on the API service, 2. Admin → Agents → Schedules → on. Both are off |

## Restrictions

- Only domains of *Admin → Settings → Allowed domains* are ever requested; `robots.txt` is respected. `www.sch.ac.kr` forbids automated access and is **not** used.
- Study in Korea lists open their items through a script: only title and date are read (status "unknown"). They are not worked around.
- `topik.go.kr` renders its pages with JavaScript and returns no text: not used. TOPIK information comes from Study in Korea and SCH notices.
- The content belongs to its publisher. The Hub stores text for review and search, quotes it with a link to the original, and keeps the source. If a publisher
  objects, turn the source off and withdraw its documents.
- The same notice found by two desks is stored once (first desk keeps it); events and jobs are shown at Mia's and Daniel's desk whoever found them.
