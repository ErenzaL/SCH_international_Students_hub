# Production readiness after Milestone 5: decision report

Date: 2026-11-23. Scope: make the existing RAG system reliable; no new features (the AI Support Office is out of scope).

**Nothing was deployed, pushed or written to production.** Production was used read-only only:
- two `--read-only` SQL queries;
- read-only downloads of the six PDF originals.

Labels are AI-drafted and not human-reviewed, so every retrieval number is **preliminary**. Brackets are 95% cluster-bootstrap intervals over scenarios on the held-out set v0.2 (100 questions, 20 scenarios × 5 languages).

## 1. Decision summary

| Change | Status | Decision |
|---|---|---|
| PDF body-size fix + removal of `\x07` marks (extractor) | implemented, 10 tests, validated on all 6 production PDFs | **Ready to deploy** |
| Re-extraction of a stored original into a new pending version (`POST /admin/versions/{id}/re-extract`, `app.cli reextract`) | implemented, tested | **Ready to deploy**; the guidebook re-extraction then needs a reviewer's approval |
| Reviewer warning for older sources (publication date or declared edition older than 3 years) | implemented, tested | **Ready to deploy** (a warning only) |
| Order-preserving evidence selection for reranked candidates | implemented, 13 tests | **Ready to deploy**, but inactive until a reranker is enabled |
| Optional ONNX reranker module (`RERANK_PROVIDER`, default `none`) | implemented, tested | **Deploy switched off** |
| Enable mMiniLM reranking in production | measured | **Not ready**: it does not fit the 512 MB / ~0.1 CPU instance |
| Lifecycle verification, evidence-sufficiency layer (off), source-quality checks (Milestone 5 sprint) | implemented, tested | ready as already reported; the evidence layer stays off or in shadow mode |
| Answer-level comparison A/B/C with Gemini | harness ready, dry-run passed | **Not run: needs your approval** (it uses your Gemini quota, see §5) |

## 2. What needs human review

1. **The new guidebook version.** After the re-extraction is run (§3.6), a reviewer must:
   - compare it with v1 in the review screen;
   - check that time-sensitive content is still current (the version carries the older-source warning);
   - approve it, or reject it.
2. **Benchmark labels.**
   - The v0.3 draft passage criteria, 200 rows, 0 reviewed: `data/review/passage_labels_v0.3_draft.jsonl`.
   - The AI-proposed labels for the new corpus_v2 documents: `data/review/label_review_new_documents_corpus_v2.csv`.
   - Until these are reviewed, no accuracy improvement can be claimed as final.
3. **Answer quality.** Correctness and faithfulness need human scores using `configs/answer_rubric_v1.md`. `run_answer_abc.py --annotation` writes a blinded worksheet once answers exist.
4. **Source metadata.** A read-only check found the following, which editors should look at:
   - one approved document has a publication date in the future (2026-12-31);
   - 5 of 26 documents have no publication date;
   - only 2 have a validity end date.

   Nothing was changed automatically.

## 3. PDF extraction validation (`guideBook_ko.pdf`)

### 3.1 The file

The file you provided has SHA-256 `8f892bb8dcb08f13…`. It is identical to the original in private storage and to the one used in Milestone 5.
- **Pages:** 94; pages 4, 5 and 91 are images with no text layer.
- **Metadata:** created 2021-03-05 (Adobe InDesign CS6), modified 2022-03-25. The cover declares "2021 개정판" (2021 revised edition).

### 3.2 Cause, verified on the file

The extractor marks a line as a heading when its font is at least 1.2× the body size. It estimated the body size from the first 20 pages, using a character-weighted modal size.

| Pages used | Modal size | Share of characters |
|---|---|---|
| First 20 pages | 6.2 pt | 40% (pages 14–18: dense embassy contact tables) |
| All 94 pages | 9.4 pt | 33%; also the most common size on 39 of the 94 pages |

