# RAG v2 — progress checkpoint

Branch `research/rag-reliability-v2` (worktree `~/projects/sch-hub-rag-v2`, from RC `8fd791b`, local
only, not pushed). The RC branch `school/rc-2026-11-27` is not touched (backup tag
`backup/2026-11-28/school-rc-2026-11-27`).

| Phase | State | Output |
|---|---|---|
| 0 Audit + baseline reproduction | **done**: BASELINE-AUDIT.md; baseline reproduced in memory (E0, E1) and on real PostgreSQL + pgvector (E2); chunker text loss found (F1) | `results/rag_v2/E1*`, `E2*` |
| 1 Dataset | **test set v0.3 frozen** (210 questions, 42 needs); card, guidelines, review checklist written | DATASET-CARD.md, LABELING-GUIDELINES.md, HUMAN-REVIEW-CHECKLIST.md |
| 2–14 | not started | |

## Resume here

1. `build_testset.py --check` must print OK before any experiment.
2. Evaluator: `scripts/rag_v2/retrieval_eval.py` (memory or postgres backend, configs in `configs.py`).
   PostgreSQL: `export PG_BIN=/data/20243508/tools/pg/bin POSTGREST=/data/20243508/tools/prst/postgrest
   PYTHON=$PWD/backend/.venv/bin/python; scripts/scratch_db.sh start /data/20243508/w/rv2; source …/env`
   (stop needs PG_BIN too).
3. Next: Phase 2 failure analysis on DEV + VALIDATION, then chunker v2 (F1).
