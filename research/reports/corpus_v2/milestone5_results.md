# Milestone 5 - multilingual reranking and error analysis (preliminary)

All results below are **preliminary**: questions and relevance labels are AI-drafted and not human-reviewed. The held-out
set v0.2 was never used for tuning but its results were inspected in Milestone 4 ("inspected, untuned"). Local
experiments (Apple M1; reranking on the GPU via MPS, CPU for the first development rows) on identical frozen candidate pools (≤ 20 chunks); corpus snapshot
da5caf39ff512c73 (corpus_v2); embedding multilingual-e5-small (ONNX int8).

## Held-out results (n = 100 questions, 20 scenarios, 5 languages)
| method       |   r1 |   r3 |   r5 |   r10 |   ndcg5 |   ndcg10 | MRR                  |
|:-------------|-----:|-----:|-----:|------:|--------:|---------:|:---------------------|
| B0           | 0.54 | 0.76 | 0.83 |  0.83 |   0.647 |    0.656 | 0.651 [0.564, 0.736] |
| B0F          | 0.55 | 0.77 | 0.85 |  0.85 |   0.664 |    0.673 | 0.663 [0.575, 0.745] |
| B0FR_bge-m3  | 0.72 | 0.82 | 0.84 |  0.85 |   0.747 |    0.75  | 0.774 [0.690, 0.852] |
| B0FR_mminilm | 0.67 | 0.85 | 0.85 |  0.85 |   0.742 |    0.745 | 0.758 [0.670, 0.842] |
| E1           | 0.47 | 0.73 | 0.78 |  0.79 |   0.594 |    0.597 | 0.600 [0.500, 0.692] |
| E2           | 0.6  | 0.8  | 0.86 |  0.88 |   0.7   |    0.717 | 0.706 [0.610, 0.800] |
| E2S          | 0.59 | 0.79 | 0.84 |  0.84 |   0.679 |    0.679 | 0.688 [0.582, 0.789] |
| E3_bge-m3    | 0.72 | 0.84 | 0.87 |  0.88 |   0.768 |    0.771 | 0.787 [0.696, 0.870] |
| E3_mminilm   | 0.69 | 0.87 | 0.88 |  0.88 |   0.77  |    0.774 | 0.781 [0.686, 0.868] |
| E4_bge-m3    | 0.66 | 0.8  | 0.86 |  0.86 |   0.727 |    0.727 | 0.737 [0.652, 0.821] |
| E4_mminilm   | 0.6  | 0.82 | 0.88 |  0.88 |   0.726 |    0.726 | 0.718 [0.621, 0.814] |

`[a, b]` = 95% cluster-bootstrap interval over scenarios.

## Key paired comparisons (held-out MRR)
- E3 (hybrid + bge-reranker-v2-m3) vs E2: +8.0 pp [+1.7, +14.0] (supported)
- E3 (hybrid + mMiniLM) vs E2: +7.5 pp [+2.4, +12.2] (supported)
- B0R (dense top-20 pool without threshold + bge-m3, method B0FR) vs B0: +12.4 pp [+4.7, +20.1] (supported)
- E4 (+ evidence selection) vs E3 (bge-m3): -5.0 pp [-10.2, +0.4] (inconclusive)
- E2 vs B0: +5.5 pp [-0.4, +12.0] (inconclusive); E2 vs E1: +10.6 pp [+3.4, +18.8] (supported)

Holm-corrected held-out MRR comparisons supported: E3_bge-m3 vs B0, B0FR_bge-m3 vs B0, E3_mminilm vs E2, B0FR_bge-m3 vs B0F, E2 vs E1, E3_bge-m3 vs E2.

## Cost
Median local time per question (Apple M1; first stage CPU, reranking GPU/MPS): E2 61 ms; E3 bge-m3 3700 ms;
E3 mMiniLM 414 ms.

## Not evaluated
Answer quality per retrieval pipeline (no working primary Gemini model locally, no human scores); human-reviewed final test set.
