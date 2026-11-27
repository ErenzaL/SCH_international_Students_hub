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
and 60 % (TEST unanswerable + not-in-sources), not 100 %. The synthetic unanswerable questions were far from every
document, while real ones sit next to related text (home internet for campus Wi-Fi, the residence-card fee for a
student-ID fee).

## 3. Results

ANSWER_RESULTS

## 4. Conflicting and missing information

ANSWER_CONFLICT

## 5. Evidence gate on answers (simulated `enforce`)

ANSWER_GATE

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
