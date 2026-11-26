# The 14 agents

States: **I** implemented · **T** tested automatically · **L** shown with live official websites or the real model on this computer · staging and production: **not tested**.
Every agent: identity, tools, languages and forbidden actions in `backend/app/services/agents/registry.py` (the server decides; the page only displays); tasks are durable
rows (claim, heartbeat, retry 3×, cancel, timeout 180 s, stale recovery, step log); a desk can be paused; students see only their own tasks; administrators see
metadata, never a student's words.

| Agent | Job | Tools (beyond search, guides, notices, deadlines) | Sources | Starts | Result | Shown | State |
|---|---|---|---|---|---|---|---|
| **Hana** reception | understands, answers, sends to the right desk | delegate | RAG, notices | student | chat with citations; redirect | chat, desks | I T L |
| **Minji** ko | Korean support, Korean review queue | terms, review queue, request draft / summary, summarize, translate, delegate | RAG, term list (draft), translation tasks | student; staff | answers; drafts that need review | chat, terms, queue (staff) | I T L |
| **Alex** en | the same for English | same | same | same | same | same | I T L |
| **Sari** id | the same for Indonesian | same | same | same | same | same | I T **L** (live notice → Indonesian answer, citation, follow-up) |
| **Minh** vi | the same for Vietnamese | same | same | same | same | same | I T **L** (queue → GPU → review → public) |
| **Mei** zh-CN | the same for Chinese | same | same | same | same | same | I T L |
| **Yuna** immigration | explains procedures, watches official guidance | checklists, source verification, official check, updates, review | RAG; 6 prepared pages (SCH, Study in Korea, HiKorea) | student; admin; schedule | quoted steps; change candidates | checklists, updates, review (admin) | I T **L** (answer with fee; refuses unknown; scheduled live check) |
| **Joon** academic | procedures, calendar, academic notices | checklists, deadlines, official check, updates | RAG; 3 prepared (board, calendar, page) | same | same | procedures, updates | I T **L** (scheduled live check: 10 new) |
| **Seo** TOPIK | dates and guides | TOPIK dates, official check, updates | notices; 3 prepared. topik.go.kr has no readable text | same | quoted dates | TOPIK, updates | I T; live sources validated |
| **Leo** scholarships | finds, dates, deduplicates | scholarship / opportunity search, official check, review | 3 prepared | same | candidates; reviewed opportunities | opportunities, review (admin) | I T **L** (live board) |
| **Mia** events | events, deadlines, changes | event search, opportunity search (events, programs), official check | notices; 2 prepared; events found by others | same | same | events, updates | I T; live sources validated |
| **Daniel** careers | jobs, internships, work-permission reminder | career search, job search, official check | 3 prepared; 2 official job APIs (**blocked: keys**) | same | candidates → approved postings, expire on their deadline | careers, updates | I T **L** (live board → approval → visible) |
| **Robo** monitoring | finds new and changed notices, alerts on broken parsers | official check, review, digest | 3 prepared | same | candidates, notifications | monitoring, review | I T **L** (by hand and by schedule: 10 new) |
| **Sumin** human support | prepares and tracks requests to people | create request (after confirmation), status, staff queue | own requests | student | ticket, routing, status | request, my requests, queue (staff) | I T L (student → consent → supporter → answer) |

Failure behaviour tested: no source, blocked or changed site, robots.txt, missing key, wrong key, provider down, worker dies, cancel, pause, quota, duplicate start, loop in
delegation, unknown tool, wrong role, retry limit. A failed source backs off, is reported to administrators and stops after five failures.

**Not autonomous today in production:** no source is configured and both schedule switches are off. Chat agents do not run continuously by design.
