# RAG evaluation

**What the labels are.** All questions, translations and labels were written by an AI assistant; no person has checked them. They measure differences
between two versions of the system. They are **not** proof of accuracy for students. A human-checked set is open ([docs/review](../review/README.md)).

## 1. Retrieval alone (no model answers)

Public Hub documents (27, 749 chunks), production embedding model `multilingual-e5-small` int8, document level.

| Set | Version | R@1 | R@5 | MRR | nDCG@5 | P@5 | best document first |
|---|---|---|---|---|---|---|---|
| pilot, 100 questions (used while developing) | `main` | 0.640 | 0.940 | 0.774 | 0.683 | 0.302 | 0.570 |
| | **candidate** | **0.760** | **0.980** | **0.853** | **0.744** | **0.320** | **0.690** |
| **held-out, 100 questions** (evaluated once, never used for tuning) | `main` | 0.520 | 0.840 | 0.657 | 0.660 | 0.234 | 0.470 |
| | **candidate** | **0.630** | **0.860** | **0.729** | **0.714** | **0.238** | **0.520** |

| MRR by language (held-out) | ko | en | id | vi | zh-CN |
|---|---|---|---|---|---|
| `main` | 0.475 | 0.735 | 0.804 | 0.539 | 0.733 |
| candidate | 0.475 | 0.762 | 0.912 | 0.642 | 0.852 |

P@5 is low by construction (few relevant documents exist). Korean did not improve: short Korean notices lose against the long Korean guidebook.
Reproduce: `eval_retrieval_benchmark.py` (pilot); the held-out set is on `research/milestone-5` (read only).

**What changed:** concept bridge (glossary terms of the question searched in official Korean and English, no model call; 17 → 70 concepts); newest edition of a
notice first; copies of one notice count once; cached question vectors.

## 2. Answers (95 questions, 5 languages, synthetic documents with invented figures)

Invented figures: a model cannot know them, so "correct" means "taken from the source".

| | correct | answerable | unanswerable refused | stale or wrong figure | unusable | right language | ms median / p95 |
|---|---|---|---|---|---|---|---|
| before (Release A + B), Qwen | 0.800 | 0.788 | 0.90 | 0.000 | 0.189 | 1.00 | 1846 / 2346 |
| **after**, Qwen, run 1 | 0.926 | 0.918 | 1.00 | 0.000 | 0.000 | 1.00 | 2128 / 2851 |
| **after**, Qwen, run 2 | 0.916 | 0.906 | 1.00 | 0.000 | 0.021 | 1.00 | 2105 / 2889 |
| excerpts only (no model) | 0.874 | 0.906 | 0.60 | 0.024 | 0.000 | 0.54 | 22 / 28 |
| Qwen **without** sources | 0.000 | 0.000 | 0.00 | 0.000 | 0.000 | 1.00 | 1345 / 2992 |
| Gemini + RAG | **NOT TESTED**: no key here (`GEMINI_LAB_KEY`) | | | | | | |

"Right language" was not measured for "before". Cited documents were right in 93–94 % (after), retrieved in 99–100 %.

| Language | before | after (two runs) |
|---|---|---|
| ko | 0.95 | 1.00 / 1.00 |
| en | 0.68 | 0.95 / 0.90 |
| id | 0.90 | 0.95 / 0.95 |
| vi | 0.74 | 0.90 / 0.90 |
| zh-CN | 0.74 | 0.84 / 0.84 |

| Kind | before | after (two runs) |
|---|---|---|
| duplicate | 0.80 | 1.00 / 1.00 |
| fact | 0.78 | 0.93 / 0.93 |
| injection | 1.00 | 1.00 / 1.00 |
| passed | 0.60 | 0.80 / 0.60 |
| stale | 0.80 | 0.87 / 0.87 |
| unanswerable | 0.90 | 1.00 / 1.00 |

**What changed:** figures compared by value (`09` = `9`, `3,35` = `3.35`); one retry for an answer without citations or in the wrong language; lone markers kept;
passed deadlines, older editions and different figures are told to the model; a source cannot close its tag; a second look by the local model (copy the words that
answer the question: 98.8 % of right sources accepted, 0 % of wrong ones). **Tried and dropped:** warning about question words that no source contains
(it fired on 81 % of answerable questions).

## 3. Error categories that remain

| Category | Example | Handling |
|---|---|---|
| deadline passed | "Can I still apply?" answered without citation in vi / zh-CN | falls back to the source list, never a wrong date |
| brand names | 김장 event not found from a Vietnamese question without the Korean word | supporter / clearer question |
| Korean retrieval | guidebook before the specific notice | reranker (research: +7–9 points MRR, needs about 120 MB more memory than the free plan has; code ready, `RERANK_PROVIDER=onnx`, off) |
| two dates in one notice | exam date given as deadline (1 of 95, zh-CN) | verify in the source; shown with citation |
| no model (excerpts only) | 60 % of unanswerable questions show something unrelated | labelled "closest information" |

## 4. Recommended production settings

`RETRIEVAL_MIN_SIMILARITY=0.80`, `RETRIEVAL_BRIDGE_WEIGHT=0.75`, `RERANK_PROVIDER=none`, `ASSISTANT_EVIDENCE_CHECK=false`, `ASSISTANT_VERIFY_LOCAL=true` (no effect with Gemini).
The bridge adds at most two vector queries and only when the model rewrite is not available. Gemini answers may cost one extra call when an answer is
unusable; the daily limits apply.
