# AI Office workspaces: production assessment (2026-11-24)

Branch `feature/agent-workspaces`, based on release candidate `cb5a6ba`. The workspaces are ready to deploy with
schedules off, but four desks (Joon, Seo, Daniel and partly Yuna) mostly show empty states until staff publish
guides and notices for them. The recommendation is in section 6.

**How it was measured.** Real Chrome against the production web build, using the release-candidate API in worker
mode on a local PostgreSQL + PostgREST scratch database, with synthetic users. Robo's check and the admin review
used the live SCH sites. All timings are from this local stack. Production adds network latency to Render and
Supabase, plus the Render free-tier cold start.

## 1. Usefulness by character

Classification codes: **KEEP** works and is worth it; **SIMPLIFY** works but overlaps something else;
**IMPROVE** the feature is fine but needs data or a fix; **DEFER** not yet; **REMOVE** none proposed. Nothing was
removed.

| Character | Primary student problem | Expected result | Data source today | Tools | Interactions (measured) | LLM needed? | Cost drivers | Failure conditions | Success criteria |
|---|---|---|---|---|---|---|---|---|---|
| Hana | "Where do I ask about X?" / general question | Grounded answer with sources, or the right desk | Approved Hub documents (RAG) | chat, delegation, desk directory | 1 click + question | **Yes** (answer) | 2 Gemini calls, about 6.6k tokens per question | No approved source: says so. Gemini quota/outage: evidence-only reply | Answer cites ≥1 approved source; handoff offered when unsure |
| 5 language supporters | Same, in one language | Answer in that language | RAG | chat, summaries/translations on request | 1 + question | **Yes** | Same as Hana; summaries are paid calls | Same | Same, in the supporter's language |
| Yuna | "What are the steps for my visa extension?" | Quoted checklist with links, plus chat | Approved visa guides (2 in the Hub) | `visa_checklist`, chat | 2 | No (checklist); yes (chat) | Embedding query (local CPU) | Thin content: few or no steps | Each step quoted from an approved guide, with a link |
| Joon | "How do I register for courses / take leave / graduate?" | Quoted procedure | Approved academic-life guides (**none in the Hub**) | `academic_checklist`, notices | 2 | No | Embedding query | No guide: empty state with next steps | ≥1 approved guide per procedure |
| Seo | "When is the next TOPIK registration?" | Dates quoted from the latest published notice | Published TOPIK announcements (**none**) | `topik_dates` | 1 | No | 1 query | No notice: empty state, official TOPIK site, ask Seo | Latest notice shown with its deadline |
| Leo | "Which scholarships can I apply for now?" | Approved opportunities, soonest deadline first | Published notices and guides, plus reviewed official-site items | `scholarship_search`, `opportunity_search`, filters | 1 to see, 3 to search | No | 2 queries | Nothing approved; closed items hidden (says so precisely) | 0 unreviewed items shown; every item has a source link |
| Mia | "What's happening on campus?" | Upcoming dated notices, detail view | Published announcements with dates | announcements API, digest task | 1 to see, 2 to open detail | No | 3 list queries | No dated notices; location only inside the notice text | Upcoming list sorted by date; official link in detail |
| Daniel | "Are there internships or jobs for me?" | Career notices, reviewed postings, work-permission reminder | Employment guides (**none**); reviewed job postings | `career_opportunity_search`, `opportunity_search(job)` | 1 | No | 2 queries | No published career content (true today until a posting is approved) | Reviewed posting visible after approval (verified, see section 2) |
| Robo | "Is the information current?" (students); "what's new on official sites?" (admins) | Watched sites, last check, health; admin checks and review | Configured official sources | monitoring status, digest, admin check and review | Student 1; admin check 2 | No | Live fetches (about 40 requests per check), about 90 s of worker time | Site blocked or changed: "needs attention" for students, error text for admins | Last successful check < 24 h; failures alert admins |
| Sumin | "I need a person to help me" | Request reaches the right language team after explicit confirmation | support tickets | request form, preview, my requests | 6 | No | 1–3 writes | Not signed in: sign-in prompt | Nothing sent before **Confirm**; preview equals what is stored |

