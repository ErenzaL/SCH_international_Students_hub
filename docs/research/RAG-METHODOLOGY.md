# RAG methodology — SCH International Student Hub

Status: measured on the university GPU workstation, 2026-11-27, branch `school/rc-2026-11-27`. Results: [RAG-RESULTS.md](RAG-RESULTS.md).
Errors: [RAG-ERROR-ANALYSIS.md](RAG-ERROR-ANALYSIS.md). Languages: [MULTILINGUAL-EVALUATION.md](MULTILINGUAL-EVALUATION.md).

## 1. Research objective

International students at Soonchunhyang University ask about visas, registration, dormitories, insurance and jobs in five languages
(Korean, English, Indonesian, Vietnamese, Simplified Chinese), while almost all official sources are in Korean or English. The question:

> Can a free-tier, CPU-only retrieval system find the right **approved** official document for a question in any of the five languages,
> and does grounding the answer in that document make the assistant measurably more reliable than an ungrounded model?

## 2. Why retrieval-augmented generation instead of a general chatbot

| Need of a student | Ungrounded chatbot | RAG in the Hub |
|---|---|---|
| The current fee / deadline of *this* university | Invents a plausible number (measured: Qwen without sources answered **0 %** of the synthetic questions correctly, see RAG-RESULTS §3) | Quotes the approved document; the number comes from the source |
| Knowing whether information is official | No provenance | Every answer cites the approved document and links the original |
| Rules that change (a notice replaces another) | Training data is frozen | Only the current approved version is searchable; older editions are flagged |
| "I don't know" when nothing exists | Usually answers anyway | Refuses or shows the closest sources (unanswerable questions refused: 100 % with Qwen + RAG) |
| Staff control over what students see | None | A human approves every source version before it can be retrieved |

## 3. System under test (what actually runs)

```
question (ko/en/id/vi/zh-CN)
  └─ query analysis: visa codes (D-2, D-4-1 …), glossary concepts, language
      ├─ dense search: multilingual-e5-small (int8 ONNX, 384 dims) over approved chunks (pgvector)
      ├─ keyword search (PostgreSQL full text + trigram)
      └─ concept bridge: glossary terms of the question written out in official Korean and English → 2 extra, weaker dense queries
  └─ weighted fusion (vector 1.0, keyword 0.35, bridge 0.75), visa-code mismatch penalty 0.5, ≤ 3 chunks per document,
     newest edition of a notice first, copies of one notice counted once, similarity floor 0.80 (render.yaml; code default 0.0)
  └─ top 10 passages → answer model (Gemini in production; local Qwen 2.5 7B in these experiments) with the passages in tagged,
     untrusted blocks → citation check, answer-language check, one bounded retry
```

Only versions with `verification_status = approved` that are the current version of a public, non-cancelled document are indexed for
students ([database.md](../database.md)); pending edits, rejected versions and drafts are never retrievable (tests:
`test_only_approved_content_is_returned`, `test_c_d_webpage_fetch_approve_then_update_creates_pending_without_changing_answers`,
`test_students_cannot_reach_drafts`, and the RLS integration tests on real PostgreSQL).

Chunking: 320 target / 420 max tokens, 48 overlap, heading-aware (tables and lists kept together).

## 4. Data

| Set | Size | Use | Provenance |
|---|---|---|---|
| Corpus | 27 approved public documents (20 Knowledge Center guides, 7 announcements; 13 Korean, 14 English), 749 chunks | index | fetched from the public production API (no credentials), hash recorded in each result file |
| Development set `retrieval-pilot-0.1` | 100 questions = 20 scenarios × 5 languages | used while the retrieval was developed | drafted by an AI assistant, **not reviewed by a person** |
| Held-out set `retrieval-heldout-0.2` | 100 questions = 20 scenarios × 5 languages | frozen before its first evaluation; never used for tuning | drafted by an AI assistant after tuning ended; evidence terms checked automatically; **not reviewed by a person** |
| Answer benchmark `rag_behaviour_v1` | 95 questions (19 per language) over synthetic documents with invented figures | answer quality | synthetic on purpose: a model cannot know an invented fee, so a correct figure proves it came from the source |
| Cross-language set `crosslang_en_ko_v1` | development half measured; **held-out half not opened** | English → Korean evidence | waits for native review, then one pre-registered look ([CROSSLANG-EVAL.md](../development/CROSSLANG-EVAL.md)) |

