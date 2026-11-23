# Errata

## 2026-11-23 - production retrieval scores in Milestone 4 were understated

**What happened.** For the four university announcements, the public API exposes the *announcement* id, which the
benchmark labels use; production search returns the *source document* id. The production runs
(`retrieval_production_*_v0.*.csv`) therefore scored every hit on an announcement as a miss.

**Correction.** `scripts/rescore_production.py` maps production ids back to label ids by exact title
(`data/id_aliases.json`) and writes `*_rescored.csv`; the original files are kept unchanged. 27/300 held-out rows and
51/300 pilot rows changed rank. Local runs were not affected (they use the public ids on both sides).

| held-out v0.2, production | R@1 (reported) | R@1 (corrected) | MRR (reported) | MRR (corrected) |
|---|---|---|---|---|
| B0 vector-only | 0.59 | 0.66 | 0.669 | 0.748 |
| E1 original hybrid | 0.41 | 0.46 | 0.551 | 0.616 |
| E2 improved hybrid | 0.60 | 0.68 | 0.693 | 0.776 |

All notebooks now read the corrected files; the Milestone 4 summary and abstract were regenerated.

## 2026-11-23 - Local E1 results vary between index builds (tie-breaking)

**What.** The local evaluation uses the in-memory store (`backend/app/repositories/memory_store.py`) as a stand-in for
the production SQL functions. Its legacy hybrid search (E1, SQL-RRF k=60) breaks equal fused scores by chunk ID, and
chunk IDs are random UUIDs on every index build. RRF ties are common: a chunk ranked n-th only by vector and one ranked
n-th only by keyword get exactly the same score. As a result, rebuilding an *identical* corpus changes local E1 rankings.

**Measured** (corpus_v2, two builds, pilot + held-out, 200 questions per method): E1 rankings differed for 109
questions (first-relevant rank for 39). Held-out E1 R@1 was 0.47 vs 0.44 and MRR 0.600 vs 0.586. E2 differed for 4
questions (MRR 0.700 vs 0.698) and E2S for 8; B0 was identical.

**Impact.** All local E1 figures (Milestone 4/5) carry roughly ±0.03 R@1 / ±0.015 MRR of build noise. The
qualitative conclusion "E2 > E1" (gap ≈ 0.10 MRR) is unaffected. Results were not rerun; the published files are kept.
Production E1 uses PostgreSQL's own deterministic ordering and is not affected. The chunk-quality experiment
(notebook 13) reports a rebuilt-C0 control to quantify this noise for its comparisons.

## 2026-11-23 - "Publication date unknown for 26 of 26 documents" was a property of the snapshot, not of production

**What.** The Milestone 5 final report (section "Source reliability") and notebook 14 reported the publication date as
unknown for all 26 corpus_v2 documents. The source-quality check read the research snapshot
(`data/snapshots/corpus_v2/document_inventory.csv` + corpus text), which does not export `source_published_at`
(it is stored on `document_versions`, not on the document). Notebook 14 says so, but the report presented the count
as a fact about the sources.

**Measured** (read-only query of production, 2026-11-23, 26 approved current documents): `source_published_at` is set
for **21 of 26** (oldest 2013-12-23; one is 2026-12-31, a date in the future that editors should check);
`valid_from` for 3 and `valid_until` for 2. The validity-period counts in the report (unknown for 24) agree with this.

**Impact.** Only the "publication date unknown" count was wrong; the recommendation (show editors a source-quality
report, never change metadata automatically) stands. The original files are kept; the production readiness report
uses the corrected counts. A future snapshot export should include `source_published_at`.
