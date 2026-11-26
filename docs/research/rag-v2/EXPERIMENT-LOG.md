# Experiment log — RAG v2

Every run is recorded here: date, configuration, dataset and version, result file and headline numbers.
Runs on TEST are marked **TEST LOOK** and are allowed only in the final pre-registered run.

| ID | Date | What | Data | Result file | Headline |
|---|---|---|---|---|---|
| E0a | 2026-11-27 | reproduce the RC baseline, in-memory store, production hybrid (`rag_research_eval.py`) | DEV v0.1 | `scripts/benchmarks/results/rag_v2/repro_memory_dev.json` | R@1 0.75, R@10 0.99, MRR 0.848 (same as the committed RC results) |
| E0b | 2026-11-27 | same | VALIDATION v0.2 | `…/repro_memory_heldout.json` | hybrid R@1 0.63, R@10 0.94, MRR 0.736 [0.663, 0.807], nDCG@10 0.750; vector-only MRR 0.631; paired hybrid − vector MRR +0.104 [+0.045, +0.164] |
| D1 | 2026-11-27 | test set v0.3 built and frozen; no system run on it | TEST v0.3 | `scripts/benchmarks/rag_v2/testset_v0.3.json` | 210 questions, question hash `52f216ed7e5d7d1f` |

Notes
- E0: ties in the in-memory store are broken by random chunk UUIDs, so results can differ between
  runs where scores are equal. The v2 framework breaks ties on content.
