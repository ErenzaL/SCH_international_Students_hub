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
| 5b TranslateGemma benchmark (4B and 12B downloaded: 3.3 GB + 8.1 GB) | dev runs in progress | – |
| 2 RAG evaluation | next | – |
| 3, 4 agents and discovery | after 2 | – |
| 6 office colours, admin | after 4 | – |
| 7–10 | later | – |

## Next executable step

1. When `dev_tg*` runs finish: compare `scripts/benchmarks/results/announcements_dev_tg*.json` with the Qwen baseline
   (`announcements_improved.json`), choose ONE configuration by the rule in TRANSLATION-EVALUATION.md, then run the held-out set once.
2. Phase 2: `scripts/eval_retrieval_benchmark.py`, `scripts/eval_multilingual_retrieval.py`, `scripts/eval_crosslang.py` (see CROSSLANG-EVAL.md: the
   held-out cross-language set is still unlooked-at; one pre-registered look only).
