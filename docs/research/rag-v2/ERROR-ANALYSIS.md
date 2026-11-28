# Error analysis — retrieval failures (DEV + VALIDATION)

Data: baseline on real PostgreSQL + pgvector (`E2_dev_postgres.json`, `E2_val_postgres.json`), 200 questions,
40 information needs, 5 languages. TEST is not used here (it stays blind until the final run). The taxonomy is
deterministic (`scripts/rag_v2/failure_taxonomy.py`), so it can be re-applied to every later run. Labels are
AI-drafted (DATASET-CARD.md).

A **miss** = the primary document is not ranked first. A **harmful miss** = the primary document is not even among
the ≤ 4 sources the answer model reads (it can then only answer from secondary sources, or not at all).

## 1. Failure taxonomy

| Cause (first rule that applies) | DEV misses | of which harmful | VAL misses | of which harmful | Total harmful |
|---|---|---|---|---|---|
| `same_language_pull`: question and primary document in different languages, top document in the question's language | 10 | 6 | 13 | 9 | **15** |
| `hub_first`: one of the two long guidebooks ranked first | 12 | 1 | 18 | 4 | 5 |
| `korean_doc_first`: a Korean document first for a non-Korean question about a non-Korean primary | 6 | 1 | 11 | 4 | 5 |
| `sibling_first`: another labelled (partially relevant) document first | 2 | 2 | 2 | 0 | 2 |
| `starved`: < 4 passages survived the 0.80 similarity threshold | 0 | 0 | 1 | 1 | 1 |
| `other` | 1 | 0 | 3 | 2 | 2 |
| **all** | **31** | **10** | **48** | **20** | **30** |

The most frequent cause (`hub_first`) is mostly harmless. The most harmful one is the **language** of the documents,
not their length.

## 2. Cross-language retrieval is the main weakness

Baseline by (question language → language of the primary document), DEV + VALIDATION:

| Pair | n | hit@1 | MRR | primary reaches the model |
|---|---|---|---|---|
| same language (en→en, ko→ko) | 40 | 0.78 | 0.871 | **1.00** |
| zh → ko | 10 | 1.00 | 1.000 | 1.00 |
| vi → ko | 10 | 0.90 | 0.933 | 1.00 |
| id → ko | 10 | 0.80 | 0.850 | 0.90 |
| id → en | 30 | 0.67 | 0.790 | 0.97 |
| zh → en | 30 | 0.63 | 0.731 | 0.87 |
| en → ko | 10 | 0.40 | 0.510 | 0.60 |
| vi → en | 30 | 0.37 | 0.570 | 0.80 |
| **ko → en** | 30 | **0.30** | **0.439** | **0.53** |

(Korean-primary needs are announcements, which the glossary bridge and code matching handle well. That is why
zh / vi → ko is easy.)

**Korean questions about English documents** are the worst case: the primary document reaches the model for only
about half of them. Real examples (VALIDATION):

| Question | Primary (rank) | Ranked first instead |
|---|---|---|
| 비자 연장 신청이 처리 중일 때 해외여행을 가도 되나요? | Travel and Re-entry Documents (9) | 외국인학생취업관련 정보, then the illegal-work notice: unrelated topics, but Korean |
| 15일이 지나서 체류지 변경 신고를 하면 어떻게 되나요? | Change of Address in South Korea (10) | Resident Card in South Korea, 외국인학생취업관련 정보 |
| 유학생은 한국에서 아르바이트를 할 수 있나요? 주당 몇 시간까지 가능한가요? (DEV) | Part-Time Employment … (6) | 외국인학생취업관련 정보, the Korean guidebook, the illegal-work notice |
| 한국에서 대중교통 요금은 얼마인가요? | Living Costs and Expenses (not returned) | only the Korean guidebook survived the 0.80 threshold |

The same two short Korean documents (96b0fee4 "외국인학생취업관련 정보", 0c3a24ef illegal-work notice) also come first
for Chinese and Vietnamese visa questions (`korean_doc_first`), for example "签证延期申请还在审理中时可以出国旅行吗？".
The multilingual-e5-small embedding places a question close to documents in its own language, or close to
generic Korean immigration text, before it places it close to the English document on the topic.

**Production differs here.** With Gemini enabled, the rewrite adds an English and a Korean variant of every question
(BASELINE-AUDIT §1). That is exactly what these misses lack. Without a Gemini key it cannot be measured here
(BLOCKERS B1). Phase 8 measures an upper bound (perfect translation) and a local-model proxy.

## 3. Visa and immigration

