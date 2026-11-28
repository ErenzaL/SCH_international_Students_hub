# Test results

## 2026-11-27, branch `school/rc-2026-11-27` (school PC; loopback only; no production access)

Mocked = in-memory store and scripted models; real = real PostgreSQL 17 + pgvector + PostgREST, real local models (Ollama on the RTX 4070),
live public websites. **Nothing ran against hosted staging or production.**

| Suite | Kind | Result |
|---|---|---|
| backend unit tests (`pytest -q`), `ruff check .` | mocked | **1,024 passed**, 47 skipped (start of day 991 / 47); ruff clean |
| SQL behaviour tests, all migrations 0001–0019 | real PostgreSQL | **15 of 15** suites (new: `llm_usage_controls`, `weekly_discovery`) |
| rollbacks 0018 and 0019, then re-apply | real PostgreSQL | ok (schedules restored, Work24 sources removed, usage tables dropped; behaviour tests pass after re-apply) |
| integration tests (RLS, RPCs, roles, GPU worker, translation) with 0018 + 0019 | real PostgreSQL + PostgREST | **94 passed**, 9 skipped (live Gemini / live websites on purpose) |
| web `tsc --noEmit`, `eslint`, `vitest run` | mocked | clean, clean, **261 passed** (start of day 257) |
| `next build` (production bundle) | – | builds |
| `npm audit --omit=dev` | – | 0 vulnerabilities |
| live source validation (`validate_sources.py`, 23 public sources) | **live** websites | **23 of 23 ok**; 3 API sources not tested (no keys) |
| retrieval research evaluation, dev + held-out | real embedding model | `rag_research_{dev,heldout}.json` |
| answer benchmark (95 questions) Qwen + RAG / excerpts / no sources | real local model | 0.916 / 0.874 / 0.000 correct |
| translation benchmark, 5 configurations dev + 2 held-out | real local models | `announcements_*.json` |
| Render-like memory run (512 MB / 0.1 CPU, `MALLOC_ARENA_MAX=2`) | emulated limits | PERFORMANCE.md §4 |

### Mission journeys

| Journey | How it is tested | Kind |
|---|---|---|
| A Indonesian RAG | browser `chats` (12 desks × 5 languages, right fee, citation); answer benchmark id 1.00 | real (Qwen) |
| B Visa (Yuna) | browser `visa`; `visa_checklist` tests | real |
| C Scholarship (Leo) | browser `scholarship` (live board → candidate → approval → visible) | real, live site |
| D Career (Daniel) | browser `career` (live board, review gating, job-site links); Work24 fixtures | real + fixtures |
| E Events (Mia) | `test_agent_operations` desk tests (event kind, upcoming); browser `office` | mocked + real |
| F Robo monitoring | browser `announcement` and `autonomy` (scheduled live checks, change detection, notifications) | real, live sites |
| G Translation ko → id | browser `gpu` rewritten: TranslateGemma 12B draft by the worker process → Indonesian reviewer → public in Indonesian only; vi refused | real |
| H Unapproved data | browser `admin` refusals; `test_students_cannot_reach_drafts`; Release 1 scope tests | real + mocked |
| I Expiration | `test_opportunity_expiry.py` (deadline day open, next day hidden, no re-crawl) | mocked |
| J Cost limit | `test_cost_controls.py` (deferral without retry loop, nothing corrupted, restart keeps budget) | mocked |
| K Model unavailable | `test_r_s_both_models_unavailable_gives_a_localized_message_and_sources_only`, `test_offline_worker_jobs_fail_visibly_after_the_attempt_limit`, GPU worker revoked in the browser | mocked + real |
| L Frontend | browser `office` (14 desks, 5 languages, phone width, wall colour), `admin`, keyboard | real |

### Browser journeys (`scripts/e2e_full.mjs`, Chromium, production web build, real API + worker + PostgreSQL, Qwen for chat, TranslateGemma 12B in the GPU worker process, LIVE public SCH / Study in Korea / HiKorea pages)

| Run | Result | What it found / what changed before the next run |
|---|---|---|
| 1 | 155 / 163 | PDF journey: the new worktree had no `backend/.venv` (environment); Journey G: no Indonesian draft |
| 2 | 161 / 168 | the draft was refused 3 of 3 times; the debug driver showed the server answering `model_not_allowed`: the GPU model allowlist only named Qwen → **fixed** (`1a6e552`) |
| 3 | 167 / 168 | Journey G end to end; one assertion was wrong (the public response lists all approved translations) → test corrected |
| **4 (fresh database)** | **168 / 168** | – |

