# RAG v2 — reliability and research validation

Branch `research/rag-reliability-v2` (from release candidate `8fd791b`), local only. Start with **FINAL-REPORT.md**.

| File | What it is |
|---|---|
| FINAL-REPORT.md | the mission report (16 sections, classification of every claim) |
| PRESENTATION-SUMMARY-KO.md | 발표용 한국어 요약 |
| BASELINE-AUDIT.md | every pipeline stage, the baseline on real PostgreSQL, what was found |
| DATASET-CARD.md · LABELING-GUIDELINES.md · HUMAN-REVIEW-CHECKLIST.md | the frozen TEST set (210 q), how labels are made, how people should review them |
| RETRIEVAL-EXPERIMENTS.md · RETRIEVAL-RESULTS.md | protocol, configurations, results on DEV / VALIDATION / TEST |
| MULTILINGUAL-RESULTS.md | the cross-language gap and what closes it |
| ANSWER-EVALUATION.md | full assistant turns with a local proxy model, closed-book baseline, gate, Gemini plan |
| CITATION-VALIDATION.md | citation and figure checks, what they cannot catch |
| ERROR-ANALYSIS.md | failure taxonomy, Korean / visa / guidebook analysis, TEST lessons |
| PERFORMANCE.md | latency and memory of the changes |
| PRODUCTION-READINESS.md | what may ship, settings, owner steps, monitoring |
| PROGRESS.md · EXPERIMENT-LOG.md · BLOCKERS.md · TEST-RESULTS.md | checkpoints |
| figures/ | SVG charts drawn from the result files (`scripts/rag_v2/charts.py`) |

Code: `scripts/rag_v2/` (test-set builder, evaluators, taxonomy, gate sweep, injection suite, regression, charts),
`backend/app/services/assistant/{gate,citation_check,injection}.py`, chunker v2 in `backend/app/services/chunking.py`.
Results: `scripts/benchmarks/results/rag_v2/` (every number in these reports comes from a file there).

Reproduce the headline TEST table (≈ 10 min, needs the corpus snapshot and loopback Ollama with `qwen2.5:7b-instruct`):

```
cd backend
.venv/bin/python ../scripts/rag_v2/build_testset.py --check
.venv/bin/python ../scripts/rag_v2/retrieval_eval.py --split test --final \
    --configs baseline,hub0.1,llm_rewrite,hub0.1_llm_rewrite --tag T1
```
(TEST was used once for this mission; re-running it is reproduction, not tuning.)