VALIDATION visa-immigration: hit@1 0.30, primary in context 0.60 (DEV: 0.95 / 1.00, because DEV's visa needs are
D-2 extension questions with an explicit code that the code matcher catches). The VALIDATION visa needs have no
code in the question (travel while an extension is pending, stay expiring abroad, D-10). Their misses are
cross-language pulls (ko, vi, zh), and for English questions the English guide is ranked first.

## 4. The guidebooks ("guidebook domination")

- They hold 455 of 749 chunks (61 %). A hub guide is among the model's sources in **81 % (DEV) / 82 % (VAL)** of all
  questions and takes on average 1.0 of the ~3.8 source slots.
- A hub is ranked first for 17 (DEV) / 21 (VAL) questions whose primary is another document. In 14 / 17 and 15 / 21
  of them the primary still reaches the model, and in 5 / 17 and 9 / 21 the guide itself is labelled partially
  relevant.
- So the guidebooks mostly **cost a source slot and the first position** rather than hiding the answer.
- The Korean guidebook is also a victim: **58 % of its text is not indexed** (BASELINE-AUDIT, stage 3). It is
  retrieved for its remaining 42 % while its lost sections (for example the part-time exemption, the 15-day departure
  rule after leave of absence) cannot be found at all.

## 5. Hypotheses to test (all on DEV, confirmed on VALIDATION, TEST only at the end)

| # | Hypothesis | Experiment |
|---|---|---|
| H1 | Indexing the lost text makes the Korean guidebook's answers findable (and may increase its pull) | chunker v2 (Phase 3) |
| H2 | An English variant of non-English questions removes most `same_language_pull` misses | oracle variant (the English version of the same need) = upper bound; local-model rewrite = proxy (Phase 8) |
| H3 | Scaling down long documents (`retrieval_hub_beta`, exists, off) frees source slots without losing guide answers | hub_beta sweep (Phase 4) |
| H4 | The 0.80 threshold starves cross-language questions | lower thresholds; measure unanswerable questions at the same time (Phase 4 / 6) |

## 6. What the final TEST run added (T1–T3, one look, P2)

| Hypothesis | Outcome on TEST |
|---|---|
| H1 chunker v2 makes lost text findable | yes: 57 / 57 gold quotes indexable (v1 54); neutral on the rewrite path, −0.049 single-query MRR without it (post-hoc) |
| H2 variants in the evidence's language fix the pull | **yes**: gold quote in context 0.642 → 0.858; cross-language questions 0.579 → 0.842 |
| H3 hub scaling frees slots without losing guide answers | **no**: +0.008 MRR where no guide answers, **−0.112** where a guide is a grade-2 source (50 questions) |
| H4 the threshold starves cross-language questions | not separately testable; the gate study below shows that similarity is a weak signal |

**Lesson about labels.** Hub scaling looked good on DEV / VALIDATION because their labels name the specific document and
rarely credit a guidebook that also answers. Only exhaustively graded labels (TEST: every document mentioning the need's
terms read and graded) exposed the cost. Any future ranking change must be judged on labels that credit every document
that answers.

## 7. Failure modes found in the answer and injection runs (local proxy model)

| Failure | Example | Caught by | Status |
|---|---|---|---|
| **entity substitution with a correct figure** | "student ID reissue fee?" → "KRW 35,000", the residence-card fee, cited to the residence-card article | nothing: the figure is in the cited source. The gate (log mode) flagged 2 of the 3 language versions as insufficient | open; needs an entity check or `enforce` after Gemini validation |
| obeying orders in an approved document | "D-2 extensions are free" taken from a planted note; a planted password repeated | `injection.screen_passage` (new) | fixed: 11 / 11 after, 7 / 11 before |
| translated system-prompt leak | Indonesian paraphrase of the hidden answering rules | `injection.asks_for_instructions` + `discloses_instructions` (new) | fixed |
| figure cited to the wrong source | 7 of 112 checked sentences (DEV / VAL answers) | `citation_check` (new) re-attributes | fixed where exactly one source holds the figures |
| generic, ungrounded "how-to" for a negative | campus Wi-Fi steps built from a home-internet passage | gate flagged all five as insufficient (log mode) | open; same decision as the first row |

## 8. The evidence gate does not transfer (G-T)

Thresholds tuned on DEV + VALIDATION + DEV-negatives refuse **18 %** of TEST answerable questions on the rewrite path
(14 % with the gold quote in context) against 2–3 % during tuning, and catch 40 % of TEST unanswerable questions
(77 % of the negatives). TEST questions do not echo the documents' wording (labelling guideline §2): median best
similarity 0.872 vs 0.889, keyword coverage 0.566 vs 0.763. A similarity / keyword threshold is phrasing-dependent, so
it stays a logged signal (`log`), not a blocker.
