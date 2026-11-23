# Milestone 5 and the retrieval reliability sprint: final report

Date: 2026-11-23. Status: **preliminary**. Questions and relevance labels are AI-drafted and **not yet human-reviewed**. Production was not changed: no database writes, no re-indexing, no deployment, no commits.

All numbers below are for the held-out set v0.2 (100 questions, 20 scenarios, 5 languages) unless stated otherwise. Brackets give 95% cluster-bootstrap intervals over scenarios. "Frozen labels" are the official v0.2 labels, which were written before corpus_v2 existed. "Proposed labels" add AI-proposed credits for the two new documents. Those are a sensitivity check only and pending human review.

Generated sources:
- notebooks 09–14 in `research/notebooks/`;
- `reports/milestone5_combined_summary.md`;
- `reports/chunk_quality/`;
- `reports/reliability/`.

## 1. What was run

| Item | Status |
|---|---|
| Error analysis and failure taxonomy (corpus_v1 and v2) | done (notebooks 09 and 14) |
| Rerankers mMiniLM (118M) and bge-reranker-v2-m3 (568M), on 3 corpora × 2 datasets × 2 pools | done, all 1,200 question runs complete |
| Context-selection experiments | done (notebook 11) |
| Paired statistics, Holm correction, subgroups | done (notebooks 12–14) |
| Guidebook extraction investigation and 6 chunking variants | done (notebook 13) |
| Evidence-sufficiency layer (backend, off by default) | implemented, 27 tests, evaluated |
| Source-quality checks (backend, read-only) | implemented, 4 tests, evaluated on corpus_v2 |
| Benchmark v0.3 draft (document vs passage relevance) | created, pending human review |
| Answer-level evaluation (citation support, unsupported-answer rate) | **not evaluated**: no LLM calls, no human-scored answers |
| Human review of labels | **not done**: 0 of 200 rows reviewed; worksheets prepared |

## 2. Main results

### Reranking is the only change with a supported accuracy gain

E3 is the improved hybrid (E2) followed by a cross-encoder reranker, both on the same frozen pool of at most 20 chunks.

| Corpus | Labels | E2 MRR | E3 mMiniLM | E3 bge-m3 | mMiniLM − E2 | bge-m3 − E2 |
|---|---|---|---|---|---|---|
| corpus_v1 | frozen | 0.769 | 0.857 | 0.858 | +8.8 [+2.5, +14.7] | +8.8 [+1.9, +15.2] |
| corpus_v2 | frozen | 0.706 | 0.781 | 0.787 | +7.5 [+2.4, +12.2] | +8.0 [+1.7, +14.0] |
| corpus_v2 | proposed | 0.768 | 0.820 | 0.821 | +5.2 [+0.6, +9.4] | +5.3 [−0.6, +10.8] |
| v2 + repaired guidebook (P1) | frozen | 0.657 | 0.728 | 0.758 | +7.2 [+0.8, +12.6] | +10.1 [+3.4, +16.5] |
| v2 + repaired guidebook (P1) | proposed | 0.746 | 0.823 | 0.814 | +7.7 [+2.9, +12.6] | +6.8 [+0.1, +13.6] |

- **mMiniLM vs bge-m3:** no detectable difference (corpus_v2: +0.6 pp [−6.0, +6.8]).
- **By language** (corpus_v2, frozen labels, E2 → E3 mMiniLM):

  | Language | E2 MRR | E3 mMiniLM MRR |
  |---|---|---|
  | ko | 0.541 | 0.604 |
  | vi | 0.639 | 0.850 |
  | en | 0.758 | 0.850 |
  | id | 0.802 | 0.825 |
  | zh | 0.792 | 0.775 |

  With 20 questions per language, the per-language intervals are wide.
- **Evidence:** reranking also raises the share of questions with a supporting passage in the assistant's context, from 0.58 to 0.65 (+7.0 pp [+3.0, +13.0]).
- **Selection undoes the gain:** passing the reranked list through the assistant's current evidence selection (E4) loses most of it in every corpus (corpus_v2: −6.3 pp [−10.8, −2.2] vs E3). If reranking is adopted, the selection step must preserve the reranker's order.

### Cost

Median time per question, on corpus_v2:

| Pipeline | Device | Median time per question |
|---|---|---|
| E2 | CPU | 60 ms |
| E3 mMiniLM | M1 GPU | 395 ms |
| E3 mMiniLM | M1 CPU (4 threads) | ≈1.2 s |
| E3 bge-m3 | M1 GPU | 3.7 s |
| E3 bge-m3 | M1 CPU | ≈9 s |

- The CPU rows come from the corpus_v1 runs, which used the CPU for their first questions.
- The reranking processes peaked at 0.9–1.1 GB of RAM.
- Nothing was measured on Render. Neither model fits a 512 MB instance unchanged.

### The guidebook fragmentation is an extraction defect, and it causes content loss

- **Cause:** the production PDF extractor estimates the body font size from the first 20 pages: 6.2 pt, where the real body text is 9.4 pt. As a result, 82% of the text is tagged as `##` headings, one per visual line.
- **Effect:** the heading-aware chunker starts a new section at every one of them, and consecutive headings overwrite each other. **Only 24% of the guidebook's Korean words reach chunk text in production.** All other corpus_v2 documents keep at least 97%.
- **Ruled out:** OCR, encoding, and the chunker's size logic.
- **Secondary issues:** table cells come out as one-word headings; page numbers and running headers become paragraphs; there are 194 BEL control characters.
- **Repairs tested:** six variants, each in a separate index (notebook 13). All of them restore 97–100% word coverage; median chunk length goes from 37 to about 450–540 characters.

