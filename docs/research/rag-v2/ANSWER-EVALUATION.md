# Answer evaluation

**Every answer here was written by a local proxy model (Qwen 2.5 7B on the school GPU, loopback Ollama, temperature 0),
which also did the query rewrite. These numbers describe the pipeline with that model. They are not Gemini numbers.**
Gemini is the production model and is unmeasured (§6).

## 1. Method (`scripts/rag_v2/answer_eval.py`)

The full assistant turn `AssistantEngine.respond()`: rewrite → retrieval → evidence selection → injection screen →
evidence gate (log) → generation → citation and figure checks → fallbacks. In-memory index of the 27 public documents
(chunker v1, as released). Deterministic metrics only (no model judges another model):

| Metric | Definition |
|---|---|
| abstained | the answer is the "not in the approved sources" class (`evidence` none / unavailable) |
| refusal phrase | heuristic: the text says "not found / no information" in one of five languages (reported, never used for claims) |
| figure recall | TEST: share of the gold figures (numbers in the gold quotes **and** the reference answer, minus figures repeated from the question) that appear in the answer; an abstention scores 0 |
| cited grade-2 / cited relevant | share of the cited sources that are grade-2 / grade ≥ 1 documents |
| cited has gold quote | TEST: a cited passage contains a gold quote |
| invented figure | unanswerable / not-in-sources: the answer states a figure (≥ 2 digits) not taken from the question |
| wrong language | the engine's own language check on the final answer |

**Fair closed-book baseline**: the same model, the same real-corpus questions, a neutral system prompt, no sources.

## 2. Why the earlier "0 % without sources" was an artefact

The release candidate's slide headline ("without sources the model answered 0 of 95 correctly; with retrieval
91.6 %; every unanswerable question refused") came from a benchmark of **synthetic documents with invented
figures**. No model can know an invented figure without the document, so 0 % measured the benchmark design, not the
value of retrieval. The fair baseline asks real questions about the real corpus, where general Korean rules (15-day
address report, TOPIK levels) can be known without sources and SCH-specific facts (dates, fees, rooms) cannot.

The refusal headline did not survive either. On real-corpus negatives the proxy abstained on **60 %** (DEV-negatives)
and 60 % (TEST unanswerable + not-in-sources), not 100 %, although on TEST it stated no invented figure. The synthetic unanswerable questions were far from every
document, while real ones sit next to related text (home internet for campus Wi-Fi, the residence-card fee for a
student-ID fee).

## 3. Results

TEST (frozen, 210 questions; `A9_test_memory_answers.json`), retrieval = RC configuration, real rewrite step with the
proxy model; 95 % intervals over needs:

| Answerable + conflicting (190) | with retrieval | closed book (same model, no sources) |
|---|---|---|
| **figure recall** (gold figures stated in the answer) | **0.59 [0.38, 0.78]** | **0.02 [0.00, 0.07]** |
| abstained | 0.163 [0.10, 0.23] | 0.00 (never abstains; "not known" phrases in 15 %) |
| cited sources that are grade-2 / grade ≥ 1 | 0.751 / 0.802 | — |
| a cited passage contains a gold quote | 0.733 [0.61, 0.84] | — |
| wrong language | 0.000 | 0.116 (English questions: 47 %, answered in Korean or Japanese) |
| fallbacks (no citations 1, output truncated 1) | 2 | — |

| Unanswerable (15) + not in sources (5) | with retrieval | closed book |
|---|---|---|
| abstained (formal "not in the approved sources" class) | 12 / 20 (unanswerable 10 / 15, not-in-sources 2 / 5) | 0 / 20 |
| stated an invented fee / figure | **0 / 20** (the automatic metric flags 2 Vietnamese / Chinese answers to the D-2-fee question; the only figure in them is the immigration number 1345, checked by hand) | 2 / 5 not-in-sources (KRW 30,000–40,000; "10–20") |

