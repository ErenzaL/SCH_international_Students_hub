# Deployment record and Gemini pilot plan (2026-11-23)

## 1. What was deployed

- **Commit:** `671824c` on `main`, which deploys through the Render deploy hooks. The previous production commit was `7e647cd`.
- **Contents:**
  - Gemini reliability (Milestone 2.2);
  - document-lifecycle checks;
  - the PDF body-size fix and control-character removal;
  - the re-extract action, a dry run by default;
  - the reranker hook, off;
  - the evidence-sufficiency layer, off.
- **Not deployed:** reranker models, the research code and data, and any configuration change.
- **Database:** no migration; migrations 0001–0012 were already applied.
- **Production documents:** no document record was changed.

### Checks before the push

| Check | Result |
|---|---|
| Backend tests (working tree) | 484 passed, 11 skipped |
| Backend tests (clean checkout of `671824c`) | 483 passed, 12 skipped (the extra skip is the real-model reranker test: no model is committed) |
| Ruff | clean |
| Web: eslint, `tsc --noEmit`, vitest, `next build` | clean; 150 tests passed; build succeeded |
| Backend typecheck | not available: no mypy or pyright in the backend environment |
| Secret, path and size scan of the staged diff | clean (one fake key inside a redaction test; no file over 200 KB) |
| Defaults | `RERANK_PROVIDER=none`, `ASSISTANT_EVIDENCE_CHECK=false` |
| Re-extract endpoint | admin only (401 without a token, 403 for supporters). A dry run by default writes nothing (tested). `?apply=true` creates a `pending_review` version only. |

### Deployment and smoke tests

- **API:** new routes went from 404 to 401 about 2 minutes after the push. `/health` is ok with the same embedding model (`multilingual-e5-small#qint8`).
- **Transient errors:** for about 40 seconds during the instance switch, some requests returned 404 or an empty 400. Every sample has been 401 since 12:30 UTC.
- **Web:** the new "AI model check" strings are in the served HTML.

Chat smoke test: anonymous chat, one synthetic question per language, nothing stored.

| Language | Result | Model | Fallback | Evidence | Answer input tokens | Output tokens | Latency |
|---|---|---|---|---|---|---|---|
| en | llm | gemini-3.5-flash-lite | yes | sufficient | 5,903 | 230 | 39.8 s (first call) |
| ko | llm | gemini-3.5-flash-lite | yes | sufficient | 5,700 | 66 | 14.0 s |
| vi | llm | gemini-3.5-flash-lite | yes | sufficient | 4,741 | 449 | 5.3 s |
| id | llm | gemini-3.5-flash-lite | yes | sufficient | 5,204 | 342 | 5.5 s |
| zh-CN | llm | gemini-3.5-flash-lite | yes | partial | 5,590 | 402 | 6.0 s |

- **Citation links:** 11 distinct cited documents; 10 open on `/knowledge/<id>`.
- **Broken link (existing bug):** one cited item is an announcement, which the public documents API hides by design. The chat links every citation to `/knowledge/<id>`, so this link shows nothing. The fix is to link announcements to the announcement page.
- **Indexing health** (read-only SQL, same checks as `/admin/rag/health`):
  - 25 of 25 published documents searchable;
  - 766 of 766 current chunks embedded with the current model;
  - 0 open jobs, 0 pending versions.

### Rollback

- **Code:**
  - quickest: Render dashboard → each service → Deploys → "Rollback" to the `7e647cd` deploy;
  - from git: `git revert 671824c && git push origin main`.
  - No schema change, so no database rollback is needed. The new code writes only audit and alert rows.
- **Configuration only** (no code rollback), on the API service:
  - return to the old context budget with `ASSISTANT_MAX_PASSAGES_PER_SOURCE=2` and `ASSISTANT_CONTEXT_CHARS=7000`;
  - reranking and the evidence layer are already off.
- **Guidebook,** after a future `--apply` and approval: `POST /api/v1/admin/documents/{document_id}/rollback` with v1's `version_id`. v1 is never modified.

## 2. Guidebook dry run (production version `612108fb-…`, no `--apply`)

- **What ran:** `app.cli reextract` from `671824c`.
- **Inputs:** a read-only production snapshot: the version, document and source rows, plus the stored original, whose SHA-256 matches `original_file.sha256`.
- **Writes:** none. Full output: `data/experiments/pdf_fix_validation/production_dry_run_2026-11-23.json`.