- **Mislabelling:** with a 6.2 pt "body", every 9.4 pt body line counted as a heading. 2,479 lines (75% of characters) became `##` lines.
- **Loss in chunking:** the chunker keeps a heading only as a section label, and consecutive labels replace each other. So the body text never reached chunk content.

### 3.3 Fix

- **Body size:** use the character-weighted modal size over all pages. The fix is a single changed line in `extractors_files._body_font_size`.
- **Control characters:** drop C0 control characters from PDF text. InDesign puts an invisible `\x07` "indent to here" mark after list markers.
- **Cost:** about +0.8 s extraction time for the guidebook (2.8 → 3.7 s). Memory is unchanged.

### 3.4 Results

Ground truth is each page's own PDF text layer. The extractor reads that same layer, so every word should reach the chunks.
- **Word recall** is computed over words in the text layer.
- **Line accuracy** checks every chunk line for a verbatim match on the page(s) the chunk cites.

| Guidebook | Before (live v1) | After |
|---|---|---|
| Body size estimate | 6.2 pt | 9.4 pt |
| Characters on heading lines | 74.7% (2,479 lines) | 3.8% (160 lines) |
| Words reaching chunk text | **26.6%** (Hangul: 3,007 of 12,314) | **97.4%** (Hangul: 11,911 of 12,314) |
| Words in chunk text or chunk headings | 41.1% | 99.0% |
| Line accuracy | 100% of 659 lines | **100% of 2,704 lines** |
| Pages with text cited by at least one chunk | 77 of 90 | 88 of 90 (pages 1–2 are the cover) |
| Table-cell words reaching chunk text | 25.5% | 85.4% |
| Chunks; median / 10th-percentile length | 291; 37 / 12 characters | 178; 449 / 92 characters |
| Chunks under 100 characters | 88.7% | 11.8% |
| Largest chunk | 367 tokens | 415 tokens (limit 420) |

### 3.5 Other PDFs: no degradation

All five other production PDFs were re-extracted from their originals, 131 pages in total.

| PDF | Pages | Body size | Output |
|---|---|---|---|
| Guide for International Student in Korea | 104 | 8.0 → 8.0 | identical apart from the `\x07` marks |
| 모집요강 | 14 | 9.0 → 9.0 | identical apart from the `\x07` marks |
| 수강신청 안내 | 5 | 12.0 → 12.0 | identical |
| 수강신청 주의사항 | 2 | 12.0 → 12.0 | identical |
| 외국인학생취업관련 정보 | 6 | 9.4 → 9.4 | identical apart from the `\x07` marks |

For all five, chunk counts, word recall and line accuracy (100%) are unchanged. The `\x07` marks are already in their live text, so these documents need no re-extraction.

### 3.6 Recovered passages

Each passage below was verbatim on the cited page, and none of its words were in any v1 chunk. Page 40 was also checked visually against the rendered page.
- **p. 40, 가. 기본원칙:** "(대상) 인증대학 재학생 중 평균학점 (이수학점 기준) C학점 (평점 2.0) 이상인 자 / (제출서류) 원칙적으로 미 징구 / FIMS 상 학사정보 확인으로 대체하고 재정입증 서류 생략". This is the visa-extension incentive for certified universities.
- **p. 40:** "하위대학 등 재학생 중 평균학점 … D학점 (평점 1.0 이하) 이하인 자 및 연수생의 경우 출석율 70% 이하인 자".
- **p. 36, 가. 외국인 등록:** the exemptions from alien registration (A-1–A-3, …), the 90-day stay rule, and the tuberculosis-screening certificate requirement.
- **p. 77, 나. 구직비자(D-10):** the D-10 document list (TOPIK or KIIP proof, employer recommendation, proof of living expenses).
- **p. 74, (5) 시간제 취업허가의 특례:** the exceptions to the part-time work permit.
- **p. 11, (2) 유학(D-2):** the countries under intensive management and the apostille / consular-confirmation requirement.

