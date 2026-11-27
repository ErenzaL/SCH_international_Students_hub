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
| E3 | 2026-11-27 | chunker v2 / v2b (no text lost) with the baseline ranking, memory | DEV, VALIDATION | `E3_{dev,val}_memory_v2{,b}.json` | v2 − v1: hit@1 −0.09 [−0.16, −0.03] DEV, −0.11 [−0.21, −0.03] VAL; primary in context +0.02 / +0.02. The now complete Korean guidebook ranks first more often (some of those passages answer the question but are unlabelled in DEV/VAL, others are noise) |
| E4 | 2026-11-27 | hub scaling sweep β ∈ {0.05 … 1.0} × chunker v1 / v2 / v2b, memory | **DEV only** | `E4*_dev_memory*.json` | best on DEV: small β. v1+β0.05 hit@1 0.79 MRR 0.849 ctx 0.92; v2+β0.05 0.77 / 0.838 / 0.96; v2+β0.1 0.76 / 0.836 / 0.96; v2b+β0.1 0.77 / 0.839 / 0.96; β ≥ 0.5 worse |

### P1 — selection rule for chunker × hub scaling, written BEFORE the VALIDATION run of E5

Candidates: chunker {v1, v2, v2b} × hub β {0, 0.05, 0.1} (9 cells; all reported).
Primary metric: `ctx_doc_hit` (the primary document is among the sources the answer model reads); secondary: strict MRR.
A candidate may replace the baseline (v1, β 0) only if, on VALIDATION, paired against the baseline:
the 95 % interval of the `ctx_doc_hit` difference has a lower bound > −0.03 **and** that of the MRR difference > −0.02.
Among qualifying candidates: the v2 family is preferred to v1 when their VALIDATION MRR differs by < 0.02 (v1 drops
text, a correctness defect independent of these metrics); then the highest VALIDATION MRR; ties → smaller β.
If no candidate qualifies, the baseline stays and chunker v2 is reported as a correctness fix with its measured cost.
The chosen configuration and the baseline are the two configurations run on TEST in the final run.
| E5 | 2026-11-27 | **P1 run**: chunker {v1, v2, v2b} × hub β {0, 0.05, 0.1}, memory | VALIDATION | `E5_val_memory{,_v2,_v2b}.json` | qualifying under P1: v1+β0.05 (MRR 0.729), **v1+β0.1 (0.737)**, v2+β0.1 (0.715). v2 trails the best v1 by 0.022 ≥ 0.02, so **P1 selects v1 + β0.1** (ctx +0.05 [+0.01, +0.10], MRR +0.081 [+0.016, +0.153] vs baseline). v2+β0.1 − v1+β0.1: VAL ctx 0.00 [−0.03, +0.03], MRR −0.022 [−0.047, +0.002], hit@1 −0.05 [−0.09, −0.01]; DEV ctx +0.04 [+0.01, +0.08], MRR 0.000 |
| E6 | 2026-11-27 | query variants in the assistant stage: oracle en / en+ko (the same need's other-language question), local rewrite proxy (engine `_queries` with Qwen 2.5 7B on loopback Ollama, temperature 0, cached in `backend/.eval-cache/rag_v2_rewrites.json`), each with and without hub β0.1 | DEV, then VALIDATION | `E6_{dev,val}_memory.json` | VAL vs baseline: Qwen rewrite ctx +0.08 [+0.01, +0.16], fused MRR +0.107 [+0.042, +0.178]; **hub β0.1 + Qwen rewrite ctx 0.94 (+0.14 [+0.04, +0.25]), fused MRR 0.808 (+0.168 [+0.056, +0.284])**; oracle en/ko + β0.1 ctx 0.98. DEV agrees (β0.1 + rewrite ctx 0.98, fused MRR +0.105 [+0.02, +0.198]) |
| D2 | 2026-11-27 | DEV-negatives v0.1: 7 unanswerable needs × 5 languages (35 questions; 3 hard negatives), DEV-only, for gate tuning | — | `scripts/benchmarks/rag_v2/dev_negatives_v0.1.json` | topics disjoint from TEST's unanswerable needs |
| E7 | 2026-11-27 | gate features (best similarity / keyword coverage / exact match over the model's passages) for baseline, hub0.1, llm_rewrite, hub0.1_llm_rewrite | DEV, VALIDATION, DEV-negatives | `E7_{dev,val,neg}_memory.json`, `E7_gate_sweep.json` | without rewrite, at ≤ 5 % false refusals the gate refuses ≤ 37 % of negatives; after a rewrite τ 0.86 / λ 0.7 refuses 3 % of answerable (2 % with evidence in context) and 77 % of negatives (80 % of hard ones) |

### G1 — evidence gate frozen for TEST (written before any TEST run)

Rule in `backend/app/services/assistant/gate.py`. Thresholds: original path τ 0.82 / λ 0.6 (DEV+VAL FRR 0.035, negatives TRR 0.34);
rewritten path τ 0.86 / λ 0.7 (FRR 0.02–0.03, TRR 0.77). On TEST the gate is reported for the configurations run there:
FRR on answerable questions (and FRR with the gold quote in context), TRR on `unanswerable` and on `not_in_sources`.
Default mode `log` (no behaviour change); `enforce` is an owner decision after a check on real (Gemini) traffic.

Notes
- E0: ties in the in-memory store are broken by random chunk UUIDs, so results can differ between
  runs where scores are equal. The v2 framework breaks ties on content.
