# Milestone 5 - multilingual reranking and error analysis (preliminary)

All results below are **preliminary**: questions and relevance labels are AI-drafted and not human-reviewed. The held-out
set v0.2 was never used for tuning but its results were inspected in Milestone 4 ("inspected, untuned"). Local
experiments (Apple M1; reranking on the GPU via MPS, CPU for the first development rows) on identical frozen candidate pools (≤ 20 chunks); corpus snapshot
c64d186541928a2b (corpus_v1); embedding multilingual-e5-small (ONNX int8).

## Held-out results (n = 100 questions, 20 scenarios, 5 languages)
| method       |   r1 |   r3 |   r5 |   r10 |   ndcg5 |   ndcg10 | MRR                  |
|:-------------|-----:|-----:|-----:|------:|--------:|---------:|:---------------------|
| B0           | 0.64 | 0.79 | 0.85 |  0.86 |   0.707 |    0.717 | 0.724 [0.636, 0.802] |
| B0F          | 0.65 | 0.81 | 0.88 |  0.89 |   0.731 |    0.741 | 0.741 [0.652, 0.817] |
| B0FR_bge-m3  | 0.77 | 0.86 | 0.88 |  0.89 |   0.8   |    0.804 | 0.819 [0.731, 0.900] |
| B0FR_mminilm | 0.75 | 0.89 | 0.89 |  0.89 |   0.802 |    0.802 | 0.818 [0.735, 0.895] |
| E1           | 0.53 | 0.78 | 0.84 |  0.85 |   0.643 |    0.648 | 0.649 [0.553, 0.742] |
| E2           | 0.67 | 0.83 | 0.91 |  0.94 |   0.763 |    0.777 | 0.769 [0.680, 0.852] |
| E2S          | 0.61 | 0.84 | 0.87 |  0.87 |   0.723 |    0.723 | 0.729 [0.627, 0.823] |
| E3_bge-m3    | 0.8  | 0.91 | 0.93 |  0.94 |   0.844 |    0.847 | 0.858 [0.787, 0.923] |
| E3_mminilm   | 0.78 | 0.93 | 0.94 |  0.94 |   0.845 |    0.847 | 0.857 [0.790, 0.920] |
| E4_bge-m3    | 0.7  | 0.9  | 0.91 |  0.91 |   0.792 |    0.792 | 0.797 [0.714, 0.871] |
| E4_mminilm   | 0.68 | 0.91 | 0.91 |  0.91 |   0.787 |    0.787 | 0.792 [0.698, 0.878] |

`[a, b]` = 95% cluster-bootstrap interval over scenarios.

## Key paired comparisons (held-out MRR)
- E3 (hybrid + bge-reranker-v2-m3) vs E2: +8.8 pp [+1.9, +15.2] (supported)
- E3 (hybrid + mMiniLM) vs E2: +8.8 pp [+2.5, +14.7] (supported)
- B0R (dense top-20 pool without threshold + bge-m3, method B0FR) vs B0: +9.5 pp [+2.5, +16.9] (supported)
- E4 (+ evidence selection) vs E3 (bge-m3): -6.0 pp [-11.3, -1.3] (supported)
- E2 vs B0: +4.6 pp [-1.4, +11.1] (inconclusive); E2 vs E1: +12.0 pp [+4.7, +20.6] (supported)

Holm-corrected held-out MRR comparisons supported: E3_bge-m3 vs B0, E2 vs E1, E3_mminilm vs E2, B0FR_bge-m3 vs B0, E3_bge-m3 vs E2.

## Cost
Median local time per question (Apple M1; first stage CPU, reranking GPU/MPS): E2 51 ms; E3 bge-m3 3941 ms;
E3 mMiniLM 404 ms.

## Not evaluated
Answer quality per retrieval pipeline (no working primary Gemini model locally, no human scores); human-reviewed final test set.