In total, 217 paragraphs are mostly new text (`data/experiments/pdf_fix_validation/summary.json`).

### 3.7 Remaining issues

None of these is a corruption of the text itself.

- **Bold checklist items still tagged as headings:** 47 items, for example "* 재정 입증서류 (미화 1만달러 상당)" and "* 여권".
  - Their text is kept as the section label of the following chunk, so it is still embedded and shown to the model.
  - But 17 chunks carry a checklist item as their section name.
  - Fixing this needs paragraph-aware re-flowing (variants C2/C3 in notebook 13). That is a larger change and was not made.
- **Page furniture inside chunk text:** 115 page-number lines and 43 running headers ("┃제3장┃…").
- **Image-only pages:** pages 4, 5 and 91 contain no text and need OCR. The v1 warning already says so.
- **Words not in chunk text:** 2.6% of words are not in chunk content. They are mostly list markers (가/나/다), cover words and the section labels above.
- **Outdated content:** the content itself dates from 2021 (fees, contacts, rules), and it was not checked against current rules.

### 3.8 New version, prepared but not created

- **Older-source flag:** the re-extracted guidebook gets the warning "Older source: published 2021-03-05 and declares a 2021 edition. Verify time-sensitive guidance (fees, amounts, deadlines, visa, work and insurance rules, contacts) against current official sources before approving…". The assistant already passes "published: 2021-03-05" with every guidebook passage.
- **Why it isn't created yet:** creating the version writes to production (a pending version, its chunks and an ingestion job), so it needs your approval.
- **Options:**
  1. Run `python -m app.cli reextract 612108fb-e5fa-4d52-be8c-0d6cf440f426` locally against production as a dry run, which writes nothing. Then run it with `--apply`.
  2. Deploy first, then call the new endpoint.
- **Safety in either case:** v1 stays live until a reviewer approves v2. Approval runs the normal index → activate → verify path; rollback to v1 stays available.

## 4. Reranker: memory and latency (Phase 4)

### 4.1 Setup

- **Machine:** Apple M1, CPU only, one fresh process per variant.
- **Workload:** the 100 held-out questions, each with its 20 real first-stage candidates (realistic question and passage lengths, up to 512 tokens per pair).
- **Reference:** the PyTorch fp32 model used in Milestone 5.
- **Agreement:** measured against that reference.
- **Quality:** held-out document MRR on the same candidates, frozen labels.

### 4.2 Results

| Variant | File | RAM after load | Peak RAM | Load | Median / p90 per question (20 pairs) | Pairs/s | Kendall τ | Same top-1 | MRR |
|---|---|---|---|---|---|---|---|---|---|
| PyTorch fp32, 1 thread | 449 MB | 691 MB | 1,309 MB | 11.0 s | 1.93 / 2.39 s | 10.4 | 1.00 | 100% | 0.781 |
| PyTorch fp32, 2 threads | 449 MB | 948 MB | 1,475 MB | 9.5 s | 1.30 / 1.58 s | 15.7 | 1.00 | 100% | 0.781 |
| ONNX optimized fp32, 1 thread | 449 MB | 854 MB | 1,026 MB | 0.8 s | 6.87 / 8.41 s | 2.9 | 1.00 | 100% | 0.781 |
| **ONNX INT8**, 1 thread, batch 4 | 113 MB | 413 MB | 933 MB | 0.6 s | 3.65 / 4.72 s | 5.4 | 0.79 | 74% | 0.766 |
| ONNX INT8, 2 threads, batch 4 | 113 MB | 394 MB | 933 MB | 0.6 s | 2.47 / 3.11 s | 8.0 | 0.79 | 74% | 0.766 |
| ONNX INT8, 1 thread, batch 1 | 113 MB | 413 MB | 690 MB | 0.6 s | 3.08 / 3.82 s | 6.6 | 0.79 | 75% | 0.767 |
| ONNX INT8, 1 thread, batch 20 | 113 MB | 400 MB | 1,793 MB | 0.6 s | 8.91 / 9.69 s | 2.4 | 0.78 | 71% | 0.770 |

