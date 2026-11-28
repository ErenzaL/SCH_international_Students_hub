# System capabilities — final implementation matrix

**Production** = the live `main` deploy (checked read-only on 2026-11-28; signed-in pages not checked, no test account
here). **This release** = `release/sch-hub-final-2026-11-30`, not yet deployed (DEPLOYMENT-STATUS.md). Local tests:
1,082 backend unit, 104 PostgreSQL integration, 15 SQL suites, 261 web unit; browser journeys 114 / 115 plus a 15 / 15 re-run (TEST-REPORT.md; RC: 168 / 168).

Status words: **production** (working live) · **release** (in this release; live after the merge) · **local** (verified only
on the workstation) · **disabled** (code present, switched off) · **external** (needs a key or permission) · **human**
(needs people) · **future**.

| Feature | Purpose | Implementation | Local tests | Production status | Depends on | Limitations | Next step |
|---|---|---|---|---|---|---|---|
| Multilingual RAG chat (ko, en, id, vi, zh-CN) | grounded answers with citations | hybrid retrieval (pgvector + full text + glossary bridge), Gemini rewrite into en / ko, Gemini answer, checks | unit, integration, RAG v2 study | **production** (one live question answered correctly with a citation) | Gemini key, budget | answer quality measured only with a local proxy; no human labels | capped Gemini run, human labels |
| RAG safety layers (injection screens, per-citation check, evidence gate in log mode) | stop planted orders, wrong citations; record weak evidence | `assistant/injection.py`, `citation_check.py`, `gate.py` | 11 / 11 injection cases; unit tests | **release** | — | gate not enforced (over-refuses) | monitor; refit gate on real traffic |
| Approved-source protection | only approved, current, valid, active content reaches answers | database view + service-role-only search; Python checks | real-PostgreSQL visibility test (8 states) | **production** (view) + release (new test) | — | — | — |
| Knowledge Center | browse approved documents and originals | public API + web | unit, browser | **production** (21 documents) | — | 13 % of corpus text not searchable with chunker v1 | chunker v2 re-index (staging first) |
| Document ingestion (web, PDF, pasted text, OCR off) | add sources | worker queue, PDF in a child process, review before publish | unit, integration, memory test | **production** | Render memory | large PDFs slow at 0.1 CPU | one upload at a time |
| Official announcements | publish reviewed notices | review → publish; read-time expiry of opportunities (release) | unit, browser | **production** (7 published) | — | — | — |
| Announcement translation | approved translations ko / en / id | drafts private until a reviewer approves; Release 1 scope | `test_release1_translation_scope.py`, browser journey G | **production: reviewer-driven**; automatic drafting off | reviewers | vi / zh-CN not drafted (chat still answers in them); no human quality rating yet | native reviewers |
| TranslateGemma 12B on the school GPU | free draft translations | outbound-only GPU worker | 72 real notices: 1 detectable fact error, all dates / money / links kept | **disabled** (`GPU_WORKER_ENABLED=false`; needs 0016) | workstation online | not for production availability | optional, never required |
| AI Office, 14 desks | specialised help per topic | registry (server decides tools / limits), desks UI | unit, browser (14 desks, 5 languages) | **production** (page live) | Gemini | desks are request-driven, not continuously autonomous | — |
| Agent tasks (manual) | desks run checks on request | durable tasks, retries, pause, audit | unit, browser | **production** (tasks) / pause switch needs 0017 | — | — | apply 0017 |
| Weekly autonomous discovery | scheduled checks of official sources | 4 weekly staggered schedules | unit, browser (scheduled live run) | **disabled** (both schedule switches off) | 0019; owner decision | not verified on hosted infrastructure | enable one schedule at a time |
| Source monitoring (Robo) | new / changed official notices | allowlist, robots.txt, change detection | 23 / 23 public sources read live | **production on request**; schedules off | — | sites can change layout | alerts after 5 failures (built in) |
| Scholarship discovery (Leo) | find scholarships | live board → candidate → human approval | browser journey | candidates only after review | reviewer | nothing is published automatically | — |
| Career discovery (Daniel) | jobs, internships | official boards; Work24 / data.go.kr / Saramin connectors | fixtures; live boards | **external**: API keys missing; Linkareer, Buddies Korea, JobKorea are links only | keys, permissions | — | apply for keys |
| Events discovery (Mia) | events and deadlines | notices + discovered events | unit | **release** (needs 0017 for its sources) | 0017 | — | — |
| Human support (Sumin) | requests to people, with consent | tickets, routing, privacy (staff see no private words) | unit, browser | **production** | staff accounts | — | — |
| Admin dashboard | review, sources, agents, settings | role-checked pages | unit, browser | **production** | — | AI usage card persistent only with 0018 | apply 0018 |
| Role-based authorization | student / supporter / admin / super-admin | server-side checks + RLS | 15 SQL suites, route smoke per role | **production** | — | — | — |
| Gemini integration | answers, rewrite, background drafts | primary 3.6 Flash, fallback 3.5 Flash-Lite, bounded retries | unit (mocked), live test skipped (no key here) | **production** (answers live) | key, budget | `gemini-3.6-flash` retirement listed for 2027-01-28 | test a newer model |
| Gemini cost management | stay inside a small budget | daily caps, background caps, usage table, emergency stop | `test_cost_defaults.py`, unit | caps **production** (live values unknown); persistence + stop need 0018 | 0018 | caps limit answers, not money | budget alert; set caps (checklist §3) |
| pgvector + hybrid retrieval | find evidence | weighted fusion; reranker off | RAG v2: same results in memory and PostgreSQL | **production** | — | no reranker (does not fit 512 MB) | — |
| Mobile / browser responsiveness | phones | responsive layout | browser at phone width | **production** | — | — | — |
| Database migrations | schema | 19 files; 0016–0019 new, additive | scratch PostgreSQL, compatibility at 0015 | production presumed at 0015 | backup | free plan has no backups | §2 of the checklist |
| Infrastructure | hosting | Render free (API, web), Supabase free | Render-like memory test | **production** | — | 512 MB headroom ~20–50 MB | `MALLOC_ARENA_MAX=2` |