| Effect of the repair (P1 vs production text, same questions) | Difference |
|---|---|
| Evidence-term coverage in the context (independent of the proposed labels) | **+5.5 pp [+0.5, +12.5]** |
| Supporting passage in the context | **+5.0 pp [+1.0, +10.0]** |
| MRR against the frozen labels | −4.6 pp [−7.8, −1.7] |

The repaired guide is a strong general source: it now competes with the specific pages for many questions. Some of those wins are correct answers the frozen labels don't credit; others are distractors. Rebuilding an identical index changes E2 by +0.0 pp, so these effects are not noise.

### The evidence-sufficiency layer detects gaps but does not measurably close them

- **What it does:** it detects quantity, date, requirement, eligibility and procedure questions in five languages, using generic patterns with no policy values. It checks the top source for that information, adds neighbouring chunks or makes one bounded search within cited documents, and records what is still missing.
- **Problems found during development:**
  1. A shape-only check passed 100% of contexts, because some number or condition is almost always present.
  2. Its completions were often off-topic, such as an admissions checklist added for a health-insurance question.
- **Fixes**, chosen on the development set only:
  1. Anchor the check to the top source.
  2. Require a relevance gate for added passages.
  3. Limit the search to already-selected documents.
- **Held-out result:**
  - **Effect:** supporting passage and evidence-term coverage are unchanged (+0.0 pp); document ranking is unchanged.
  - **Activity and cost:** it added passages for 20–25% of questions, at a median of about 5 ms (p90 about 100 ms).
  - **Why no effect:** on the development set, more than half of the added passages still came from non-relevant documents. When retrieval picks the wrong document, more of that document doesn't help.
- **Verdict:** valuable as a **recorder** of incomplete evidence, not shown to be an improver.

### Failure audit

Corpus_v2, the assistant path, 200 questions. Rules are automatic and a question can fall into several types.

| Failure type | Questions |
|---|---|
| Correct document, wrong passage | 28 |
| Top source is the 2021-edition guidebook | 28 |
| Wrong document | 21 |
| Missing numeric or conditional evidence | 21 |
| Cross-language failure | 21 |
| Fragmented context | 10 |
| Potentially conflicting figures | 10 |
| Incomplete labels | 9 |
| No failure rule matched | 108 |

All wrong-document failures are cross-language questions (the base rate is 80%). No passage stating an expired deadline reached a context.

### Source reliability

Read-only checks; missing metadata is reported as unknown.

| Field | Documents (of 26) reported as unknown |
|---|---|
| Publication date | 26 |
| Validity period | 24 |
| Source domain | 21 |

> **Correction (2026-11-23, see `ERRATA.md`):** the publication-date count describes the research snapshot, which
> does not export `source_published_at`. In production 21 of 26 approved documents have a publication date.

- **Duplicate content:** 96% of the employment PDF is contained in the guidebook.
- **Old edition:** the guidebook declares a 2021 edition.

### Corrections made during the analysis (see `ERRATA.md`)

- **E1 tie-breaking:** the local in-memory store breaks E1 ties by random chunk ID, so local E1 results vary by up to ±0.03 R@1 between index builds. The conclusion that E2 beats E1 (+10.6 pp) is unaffected.
- **Production ID mismatch:** the earlier production ID mismatch was corrected by rescoring.

## 3. Recommended architecture and production order

Nothing below has been deployed. Each step needs your approval.

1. **Fix the PDF extraction first.** This is a data-integrity bug: about 76% of an approved document is not searchable today.
   - **Minimal change:** estimate the body font size over all pages (variant P1). Better: also re-flow wrapped lines and drop page furniture (variants C2/C3).
   - **Rollout:** re-extract the guidebook as a new version through the normal approval flow; the old version stays active until the new one is indexed.
   - **How to judge it:** by evidence coverage, not by the frozen labels.
2. **Retrieval: E2 plus the mMiniLM reranker over the top 20.**
   - **Why:** the only supported accuracy gain; bge-m3 is not better and costs 9× more.
   - **Required change:** the assistant's evidence selection must keep the reranker's order.
   - **Constraint:** about 1 GB RAM and about 1 s per question on CPU. It needs a larger instance or an int8/ONNX-quantized model, re-measured on that hardware before any decision. This is the main cost.
3. **Evidence-sufficiency layer: shadow mode only.**
   - **How:** enable it with logging of `evidence_check` reports, without changing answers.
   - **Why not more:** its completion step is not shown to help.
4. **Source-quality report for editors.**
   - **Contents:** unknown fields, old editions, overlapping documents.
   - **Rule:** no automatic metadata changes.
5. **Human review before claiming improvements.**
   - **What:** the v0.3 draft (`data/review/passage_labels_v0.3_draft.jsonl`) and the label review of the new documents.
   - **Rule:** keep v0.1/v0.2 frozen; the held-out set stays untuned.

## 4. Limitations

- All labels are AI-drafted.
- The proposed labels and the passage criteria are machine-derived and pending review.
- 20 scenarios give wide intervals.
- No answers were generated or graded.
- Latency is local Apple M1 timing, not Render.
- The guidebook's 2021 content may be outdated even where it is relevant for retrieval.
- Pages 4, 5 and 91 of the guidebook are images and remain unextracted.