### 4.3 One API process (backend modules + production e5 INT8 embedder + INT8 reranker, batch 4)

| Stage | RAM |
|---|---|
| API modules | 78 MB |
| + e5 embedder loaded | 455 MB |
| + reranker loaded | 613 MB |
| Peak while reranking | 893–1,116 MB |

The median reranking time in this process was 2.6–3.8 s.

### 4.4 What this means

- **Memory:** it does not fit the current instance. The API with the embedder already uses about 455 MB of the 512 MB, and the reranker adds about 160 MB to load, then several hundred MB of activations.
  - No variant measured fits.
  - Batch 1 lowers the peak but not below the limit.
- **CPU:** the web instance has about 0.1 CPU (see `docs/ingestion.md`). One M1 core needs 3–4 s per question with INT8, so the instance would need tens of seconds per question. That is not acceptable for chat.
  - Render's x86 CPUs have different INT8 kernels (VNNI), so the ratio may differ. This was **not measured**.
- **Quality:**
  - ONNX fp32 reproduces the PyTorch scores exactly.
  - INT8 changes the ranking noticeably (τ = 0.79, same top passage for 74% of questions).
  - INT8's held-out MRR loss is −1.5 pp [−4.7, +1.9]: not detectable with 100 questions, but not shown to be zero.
- **Speed on M1:** PyTorch is faster than ONNX here because it uses Apple's Accelerate matrix units. This advantage does not carry over to Render.
- **Conclusion:** running the reranker needs either a separate small reranking service or a larger instance. Neither was set up, as instructed (no hosting upgrade, no paid services).

## 5. End-to-end quality: A vs B vs C (Phases 3 and 5)

### 5.1 Pipelines

| Pipeline | What it is |
|---|---|
| **A** | The deployed code (`main` at 7e647cd, run from a separate git worktree) |
| **B** | Improved hybrid retrieval and evidence selection (the uncommitted Milestone 2.2 code) |
| **C** | B + mMiniLM INT8 reranking over the top 20 + order-preserving selection |

All three use:
- the same 100 held-out questions;
- the corpus_v2 production text;
- the same embedder;
- the same context budget (4 sources × 3 passages, 9,000 characters);
- one query per question.

### 5.2 Retrieval and context quality (measured; no LLM)

| Pipeline | MRR (frozen labels) | R@1 | nDCG@5 | MRR (with AI-proposed labels) | Supporting passage in context* | Evidence-term coverage* | Context characters (median) | Reranking time (median, M1, 1 thread) |
|---|---|---|---|---|---|---|---|---|
| A, deployed | 0.695 [0.595, 0.792] | 0.60 | 0.674 | 0.763 | 0.58 | 0.580 | 4,125 | – |
| A with its deployed budget (2 passages, 7,000 characters) | 0.695 | 0.60 | 0.674 | 0.763 | 0.55 | 0.560 | 3,456 | – |
| B | 0.684 [0.585, 0.783] | 0.59 | 0.667 | 0.752 | 0.58 | 0.585 | 4,209 | – |
| **C** | **0.759** [0.660, 0.850] | 0.67 | 0.748 | 0.810 | 0.63 | 0.620 | 6,213 | 3.7 s (p90 4.8 s) |
| C with the old selection | 0.720 | 0.62 | 0.720 | 0.770 | 0.62 | 0.620 | 6,127 | 3.9 s |
| Milestone 5 reranked list (PyTorch) + new selection (E4fix) | **0.781** | 0.69 | 0.768 | 0.818 | 0.66 | 0.640 | 6,116 | – |

\* v0.3-draft passage criteria and AI-proposed documents: pending human review.

### 5.3 Paired differences

