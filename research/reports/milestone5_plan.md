# Milestone 5 - experimental plan (written before any Milestone 5 experiment was run)

## Data splits and leakage status

| Set | Records | Role in Milestone 5 | Leakage status |
|---|---|---|---|
| retrieval-pilot-0.1 | 100 (20 scenarios × 5 languages) | **development**: error analysis, any choice of reranker settings | contaminated - used for tuning in Milestones 1-2.2 |
| retrieval-heldout-0.2 | 100 (20 × 5) | **held-out evaluation**: run once per pre-specified configuration | never used for tuning; *results and error cases were inspected* in Milestone 4 (and H04 is named in the brief), so it is "inspected, untuned" - not a pristine final test |
| retrieval-reviewed-1.0 | - | final test, after independent human review | does not exist yet |

The 200-row `label_review_worksheet.csv` is exactly pilot (100) + held-out (100); no row has been reviewed.

Rules: (1) every Milestone 5 configuration is fixed from documentation or from the development set before it is
evaluated on held-out v0.2; (2) nothing is changed after seeing held-out results - a change motivated by a held-out
failure (e.g. H04) is reported as a hypothesis for the next test set, not as a validated improvement; (3) no
retrieval code in `backend/` is changed in this milestone.

## Pre-specified configurations

| ID | First stage | Reranker | Selection | Candidates |
|---|---|---|---|---|
| B0 | dense (vector) | - | - | top 30 chunks |
| E1 | SQL RRF hybrid | - | - | top 30 chunks |
| E2 | weighted hybrid | - | - | top 30 chunks (≤ 5 per document) |
| B0R | dense | cross-encoder | - | same 30 chunks reranked |
| E3 | weighted hybrid | cross-encoder | - | same 30 chunks reranked |
| E4 | weighted hybrid | cross-encoder | assistant evidence selection (≤ 4 documents) | same |

Ranking unit: chunks → documents by first occurrence. Metrics: Recall@1/3/5/10, MRR, nDCG@5/10 (document level, binary),
latency of first stage, reranking and total. 95% cluster-bootstrap intervals over scenarios, paired differences,
exact McNemar for Recall@1. Reranker input: the original question and `heading + passage`, truncated by the model.

## Out of scope for this milestone (and why)

- Gemini answer-quality comparisons between pipelines: production cannot switch pipelines per request, no API key is
  available locally, the primary model is not working, and no human reviews exist (Phase 7 gate not met).
- Changing production retrieval, Render, or the database.
