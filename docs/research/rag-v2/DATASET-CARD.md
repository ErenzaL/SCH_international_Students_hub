# Dataset card — SCH Hub RAG evaluation sets (rag-v2)

**Status: AI-drafted, not reviewed by any person.** Every label below was written by an AI assistant
(Claude) from the corpus text. No native speaker, international-office staff member or second
annotator has checked it. Results on these sets are *locally evaluated*, never *human-validated*.

## 1. Splits

| Split | File | Version | Questions | Information needs | Role |
|---|---|---|---|---|---|
| DEV | `scripts/benchmarks/retrieval_pilot_v0.1.json` (sha256 `910c442d…`) | retrieval-pilot-0.1 | 100 | 20 scenarios × 5 languages | all tuning, error analysis, printing misses |
| VALIDATION | `backend/.eval-cache/heldout_v0.2.json` (sha256 `a2733501…`, not in git) | retrieval-heldout-0.2 | 100 | 20 scenarios × 5 languages | choosing between candidate configurations. Its misses were already examined in the 2026-11-27 mission, so it is **not blind** any more |
| TEST | `scripts/benchmarks/rag_v2/testset_v0.3.json` | retrieval-test-0.3 | **210** | **42 needs × 5 languages** | one final run of the pre-registered configurations, all at the same time |

Languages in every split: ko, en, id, vi, zh-CN (equal counts).

**Freeze.** The test set was built and committed before any rag-v2 experiment. The hash of its question
records is in `testset_v0.3.sha256`. `python scripts/rag_v2/build_testset.py --check` rebuilds the set
from the source file and the corpus and fails if anything differs. Any later change makes a new
version (0.3.1, …) with a changelog entry. Results from different versions are not compared.

**Test-set use rule.** Per-question test results are not looked at until the final run. Every run on
TEST is logged in `EXPERIMENT-LOG.md` with the configuration hash. Configurations are chosen on DEV and
VALIDATION only. The unchanged baseline is evaluated on TEST in the same final run as the candidates.

## 2. Corpus

`backend/.eval-cache/public_corpus.json` (sha256 prefix `7bb1a20f19fd28bc`): the 27 approved public
documents of the hub (20 guides or knowledge articles, 7 university announcements; 13 Korean,
14 English; 749 chunks with the v1 chunker). Two hub guides (Guide for International Student in
Korea, 157,061 characters; 한국 유학생 생활 가이드북, 85,568 characters) hold about two thirds of the
text. The snapshot is not in git (the repository is public). It contains public documents only, with
no student data.

## 3. Test-set composition (v0.3)

| | Count (questions) |
|---|---|
| answerable | 185 |
| conflicting sources (WRK-02: 25 vs 20 weekday hours) | 5 |
| not in sources (VIS-11: D-2 extension fee, which the sources deliberately omit) | 5 |
| unanswerable (parking, tuition instalments, airport pickup; verified absent by exhaustive search) | 15 |
| topics | academic 35, visa/immigration 40, residence card 15, part-time work 25, dormitory 30, health 10, TOPIK 10, employment 10, admission 10, scholarship 5, records 5, unanswerable topics 15 |
| difficulty | simple 185, multi-step 20, procedure 5 |
| special types | numeric 65, eligibility 35, multi-passage 20, referral 15, date-sensitive 15, outdated source 10, urgent 5 |
| source language of the evidence | Korean 23 needs, English 16 needs, none 3 |
| documents with at least one grade-2 label | 20 of 27 |
| overlap with DEV / VALIDATION | none 125, related 80, same_family 5 |

A hub guide is a correct (grade-2) source in 12 needs (13 guide grades of 2, 6 of 1), for example
VIS-05 (leave of absence, answered only by the two guides) and TPK-02 (TOPIK validity, only the English
guide). A system that never ranks
guides first is therefore not rewarded automatically.

## 4. Labels per question