Holm correction is applied across all 12 tests.

| Comparison | Measure | Difference | 95% interval | Holm-adjusted p |
|---|---|---|---|---|
| C − A | MRR | **+6.4 pp** | [+0.6, +11.9] | 0.32 |
| C − B | MRR | **+7.5 pp** | [+1.1, +13.8] | 0.23 |
| C − C with old selection | MRR | **+3.9 pp** | [+0.1, +8.0] | 0.46 |
| B − A | MRR | −1.1 pp | [−3.9, +1.2] | 1.0 |
| C − A | supporting passage | +5.0 pp | [0.0, +10.0] | 0.60 |
| C − A | evidence-term coverage | +4.0 pp | [0.0, +8.0] | 0.75 |

### 5.4 Reading

- **The selection fix works.**
  - With the Milestone 5 reranked lists, the new selection reproduces the reranker's quality exactly: E4fix 0.781 = E3 0.781, where the old selection gave E4 0.718.
  - On the production-style pool, it adds +3.9 pp to C.
  - Deduplication, source caps and character budgets still hold. The median share of context taken by one document is 0.50 for C and 0.52 for A, so one document does not take over.
- **Reranking:**
  - C's direction matches Milestone 5 (vector-only, hybrid and reranked runs on three corpus versions and both label sets).
  - Its intervals exclude zero, but after Holm correction over 12 tests on 20 scenarios none of the comparisons is significant.
  - C uses INT8 (−1.5 pp versus fp32) and a different candidate pool from Milestone 5.
- **B vs A:** the uncommitted hybrid and selection changes do not change ranking quality with a single query (−1.1 pp, interval includes 0). They were designed for answers with several rewritten queries, which this test does not exercise.
- **By language** (MRR, A → C):

  | Language | A | C |
  |---|---|---|
  | en | 0.76 | 0.85 |
  | id | 0.79 | 0.80 |
  | ko | 0.50 | 0.55 |
  | vi | 0.63 | 0.85 |
  | zh | 0.79 | 0.74 |

  Korean remains the weakest language; it is also the guidebook's language (§3).

### 5.5 Answer-level measures: not run

The following were **not run**:
- answer correctness and faithfulness;
- citation accuracy and language consistency of generated answers;
- response latency and generation success with Gemini.

Why not:
- Local Gemini is not configured: settings read `.env`, while the local file is named `.env ` with a trailing space.
- A run spends your Gemini quota: about 300 answers plus about 300 query rewrites for A, B and C on 100 questions. If the key is shared with production, this could use up the live chat's daily allowance.
- It sends benchmark questions and official-document passages to Google.

What is ready:
- `research/scripts/run_answer_abc.py` runs the full assistant path for each pipeline with one model, the same prompt (system_v2, sha `602ba59399c5a54c`, identical in the deployed and current code) and the same budget.
- It records every case, including failures, and computes:
  - generation success;
  - language consistency;
  - citation precision against frozen and AI-proposed labels;
  - evidence completeness (evidence terms in the answer);
  - latency.