By language, with retrieval (figure recall / abstained): en 0.68 / 0.21, id 0.67 / 0.13, ko 0.66 / 0.11,
**vi 0.37 / 0.24**, zh-CN 0.57 / 0.13. Vietnamese is the weakest, in line with the proxy's Vietnamese rewrites
(MULTILINGUAL-RESULTS §3).

DEV + VALIDATION + DEV-negatives (A1; no gold figures in DEV / VAL): abstained 0.07 / 0.13 on answerable, 0.60 on
negatives; invented figure 3 / 35 negatives (the residence-card fee given as a student-ID fee); wrong language 0.

With hub scaling 0.1 instead of the RC ranking (A9h, registered in P2) nothing changes significantly: figure recall
0.633 (+0.043 [−0.074, +0.156]), abstained 0.147, cited passage with a gold quote 0.716 (−0.020 [−0.067, +0.026]);
negatives abstained 15 / 20, again 0 invented fees (three automatic flags, all the 1345 number). Hub scaling stays off
(it lost on TEST retrieval, RETRIEVAL-RESULTS §3).

**Reading.** Retrieval is what makes figures right: 59 % against 2 % closed book on the same real questions. The
remaining gap is partly abstention (16 % of answerable questions, more in Vietnamese) and partly passages that never
reach the model (RETRIEVAL-RESULTS §6).

## 4. Conflicting and missing information

- **WRK-02** (25 weekday hours in the 2026-reviewed article vs 20 in the 2021 guidebook): all five answers state
  **25 hours**, the newer value, and **none mentions the older source or the disagreement** (0 / 5 surfaced the
  conflict). The answer is the better-supported one, but the student is not told that an older official text says
  otherwise. The prompt's conflict instruction was not followed by the proxy; Gemini is unmeasured.
- **VIS-11** (D-2 extension fee, deliberately not stated by the sources): **no answer gives a fee** (5 / 5). Two are
  formal abstentions; three say in their own words that the fee is not specified and point to HiKorea / 1345.

## 5. Evidence gate on answers (simulated `enforce`)

Recomputed from the TEST answer rows (gate decision logged per answer): enforcing the frozen thresholds would raise
abstention on **answerable** questions from 31 to **60 of 190** (16 % → 32 %) and on unanswerable / not-in-sources
from 12 to 14 of 20. On DEV / VAL the same simulation added only 2–3 refusals. **Do not enforce**; the logged decision
stays useful for monitoring (PRODUCTION-READINESS §4).

## 6. Gemini: blocked, prepared

There is no Gemini key on the school server, and production secrets must not be copied here (B1). Prepared command
(owner, with their own key exported only in that shell):

```
cd backend
LLM_API_KEY=… .venv/bin/python ../scripts/rag_v2/answer_eval.py --provider gemini --split test --final \
    --config baseline --max-questions 210 \
    --prices "gemini-3.6-flash=IN/OUT,gemini-3.5-flash-lite=IN/OUT" --confirm-paid-run --tag G1
```

It refuses to start without the key, a question cap, owner-supplied prices (USD per million tokens, from the official
list) and `--confirm-paid-run`, and it prints the estimate first. **Size of a full TEST run**, from the proxy run's
measured prompts (A1: mean 4,958 input / 170 output tokens per answer, p95 6,538 / 414) plus one short rewrite call per
question: about **1.2 million input and 0.06 million output tokens** for 210 questions, before thinking tokens
(`GEMINI_THINKING_LEVEL=low`), which are billed as output. Gemini's tokenizer differs from Qwen's, so treat this as ±20 %.
Prices are not stated here: copy them from the official list on the day of the run.

## 7. Human rating

`scripts/benchmarks/results/rag_v2/A9_test_human_rating.csv` (and `A1_*`): one row per answer with H1 correct (0–2),
H2 complete (0–2), H3 faithful to the sources, H4 citations right, H5 language natural, H6 safe refusal / referral.
Not filled; no human rating exists yet.