Journeys in run 4: setup, announcement, PDF (upload → extraction → review → Korean search → English answer), visa, chats (12 desks, 5 languages),
career (live board → candidate → approval; job-site links not connected), scholarship (live), **gpu = Journey G** (worker token once,
`--check`, Indonesian draft by TranslateGemma 12B in 5.2 s, `needs_review`, Vietnamese request refused, other-language reviewer refused,
Indonesian reviewer approves, Indonesian page shows it, Vietnamese page shows the original with the note, revoked worker refused,
waiting job cancelled in the browser), escalation (Sumin, consent first), admin (every page, refusals), office (14 desks, 5 languages,
phone width, keyboard, **wall colour check**), autonomy (weekly slots planned on Mondays, nothing runs early, then three scheduled LIVE
checks: Robo 10 read, Joon 10 read / 10 new, Yuna 1 read; admins notified; nothing became public). No page errors, missing texts or
hydration errors. Screenshots: `docs/integration-screenshots/2026-11-27/`.

---

## 2026-11-26, branch `staging/local-first`: tier L1 of [STAGING.md](../owner/STAGING.md) (no third Supabase project)

Everything on the university server, loopback only, synthetic data only. The official websites are replaced by `scripts/synthetic_web.py`
(same markup as the real boards, invented notices), so no journey read a real website.

| Check | Result |
|---|---|
| `cd backend && pytest -q` | **991 passed**, 47 skipped |
| SQL behaviour tests on PostgreSQL 17 + pgvector, all migrations | **13 of 13** |
| integration tests on real PostgreSQL + PostgREST (RLS, RPCs, roles) | **94 passed**, 9 skipped (live Gemini and live websites, on purpose) |
| `e2e_full.mjs`, every journey: setup, announcement, pdf, visa, chats, career, scholarship, gpu, escalation, admin, office, autonomy (real Qwen on the GPU, GPU worker process, synthetic websites) | **156 of 158**; both failures were one selector of the new `pdf` journey (two "Open review" links); fixed and rerun: **8 of 8** |
| local Supabase stack (tier L2) | not run here: no Docker access on this server; runs on the MacBook (`scripts/local_supabase.sh`) |

The journeys cover: login of all six roles; RAG answers with sources in five languages (12 chat desks); all 14 agents' workspaces; discovery,
review and approval for notices, jobs and scholarships; scheduled agents that start only when an administrator enables them; PDF upload →
extraction by the worker → review → approval → Korean search → an English answer from Qwen quoting the PDF; GPU translation draft →
language review → public, revocation and cancel; private escalation; every admin page and the role refusals; phone and keyboard use.

## 2026-11-25, branch `integration/release-candidate`

## Mocked (no real service)

| Command | Result |
|---|---|
| `cd backend && ruff check .` | clean |
| `cd backend && pytest -q` | **952 passed, 47 skipped** (`main` 604/37, A+B merged 864/45) |
| `cd apps/web && npx tsc --noEmit && npx eslint && npx vitest run` | clean, clean, **256 passed** (`main` 240) |
| `cd apps/web && npx next build` | builds |

## Real PostgreSQL 17 + PostgREST on this computer (`scripts/scratch_db.sh`)

| Database | Result |
|---|---|
| SQL behaviour tests, all migrations | **13 of 13** |
| integration tests, all migrations, twice | **94 passed**, 9 skipped (live services) |
| only 0001–0015 | 87 passed, 16 skipped |
| without 0017 / without 0016 | 92 / 11 and 89 / 14 |
| `main` on the old and on the new schema after the candidate used it, then the candidate again | 27 passed each, 87 / 94 again |
| 0017 rollback and forward, twice; re-applied; without 0016 | ok |
| Release A staging script against the candidate | **14 of 14** |

## Browser (Chromium, production web build, real API)

| Test | Result |
|---|---|
| `e2e_review.mjs` (Release A) | **23 of 23** |
| `e2e_full.mjs`: setup, announcement, visa, career, scholarship, GPU, escalation, admin, office, autonomy | **141 checks**; first full run 140, the one failure was a mistake in the test (counted notices that were approved on purpose); corrected and rerun with the affected journeys: 19 of 19 |
| `e2e_full.mjs` chats: 12 desks, five languages | **15 of 15** (with setup) |

`e2e_full` uses: real database and access rules, real worker, **real Qwen on the GPU**, **live official websites**, the GPU worker as its own process, six made-up accounts.
Sign-in is a stand-in for Supabase Auth. Not covered: Safari, Firefox, real phones, screen readers.

## Real GPU (RTX 4070, qwen2.5:7b-instruct)

| Test | Result |
|---|---|
| `e2e_gpu_worker.py` | **20 of 20** |
| `rag_lab.py --modes qwen`, 95 questions, two runs | 92.6 % and 91.6 % correct (before 80.0 %) |
| `bench_qwen_capabilities.py` | see [GPU-EVALUATION.md](GPU-EVALUATION.md) |

## Live, read-only

| | Result |
|---|---|
| `validate_sources.py` on 23 official sources | 23 ok |
| `doctor --api --web` on production (GET only) | 10 of 10 PASS |
| production database, Render, GitHub settings, Gemini | **not tested / not touched** |

## Hosted staging

**Not tested**: no staging project exists.

## Other

`pip-audit`, `npm audit` (2026-11-24): nothing found; dependency files unchanged. Secret patterns in 38 commits: only placeholders in tests. gitleaks: not run.