Per-capability classification:

| Capability | Class | Why |
|---|---|---|
| Grounded chat (Hana, supporters, the chat tabs of service desks) | KEEP | Core value; the only place an LLM is necessary |
| Desk directory, delegation | KEEP | Deterministic routing, free |
| Yuna, Joon, Seo checklists and dates | KEEP the code, **IMPROVE the data** | Joon and Seo are empty today: no academic-life guides or TOPIK notices are approved in the Hub. Publish 수강신청, 휴학·복학, 졸업 guides and the TOPIK schedule first |
| Leo list, filters, verification labels | KEEP | Measured: 0 unreviewed items reach students |
| Leo "full scholarship check" background task | SIMPLIFY | It searches the same approved content the list already shows; keep it in the Tasks tab only |
| Mia list and detail | KEEP | |
| Mia / Robo "what changed" digests | SIMPLIFY | Useful for returning students; could become "new since your last visit" badges instead of a background task |
| Event location field | IMPROVE | Announcements already have structured `location` evidence in review; show it when confirmed |
| Daniel notices and reviewed postings | KEEP (+ IMPROVE data) | No employment guides yet |
| Daniel external job search | DEFER | Not connected on purpose; the UI says so |
| Robo monitoring status, manual admin check, review queue | KEEP | |
| Scheduled checks | DEFER | Off. Enable only after approval and after the worker-contention item in section 3 |
| AI summaries of new discoveries (`summarize_new`) | DEFER | Off. LLM cost with little benefit over the quoted original |
| Sumin request flow and history | KEEP | |
| Free-text request box in every Tasks tab | SIMPLIFY | Overlaps the chat for chat-first desks |
| Chat tab of Sumin | SIMPLIFY | Little value next to the request form |

## 2. End-to-end workflows (actual outcomes)

| # | Workflow | Outcome | Interactions | Time |
|---|---|---|---|---|
| 1 | Academic procedure via Joon | No approved academic guide in the Hub: empty state with next steps (ask Joon, ask a person) | 2 | 2.4 s first call (embedding model warm-up 2.2 s), then about 40 ms |
| 2 | Latest TOPIK announcement via Seo | None published: empty state with official TOPIK site and "ask Seo" | 1 | 87 ms |
| 3 | Approved scholarships via Leo | 2 approved opportunities, 0 unreviewed; search "장학금" → 2 | 1 (3 with search) | 107 ms |
| 4 | Upcoming event via Mia | 2 upcoming dated notices; detail opened with the official link | 2 | 538 ms (3 list calls) |
| 5 | Career guidance via Daniel | Before review: 0 items. After workflow 7: the reviewed G-LAMP internship appears under reviewed postings | 1 | about 100 ms (load test) |
| 6 | Admin runs Robo's check (live SCH sites) | Completed: 4 sources, 0 new, 1 updated. A student watching the office saw Robo working | 2 | 91 s (polite fetching, 1.5 s between requests) |
| 7 | Admin reviews and approves discovered items | 2 real notices sent to review from Leo's and Robo's queues; each official page fetched and stored as a pending version in 0.3–0.4 s; approved in the review flow | 3 per item to send; 3 per item to approve in the admin console | Indexing 1.0–1.4 s after approval |
| 8 | Student sees an item only after publication | Hidden before review and while pending (polled 203 s); visible within seconds after approval, as verified, in Leo and Daniel | 1 | |
| 9–10 | Support request via Sumin | Ticket count 4 → 4 after preview (nothing sent) → 5 after Confirm; the preview showed exactly the stored subject | 6 | 3.3 s including typing |

Problems found and fixed during these runs:
- After "Send to review" the card vanished from the queue, so the admin got no confirmation. The card now stays and
  shows its new status, with a Refresh button.
- A task-list hint pointed to a start button that Daniel doesn't have.

Environment limitation: the admin review console (`/admin/*`) checks the Supabase session on the server, and the
local stack has no Supabase Auth. So workflow 7's approve click used the same endpoint the console calls
(`POST /admin/versions/{id}/approve`); the console's button is covered by its component tests. This must be
smoke-tested on staging or production.

