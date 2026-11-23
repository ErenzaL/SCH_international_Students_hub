# Reviewer guide - SCH multilingual RAG evaluation

You are checking AI-drafted evaluation data. Nothing counts as "human-reviewed" until a named reviewer has filled in
the columns below. Never edit the benchmark JSON files directly; work only in the two CSV files.

## A. Label review - `label_review_worksheet.csv` (200 rows)

`split`: **development** (pilot v0.1, used for tuning) or **held-out** (v0.2). Keep them separate; the reviewed
held-out rows become the final test set `retrieval-reviewed-1.0`. Work in `priority` order: **1-high** rows are
immigration, residence card, work and health-insurance questions and time-sensitive notices.

For each row:
1. Read the question (translate if needed) and open the documents in `expected_documents` in the Knowledge Center.
2. **Correct label?** Does each listed document actually answer the question? Is `primary_document` the most specific
   one? Look at `top3_retrieved_not_labeled_E2`: if one of those also answers the question, it is a *missing label*.
3. **Time-sensitive?** If the answer depends on a date that has passed (see `temporal_flag`), mark `reject` or note
   that the question must be rewritten for the current period.
4. **Reference answer** (1-high rows): write a short, correct answer in English from the official source, with the
   source title. Do not use the assistant's answer as the reference.
5. Fill in:
   - `reviewer` - your name or initials; `decision` - **accept** (labels correct), **fix** (put the correct document ids,
     separated by `;`, in `corrected_expected_document_ids`) or **reject** (question unusable);
   - a second reviewer fills `reviewer_2` / `decision_2` independently (do not look at the first decision first);
   - `agreement` = yes/no; disagreements are settled by a third person in `adjudicated_by` + `final_decision`.

## B. Answer review - `answer_annotation_template.csv` (27 recorded production answers)

Score every row with `configs/answer_rubric_v1.md` (0-2 per dimension): correctness, relevance, faithfulness,
citation accuracy; count `unsupported_claims`; `language_ok` yes/no; for out-of-scope questions,
`appropriate_abstention` yes/no. Set `judge_type` = **human** (never fill human columns with model output; an LLM
judge must use `judge_type = llm` and name `judge_model`). Failed or unavailable generations stay in the file and are
scored as "no answer".

## Definitions

- **Relevant document**: an approved document whose text answers the question for the current period.
- **Primary document**: the single most specific relevant document.
- **Unsupported claim**: a factual statement (requirement, number, date, office, URL) not found in any approved source.
- **Disagreement**: the two reviewers' decisions differ (accept vs fix vs reject, or different corrected ids).

Check progress at any time: `research/.venv/bin/python research/scripts/review_status.py`.
