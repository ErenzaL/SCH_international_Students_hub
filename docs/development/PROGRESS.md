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
| 1 cost controls (migration 0018, persistent budgets, estimates from configured prices, spend ceiling, emergency stop) | done, tested | `4666ea3` |
| 5a announcement translation scope ko/en/id, verified-only display | done, tested | `4666ea3` |
| 2 RAG research evaluation (dev + held-out, CIs, paired tests) | done | `48a5a12` |
| 4 weekly staggered schedules (0019), Work24 connector, read-time expiry, job-site links | done, tested | `2ca6734` |
| 5b TranslateGemma benchmark: 12B + shared prompts chosen on dev (rule fixed before held-out) | dev done; held-out running | `aed8a09` |
| 6 office wall colour, admin AI usage card | done, unit-tested; browser screenshots pending | `a6dd5dd` |
| 7 security: secret scan of changes clean, `npm audit --omit=dev` 0, rollbacks 0018/0019 tested | done (pip-audit blocked) | – |
| 8 end-to-end: integration 94/9 with 0018+0019; browser journeys pending (web build OK) | in progress | – |
| 9 research reports: methodology, results, error analysis, translation (draft) | in progress | – |
| 10 final checklist (draft), readiness | in progress | – |

## Next executable step

1. Held-out translation runs (`heldout_tg12b_shared`, `heldout_qwen7b_shared`) → fill TRANSLATION-EVALUATION §5.
2. `rag_lab.py --modes qwen,retrieval,nocontext --json …/rag_behaviour_rc1127.json` (answers + tokens per answer) → RAG-RESULTS §7, COST-EVALUATION.
3. Memory re-run `render_like_rc1127_arena2.*` (work dir `/data/20243508/w`) → PERFORMANCE.md.
4. Browser journeys: fresh scratch DB, `dev_stack.py --synthetic-web`, `next start`, `node scripts/e2e_full.mjs` (Journey G rewritten for Indonesian).