Also re-run on a fresh database:
- Phase 4 browser suite: 21/21, after updating one check to the new rule that students only see reviewed items;
- translation and document-viewer verification: 12/12;
- workspace desktop and phone suite: 29/29 with no page errors.

## 3. Cost and performance

### What uses what

| Interaction | Gemini | RAG retrieval | Database | Official-site fetching | Background job |
|---|---|---|---|---|---|
| Chat question (any chat tab) | 2 calls (query rewrite + streamed answer) | yes (local ONNX e5 embedding + pgvector/keyword) | yes | no | no |
| Opening any workspace; lists, filters, checklists, TOPIK dates, monitoring status | **0** | checklists only (embedding query, no LLM) | yes | no | no |
| Digests, scholarship check, support request | **0** | no | yes | no | yes (short, under 0.3 s) |
| Explicit "summarize" / "translate" request | 1–3 calls | no | yes | no | yes |
| Admin official-source check | 0 (summaries off) | no | yes | yes, about 40 requests | yes, about 90 s |
| Send to review / approval | 0 | indexing (local embeddings) | yes | 1 request per item | yes, 0.3–1.4 s |
| Admin AI translation draft | 1 per chunk | no | yes | no | yes |

A backend test (`test_workspace_actions_never_call_the_model`) enforces the "0 Gemini calls" column for every
workspace action. It includes a control check that the model was reachable.

### Measurements (local stack)

**Workspace loading**, from the click to the first data:
- desktop: 25–200 ms;
- phone with 4× CPU throttling and slow network: 160–490 ms.

**API latency (p50):**

| Call | p50 |
|---|---|
| Directory | 11 ms |
| Monitoring status | 14 ms |
| Announcements | 12 ms |
| Tool searches | 31–55 ms |
| Checklists (RAG) | 40–42 ms; 2.2 s on the first call after a restart (model load) |

**Database:** the workspace queries run in under 1 ms of execution plus about 1 ms of planning, so in production
latency is dominated by the Render↔Supabase network round trip.

**Agent tasks:**
- digests, scans and support requests finish in 0.1–0.3 s;
- a live official-source check takes about 89–91 s.

**Retries:** none across all agent tasks and ingestion jobs. Failed ingestions in the scratch database come from
integration tests that fail on purpose.

**Worker contention:**
- One worker runs ingestion, translation and agent tasks. An upload queued during an official-source check waits
  up to the remaining check time, about 90 s worst case. Phase 4 measured 7.4 s behind an 8.5 s check.
- Chat and workspaces are not affected.
- Mitigations: keep checks at night, or check one source per task.

**Resources:**
- API process: 354 MB (ONNX embedding model loaded). An earlier steady-state measurement was 440 MB.
- Web server: 98 MB.
- Scratch database: 47 MB.

**Gemini tokens per chat question**, measured in production on 2026-11-23 (research record): about 6.1k input and
about 0.5k output over 2 calls. Thinking can add up to about 1k output.

**Production note:** every answer in that smoke test came from the fallback model `gemini-3.5-flash-lite`. The
primary `gemini-3.6-flash` was failing for the key and needs diagnosis.

### Monthly cost estimate

**Assumptions (explicit):**
- Usage: 10 chat questions per monthly active student (25 for the heavy case). Workspace use is free of LLM cost.
  5% of students request one summary a month (about 3.5k tokens). About 40 admin translation drafts a month.
- Prices (Nov 2026; re-check before budgeting):

  | Item | Price |
  |---|---|
  | Gemini 3.5 Flash-Lite | $0.30 / $2.50 per 1M input/output tokens |
  | Gemini 3.6 Flash | $1.50 / $7.50 (some sources list $0.75 / $3.75 as an introductory rate to 2026-12-31) |
  | Render Starter (512 MB) | $7 |
  | Render Standard (2 GB) | $25 |
  | Supabase Pro | $25 (includes Micro compute and 8 GB of database) |

