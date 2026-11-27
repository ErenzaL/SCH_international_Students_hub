# Experiment log — RAG v2

Every run is recorded here: date, configuration, dataset and version, result file and headline numbers.
Runs on TEST are marked **TEST LOOK** and are allowed only in the final pre-registered run.

| ID | Date | What | Data | Result file | Headline |
|---|---|---|---|---|---|
| E0a | 2026-11-27 | reproduce the RC baseline, in-memory store, production hybrid (`rag_research_eval.py`) | DEV v0.1 | `scripts/benchmarks/results/rag_v2/repro_memory_dev.json` | R@1 0.75, R@10 0.99, MRR 0.848 (same as the committed RC results) |
| E0b | 2026-11-27 | same | VALIDATION v0.2 | `…/repro_memory_heldout.json` | hybrid R@1 0.63, R@10 0.94, MRR 0.736 [0.663, 0.807], nDCG@10 0.750; vector-only MRR 0.631; paired hybrid − vector MRR +0.104 [+0.045, +0.164] |
| D1 | 2026-11-27 | test set v0.3 built and frozen; no system run on it | TEST v0.3 | `scripts/benchmarks/rag_v2/testset_v0.3.json` | 210 questions, question hash `52f216ed7e5d7d1f` |
| E1 | 2026-11-27 | v2 evaluator, memory store, configs baseline / vector / no_bridge / hybrid_legacy | DEV | `E1_dev_memory.json` | baseline strict hit@1 0.69, MRR 0.782; lenient 0.76 / 0.853 (reproduces E0a within tie noise) |
| E1s | 2026-11-27 | baseline, memory, chunk-id seeds 1 / 2 / 3 (tie-break sensitivity) | DEV, VALIDATION | `E1seed{1,2,3}_{dev,val}_memory.json` | first-relevant rank changes for 2 / 100 (DEV) and 1 / 100 (VAL) questions; hit@1 ± 0.01 |
| E2 | 2026-11-27 | **real PostgreSQL 17.12 + pgvector 0.8.1 (HNSW) + PostgREST + all migrations**, configs baseline / vector / keyword / no_bridge / hybrid_legacy | DEV, VALIDATION | `E2_{dev,val}_postgres.json` | baseline DEV hit@1 0.69, MRR 0.782; VAL 0.52, 0.655 [0.536, 0.767] (lenient 0.735 [0.635, 0.825]; question-level would give [0.660, 0.803]); same first-relevant rank as memory for 98 / 100 on both |
| F1 | 2026-11-27 | finding, not a run: chunker drops consecutive heading lines | corpus | BASELINE-AUDIT.md §2 stage 3 | 57.7 % of the Korean guidebook's text and 13.3 % of the corpus in no chunk; 3 / 57 test quotes affected |

Notes
- E0: ties in the in-memory store are broken by random chunk UUIDs, so results can differ between
  runs where scores are equal. The v2 framework breaks ties on content.
