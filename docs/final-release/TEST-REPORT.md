# Final test report — release `release/sch-hub-final-2026-11-30`

Every row was run and its output read on 2026-11-27/28. "Local" = the school workstation (scratch PostgreSQL, local stack,
never production). "Hosted" = the live production site, read-only, no login.

## Local verification (the release code)

| Suite | Passed | Failed | Skipped | Not run | Environment | Evidence |
|---|---|---|---|---|---|---|
| backend unit / component | **1,072** | 0 | 54 | — | backend venv, in-memory store | `pytest tests/` (the skips are integration tests needing a database, and one freeze test needing the gitignored corpus) |
| frontend unit | **261** | 0 | 0 | — | vitest | `npx vitest run`; `tsc --noEmit` and `eslint` clean |
| PostgreSQL integration (all migrations) | **100** | 0 | 9 | — | scratch PostgreSQL 17 + pgvector + PostgREST | same tree as `research/rag-reliability-v2` (identical tree hash) |
| PostgreSQL integration, **production schema (0001–0015 only)** | **93** | 0 | 16 | — | same, database rebuilt without 0016–0019 | the 7 extra skips are the 0016 / 0017 feature tests |
| every parameter-free GET endpoint × 5 roles at schema 0015 | 210 calls | **0 server errors** | — | — | same | 119 × 200, 84 × 401/403 (correct refusals), 7 × 404 |
| SQL behaviour suites (RLS, lifecycle, budgets, …) | **15** | 0 | 0 | — | scratch PostgreSQL | run by `scratch_db.sh start` |
| source visibility (draft, pending, superseded, cancelled, archived, expired, future, inactive) | **6** tests, 8 states | 0 | 0 | — | real PostgreSQL | `tests/integration/test_rag_v2_visibility.py` |
| browser journeys (setup, chats, admin, office, escalation) | **114** | 1 | 0 | announcement, pdf, visa, career, scholarship, gpu, autonomy (not affected by the release changes; RC: 168 / 168) | local stack, Chromium, Qwen on the GPU, production web build | the one failure: the Chinese desk's answer did not arrive within 60 s (timeout, not a wrong answer); re-run of `chats`: **15 / 15** |
| RAG retrieval / answer / injection evaluations | see reports | — | — | Gemini runs (no key) | memory + PostgreSQL, local proxy model | `docs/research/rag-v2/` |
| Gemini usage-limit and fallback tests | in the backend unit count | 0 | — | live Gemini test (no key) | mocked provider | `test_cost_defaults.py`, budget and fallback tests |
| translation approval, Release 1 scope, deadline expiry | in the unit / browser counts | 0 | — | — | | `test_release1_translation_scope.py`, `test_opportunity_expiry.py`, browser journey G (RC) |
| secret-pattern scan of the release diff | clean | — | — | gitleaks (not installed) | `git diff origin/main` | no key, token or private key pattern; `.env.example` placeholders only |

## Hosted verification (production, read-only, 2026-11-28)

| Check | Result |
|---|---|
| API `/health`, `/api/v1/assistant/status` | 200; Supabase configured; answer generation enabled |
| public API: categories, Knowledge Center, announcements | 200; 11 categories, 21 documents, 7 announcements |
| 10 public pages incl. `/ai-office`, `?lang=ko` | 200 (`/assistant`, `/admin` redirect when signed out) |
| one RAG question (Korean, residence-card fee) | correct answer (35,000원 since 2025-01-01), Korean, correct citation, 27.6 s |
| signed-in journeys, admin, review, AI usage card | **not run** (no test account on this workstation) |
| the release itself on production | **not run** (not deployed; see DEPLOYMENT-STATUS.md) |

The hosted checks describe the currently deployed `main`, not this release.
