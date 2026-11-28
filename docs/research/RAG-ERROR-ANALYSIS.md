# RAG error analysis

Source: the held-out run of `scripts/rag_research_eval.py` (production configuration) and a per-question inspection of its misses
(2026-11-27), plus the answer benchmark. Numbers refer to the held-out set unless stated.

## 1. The main failure: general guidebooks outrank specific documents

37 of 100 held-out questions do not have a relevant document at rank 1. Where the miss goes:

| Rank of the first relevant document | Questions |
|---|---|
| 2 | 14 |
| 3 – 5 | 9 |
| 6 – 10 | 8 |
| not in the first 10 | 6 |

The documents that most often take rank 1 by mistake:

| Wrongly ranked first | Times |
|---|---|
| 외국인학생취업관련 정보 (employment guide for international students, long) | 12 |
| 한국 유학생 생활 가이드북 (Korean student-life guidebook, long) | 7 |
| Guide for International Student in Korea (long) | 7 |
| Resident Card in South Korea | 3 |

These are long documents that mention almost every topic once. Examples of what they pushed down (all five languages behaved alike):

| Question (held-out) | Should be first | Was first |
|---|---|---|
| H04 "Can I travel abroad while my visa extension application is pending?" (en, ko, id, vi, zh) | Travel and Re-entry Documents | D2 visa extension / guidebooks |
| H05 "What happens if my period of stay expires while I am outside Korea?" (5 languages) | Travel and Re-entry Documents | Guide for International Student in Korea / guidebooks |
| H06 "How do I change from D-2 to the D-10 job-seeking visa after graduation?" (en, ko, vi) | Changing visa status | employment guide / Guide for International Student |
| H07 "D-2-7 일-학습 연계 유학 비자는 무엇인가요?" (ko) | Residence Eligibility and Stay Duration | employment guide |

This explains the two weak spots of RAG-RESULTS: **visa / immigration** (R@1 0.30; 14 of the 37 misses) and **Korean** questions (the
Korean guidebooks share most words with a Korean question).

**Why it is less harmful than R@1 suggests:** the assistant reads 10 passages, so the specific document is still in the model's context
for 94 % of the questions (R@10). The answer can be right while the first citation is a guidebook; the answer benchmark (§3) measures that.

**What was tried and NOT adopted:** a length penalty for long documents (`RETRIEVAL_HUB_BETA`) and a cross-script weight
(`RETRIEVAL_CROSS_SCRIPT_WEIGHT`) improved the development sets but failed the blind sets ([KOREAN-RETRIEVAL.md](../development/KOREAN-RETRIEVAL.md));
both stay off. A cross-encoder reranker gained +7–9 MRR points in earlier research but needs ~120 MB more memory than the free plan has.

**Not done on purpose:** tuning on this held-out set. The misses above are now known, so this set is no longer blind for a length
penalty; a new held-out set (or the human-reviewed one) is needed before the next ranking change. Pre-registered next experiment:
the reranker and a length penalty on a fresh 100-question set, adopted only if MRR improves with a paired interval above zero.

## 2. Korean questions

Held-out Korean MRR 0.505 vs. 0.912 for Indonesian. Two causes seen in the misses: (1) the Korean guidebooks (§1) match Korean wording
of every topic; (2) Korean questions use the official terms (체류기간, 재입국) that appear in many documents, while questions in other
languages are bridged only to the specific glossary terms. English questions about Korean documents were the weak case in earlier work;
on this held-out set English is 0.767 (vector-only 0.787: the hybrid did not help English here, difference within noise).

## 3. Answer-stage errors (answer benchmark, Qwen 2.5 7B + RAG)

| Category | Example | Handling in the product |
|---|---|---|
| passed deadline asked as "can I still apply?" | answered without a citation in vi / zh-CN | falls back to the source list, never a wrong date |
| brand or event names | 김장 event not found from a Vietnamese question without the Korean word | the supporter desk; clearer question |
| two dates in one notice | exam date given as the deadline (1 of 95, zh-CN) | always shown with its citation |
| no model (excerpts only) | 60 % of unanswerable questions show something unrelated | labelled "closest information", never as an answer |

No answer gave a stale or contradicting figure in either Qwen run (0 / 95), and every unanswerable question was refused.

## 4. Data and label risks

* Labels are AI-drafted: a "miss" may be a label error (e.g. a guidebook that really answers the question). The human worksheet is the fix.
* The corpus has 27 documents; with a larger corpus the hub-document problem is expected to grow, not shrink.
* Visa codes are handled by rule (code-mismatch penalty); questions that name no code rely on the glossary.

## 5. Implications

1. Before more ranking work, get people to review the labels and add specific documents (TOPIK, scholarships, leave of absence) — the
   content gaps listed in [FINAL-READINESS.md](../development/FINAL-READINESS.md) matter more than ranking tweaks.
2. Splitting the long guidebooks into section documents (one per topic) would attack the cause directly without a ranking change; it is
   a content decision for the owner (it changes what reviewers approve).
3. Keep reporting R@10 and answer correctness next to R@1: they describe what students experience.
