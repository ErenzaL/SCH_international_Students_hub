# Integrated release: translation and document viewer + AI Support Office (prepared 2026-11-24)

| | |
|---|---|
| Branch | `integration/release-ai-office`, from `main` = `671824c` (deployed) |
| Merged branches | `release/translation-viewer` (`44224d8`), `feature/ai-office` (`9800ae3`) |
| State | Local only: not pushed, not deployed |
| Not included | `research/milestone-5`, the held-back Gemini failover patch (`.git/release-backups/gemini-failover.patch`) |

## Merge

- **Conflict:** one, in `apps/web/src/features/chatbot/chat-widget.tsx`. Resolved by keeping both behaviours:
  - the AI Office's shared chat (`useAssistantChat` + `ChatBody`; the widget is hidden on `/ai-office`);
  - the release's phone behaviour: the floating widget closes when a citation to a site page is opened, and the conversation is kept. It now flows through `ChatBody`'s `onNavigate`.
- **Locale files:** merged automatically and validated (5 languages, every key present).
- **Test fix:** the PDF viewer test now waits for the loader effect. It failed about 1 in 5 full-suite runs; it now passed 8 of 8.

## Verification

| Check | Result |
|---|---|
| Backend | 518 passed, 15 skipped; ruff clean |
| Real database (PostgreSQL 18 + pgvector + PostgREST) | integration tests 8 passed; all SQL behaviour suites passed |
| Migration 0013 on existing data | data identical; rollback and re-apply tested |
| Web | 198 tests passed; lint, typecheck and production build clean |
| Real Chrome, against a local seeded backend from this branch (not production data) | 75 checks passed: viewer / citations / translation 30, AI Office 31, tablet + translation UI + floating chat 14 |

- **Viewports:** desktop, tablet portrait and landscape, phone, keyboard, and reduced motion.
- **Screenshots:** `docs/integration-screenshots/`.

**Safe defaults, confirmed:**
- `RERANK_PROVIDER=none`;
- `ASSISTANT_EVIDENCE_CHECK=false`;
- `AUTO_TRANSLATE_ANNOUNCEMENTS=false` and `AUTO_TRANSLATE_DOCUMENTS=false`;
- `PUBLIC_MACHINE_TRANSLATIONS=false`;
- the backfill is a dry run unless `--apply`.

**Diff check:**
- **Dependency:** one new one, `pdfjs-dist` 6.4.299 (pinned).
- **Scan:** no secrets, research data, PDFs or model weights.
- **Assets:** 17 character PNGs (about 1.5 MB).

## Deployment

Each step needs approval.

1. **Gemini.** Run Admin → Settings → AI model check. Set verified `GEMINI_PRIMARY_MODEL` / `GEMINI_FALLBACK_MODEL`; the only one proven so far is `gemini-3.5-flash-lite`. Translation stays off.
2. **Backup.** On the owner's computer, kept private:
   - `supabase db dump --linked -f backup-schema.sql`
   - `supabase db dump --linked --data-only -f backup-data.sql`
3. **Migration first.** The deployed code works with it (tested).
   - `supabase db push --remote --dry-run` should list only `20261123000013`;
   - then `supabase db push --remote`.
4. **Code.** Merge `integration/release-ai-office` into `main` and push. The deploy hook rebuilds the API and web services.
5. **Checks:**
   - `/health`;
   - `/ai-office`: characters, a supporter chat, desk lists;
   - the guidebook at `?page=40`; a Word preview;
   - a chatbot citation to an announcement;
   - the floating chat on `/knowledge`.
6. **Later, separately:** the translation pilot, the backfill batches and guidebook v2 (`docs/release-translation-viewer.md`).

## Rollback

| What | How |
|---|---|
| Code | Render → Deploys → roll back to `671824c`, or revert the merge on `main` and push. Compatible with migration 0013. |
| Translations | `PUBLIC_MACHINE_TRANSLATIONS=false` and `AUTO_TRANSLATE_*=false`. |
| Schema | Only after the code is rolled back: `supabase/rollback/20261123000013_automatic_translation_down.sql`. |
| AI Office | Frontend only: rolling back the code removes it. No data. |

## Limitations

- The local browser checks used a scripted model, a fake translator and seeded data. Real Gemini answers and translations are not verified.
- On a portrait tablet, the open panel leaves a narrower, scrollable office beside it.
- Office conversations opened from a phone citation are kept in session storage and restored when the character is reopened. The panel itself closes because the page changes.
