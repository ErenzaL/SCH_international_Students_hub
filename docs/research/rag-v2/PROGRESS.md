# RAG v2 — progress checkpoint

Branch `research/rag-reliability-v2` (worktree `~/projects/sch-hub-rag-v2`, from RC `8fd791b`, local
only, not pushed). The RC branch `school/rc-2026-11-27` is not touched (backup tag
`backup/2026-11-28/school-rc-2026-11-27`).

| Phase | State | Output |
|---|---|---|
| 0 Audit + baseline reproduction | in-memory baseline reproduced exactly (see EXPERIMENT-LOG E0); audit document and real-PostgreSQL baseline next | `results/rag_v2/repro_memory_*.json` |
| 1 Dataset | **test set v0.3 frozen** (210 questions, 42 needs); card, guidelines, review checklist written | DATASET-CARD.md, LABELING-GUIDELINES.md, HUMAN-REVIEW-CHECKLIST.md |
| 2–14 | not started | |

## Resume here

1. `build_testset.py --check` must print OK before any experiment.
2. Write BASELINE-AUDIT.md, then run the real PostgreSQL + pgvector baseline (scratch DB through
   `scripts/scratch_db.sh`, socket under `/data/20243508/w`).
3. Experiment framework with content-based tie-breaks (the in-memory store breaks ties by random UUID).
