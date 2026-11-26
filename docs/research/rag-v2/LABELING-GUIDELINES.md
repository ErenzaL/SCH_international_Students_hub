# Labelling guidelines — RAG test set

These are the rules that the v0.3 test set was written with. Reviewers and future versions follow the
same rules, so that numbers stay comparable.

## 1. Information needs

- One need = one fact or one decision a student wants, answerable (or deliberately not answerable)
  from the corpus snapshot.
- Write needs from the **documents**, never from retriever or chatbot output. Do not run the system on
  a question before its labels are fixed.
- A need must not be answered by any DEV or VALIDATION question (DATASET-CARD §5). Record any remaining
  overlap as `related` or `same_family`.
- No private information: no real student names, numbers, cases or conversations.

## 2. Questions (five languages)

- Write each language version as a student would ask it, in that language's normal register: for
  example 해요체 in Korean, a casual "saya" in Indonesian, plain Vietnamese with diacritics, simplified
  Chinese. Keep official codes as students type them (D-2, ARC, TOPIK).
- All five versions ask **the same thing** with the same constraints (year, visa, dormitory). Do not add
  hints in one language that the others lack.
- Do not copy the document's wording into the question when a student would not use it. Lexical
  overlap would make retrieval artificially easy.

## 3. Relevance grades (document level)

| Grade | Meaning | Example (VIS-09, "How long is D-10 granted at a time?") |
|---|---|---|
| 2 | the document states what is needed to answer | 96b0fee4 / d60bc363 "1회 부여 체류기간의 상한: 6개월"; 26fbef6d "extended in 6-month increments" |
| 1 | same need; general rule or part of the answer, without the asked detail | a document that only says D-10 must be applied for after graduation |
| 0 | anything else, including the same topic with a different fact | the D-2 extension page |

- Grade what the text says, not what is true outside the corpus.
- A document graded 2 for an outdated or conflicting answer stays 2. The `types` field marks
  `outdated_source` and `conflicting_sources`.
- Duplicate notices (same text posted twice) get the same grade.
- Long guides are graded like any other document: if the guide states the fact, it is 2.

## 4. Gold evidence quotes

- Copy verbatim from the document text. Quotes are compared after NFC normalisation, whitespace
  collapsing and removal of stand-alone markdown `#` marks.
- Take the shortest span that still proves the answer (one sentence or table row). Use several quotes
  for multi-passage needs.
- Every quoted document must have a grade. Every grade-2 document should normally have a quote.

## 5. Answerability and expected behaviour

| Class | Definition | Correct system behaviour |
|---|---|---|
| answerable | at least one grade-2 document, sources agree | answer with citations to supporting passages |
| conflicting | two grade-2 documents disagree on the asked fact | give both values with their sources and dates; prefer the newer one; send the student to the deciding authority |
| not_in_sources | related documents exist but none states the asked fact | say the approved sources do not state it; no number; point to the official channel |
| unanswerable | no document covers the need (checked by exhaustive search) | say the hub has no approved information; no invented policy; offer human help |

## 6. Reference answers

Write in English, one to three sentences, with only facts from the gold evidence. Mention the source
date when the type is `outdated_source`. Reference answers are for graders only and are never given
to a system.

## 7. Grading other documents

After writing a need, run the builder. Read every document in `mentioning_but_ungraded` of
`testset_v0.3_termhits.json` in context. Either grade it, with a reason in `grading_notes`, or leave
it at 0. Lexical coincidences (for example "ocu" inside "focus") stay at 0.

## 8. Changes

After the freeze, no label is edited in place. Corrections, including those from human review, go
into a new version with a changelog entry. Its results are reported separately.
