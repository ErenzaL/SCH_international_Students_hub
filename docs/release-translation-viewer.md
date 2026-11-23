# Release: original document viewer, citations, Korean ↔ English translation (prepared 2026-11-23)

- **Branch:** `release/translation-viewer`, made from `main` = `671824c` (the deployed commit).
- **State:** not committed, not pushed, not deployed.
- **Research:** stays on `research/milestone-5`; none of it is in this branch.
- **Held back:** the Gemini "fail over without retry" change is not part of this release. It is kept as `.git/release-backups/gemini-failover.patch` and applies cleanly on top of this branch.

## 1. What is in the branch

| Area | Files |
|---|---|
| Original PDF viewer, Word preview | `apps/web/src/features/knowledge/{pdf-viewer,document-original}.tsx`, `knowledge-article.tsx`, `app/knowledge/[id]/page.tsx`, `backend/app/services/originals.py`, `public.py` (service + API), `package.json` (`pdfjs-dist` 6.4.299, pinned) |
| Citation navigation | `backend/app/services/assistant/engine.py` (`citation_link`), `apps/web/src/features/chatbot/{chat-message,chat-widget}.tsx` |
| Translation (auto, queue, checks, backfill) | `backend/app/services/translation/{auto,quality,backfill}.py`, `document_translations.py`, `translations.py`, `translation_drafts.py`, `ingestion/pipeline.py` (job type, quota deferral), `container.py`, `config.py`, `cli.py`, `api/admin_announcements.py`, the announcement and Knowledge Center pages, the admin translation editor, the message files |
| Migration | `supabase/migrations/20261123000013_automatic_translation.sql`; manual rollback `supabase/rollback/20261123000013_automatic_translation_down.sql` |
| Guidebook extractor | `ingestion/extractors_files.py` (bullet glyphs are not headings), `source_quality.py` + `pipeline.py` (page checklist for older sources) |
| Tests / docs | `backend/tests/test_{auto_translation,citation_links,original_documents,pdf_reextraction}.py`, `tests/integration/test_auto_translation_integration.py`, `supabase/tests/behavior_test_automatic_translation.sql`, the web `*.test.tsx`, `docs/translation.md`, this file |

## 2. Migration 0013: safety findings

Verified on a scratch PostgreSQL 18 + pgvector + PostgREST with all 13 migrations (`scripts/run_sql_tests.sh`) and a dedicated upgrade test.

| Check | Result |
|---|---|
| Existing records | Data seeded on 0001–0012, then 0013 applied: checksums of translations, jobs and versions identical. New columns filled by defaults (`scope='full'`, `warnings='[]'`). |
| Constraint names | Match production exactly (read-only `pg_constraint` query), so the old checks are replaced, not duplicated. Every existing status is in the new lists, so validating existing rows cannot fail. |
| Permissions / RLS | No grant or policy changes. anon still sees only `human_approved`, current rows; a machine or `needs_review` row is invisible (behaviour test). Students get machine translations only through the API, and only when enabled. |
| Idempotency | `drop … if exists` / `add column if not exists` / `create … if not exists`. Applying 0013 twice more after a rollback: no error, data unchanged. |
| Translation uniqueness | `unique(version_id, language_code)` (documents) and `unique(announcement_id, language_code)` are unchanged, as is the version-ownership trigger. New: a **unique partial index**, so there is at most one queued/running job per translation row. The code returns the existing job when two requests race; tested in memory and through PostgREST. |
| Backward compatibility | The deployed code (`671824c`) passes its integration tests on the migrated schema. The new code passes all integration tests (8) against real Postgres. |
| Locking | `ALTER TABLE … ADD CONSTRAINT` takes a short exclusive lock on three small tables (tens of rows). |
| Failure recovery | Every statement is re-runnable: if a push stops halfway, run it again. Full rollback: `supabase/rollback/…_down.sql`, tested. It turns `needs_review` into `rejected`, deletes announcement translation jobs, and restores the old checks. |

## 3. Gemini: how to verify production models without exposing the key

Production currently answers only with `gemini-3.5-flash-lite`, the configured fallback. The cause for the primary is not yet verified: a stored error says "model not available", but a zero quota looks the same.

### Option A: in the site (no key leaves Render)

1. Sign in as an admin.
2. Go to **Admin → Settings → AI model check → Check AI models**. This makes two tiny calls per configured model and is limited to 3 runs a minute.
3. Each row shows the model, the call (generate / stream), the result, and the HTTP status, Google status, quota id and Google's message. Key-like text is redacted.
4. Record:
   - **404 / NOT_FOUND:** the model ID is not available to this key.
   - **429 with `limit: 0`:** the model is not in the project's tier.
   - **403:** the key is not permitted.
   - **OK:** usable.

### Option B: list every model the key can use (on your own computer)

The key is typed, not stored or echoed:

```bash
cd backend
read -rs GEMINI_KEY
LLM_PROVIDER=gemini LLM_API_KEY="$GEMINI_KEY" GEMINI_PRIMARY_MODEL=<current primary> \
  GEMINI_FALLBACK_MODEL=<current fallback> .venv/bin/python -m app.cli check-llm --list --generate
unset GEMINI_KEY
```

### Choosing models (no IDs are guessed here)