| | Stored v1 | Re-extracted |
|---|---|---|
| Characters | 85,568 | 77,210 |
| Chunks | 291 | 178 |
| Median chunk length | 37 | 454 |
| Chunks under 100 characters | 258 | 21 |
| Words of the text layer in chunk text | 26.6% | 97.3% |
| … including headings | 41.2% | 99.0% |
| Pages with at least one chunk (of 94) | 77 | 88 |
| Share of text in heading lines | – | 3.5% |

- **Pages without chunks after the fix:**
  - pages 3, 4, 5 and 91 are images with no text layer; they need OCR or manual text;
  - pages 1 and 2 are cover pages with almost no text.
- **Warnings:**
  - those image-only pages;
  - "Older source: published 2021-03-05 and declares a 2021 edition…", which asks the reviewer to verify fees, deadlines, visa, work and insurance rules, and contacts.
- **Apply status:** `can_apply: true`; no job is open for the source.

## 3. Gemini A/B pilot: plan only, not run

**Production fact found by the smoke test:** every answer came from the **fallback** model, `gemini-3.5-flash-lite`. The primary model is failing for this key (unavailable, quota or permission). Diagnose this first: Admin → Settings → "AI model check" makes 4 tiny requests. It also means a pilot run with the same key competes with students for the same daily quota.

**Design.** Questions come from the held-out v0.2 set: 4 scenarios × 5 languages = 20 synthetic questions (`--limit 20`, scenarios H01–H04). The pilot never touches production data. It runs on the local corpus_v2 index, which holds the same text as production.

| Setting | A (previous production) | B (current production) |
|---|---|---|
| Code | `7e647cd`, run as a git worktree | `671824c`, the working tree |
| Gemini model | one pinned model, no fallback | the same pinned model, no fallback |
| Context budget | 4 sources × 3 passages, 9,000 characters | same |
| System prompt | `system_v2` (identical sha) | same |

- **Scope:** `C` (B + INT8 reranker) can be added later for 50% more calls.
- **Why no fallback:** every answer then comes from the same model, and failures count as failures.

**Estimated usage**, from the measured smoke-test tokens:

| | Per question | Pilot (40 answers) |
|---|---|---|
| Requests (query rewrite + answer) | 2 | **80** |
| Worst case with retries (2 attempts, no fallback) | 4 | 160 |
| Input tokens (answer about 5.6k + rewrite about 0.5k) | about 6.1k | **about 245k** |
| Output tokens (answer about 0.3–0.45k + rewrite about 0.15k) | about 0.5k | **about 20k** (up to about 60k if the model uses "low" thinking) |
| Wall time at `--pause 8` | about 15 s | about 10–12 min (at most about 8 requests per minute) |

- **Quota:** I do not know this project's Gemini limits. Check Google AI Studio → rate limits for the key's project and confirm room for **at least 160 requests that day** on the pinned model.
- **Cost:** on a project without billing these calls are free-tier. If billing is enabled on that project, they are billed. Nothing was enabled.

**Safeguards already in the script:**
- `--max-consecutive-failures 3` stops on a quota or outage; results so far are kept;
- every case is recorded, including failures;
- synthetic questions only;
- the key is read from the environment and never written.

**Measured automatically:**
- generation success;
- language consistency;
- citation precision and hit rate (frozen labels, and frozen + AI-proposed labels);
- evidence-term coverage;
- latency;
- served model.

**Not scored automatically:** correctness and faithfulness. `--annotation` writes a blinded worksheet (40 rows, about 1–2 hours for one reviewer). No LLM judge is used. Any AI-drafted judgment must be labelled as such.

**Commands** (run only after approval; replace `<model>` with the model chosen after the AI model check):

```bash
# B: current production code
cd backend
read -rs GEMINI_KEY
LLM_PROVIDER=gemini LLM_API_KEY="$GEMINI_KEY" GEMINI_PRIMARY_MODEL=<model> GEMINI_FALLBACK_MODEL= \
  .venv/bin/python ../research/scripts/run_answer_abc.py B --limit 20 --pause 8
unset GEMINI_KEY

# A: previous production code
git worktree add ../_wt_prev 7e647cd
cd ../_wt_prev/backend
read -rs GEMINI_KEY
LLM_PROVIDER=gemini LLM_API_KEY="$GEMINI_KEY" GEMINI_PRIMARY_MODEL=<model> GEMINI_FALLBACK_MODEL= \
  <repo>/backend/.venv/bin/python <repo>/research/scripts/run_answer_abc.py A --backend . --limit 20 --pause 8
unset GEMINI_KEY

# blinded worksheet for human review
<repo>/backend/.venv/bin/python <repo>/research/scripts/run_answer_abc.py --annotation
```
