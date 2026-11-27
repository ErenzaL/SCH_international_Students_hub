# Final report — production-grade RAG reliability and research validation

Date 2026-11-27 · branch `research/rag-reliability-v2` · school workstation · details in the files listed in §13.
**Labels are AI-drafted and unreviewed; answer quality was measured with a local proxy model (Qwen 2.5 7B), not
Gemini; nothing is on staging or production.**

## 1. Executive summary

What actually improved, measured on a test set frozen before any experiment (210 questions, 42 needs, 5 languages):

1. **Query variants in the evidence's language are the biggest lever.** Adding the rewrite's English / Korean variants
   (production already asks Gemini for them; measured here with a local proxy) raises the share of questions whose
   gold evidence passage reaches the answer model from **64.2 % to 85.8 %** (+21.6 points [+14.7, +28.4]), and the share
   whose answer document does from 84.2 % to 97.4 %. Cross-language questions: 57.9 % → 84.2 %. The weak spot is
   therefore the **path without a rewrite** (no LLM, provider down, budget spent), which must be monitored.
2. **A chunking defect hid 13 % of the approved corpus** (58 % of the Korean guidebook) from search. Chunker v2 indexes
   all of it (TEST: 57 / 57 gold quotes indexable vs 54); it is neutral on the rewrite path and recovers evidence that was
   unreachable (VIS-05 0.0 → 0.4, VIS-10 0.6 → 1.0).
3. **Deterministic safety layers**: prompt-injection screens (7 / 11 → 11 / 11 cases, 0 false positives on the corpus
   and 410 questions), a per-citation support check (re-attributed 7 of 112 figure citations), an evidence gate in
   `log` mode with monitoring fields, and a real-PostgreSQL test that no unapproved, superseded, cancelled, archived,
   expired, not-yet-valid or inactive-source content can reach an answer.

