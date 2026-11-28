# Final readiness — 2026-11-27

**Verdict: development-complete release candidate, locally verified. Not staging-verified, not production-verified.** Nothing was pushed,
deployed or changed in production. Branch `school/rc-2026-11-27` (local commits on top of `origin/main` `c5098cc`).

## 1. Classification

| Level | What |
|---|---|
| **Locally implemented** | everything in the table of §2 |
| **Locally verified** (automated tests, real PostgreSQL + PostgREST, real browser, real local models on the RTX 4070, live public sources read today) | cost controls, budgets across restarts, emergency stop; Release 1 translation scope and verified-only display; TranslateGemma drafts through the GPU worker; 14 agents; weekly schedules; read-time expiry; Work24 parser (fixtures); RAG retrieval and answers (Qwen); admin AI usage card; office colours; RLS of the new tables; rollbacks |
| **Hosted staging verified** | **nothing** (no staging service exists; the MacBook L2 stack and the Render probe need the owner) |
| **Production verified** | **nothing new** (production was not touched) |
| **Needs human review** | translation drafts (ko/en/id reviewers), RAG and cross-language labels, Gemini privacy tier, second-person code review |
| **Externally blocked** | Gemini answer quality (needs a paid, capped run), Work24 / data.go.kr / Saramin keys, JobKorea / Linkareer / Buddies permission, Google Search API (closed), university IT consent for the GPU, migrations 0016–0019 in production |

## 2. Acceptance criteria of the mission

| Criterion | State | Evidence |
|---|---|---|
| existing public features keep working | locally verified | 1,024 unit, 94 integration, 15 SQL suites, 261 web, **168 / 168 browser checks** (TEST-RESULTS.md) |
| RAG uses approved, attributable evidence | verified | `test_only_approved_content_is_returned`, RLS tests, citations 92.9 % correct in the answer benchmark |
| reproducible multilingual retrieval and answer evaluation | done | `rag_research_eval.py`, `rag_lab.py`, results in `scripts/benchmarks/results/` |
| no fabricated metrics | yes | every number links to a result file; labels marked AI-drafted |
| 14 agent roles, each capability real | verified (registry + tests); one control fixed (vi/zh announcement draft button) | AGENT-MATRIX.md, registry dump in §3 |
| weekly autonomous workflows, production schedules off | verified | 0019, `test_schedules_are_disabled_by_default_and_need_both_switches`, browser autonomy journey |
| external discoveries need approval | verified | discovery tests, browser career/scholarship journeys |
| expired opportunities never shown as open | verified (read-time) | `test_opportunity_expiry.py` |
| announcement translations follow the selected language; unapproved private | verified | `test_release1_translation_scope.py`, browser Journey G |
| local Gemma translation evaluated and described honestly | done | TRANSLATION-EVALUATION.md (no human rating yet) |
| Gemini configured for live chat and RAG | configured, **not measured** | checklist §1 |
| spending bounded by enforceable controls | yes, but the default chat cap is high for a small budget | COST-EVALUATION.md §3, checklist 0.5 |
| production needs no university server | yes | GPU worker optional, 48 h hand-over, `GPU_WORKER_ENABLED=false` default |
| office visual change | done | browser check + screenshots |
| admin functions work | locally verified | browser admin journey |
| database permissions and RLS tested | yes | 15 SQL suites, integration tests |
| core browser journeys pass | **168 / 168** on a fresh stack (run 4) | TEST-RESULTS.md |
| resource constraints documented and tested where possible | yes (emulated 512 MB / 0.1 CPU) | PERFORMANCE.md §4 |
| manual production steps documented | yes | FINAL-SETUP-CHECKLIST.md |
| no production system changed | yes | – |

## 3. The 14 agents (registry of this branch)

| Agent | Job | Tools (count) | Sources (live today) | Can never |
|---|---|---|---|---|
| Hana (reception) | understands, answers with citations, routes | 7 | RAG, notices | decide eligibility, submit, publish |
| Minji / Alex / Sari / Minh / Mei | language support ko / en / id / vi / zh; review queue of their language | 12 each | RAG, term list, translation queue | publish; vi/zh: no machine drafts of announcements (Release 1) |
| Yuna (immigration) | visa checklists from approved guides, official updates | 12 | 6 pages (SCH, Study in Korea, HiKorea) | visa decisions, file anything |
| Joon (academic) | procedures, calendar, academic notices | 11 | 3 (board, calendar, page) | decide eligibility |
| Seo (TOPIK) | TOPIK dates and guides | 11 | 3 | – |
| Leo (scholarships) | finds, dates, deduplicates scholarships and programmes | 15 | 3 | decide eligibility, claim openings |
| Mia (events) | events with upcoming / past distinction | 12 | 2 | – |
| Daniel (career) | jobs and internships, official links | 15 | 3 + Work24 / data.go.kr / Saramin (keys missing) + 7 not-connected site links | judge work legality |
| Robo (monitoring) | new and changed notices, broken-parser alerts | 14 | 3 | publish announcements |
| Sumin (human support) | request drafts, confirmation, routing, status | 9 | own requests | send without confirmation, show others' requests |

## 4. Known risks

| Risk | Mitigation |
|---|---|
| Korean and visa questions retrieve a general guidebook first (held-out R@1 0.30 for visa) | the specific document is usually in the 10 passages read; split guidebooks; pre-registered reranker test |
| Gemini answer quality unmeasured | capped owner-approved run before release |
| default daily chat cap too high for the budget | set `AI_DAILY_LIMIT_GLOBAL` (checklist 0.5) and a Google budget alert |
| AI-drafted labels and glossary | native review worksheets |
| free Render memory margin is small | `MALLOC_ARENA_MAX=2`, staging probe first |
| new UI strings in vi / zh / id written by an AI assistant | native check |
