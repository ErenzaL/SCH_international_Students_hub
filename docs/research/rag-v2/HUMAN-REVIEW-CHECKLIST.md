# Human review checklist — RAG test set v0.3

**No one has done this review yet.** Until it is done, every result on the test set is labelled
"AI-drafted labels, not human-validated".

## Who

| Role | Needed for | Minimum |
|---|---|---|
| Native speaker per language (ko, en, id, vi, zh-CN) | R1 naturalness, R2 same meaning | 1 per language; 2 for ko and en if possible |
| Domain reviewer (international office or a senior international student) | R3–R6 | 1, a second for the agreement sample |
| Adjudicator (not the annotator) | disagreements | 1 |

Reviewers need only the public corpus documents and the sheet. They never need production data, chat
logs or credentials.

## Material

- `scripts/benchmarks/rag_v2/testset_v0.3_review.csv`: one row per question (210 rows, UTF-8 with BOM,
  so it opens in Excel). It contains the question, answerability, overlap, graded documents (id prefix
  and title), gold quotes, reference answer, and other documents that mention the key terms.
- The 27 corpus documents, from the admin document view or the snapshot.

## Steps

1. **Language pass (native speakers, about 1–2 hours per language).** For each question in your
   language, fill in:
   - **R1**: is it natural, as a student would ask (y/n plus a better wording)?
   - **R2**: does it mean the same as the English version, with nothing added or missing (y/n)?
2. **Evidence pass (domain reviewer, about 3 hours, one row per need, i.e. the `-en` rows).** Fill in:
   - **R3**: do the gold quotes support the reference answer (y/n)?
   - **R4**: are the grades right (y/n plus the corrected grades)?
   - **R5**: is any other document relevant? Check the `other_documents_mentioning_terms` column.
   - **R6**: is the answerability class right? For `unanswerable`, confirm the university really has no
     approved page on it.
3. **Agreement sample.** A second domain reviewer repeats step 2 for 12 randomly drawn needs (seed 7).
   Report Cohen's κ on the document grades (0/1/2) and the raw agreement on answerability.
4. **Adjudication.** The adjudicator resolves each disagreement and writes the reason in `notes`.
5. **Record.** Save as `testset_v0.3_review_completed.csv`, with reviewer initials and date per row.
   Build v0.3.1 from the corrections (LABELING-GUIDELINES §8). Only reviewed rows get
   `review_status: human_reviewed`.

## Acceptance for calling the labels human-validated

- every need has passed R3–R6, and every question has passed R1–R2;
- κ ≥ 0.6 on the agreement sample (if lower, revise the guidelines and repeat);
- the changelog lists every change from v0.3.

## What the review does not establish

It does not show that the documents are legally correct or current. It shows only that the labels
match the documents.