- `relevant`: graded document relevance. **2** = the document states what is needed to answer;
  **1** = same need, general rule or part of it, without the asked detail; unlisted = 0.
  Grade 1 is used for graded metrics (nDCG) and for the lenient variants. Strict Recall, MRR and Hit
  count grade 2 only.
- `evidence`: verbatim gold quotes (NFC, whitespace collapsed, stand-alone markdown `#` marks
  removed). A retrieved passage is **passage-relevant** when its normalised text contains a gold
  quote. The builder checks that every quote exists in its document.
- `answerability`: `answerable`, `conflicting`, `not_in_sources`, `unanswerable`. The expected
  behaviour is in LABELING-GUIDELINES.md §5.
- `reference_answer`: English, for answer grading. Not shown to any system.
- `overlap_with_dev_validation`: see §5.
- `label_origin: ai_drafted_from_corpus`, `review_status: draft_unreviewed`.

## 5. How the splits are separated

Splits are separated **by information need**, not by question. A test need was replaced when a
correct answer to some DEV or VALIDATION question would have to contain its key fact. In the first
draft, 17 of 40 needs were replaced this way (for example winter-dorm daily fee, the penalty for
missing Healthcare Day, the ARC fee, the late address-report fine, working while a permit is pending,
TOPIK levels). Remaining overlap is recorded per need:

- `related` (16 needs): same document section or topic, different asked fact (for example VIS-06 "my
  stay already expired" against DEV "when should I apply to extend").
- `same_family` (1 need, WRK-02): a specialised case of DEV `part_time_hours`. It is kept because it
  is the only genuine source conflict in the corpus. Report it separately.

**Document overlap is unavoidable** (27 documents) and allowed: most test grade-2 documents also
appear in DEV or VALIDATION. Results are reported for the whole test set and for the `none` subset.

## 6. How the labels were made

1. Information needs were chosen by reading the corpus documents. **No retriever output was used.**
2. Gold quotes were copied from the documents and validated automatically.
3. For each need, an exhaustive case-insensitive search of its key terms over all 27 documents
   (`testset_v0.3_termhits.json`) listed every other document that mentions them. Each hit was read in
   context and graded or left at 0, with the reason in `grading_notes` (16 needs carry such a note).
   For example, the Korean guidebook states the D-10 6-month grant and the part-time exemption word
   for word.
4. Questions were written separately for each language in a student register, not translated word by
   word. They have not been checked by native speakers.

## 7. Known limitations

- **No human review.** The grades, the question wording in id/vi/zh-CN and the reference answers are
  unverified. The review sheet is `testset_v0.3_review.csv` (HUMAN-REVIEW-CHECKLIST.md).
- **Same author as the system's evaluator.** The annotator also designs the experiments. This is a bias
  risk, mitigated only by freezing before tuning.
- **Small corpus.** 42 needs over 20 documents. The 95% intervals are wide and the five language
  versions of one need are correlated, so the bootstrap resamples needs, not questions.
- **Time-bound.** The dates in the 2026-2 course and winter-2026 dormitory notices expire. The test
  set describes this snapshot only.
- **Some source documents flag themselves as drafts** ("REVIEW REQUIRED before authoritative
  release"). Labels say what the documents state, not what is legally true.
- **Unanswerable needs are only "absent from this corpus"**, not from the university.

## 8. Known issues in DEV and VALIDATION (kept unchanged)

- DEV scenario `residence_card_apply` (5 questions) lists document `c5cefc3c…`, which is not in the
  corpus snapshot. The evaluator ignores labels outside the corpus and reports how many were dropped.
- DEV and VALIDATION have document-level labels only, no unanswerable questions, and were drafted by
  translating 20 scenarios into 5 languages.
- 13 of the 15 VALIDATION primary documents are also DEV primary documents.

## 9. Rebuild

```
backend/.venv/bin/python scripts/rag_v2/build_testset.py          # validate + write
backend/.venv/bin/python scripts/rag_v2/build_testset.py --check  # verify the freeze
```
