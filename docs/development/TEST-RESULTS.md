# Test results

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
