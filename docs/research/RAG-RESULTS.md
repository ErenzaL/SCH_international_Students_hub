# RAG results

Measured 2026-11-27 on the university workstation (commit `48a5a12` and later; retrieval code unchanged since the release candidate).
Method: [RAG-METHODOLOGY.md](RAG-METHODOLOGY.md). Raw files: `scripts/benchmarks/results/rag_research_dev.json`,
`rag_research_heldout.json`, `rag_behaviour_*.json`. **Labels were drafted by an AI assistant and are not reviewed by people.**

## 1. Retrieval — held-out set (100 questions, never used for tuning)

| Configuration | R@1 | R@3 | R@5 | R@10 | MRR@10 | nDCG@5 | nDCG@10 | P@5 | Top-1 primary |
|---|---|---|---|---|---|---|---|---|---|
| vector only | 0.50 [0.41–0.59] | 0.78 | 0.82 | 0.83 | 0.631 [0.551–0.708] | 0.619 | 0.620 | 0.214 | 0.44 |
| hybrid of `main` (legacy) | 0.47 [0.37–0.57] | 0.71 | 0.80 | 0.82 | 0.601 [0.521–0.680] | 0.594 | 0.599 | 0.218 | 0.37 |
| hybrid without bridge | 0.61 [0.51–0.70] | 0.82 | 0.86 | 0.92 | 0.727 [0.654–0.798] | 0.710 | 0.743 | 0.240 | 0.53 |
| **hybrid (production)** | **0.63 [0.53–0.72]** | **0.82** | **0.86** | **0.94** [0.89–0.98] | **0.736 [0.663–0.807]** | **0.709** | **0.750** [0.690–0.807] | 0.240 | 0.52 |

## 2. Retrieval — development set (100 questions, used while developing)

| Configuration | R@1 | R@3 | R@5 | R@10 | MRR@10 | nDCG@10 | Top-1 primary |
|---|---|---|---|---|---|---|---|
| vector only | 0.60 [0.50–0.70] | 0.81 | 0.87 | 0.87 | 0.710 [0.635–0.782] | 0.633 | 0.51 |
| hybrid of `main` (legacy) | 0.59 [0.49–0.68] | 0.78 | 0.82 | 0.82 | 0.690 [0.610–0.765] | 0.596 | 0.42 |
| hybrid without bridge | 0.72 [0.63–0.80] | 0.93 | 0.98 | 0.99 | 0.832 [0.774–0.885] | 0.779 | 0.64 |
| **hybrid (production)** | **0.75 [0.66–0.83]** | **0.96** | **0.98** | **0.99** | **0.848 [0.794–0.900]** | **0.810** | **0.68** |

The development scores are about 0.11 MRR higher than the held-out scores: the expected optimism of a set that guided development. Quote
the **held-out** numbers.

## 3. Are the improvements real? (paired bootstrap, 5,000 resamples)

| Comparison (held-out) | Metric | Difference | 95 % interval | p(≤0) | questions better / worse |
|---|---|---|---|---|---|
| production − vector only | MRR@10 | **+0.104** | [+0.045, +0.164] | 0.0004 | 33 / 8 |
| | Recall@1 | **+0.130** | [+0.03, +0.23] | 0.0064 | 20 / 7 |
| | nDCG@10 | **+0.130** | [+0.081, +0.181] | < 0.0002 | 47 / 15 |
| production − legacy hybrid | MRR@10 | **+0.135** | [+0.069, +0.201] | < 0.0002 | 34 / 10 |
| | Recall@1 | **+0.160** | [+0.06, +0.26] | 0.0012 | 22 / 6 |
| production − without bridge | MRR@10 | +0.009 | [−0.015, +0.032] | 0.22 | 8 / 4 |
| | nDCG@10 | +0.006 | [−0.013, +0.025] | 0.26 | 14 / 13 |

* The weighted hybrid ranking (dense + keyword, visa-code penalty, edition and duplicate handling) is a **significant** improvement over
  both dense-only retrieval and the old ranking, on data it was not tuned on.
* The concept bridge helped on the development set (nDCG@10 +0.031, interval [+0.011, +0.051]) but shows **no significant effect on the
  held-out set**. It is kept because it costs no model call and does not hurt, but no improvement is claimed for it.

## 4. By language (held-out, production configuration; 20 questions each)

| Language | R@1 | R@5 | MRR@10 [95 %] | nDCG@10 | vector-only MRR |
|---|---|---|---|---|---|
| Korean | 0.40 | 0.55 | 0.505 [0.313–0.693] | 0.547 | 0.308 |
| English | 0.65 | 0.90 | 0.767 [0.610–0.905] | 0.784 | 0.787 |
| Indonesian | 0.85 | 1.00 | 0.912 [0.812–1.000] | 0.891 | 0.846 |
| Vietnamese | 0.45 | 0.90 | 0.642 [0.490–0.790] | 0.710 | 0.577 |
| Chinese | 0.80 | 0.95 | 0.852 [0.700–0.975] | 0.814 | 0.637 |

Korean questions are the weakest (cause: §RAG-ERROR-ANALYSIS 2). With 20 questions per language the intervals overlap widely; only
"Korean is lower than Indonesian and Chinese" is supported by non-overlapping intervals.

## 5. By topic (held-out, production)

| Topic | n | R@1 | MRR@10 |
|---|---|---|---|
| dormitory | 5 | 1.00 | 1.000 |
| health insurance | 10 | 0.90 | 0.950 |
| TOPIK | 5 | 0.80 | 0.900 |
| daily living | 5 | 0.80 | 0.900 |
| residence card | 20 | 0.75 | 0.820 |
| university announcements | 5 | 0.80 | 0.800 |
| academic procedures | 15 | 0.60 | 0.687 |
| housing | 5 | 0.60 | 0.667 |
| part-time employment | 10 | 0.40 | 0.592 |
| **visa / immigration** | 20 | **0.30** | **0.506** |

Topics with 5 questions are anecdotal. Visa / immigration is the most important weak spot (analysis in RAG-ERROR-ANALYSIS §1).

## 6. Coverage and speed (held-out, production)

* 13 of the 15 documents that are relevant to some held-out question are ranked first for at least one of their questions (0.87).
* Search latency in-process on the workstation CPU: p50 107 ms, p95 127 ms (vector only: p50 22 ms). The hybrid makes up to three dense
  queries plus a keyword query. **Hosted latency on Render (0.1 CPU) is not measured here** (see [PERFORMANCE.md](PERFORMANCE.md)).

## 7. Answers (grounded generation)

ANSWER_SECTION_PLACEHOLDER

## 8. What a student can expect (plain statement for slides)

* For a question in any of the five languages, the right official document is **among the first 10 passages the model reads in 94 %** of
  held-out questions and **ranked first in 63 %** (AI-drafted labels, 100 questions, 95 % interval 53–72 %).
* Hybrid retrieval beats plain vector search by **+0.10 MRR** (interval +0.05 to +0.16) on unseen questions.
* Korean questions and visa questions are the weakest; long general guidebooks crowd out specific notices.