- **Primary:** the model you intend to use, only if both its probes are OK. Otherwise use a model from the `--list` output that passes `--generate`.
- **Fallback:** a different model that passes. Prefer one with a different `quota_id`, so one exhausted quota does not stop both. Until a second model is verified, set primary = `gemini-3.5-flash-lite` (the only one proven in production) and leave the fallback empty. Each answer then stops spending a failed call on the broken primary.
- **Translation model (`TRANSLATION_MODEL`):** empty (use the assistant's models) or the cheapest verified model. Translations share the key, and therefore the project quota, with the chatbot.

### Limits

Read the per-model RPM / RPD in Google AI Studio for this project (free tier; do not enable billing).

- **Chat:** an answer costs 2 calls (rewrite + answer), so keep `AI_DAILY_LIMIT_GLOBAL` × 2 + the translation budget under the model's RPD.
- **Translation pilot:** `TRANSLATION_DAILY_JOB_LIMIT=10` (each job is at most 6 calls). The full backfill is about 53 calls in total.

## 4. Viewer and citation checks in a real browser

Run in Chrome via Playwright against a local, seeded backend, using the real 94-page guidebook, a numbered 12-page PDF, a Word file with an image, a web source and a Korean announcement.

**Passed (30 checks, desktop 1280 px and iPhone-size 390 px, touch):**
- **Original file only:** the viewer fetches `/original`, never a search endpoint.
- **PDF controls:** `?page=7` and `?page=40` open the right page; next / previous / typed page, zoom, fit width and full screen (fills the phone screen) work.
- **Downloads:** the original PDF and Word files download as attachments.
- **Text version:** collapsed and labelled.
- **Word preview:** sandboxed, with table, list, bold and image; the test heading's `<script>` shows as text.
- **Web sources:** link to the official URL.
- **Announcements:** show the unverified machine translation label and "View original".
- **Citations:** chat citations open the announcement page and the PDF at the cited page. On the phone the chat closes and the conversation is kept.
- **Layout:** no horizontal overflow on the phone; no page errors.

**Found and fixed during these checks:**
- full screen was 8 px short on phones;
- zooming or entering full screen lost the current page (it jumped from 40 to 27);
- leaving full screen on a phone moved to the next page.

**Not executed:**
- real iOS Safari / Android devices (emulated sizes only);
- production storage (a local in-memory store);
- Gemini translations (a scripted translator).

**Signed URLs:** not used by design. The API reads the private bucket after the publication checks and streams the file. No storage URL is exposed, and drafts, older versions and withdrawn documents return 404 (tests).

## 5. Deployment sequence (each step needs your go-ahead)

1. **Gemini.** Run the model check (section 3). Set the verified `GEMINI_PRIMARY_MODEL` / `GEMINI_FALLBACK_MODEL` on the API service; Render redeploys.
2. **Backup.** Free-tier Supabase has no downloadable backups. Take a dump on your own computer, kept private (it contains personal data):
   - `supabase db dump --linked -f backup-schema.sql`
   - `supabase db dump --linked --data-only -f backup-data.sql`
3. **Migration first** (the deployed code works with it):
   - `supabase db push --remote --dry-run` should list only `20261123000013`;
   - then `supabase db push --remote`;
   - check: `select version from supabase_migrations.schema_migrations order by 1 desc limit 1`.
4. **Code.** Commit this branch, merge to `main`, push. The deploy hook redeploys both services. All translation switches stay at their defaults (off).
5. **Health:**
   - `/health`;
   - `GET /api/v1/knowledge/documents/<guidebook id>/original` returns 200 application/pdf;
   - `GET /api/v1/admin/rag/health` (admin);
   - a draft document's `/original` returns 404.
6. **Viewer.** Open the guidebook (`/knowledge/d60bc363-…?page=40`), a Word document and a web document, on a phone and a computer.
7. **Citations.** Ask the chatbot about part-time work and confirm the announcement and PDF citation targets.
8. **Pilot:**
   - set `AUTO_TRANSLATE_ANNOUNCEMENTS=true`, `AUTO_TRANSLATE_LANGUAGES=ko,en`, `TRANSLATION_DAILY_JOB_LIMIT=10`;
   - leave `PUBLIC_MACHINE_TRANSLATIONS=false`;
   - publish or re-publish one announcement, or use "Machine-translate" in the admin editor.
9. **Inspect quality.** A reviewer reads the machine translation in the admin editor (warnings shown). If acceptable, set `PUBLIC_MACHINE_TRANSLATIONS=true`, optionally with `MACHINE_TRANSLATION_HIGH_RISK=review` at first.
10. **Backfill.**
    - Dry run: `python -m app.cli translate-backfill`. On the production snapshot: 24 pairs, ~53 requests, ~103k input / ~30k output tokens, 5 long documents summary-only.
    - Then `--apply --limit 5` per batch, after approval each time. Set `AUTO_TRANSLATE_DOCUMENTS=true` only after that.
11. **Guidebook v2.**
    - `POST /api/v1/admin/versions/612108fb-…/re-extract?apply=true` (admin), or `python -m app.cli reextract … --apply`.
    - This creates `pending_review` v2 only. A reviewer checks it with the page checklist warning and approves; v1 stays live until then.

## 6. Rollback

| What | How |
|---|---|
| Code | Render → service → Deploys → Rollback to `671824c`, or `git revert <merge>` + push. Safe with migration 0013 in place (tested). |
| Translations shown to students | `PUBLIC_MACHINE_TRANSLATIONS=false` (immediate; originals shown). |
| Stop generating | `AUTO_TRANSLATE_ANNOUNCEMENTS=false`, `AUTO_TRANSLATE_DOCUMENTS=false`. Queued jobs can be left; they only write translation rows. |
| Schema | Only after the code is back on `671824c`: run `supabase/rollback/20261123000013_automatic_translation_down.sql` with psql. |
| Guidebook | v1 is never modified. Before approval, reject v2. After approval, `POST /api/v1/admin/documents/{id}/rollback` with v1's `version_id`. |
