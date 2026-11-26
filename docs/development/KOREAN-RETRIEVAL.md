# Korean retrieval: what is weak, what was tried

Corpus: the 27 public Hub documents, production embedding model (multilingual-e5-small int8). Labels written by an AI assistant, **not checked by people**.

## 1. Diagnosis

| Finding | Evidence |
|---|---|
| A large part of the earlier "Korean weakness" (held-out MRR 0.475) was **missing labels**: the long Korean guidebook answers most Korean questions but was added to the corpus after the labels | with the AI-proposed extra labels of `research/milestone-5`: Korean pilot MRR 0.754 → 0.975, held-out 0.475 → 0.667 |
| Korean questions about **short Korean notices** work | new probe (8 notices × 5 languages): Korean MRR **1.000** |
| **English** questions about Korean notices do not | the same probe: English MRR **0.271** |
| The real pattern: **hub documents**. Long, general documents, above all three Korean ones (85,000-character guidebook, admissions guide, employment overview) come first in most misses | first blind set: of 24 misses, 15 had one of these three first and 4 the 157,000-character English guide |

## 2. Experiments (development sets: pilot, probe; the held-out set was inspected in this round and is no longer blind)

**A. Concept bridge for one-concept questions.** Probe English 0.271 → 0.35, pilot unchanged. Not kept.

**B. Cross-script concept titles** (an English question, a Korean notice whose title holds the question's glossary concepts):

| Set | MRR off | MRR on | ko off | ko on | en off | en on |
|---|---|---|---|---|---|---|
| pilot | 0.853 | 0.863 | 0.754 | 0.854 | 0.900 | 0.900 |
| pilot+sens | 0.944 | 0.954 | 0.975 | 0.975 | 0.900 | 0.925 |
| held | 0.729 | 0.684 | 0.475 | 0.688 | 0.762 | 0.679 |
| held+sens | 0.790 | 0.758 | 0.667 | 0.808 | 0.762 | 0.704 |
| probe | 0.750 | 0.888 | 1.000 | 0.917 | 0.271 | 0.750 |
| FRESH | 0.582 | 0.571 | 0.530 | 0.567 | 0.633 | 0.556 |

**C. Long-document penalty** (passages of a document with *n* chunks scaled by (median / n)^β): β = 0.1 puts the specific document first more often but
lowers MRR when the guidebook counts as relevant (pilot with extra labels 0.944 → 0.914).

## 3. Second blind set (45 questions, ko / id / zh-CN, committed before experiment C, evaluated once)

| Setting | Labels | R@1 | R@5 | MRR | ko | id | zh-CN |
|---|---|---|---|---|---|---|---|
| baseline | blind-v2 | 0.489 | 0.800 | 0.602 | 0.517 | 0.667 | 0.622 |
| baseline | blind-v2 + long guides acceptable | 0.733 | 0.978 | 0.845 | 0.836 | 0.833 | 0.867 |
| cross-script titles | blind-v2 | 0.489 | 0.889 | 0.631 | 0.580 | 0.650 | 0.663 |
| cross-script titles | blind-v2 + long guides acceptable | 0.800 | 0.978 | 0.879 | 0.869 | 0.867 | 0.900 |
| long-document penalty 0.1 | blind-v2 | 0.644 | 0.844 | 0.723 | 0.600 | 0.800 | 0.769 |
| long-document penalty 0.1 | blind-v2 + long guides acceptable | 0.733 | 0.956 | 0.819 | 0.752 | 0.850 | 0.856 |

## 4. Decision

Neither B nor C helps on every set. **Both stay off** (`RETRIEVAL_CROSS_SCRIPT_WEIGHT=0`, `RETRIEVAL_HUB_BETA=0`) and can be switched on per environment.
What should count as "relevant" (the specific official page, or a long guide that also answers) is a decision for people: with the specific page as the
target, C is clearly better (blind MRR 0.602 → 0.723); with the guides as acceptable answers it is slightly worse (0.845 → 0.819). Because the chat
gives the model up to four sources and R@5 is 0.80–0.98, the effect on answers is smaller than these rank numbers suggest.

**Recommended next steps:** 1) native reviewers label 50 Korean questions (`docs/review`) so that the target is decided by people; 2) try C on staging
with real questions; 3) a cross-encoder reranker (research: +7–9 points MRR) needs about 120 MB more memory, which the free 512 MB instance does not have
([RENDER-MEMORY.md](RENDER-MEMORY.md)); 4) split the 85,000-character guidebook into chapter documents in the Knowledge Center (an editorial change, no code).

Files: `scripts/benchmarks/retrieval_fresh_ko_check_v1.json`, `…_v2.json`, `scripts/benchmarks/results/korean_retrieval_round.json`.
