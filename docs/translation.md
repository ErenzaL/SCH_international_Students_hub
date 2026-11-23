# Automatic translation and original documents (2026-11-23)

## Three separate concerns

| Concern | Where it lives | Never does |
|---|---|---|
| A. Original document (storage + viewing) | private bucket `source-files`; `GET /api/v1/knowledge/documents/{id}/original` | expose the bucket; serve a draft, an older version or a private document |
| B. Display translation | `announcement_translations`, `document_translations` (+ revisions) | change the original; create chunks or embeddings |
| C. RAG indexing / retrieval | `document_chunks`, `searchable_chunks` | use translations; reconstruct a document view from chunks |

## Original documents in the Knowledge Center

The document page shows the original by type (`original.kind` in `GET /api/v1/knowledge/documents/{id}`):

| Kind | Shown as | Notes |
|---|---|---|
| `pdf` | pdf.js viewer | Pages drawn in the browser (lazy, so long PDFs stay light), page navigation, zoom, fit to width, full screen (a CSS overlay that also works on phones), open in a new tab, download. `?page=N` opens at page N (chatbot citations). |
| `docx` | Formatted preview in an `<iframe sandbox="">` | Built from the file's structure with python-docx: headings, paragraphs, bold/italic, lists, tables, embedded raster images. Every text is escaped, so no markup or script from the file reaches the page, and the frame cannot run code. Download is always offered. |
| `web` | Link to the official page | Captured text sits in a collapsed "Text version", labelled as captured text. |
| `text` | The approved text | Pasted or manual entries: this text is the original. |

- For PDFs and Word files, the extracted text is a collapsed "Text version (extracted for search and translation)". It is never presented as the document.
- **Access control:** the original route applies the same checks as the public document page: public source, not withdrawn or archived, current approved version only.
- **Missing or unreadable file:** a 404 with code `original_unavailable`. The page then offers open and download links.
- **Server-side DOCX→PDF conversion:** not available. LibreOffice cannot be installed on the Render Python runtime.

## Automatic Korean ↔ English translation

### Flow

1. Each of these queues a durable job (`translate_announcement` / `translate_document`) per missing target language in `AUTO_TRANSLATE_LANGUAGES`:
   - an announcement is published or re-published;
   - a document version becomes active.
2. The worker claims jobs with `FOR UPDATE SKIP LOCKED`. A restart re-queues running jobs through the heartbeat check.
3. Publication never waits for a translation.

### Idempotency, cache and budget

- **Idempotent:** a row that already holds a machine translation of the same content hash is left alone.
- **Cache:** identical text translated before (same hash and language) is copied, not sent to the model again.
- **One open job per row:** enforced by a unique partial index (migration 0013); a request that races another gets the existing job.
- **Long documents:** documents over `TRANSLATION_FULL_MAX_CHARS`, or needing more than `TRANSLATION_MAX_REQUESTS_PER_JOB` calls, get the title plus an AI summary (`scope = summary`). Students see "Summary only, not a full translation".
- **Daily budget:** at most `TRANSLATION_DAILY_JOB_LIMIT` translation jobs start per UTC day. More wait until tomorrow.
- **Quota:** an exhausted provider quota defers the job by `TRANSLATION_QUOTA_RETRY_SECONDS` instead of failing it, up to `TRANSLATION_MAX_DEFERRALS` times. Transient errors retry with backoff.

### Quality checks

The checks are in `app/services/translation/quality.py`. They look for:
- lost URLs, e-mail addresses, phone numbers, visa codes or numbers;
- heading or table-row changes;
- the wrong target language;
- truncation or missing paragraphs;
- leftover placeholders;
- numbers, URLs or codes the original does not contain.

Any finding sets the status to `needs_review`: the translation is never shown to students, and reviewers are notified.

### Display

- **Machine translations:** shown only when `PUBLIC_MACHINE_TRANSLATIONS=true`, always labelled, with "View original".
- **High-risk content:** immigration, employment, insurance, fees or legal content is labelled "Unverified machine translation". With `MACHINE_TRANSLATION_HIGH_RISK=review` it is hidden until approved.
- **Precedence:** human-approved translations always win. The machine never overwrites a person's draft.

### Admin

- **Announcement translation editor:** shows the machine-translation state, model, time, check warnings and last job error, with a "Machine-translate / Translate again" button. The button calls `POST /api/v1/admin/announcements/{id}/translations/{lang}/machine-translate`.
- **Document translations:** keep their existing tab (AI draft, edit, approve).

### Backfill

| Command | What it does |
|---|---|
| `python -m app.cli translate-backfill` | Dry run: counts, long documents, estimated requests and tokens. |
| `python -m app.cli translate-backfill --apply --limit 10` | Queues 10 jobs for the API worker. Safe to re-run; it resumes. |

### Settings (all off or conservative by default)

| Variable | Default | Meaning |
|---|---|---|
| `AUTO_TRANSLATE_ANNOUNCEMENTS` | `false` | queue machine translations when an announcement is published |
| `AUTO_TRANSLATE_DOCUMENTS` | `false` | the same for document versions (existing setting) |
| `AUTO_TRANSLATE_LANGUAGES` | `ko,en` | target languages generated automatically; add `id,vi,zh-CN` later, no schema change |
| `PUBLIC_MACHINE_TRANSLATIONS` | `false` | show clean machine translations to students (labelled) |
| `MACHINE_TRANSLATION_HIGH_RISK` | `label` | `label`: shown as unverified; `review`: hidden until approved |
| `TRANSLATION_MODEL` | `""` | Gemini model for translation jobs (`""` = the assistant's primary/fallback) |
| `TRANSLATION_FULL_MAX_CHARS` | `12000` | longer documents: title + summary only |
| `TRANSLATION_SUMMARY_SOURCE_CHARS` | `40000` | text given to the summarizer (plus every section heading) |
| `TRANSLATION_MAX_REQUESTS_PER_JOB` | `6` | model calls per job |
| `TRANSLATION_DAILY_JOB_LIMIT` | `60` | translation jobs per UTC day |
| `TRANSLATION_QUOTA_RETRY_SECONDS` / `TRANSLATION_MAX_DEFERRALS` | `3600` / `24` | quota deferral |

**Database:** migration `20261123000013_automatic_translation.sql` (additive). It adds:
- the `needs_review` status;
- `document_translations.scope`;
- provider, model, generated time and warnings on announcement translations;
- the `translate_announcement` job type.