- Free tiers are not assumed:
  - Render free instances sleep, which means cold starts, and their hours are limited.
  - Supabase Free pauses inactive projects.
  - The Gemini free tier has daily request limits. Check its current terms on whether prompts may be used to improve
    Google's products, because student questions would be sent.

| Monthly active students | Chat questions | Gemini, Flash-Lite (typical / heavy) | Gemini, 3.6 Flash (typical / heavy) | Hosting | **Total per month** |
|---|---|---|---|---|---|
| 100 | 1,000 | $3 / $8 | $13 / $32 | $57 | **about $60–$90** |
| 500 | 5,000 | $16 / $39 | $65 / $161 | $57 | **about $73–$220** |
| 2,000 | 20,000 | $62 / $155 | $258 / $645 | $57–$82 * | **about $120–$730** |

Notes on the table:
- **Per question:** Flash-Lite about $0.0031, 3.6 Flash about $0.013; up to about 1.6× with thinking tokens.
- **Summaries and admin translation drafts:** under $3 a month at all sizes.
- **Hosting:** API on Render Standard ($25), because 512 MB leaves no headroom for ingestion, PDF extraction and the
  worker. Web on Render Starter ($7). Supabase Pro ($25).
- **\* At 2,000 students,** add a separate worker (Starter $7 to Standard $25) so uploads never wait behind
  official-site checks.
- **Biggest lever:** the model choice. Flash-Lite is about 4× cheaper per question than 3.6 Flash. The workspaces
  themselves add no AI cost.

## 4. Fixes in this hardening round

- **Link extraction.** Site menus are no longer mistaken for application links. Links inside nav, header, footer,
  menus and banners are skipped; watched pages honour their content selector; and site services like "홍보신청" or
  login links are never treated as applications. The academic-calendar source uses `div.schedule-board`.
  - Validated live on all 9 proposed sources: every remaining application link is the notice's own form or
    attachment.
- **Admin tabs.** Review and Sources have their own always-visible row on desktop and phone.
- **Empty states.** Every workspace empty state offers next steps: clear filters, include closed items, past
  events, guides, ask in chat, or ask a person through Sumin.
- **Public monitoring status.** It now has an exact key allowlist. The server schedule switch and "enabled but off
  on the server" are admin-only; students see automatic checks as on or off.
- **Intermittent integration failures.** All were caused by test isolation on a reused database, not by product
  bugs:
  - the daily translation budget ran out after repeated runs;
  - documents with identical text tied in search ranking;
  - the seed announcement was pushed off the first page;
  - tests checked or left behind real official sources.

  Afterwards the suite passed 20 of 20 repeated runs, with and without a competing worker.

## 5. Remaining limitations

1. **Content gaps.** Academic, TOPIK and employment content is missing from the Hub, so Joon, Seo and Daniel mostly
   show (helpful) empty states until staff publish guides or notices.
2. **Admin console approval click** is not exercised in a real browser locally (needs Supabase Auth); smoke-test it
   after deployment.
3. **Single worker.** Official-source checks can delay uploads by up to about 90 s. Schedules are off; run checks at
   night.
4. **Events** have no structured location in the workspace (it's inside the notice text).
5. **Support topic** is stored as a subject prefix (no category column, by design: no new tables).
6. **Primary Gemini model** fails in production (fallback answers). Diagnose this before relying on the cost
   figures for 3.6 Flash.
7. **Render free tier.** Production ran on free 512 MB instances as of 2026-11-22: cold starts and little memory
   headroom.
8. **Prices** above are from third-party summaries of Nov 2026 rates and the providers' pages. Confirm them on
   ai.google.dev, render.com/pricing and supabase.com/pricing.

## 6. Deployment readiness

**Recommendation: ready for a staged deployment of the workspaces together with the release candidate**, using the
Phase 4 checklist (backup, migrations 0013–0015, merge, smoke test). Schedules stay off and no paid service is
turned on automatically. Before promoting the office to students:

1. publish the missing academic, TOPIK and employment guides/notices;
2. fix the primary Gemini model, or deliberately pin Flash-Lite;
3. move the API to a 2 GB instance before running official-source checks regularly;
4. smoke-test the admin review approval and one live Robo check on production.
