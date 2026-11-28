# RAG v2 — progress checkpoint

Branch `research/rag-reliability-v2` (worktree `~/projects/sch-hub-rag-v2`, from RC `8fd791b`), local only, not pushed.
The RC branch `school/rc-2026-11-27` is untouched (backup tag `backup/2026-11-28/school-rc-2026-11-27`).

| Phase | State | Main output |
|---|---|---|
| 0 audit + baseline reproduction | done | BASELINE-AUDIT.md; E0–E2 (memory and real PostgreSQL) |
| 1 dataset | done; **TEST frozen**; human review pending | DATASET-CARD.md, LABELING-GUIDELINES.md, HUMAN-REVIEW-CHECKLIST.md |
| 2 failure analysis (visa, Korean, guidebook) | done | ERROR-ANALYSIS.md, `failure_taxonomy.py` |
| 3 ingestion / chunking | done: chunker v2 / v2b behind `CHUNKER_VERSION` | E3, T2 |
| 4 retrieval experiments | done (hub scaling, variants, stores); reranker / larger embeddings excluded (memory) | RETRIEVAL-EXPERIMENTS.md, RETRIEVAL-RESULTS.md |
| 5 metrics + statistics | done: strict / lenient / passage / context metrics, need-level bootstrap | `lib.py`, `compare.py` |
| 6 evidence gate, injection, context | gate (log) + injection screens done; gate does not transfer to TEST | `gate.py`, `injection.py`, E7, G-T, J1–J2 |
| 7 citation / figure verification | done | `citation_check.py`, CITATION-VALIDATION.md |
| 8 multilingual | done | MULTILINGUAL-RESULTS.md |
| 9 answer evaluation | done with a **local proxy**; Gemini blocked (B1) | A1, A9, ANSWER-EVALUATION.md |
| 10 performance | done (A/B) | PERFORMANCE.md |
| 11 monitoring + regression | done | PRODUCTION-READINESS.md §4, `regression.py` |
| 12 security | done (visibility on PostgreSQL, injection) | `test_rag_v2_visibility.py`, J2 |
| 13 tests | done | TEST-RESULTS.md |
| 14 reports | done | README.md, FINAL-REPORT.md, PRESENTATION-SUMMARY-KO.md |

## Resume here

Everything of this mission is committed. Owner actions: FINAL-REPORT §15. To repeat a measurement, see README.md;
PostgreSQL runs need `export PG_BIN=/data/20243508/tools/pg/bin POSTGREST=/data/20243508/tools/prst/postgrest
PYTHON=$PWD/backend/.venv/bin/python; scripts/scratch_db.sh start /data/20243508/w/rv2` (stop needs `PG_BIN` too).
