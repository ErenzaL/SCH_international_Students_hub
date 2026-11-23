# Dataset update: corpus_v1 → corpus_v2

Snapshot taken 2026-11-23 02:32 UTC from production Supabase using read-only queries (`research/sql/`). No production
record was changed and nothing was reindexed. The corpus_v1 results, figures and reports are unchanged. corpus_v2
outputs are in `data/snapshots/corpus_v2/`, `data/results/corpus_v2/`, `figures/corpus_v2/` and `reports/corpus_v2/`.

## 1. New documents (uploaded through the Admin Dashboard)

| | 한국 유학생 생활 가이드북 | 외국인학생취업관련 정보 |
|---|---|---|
| document ID | d60bc363-0aae-44e5-b0c3-df8c61ad6f66 | 96b0fee4-18e9-4ea2-adb5-db654c9ac238 |
| source type / language | uploaded PDF / ko | uploaded PDF / ko |
| category | daily-living | part-time-employment |
| status / version | approved, version 1 | approved, version 1 |
| pages / chunks | 94 / 291 | 6 / 18 |
| embedded / searchable | 291 / 291 | 18 / 18 |
| indexing | succeeded, no failed jobs | succeeded, no failed jobs |
| source URL | none | none |
| duplicate content hash or title | none | none |

## 2. Counts (v1 → v2)

- Documents: 24 → 26. Active documents: 23 → 25. The one inactive document is the canceled sample announcement, which is correctly unsearchable.
- Pages: 125 → 225.
- Active chunks: 457 → 766, all embedded.
- Chunks by language: Korean 73 → 382, English 384 → 384.
- Chunks by category: daily-living 261 → 552, part-time-employment 18 → 36. Other categories are unchanged.
- Median chunk length: 456 → 186.5 characters.
- Embeddings: intfloat/multilingual-e5-small, ONNX int8, 384 dimensions, for all 766 chunks.

## 3. Indexing verification

- Every active document's current version is indexed.
- For every active document, chunks = embedded chunks = searchable chunks.
- No duplicate content hashes and no duplicate titles.
- Job history: index_version succeeded 21, ingest succeeded 22, ingest failed 2. The two failed ingest jobs are not linked to any current document.
- Two documents have a `valid_until` date.

## 4. Data-quality problems found

1. **The guidebook PDF is badly fragmented.**
   - Its 291 chunks have a median of 37 characters; 258 are under 100 characters.
   - The PDF layout breaks text into headings and labels instead of paragraphs, so many chunks carry little meaning.
   - These short chunks still rank highly for Korean and Vietnamese questions.
   - The fix is re-extraction or merging of short blocks. That is a production change, so it was not done.
2. **No source URL** on 21 of 26 documents, including both new PDFs. Citations for these cannot link to an original.
3. Both new documents are Korean only. No translations exist yet.

## 5. Benchmark impact

The questions and labels are the same frozen sets. Nothing was tuned on the held-out set.

| local, held-out v0.2 | R@1 v1 → v2 | MRR v1 → v2 |
|---|---|---|
| B0 vector | 0.64 → 0.54 | 0.718 → 0.647 |
| E1 original hybrid | 0.53 → 0.47 | 0.649 → 0.600 |
| E2 improved hybrid | 0.67 → 0.60 | 0.762 → 0.700 |
| E2S + evidence selection | 0.63 → 0.59 | 0.742 → 0.682 |

The pilot set (development) drops the same way; E2 MRR goes 0.874 → 0.792.

Per-question detail is in `data/results/corpus_v2/snapshot_impact_corpus_v1_to_corpus_v2.csv`:
- A new document now ranks first for 22–27 held-out and 19–22 pilot questions, depending on the method.
- For E2 on held-out, 21 questions got worse and 2 improved; 8 questions lost their rank-1 hit.
- New documents contain the evidence terms for 10 of the 20 held-out scenarios: H01, H03, H06, H07, H11, H13, H14, H16, H17 and H19.
- For 7 E2 held-out questions, the new top-1 document contains the evidence terms.
- The pilot set has no evidence terms, so this check cannot be made for it.

**Interpretation.** The frozen labels were written before these documents existed. Some of the "drops" are probably correct answers from the new guide that the labels don't credit, and the fragmented chunks cause others. The v2 numbers should not be read as worse retrieval until the labels are reviewed and revised as v0.3 by human reviewers. Labels were not changed automatically.

## 6. Notebooks

- Every notebook takes `RAG_SNAPSHOT` (default `corpus_v2`). corpus_v1 outputs stay in their original folders.
- Notebooks 01–08 ran on corpus_v2 without errors.
- 01 adds a comparison of the two snapshots, covering the new documents, indexing coverage and a change summary.
- In 03, 05 and 06, the production-answer and production-retrieval panels read "Not evaluated" for corpus_v2. No production run was made against v2.

## 7. Missing information and open problems

- Label coverage for the new documents (see 5).
- Fragmented chunks in the guidebook.
- Missing source URLs.
- The production retrieval run on corpus_v2 has not been done.
- Human review of the labels has not started: 0 of 200 rows are reviewed.

## 8. Recommended next steps

1. Human review of the evidence-term matches in the new documents, then a v0.3 label set. Keep v0.2 frozen for comparison.
2. Re-extract the guidebook so short blocks merge into paragraphs, then compare a corpus_v3 snapshot against v2.
3. Add source URLs where the documents have a public original.
4. Report Milestone 5 reranking results for both snapshots, and treat corpus_v2 results as provisional until the labels are revised.