Topics covered: visa/immigration, residence card, academic procedures, part-time employment, health insurance, dormitory, housing,
TOPIK, employment, university announcements, daily living. Question kinds: simple, procedure, multi-step, time-sensitive,
cross-language; the answer benchmark adds duplicate, stale, passed-deadline, unanswerable and prompt-injection cases.

Human validation: the label review worksheet is `research/data/review/label_review_worksheet.csv` (branch `research/milestone-5`) and
[docs/review](../review/README.md). Until people fill it, every percentage below is "agreement with AI-drafted labels".

## 5. Evaluation setup

* Index built exactly as production builds it (same chunker, same embedding model and quantisation, same ranking code), in an in-memory
  store that mirrors the SQL functions; script `scripts/rag_research_eval.py`, read-only, no model call.
* 10 passages per question, the same as the assistant (candidate pool 30); one passage per document so that the ranked list holds up to
  10 distinct documents (the document order is unchanged by this; checked: identical Recall@1).
* Four configurations on the same index and questions:
  `vector` (dense only) · `hybrid_legacy` (equal-weight RRF of `main` before Release A) · `hybrid_nobridge` (current ranking without the
  concept bridge) · `hybrid` (**production**).
* Every configuration ran on the development set and then once on the held-out set; no setting was changed in between.

## 6. Metrics (document level)

| Metric | Definition |
|---|---|
| Recall@k (k = 1, 3, 5, 10) | share of questions with at least one relevant document among the first k documents |
| MRR@10 | mean of 1 / rank of the first relevant document; 0 if it is not in the first 10 |
| nDCG@5, nDCG@10 | graded: the most specific relevant document ("primary") gain 2, other relevant documents gain 1; log2 discount |
| P@5 | relevant documents among the first 5, divided by 5 (low by construction: most questions have 1–3 relevant documents) |
| Top-1 primary | the most specific document is ranked first (stricter than Recall@1) |
| Coverage | share of the documents that are relevant to some question which are ranked first for at least one of their questions |
| Latency p50 / p95 | in-process search time on the school workstation CPU (no network, no database) — **not hosted latency** |

Answer metrics (rule-based, no model judge): correct (every required figure/term of the reference present and nothing contradicting),
fact recall, cited (the answer cites a document that contains the fact), retrieved (the needed document was in the context), stale or
wrong figure, unanswerable refused, answer in the question's language, latency.

## 7. Statistics

* 95 % intervals: percentile bootstrap over questions, 5,000 resamples, seed 7.
* Differences between configurations: **paired** bootstrap (the same resampled questions for both), 5,000 resamples; reported as the
  mean difference, its 95 % interval and `p(≤0)` = share of resamples in which the improvement vanishes.
* Proportions of the answer benchmark: Wilson 95 % intervals.
* With 20 questions per language, per-language intervals are wide (often ±0.15–0.20); differences between languages smaller than that
  are not claimed.

## 8. Reproduce

```bash
cd backend
EMBEDDING_PROVIDER=e5_onnx .venv/bin/python ../scripts/rag_research_eval.py --set dev
EMBEDDING_PROVIDER=e5_onnx .venv/bin/python ../scripts/rag_research_eval.py --set heldout
.venv/bin/python ../scripts/rag_lab.py --modes qwen,retrieval,nocontext      # answers; local Ollama, no paid API
```
Outputs: `scripts/benchmarks/results/rag_research_{dev,heldout}.json`, `rag_behaviour_*.json`. The corpus file is
`backend/.eval-cache/public_corpus.json` (git-ignored; re-fetch with `eval_retrieval_benchmark.py --fetch-corpus https://sch-hub-api.onrender.com`).

## 9. Limitations (read before quoting a number)

1. Labels are AI-drafted and not reviewed by people; the numbers measure agreement with those labels.
2. The corpus is small (27 documents). With few candidates, Recall@10 is close to 1 for any reasonable system; Recall@1 and MRR are the
   informative metrics.
3. Production answers use **Gemini**; Gemini + RAG is **not measured** (no API key on the development server, on purpose). The answer
   numbers are for local Qwen 2.5 7B + RAG.
4. Latency is in-process on the school workstation, not the 0.1-CPU Render service.
5. The answer benchmark is synthetic; it measures grounding behaviour, not the completeness of the Hub's real content.
