# Progress — mission of 2026-11-27 (school PC)

**Resume here.** Worktree `~/projects/sch-hub-2026-11-27`, branch `school/rc-2026-11-27` (local only, no upstream, nothing pushed).
Python: `~/projects/SCH_international_Students_hub/backend/.venv/bin/python` (3.11). Node: `/data/20243508/tools/node/bin`.
Test database: `scripts/scratch_db.sh start <dir>` with `PG_BIN=/data/20243508/tools/pg/bin POSTGREST=/data/20243508/tools/prst/postgrest`.
Plan: [MASTER-PLAN.md](MASTER-PLAN.md). Blockers: [BLOCKERS.md](BLOCKERS.md). Measured results: [TEST-RESULTS.md](TEST-RESULTS.md).

## Baseline (Phase 0)

| Item | Value |
|---|---|
| GitHub baseline | `origin/main` = `c5098cc` (fetched 2026-11-27; only new commit: character artwork) |
| New branch | `school/rc-2026-11-27` created at exactly `c5098cc` |
| School-only work | `staging/local-first` `5967ce9` (Release A, Release B, release candidate, staging checks; 52 commits) merged as `b104bc4` after review: no file overlaps the origin commit, secret scan of added lines clean |
| Backups | every local branch tagged `backup/2026-11-27/<branch>`; full bundle `~/backups/sch-hub-2026-11-27/all-branches.bundle` (0700) |
| Untouched | all old branches and both old worktrees (`~/projects/SCH_international_Students_hub`, `~/projects/sch-hub-rc`), `research/milestone-5` |
| MacBook work | not looked at, not merged (instruction) |
| Credentials on this server | none found (no `.env` files); none added |
| Baseline tests | backend 991 passed / 47 skipped; integration (real PostgreSQL 17 + PostgREST) 94 passed / 9 skipped; SQL suites all passed; web tsc, eslint clean, vitest 257 passed |
| Hardware | RTX 4070 12 GB (idle, no other GPU users), 31 GB RAM (26 GB free), 20 CPU threads, root disk 91 % used, `/data` 908 GB free; Ollama 0.40.2 on 127.0.0.1:11434 only |

## Phases

| Phase | State | Commit |
|---|---|---|
| 0 audit and baseline | done | `b104bc4` |
| 1 cost controls (0018) | done, tested | `4666ea3` |
| 2 RAG research evaluation | done | `48a5a12` |
| 3 agents: verified; vi/zh queue control fixed | done | `7b786c9` |
| 4 weekly schedules (0019), Work24, read-time expiry, job-site links; 23/23 sources live today | done | `2ca6734`, `99dc493` |
| 5 translation scope + TranslateGemma benchmark (12B chosen; held-out 20/20) | done | `4666ea3`, `aed8a09`, `99dc493` |
| 6 office colour, admin AI usage card | done | `a6dd5dd` |
| 7 security review, rollbacks 0018/0019 | done (pip-audit blocked) | `99dc493`, `4d13699` |
| 8 tests: unit 1022/47, web 261, SQL 15/15, integration 94/9, browser 155/163 first run (PDF env + Journey G) → re-run | in progress | – |
| 9 research reports | done | `4d13699` |
| 10 checklist + readiness | done, final numbers pending | – |

## Open item being worked on

Journey G in the browser: the GPU worker's TranslateGemma 12B output for the synthetic notice is refused as wrong-language in the worker
path (3 of 3 drains) while the same text passes 10 of 10 when generate() is called directly. Debug driver: `/data/20243508/w/dbg/drive.py`.
