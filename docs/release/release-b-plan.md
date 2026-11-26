# Release B: GPU worker integration (off by default)

Branch `release/b-gpu-worker`, on top of Release A. Not pushed, not deployed. `GPU_WORKER_ENABLED=false`.
Release B must not be deployed before Release A; it contains A's commits.

## Commits

| Commit | Content | Runtime code in production |
|---|---|---|
| `66e7c89` | Ollama provider (optional, loopback only) | new provider, unused unless selected |
| `3da80c2` | Local development backend, benchmark, docs | no |
| `62c98be` | **Migration 0016** + rollback + SQL tests | schema |
| `2e2a495` | GPU worker API | yes, every endpoint 404 while off |
| `3b9e238` | GPU worker client | no (runs at the university) |
| `0c74ea6` | End-to-end test, checklist, gateway assessment | no |
| `df97422` | Jobs never wait forever; routing only to a usable worker | yes |
| `8575ee5` | Benchmark on real public notices | no |
| `e6d857e` | Drafts of local models: exact dates, terms, stricter checks | only for local models |
| `0ed3a74` | Helper for one pilot translation | no |
| `2e28ac5` | Assessment | no |
| (last commit) | Review materials, retention proposal, this plan | no |

Every commit that changes code was tested on its own.

## Migration

| Migration | Release | Needed for |
|---|---|---|
| none | A | — |
| `20261124000016_gpu_worker.sql` | **B only** | `GPU_WORKER_ENABLED=true`. Release B with the feature off also runs without it (tested); apply it first anyway |

## What runs in production while the feature is off

Reviewed line by line against Release A:

| Shared code | Effect when off |
|---|---|
| assistant engine | one attribute check; the extra text is only sent to local models. 22 recorded prompts are byte-identical to `main` |
| translation services | `run_job` split into two methods, same order of checks; same Gemini prompts and quality checks |
| `summarize_document` | a limit that only local models define |
| job worker loop | one clean-up query at start and hourly; without 0016 it logs one database error, then stops trying |
| agent schedule gate | unchanged (the filter is only used when the feature is on) |
| failure alert of announcement translations | new wording instead of "Sync failed" |
| `claim_ingestion_job` (0016) | `and executor = 'local'`, which is true for every existing row |
| API start | Ollama is not contacted; no new dependency in `requirements.txt` |

Not touched: `render.yaml`, workflows, web app, chat prompts, retrieval, agents, schedules.

## Tests

| Check | Result |
|---|---|
| Mocked suite | 823 passed, 44 skipped |
| PostgreSQL + PostgREST, 0016 applied | 91 passed, 9 skipped |
| Feature off, 0016 **not** applied | 86 passed, 9 skipped |
| `main` and Release A on a database with 0016 | 27 and 29 passed |
| SQL behaviour tests | 12 of 12 files |
| Real GPU, end to end, on this branch | 20 of 20 |

## Order

1. Release A is live and stable for at least one week.
2. Blockers of the readiness report closed; approvals given in writing.
3. Backup. Apply 0016 when no job is running. Check the running Release A.
4. Deploy Release B with `GPU_WORKER_ENABLED` unset. Checks as in [gpu-worker-readiness.md](gpu-worker-readiness.md), section 9.
5. Only after that, and with separate approval: the single pilot translation (same document).
6. Evaluate with the [review record](../review/README.md). Anything beyond the pilot needs a new decision.

Stop: `GPU_WORKER_ENABLED=false` or revoke the worker. Roll back: redeploy Release A; the schema can stay
(SQL rollback: `supabase/rollback/20261124000016_gpu_worker_down.sql`).