What did **not** work, and was therefore not adopted: **hub scaling** (won on DEV and VALIDATION, lost on TEST:
−0.112 MRR on questions answered by a guidebook) and **enforcing the evidence gate** (thresholds tuned on DEV / VAL refuse
18 % of TEST's answerable questions).

## 2. Git status

ANSWER_GIT_STATUS

## 3. Baseline reproduction

| Split | Measure | RC result (`rag_research_*.json`) | Reproduced, memory (E0 / E1) | Reproduced, **real PostgreSQL + pgvector** (E2) |
|---|---|---|---|---|
| DEV | R@1 / R@10 / MRR (lenient) | 0.75 / 0.99 / 0.848 | 0.75 / 0.99 / 0.848 (E0); 0.76 / 0.99 / 0.853 (E1, seeded ties) | 0.76 / 1.00 / 0.853 |
| VALIDATION | R@1 / R@10 / MRR (lenient) | 0.63 / 0.94 / 0.736 | 0.63 / 0.94 / 0.736 | 0.63 / 0.95 / 0.735 |
| VALIDATION | MRR 95 % interval | [0.663, 0.807] (over questions) | — | **[0.635, 0.825] over needs** (one third wider; the five language versions of a need are not independent) |

Memory and PostgreSQL agree on the first relevant rank for 98 / 100 (DEV), 98 / 100 (VAL), 208 / 210 (TEST) questions.
Tie-break noise: ≤ 0.01 hit@1. Full audit of every pipeline stage: BASELINE-AUDIT.md.

## 4. Dataset validation

| Item | Value |
|---|---|
| TEST v0.3 | **210 questions = 42 needs × ko / en / id / vi / zh-CN**; frozen and committed before any experiment (question hash `52f216ed7e5d7d1f`, `build_testset.py --check`) |
| answerability | 37 answerable, 1 conflicting (25 vs 20 weekday hours), 1 not-in-sources (D-2 extension fee), 3 unanswerable (verified absent by exhaustive search) |
| topics | academic 35, visa 40, residence card 15, part-time work 25, dormitory 30, health 10, TOPIK 10, employment 10, admission 10, scholarship 5, records 5, unanswerable 15 (questions) |
| sources | 20 of 27 documents carry a grade-2 label; 56 grade-2 and 26 grade-1 labels; evidence in Korean documents for 23 needs, English 16; hub guides are a correct answer in 10 needs |
| evidence | 57 verbatim gold quotes, all validated against the corpus snapshot |
| provenance | written from the documents by an AI assistant (Claude), **never from retriever output**; every document mentioning a need's terms read and graded |
| human review | **none** (sheet `testset_v0.3_review.csv`, checklist HUMAN-REVIEW-CHECKLIST.md) |
| leakage checks | splits separated by information need: 17 of 40 first-draft needs that a DEV / VAL answer would contain were replaced; remaining overlap labelled per need (none 125 q, related 80 q, same_family 5 q); results are also reported for the `none` subset. DEV-negatives (35 q, gate tuning) are disjoint from TEST (tested) |
| other splits | DEV v0.1 and VALIDATION v0.2 (100 q each) kept unchanged; VALIDATION is not blind (inspected in the previous mission); their labels are not exhaustive (BLOCKERS B4); 5 DEV labels point outside the corpus and are dropped |

## 5. Retrieval results

TEST, 190 answerable questions, 95 % intervals over needs (memory store; PostgreSQL agrees, T3):

| Method | hit@1 | hit@3 | hit@10 | recall@10 | MRR | nDCG@10 | answer doc reaches the model | gold passage reaches the model |
|---|---|---|---|---|---|---|---|---|
| vector only (DEV / VAL, PostgreSQL) | 0.51 / 0.45 | | 0.78 / 0.76 | | 0.620 / 0.575 | 0.637 / 0.626 | | |
| existing hybrid (RC) | 0.647 [0.56, 0.73] | 0.800 | 0.942 [0.91, 0.97] | 0.928 | 0.742 [0.68, 0.80] | 0.765 [0.72, 0.81] | 0.842 [0.79, 0.89] | 0.642 [0.55, 0.73] |
| + hub scaling 0.1 (rejected) | 0.605 | | 0.947 | | 0.718 | 0.734 | 0.837 | 0.632 |
| **+ query variants (rewrite proxy)** | (same ranking per query) | | | | fused 0.731 | | **0.974 [0.95, 0.99]** | **0.858 [0.77, 0.94]** |
| + chunker v2 and variants (post-hoc) | | | | | fused 0.740 | | 0.968 | 0.874 |

Per-topic results and the DEV / VALIDATION tables: RETRIEVAL-RESULTS.md §1, §6. Weakest topic on TEST: admission
(the long admission guide is found, but its footnote / refund passages never reach the model).

## 6. Visa retrieval

- **Original failures** (VALIDATION, baseline, PostgreSQL): visa-immigration hit@1 0.30, primary document reaches the
  model 0.60. Questions without a visa code (travel while an extension is pending, a stay expiring abroad, D-10)
  failed. Korean, Vietnamese and Chinese versions retrieved two short Korean documents (employment info, illegal-work
  notice) instead of the English travel article; English versions retrieved the English hub guide first.
- **Root causes**: same-language pull of the embedding (the most harmful cause overall, 15 of 30 harmful misses), hub
  guides taking the first position (mostly harmless), and on TEST passage selection inside long documents.
- **Changes and measured results** (visa + residence card): DEV primary doc in context 0.97 → 1.00 with variants;
  VALIDATION 0.75 → 0.78; **TEST 0.90 → 1.00, gold passage 0.56 → 0.82**. Remaining weak TEST needs: VIS-05 (guidebook-only
  answer, 0.4 even with v2), VIS-10 (0.6 with v1, 1.0 with v2).

## 7. Korean and multilingual retrieval

TEST, gold passage reaches the model (baseline → with variants): en 0.53 → 0.84, ko 0.66 → 0.92, id 0.61 → 0.79,
vi 0.61 → 0.87, zh-CN 0.82 → 0.87; cross-language 0.58 → 0.84; same language 0.89 → 0.92. DEV + VAL: Korean questions
about English documents were the worst pair (hit@1 0.30, primary in context 0.53). The local rewrite proxy has
visible flaws (19 % of Vietnamese "standalone" questions written in Chinese; Chinese characters in 27 Korean variants)
and still gives the largest gain. Release 1 translation scope (ko / en / id) is unchanged. MULTILINGUAL-RESULTS.md.

## 8. Gemini RAG evaluation

ANSWER_SECTION_8

## 9. Faithfulness and citation reliability

ANSWER_SECTION_9

## 10. Safety and source integrity

| Check | Where | Result |
|---|---|---|
| unapproved (draft, pending), superseded version, cancelled, archived, expired, not-yet-valid, inactive-source content never returned by search in any mode, never selected for an answer, not counted by hub scaling (positive control found) | `tests/integration/test_rag_v2_visibility.py`, **real PostgreSQL + PostgREST + migrations** | 6 / 6 passed; the hidden versions have embedded chunks (the view hides them, the test is not trivial) |
| visibility view and function permissions | BASELINE-AUDIT §2 stage 6 (read); SQL behaviour suites | `searchable_chunks` revoked from anon / authenticated; `search_knowledge_v2` service-role only; 15 / 15 SQL suites passed |
| orders hidden in approved documents, prompt extraction, source override | `injection_eval.py` (local proxy), `test_injection_screen.py` | 7 / 11 → **11 / 11**; unit tests 14 / 14 |
| expired passages, older editions and copies of notices | `_select` (RC) + families tests | unchanged, tests pass |
| research data | — | public documents and AI-written questions only; no student data, no production credentials; Ollama and PostgreSQL loopback / socket only |

## 11. Performance

Measured A/B (separate processes, 200 questions): peak RSS 460 MB (RC settings) vs 437 MB (v2), `respond()` p50
110.0 vs 109.9 ms; the new checks cost 2 µs (gate), 0.1 ms (citations) and 0.7 ms (injection screen) per answer; the
hub cache is 3.5 KB. Search p50 85–92 ms on PostgreSQL. No new model or dependency, so Render compatibility is
unchanged from the RC's emulation (457 MB PSS peak with `MALLOC_ARENA_MAX=2`). A reranker (+120 MB) or a larger embedding
model would not fit in 512 MB. Hosted latency: not measured. PERFORMANCE.md.

## 12. Test results

ANSWER_SECTION_12

## 13. Research artifacts

| What | Where |
|---|---|
| TEST set, source, review sheet, term hits, hash | `scripts/benchmarks/rag_v2/testset_v0.3*.{json,csv,sha256}` |
| DEV-negatives | `scripts/benchmarks/rag_v2/dev_negatives_v0.1.json` |
| scripts | `scripts/rag_v2/` — `build_testset.py`, `lib.py`, `configs.py`, `retrieval_eval.py`, `answer_eval.py`, `compare.py`, `failure_taxonomy.py`, `gate_sweep.py`, `injection_eval.py`, `perf_check.py`, `regression.py`, `charts.py` |
| result files (every number in the reports) | `scripts/benchmarks/results/rag_v2/` (E*, T*, A*, J*, P1_perf_*, REGRESSION_REFERENCE.json, rewrites_qwen2.5-7b.json) |
| charts | `docs/research/rag-v2/figures/*.svg` |
| reports | `docs/research/rag-v2/` (README.md lists them) |
| product code | `backend/app/services/assistant/{gate,citation_check,injection}.py`, `chunking.py` (v2), `engine.py`, `conversations.py`, config settings; tests in `backend/tests/` |

## 14. Remaining limitations

- No human has validated a single label, question or answer (B2).
- Gemini answers and the Gemini rewrite are unmeasured; every answer number is a local 7B proxy (B1).
- DEV / VALIDATION labels are not exhaustive, which misled the hub-scaling selection; they should be regraded or retired (B4).
- The evidence gate's similarity thresholds do not transfer between question styles (B5); entity substitution
  (a correct figure for the wrong thing) is not caught by any deterministic check.
- Passage selection inside long documents (admission guide, guidebook-only answers) is the largest remaining retrieval
  gap.
- The TEST set is small (42 needs; 38 questions per language cell), dated (2026-2 course and winter-2026 dormitory
  notices) and specific to this corpus snapshot.
- The injection suite has 11 cases; two of them never retrieved the injected document.
- Not measured: hosted latency / memory, real traffic, the production index (only its stored text).

## 15. Required human actions

| For | Exact items |
|---|---|
| human label validation | native speakers (ko, en, id, vi, zh-CN) fill R1–R2, a domain reviewer from the international office fills R3–R6 in `testset_v0.3_review.csv`; a second reviewer grades 12 random needs (κ ≥ 0.6); build v0.3.1 from the corrections (HUMAN-REVIEW-CHECKLIST.md) |
| Gemini key setup | the key stays in Render / your machine, never on the school server or in the repository; for the benchmark, export `LLM_API_KEY` only in the shell that runs it |
| approved paid benchmark | copy current prices from the official Gemini price list, choose a cap, run `answer_eval.py --provider gemini --split test --final --max-questions N --prices "…" --confirm-paid-run` (prints the token-based estimate first) |
| reviewer checks | second-person code review of the branch; rate a sample of `A9_test_human_rating.csv`; review documents whose header says "REVIEW REQUIRED" / "Draft" (6 approved) |
| hosted staging | deploy the branch to staging, set `CHUNKER_VERSION=v2`, re-index, store a regression reference, run the monitoring query (PRODUCTION-READINESS.md §3–4) |
| final production verification | merge / deploy approval, re-index in production with v2, a few weeks of the monitoring query (rewrite failures, gate decisions, screened sentences) |

## 16. Final recommendation

ANSWER_SECTION_16