- `--annotation` produces a blinded worksheet for human correctness and faithfulness scores.
- The dry run passed (5 questions × B and C; C's reranking ran in the real assistant path).

## 6. Deployment risks

| Risk | Affects | Mitigation |
|---|---|---|
| The new extractor changes the text of other PDFs on future uploads | new uploads only | Validated byte-identical (apart from `\x07`) on all 6 production PDFs; existing versions are not re-extracted automatically |
| Body-size estimate over all pages costs time on very long PDFs | ingestion | +0.8 s for 94 pages; the 300-page limit and the extraction timeout are unchanged |
| The older-source warning appears on many new versions | reviewers | Warning only; threshold configurable (`SOURCE_REVIEW_AGE_DAYS`) |
| The guidebook v2 makes a 94-page general guide compete with specific pages | retrieval | Milestone 5: evidence found +5 pp, frozen-label MRR −4.6 pp (labels do not credit the guidebook); review after approval with the health check |
| The guidebook content is from 2021 | answers | Older-source warning plus the published date in the model's context; editors verify before approving |
| Enabling the reranker on the current instance | the whole API | **Do not enable**: memory limit exceeded and latency too high |
| Uncommitted Milestone 2.2 changes (Gemini, selection) ship with this deploy | chat | Already tested (483 backend tests pass); they were part of the measured pipeline B |
| Deploying requires a push to `main`, which triggers the Render deploy hook | production | Push only with your approval; deploy outside busy hours |

## 7. Rollback plan

- **Code:** revert the deploy commit and push, or roll back to the previous deploy in the Render dashboard. There are no database migrations in this change set.
- **Guidebook v2:** if v2 is approved and proves worse, use **rollback to v1** in the document's version history (`rollback_document_version`). v1's chunks and embeddings are kept, so rollback needs no re-embedding. A v2 that hasn't been approved can be rejected; v1 stays live.
- **Reranker:** it stays off by default. If it is ever enabled, set `RERANK_PROVIDER=none` to switch it off; selection then returns to first-stage ordering. A reranker error already falls back automatically, per answer.
- **Evidence layer:** `ASSISTANT_EVIDENCE_CHECK=false`, the default.

## 8. Recommended final architecture

1. **Now, after your approval:**
   - Commit and deploy the production changes:
     - extractor fix;
     - re-extraction endpoint and CLI;
     - older-source warning;
     - order-preserving selection;
     - reranker module switched off;
     - lifecycle verification;
     - evidence layer off;
     - source-quality checks.
   - Then re-extract the guidebook into a pending v2 and have it reviewed.
2. **Retrieval:**
   - Keep the weighted hybrid with the current selection in production (A/B: no difference).
   - The order-preserving selection is in place for when reranking becomes affordable.
3. **Reranking:** recommended for quality, by +6 to +8 pp MRR, consistently across studies. It should run only where it fits: a separate reranking service with at least about 1 GB RAM and a dedicated vCPU, or a larger API instance.
   - Measure INT8 vs fp32 again on that x86 hardware.
   - Prefer fp32 ONNX if the latency allows, since INT8 changes a quarter of the top-1 choices.
   - Re-measure end-to-end latency there before enabling it.
   - This needs a hosting decision from you, so it was not set up.
4. **Before claiming improvements:**
   - Human review of v0.3 and the new-document labels.
   - The Gemini answer comparison (§5.5) with human scoring of correctness and faithfulness.

## Files

- **PDF validation:**
  - `research/scripts/validate_pdf_fix.py`
  - `research/data/experiments/pdf_fix_validation/summary.json`
  - `guidebook_old.md` / `guidebook_new.md`, in the same folder
- **Reranker runtime:**
  - `research/scripts/export_reranker_onnx.py`
  - `research/scripts/bench_reranker_runtime.py`
  - `research/data/experiments/reranker_runtime/`
  - `reports/production_readiness/reranker_*.csv`
- **A/B/C:**
  - `research/scripts/run_readiness_eval.py`
  - `research/scripts/readiness_analysis.py`
  - `research/data/experiments/readiness/`
  - `reports/production_readiness/abc_*.csv`
- **Answer harness:**
  - `research/scripts/run_answer_abc.py` (dry run in `research/data/experiments/answers_abc/`)
- **Backend:**
  - `extractors_files.py`
  - `pipeline.py` (`request_reextraction`, older-source warning)
  - `source_quality.py` (`age_review_warning`)
  - `api/admin_documents.py` (`re-extract`)
  - `cli.py` (`reextract`)
  - `retrieval/rerank.py`
  - `assistant/engine.py` (`_rerank`, `_select(preserve_order)`)
  - `core/config.py`
- **Tests:**
  - `tests/test_pdf_reextraction.py`
  - `tests/test_rerank_selection.py`
