# Ingestion

```
register URL → validate (scheme, allowlist) → DNS/IP check → robots.txt → GET (manual redirects, each revalidated)
→ extract main content → normalize → SHA-256 → compare with existing versions → new version (pending_review)
→ chunk → embed (passage:) → admin review → approve (atomic) → searchable
```

## Safety rules

* Only the exact registered page is fetched – **no crawling**.
* http/https only; no credentials in URL; ports 80/443 only; literal IPs rejected; host must match `ALLOWED_SOURCE_DOMAINS`
  (default: sch.ac.kr, studyinkorea.go.kr, hikorea.go.kr, topik.go.kr, nhis.or.kr, moel.go.kr).
* Every resolved IP must be public (loopback, private, link-local incl. 169.254.169.254, CGNAT, multicast, reserved are blocked).
* Redirects are followed manually (max 4); each hop is re-validated against the allowlist and IP rules.
* robots.txt is respected (403 on robots.txt = disallowed; unreachable = `robots_unavailable`).
* Timeouts (10 s connect / 20 s read), streaming size limit (5 MB), TLS verification never disabled (`ssl_error` reported).
* 401/403/406/429 or blocking → clear `http_xxx` error; no captcha/auth/anti-bot bypass. Use manual import.
* A failed fetch/extraction never produces empty content and never touches the last approved version.
* Residual risk: DNS rebinding by someone controlling an allowlisted domain's DNS (resolution is checked immediately before each request, not pinned).

## Extractors

* **HTML**: Trafilatura (markdown, tables, links) → BeautifulSoup fallback (drops nav/footer/boilerplate; headings, lists, pipe tables, absolutized links). EUC-KR/CP949 decoded. Title-only pages fail with `empty_extraction`.
* **PDF** (PyMuPDF): per-page text with `[Page N]` markers → page references on chunks; image-only → `needs_ocr`; partial scans warn.
* **DOCX** (python-docx): headings, lists, tables. Zip-bomb and magic-byte checks.
* **Manual text / KakaoTalk**: normalized text. KakaoTalk text requires `authorized_by_supporter` and is redacted (sender names, timestamps, phones, e-mails, ID/account numbers) before storage. Private KakaoTalk groups are never read automatically.
* Uploads: type/extension/magic/size validated, then stored in the private bucket; invalid files are not stored.

## Versioning, chunking, embeddings

Identical normalized content ⇒ `unchanged` (no version). Changed ⇒ new `pending_review` version; an older *pending* one is `superseded`; an approved one is never touched.
Chunker: headings/paragraphs, ~320 target / 420 max estimated tokens, ~48 token overlap within a section, numbered lists and dates kept intact, page ranges preserved, strategy id `v1` stored. `POST /admin/versions/{id}/reprocess` rebuilds chunks and reuses embeddings whose input hash/model are unchanged.
Embeddings: `intfloat/multilingual-e5-small`, 384-d, `passage:`/`query:` prefixes, L2-normalized, CPU, lazy; if the model cannot load, chunks are stored without vectors, the job reports `embedding_unavailable`, approval is blocked until a successful reprocess, and search falls back to keyword with an explicit warning.

## Source registry and verified access (tested live, 2026-11-22, from a development laptop in Korea)

Command: `python scripts/check_sources.py`

| Source | Result |
|---|---|
| SCH international notices (sgee.sch.ac.kr) | **OK** – 200, extracted board list (titles/dates/links), ~2,100 chars |
| Study in Korea – visa & stay | **OK** – 200, ~3,600 chars, 21 chunks; page is served in **Korean** (registered as `ko`) |
| Hi Korea | fetched, **empty extraction** (content not in static HTML; JS-rendered or portal shell) |
| TOPIK | fetched, **empty extraction** |
| NHIS | fetched, only a logo/stub page → rejected as empty |
| MOEL | fetched, **empty extraction** |

For the last four use *Submit text* / *Upload* with official material. Results can differ by network and over time; always test your own.
The SCH notice board is a *list page*: it is a convenient change detector, but per-notice detail URLs would need to be registered individually (no crawling).

## Phase 1 demonstration

`scripts/demo_pipeline.py` (in-memory store, real network, real E5): ingests the Study-in-Korea page (21 chunks embedded, approved), shows a second fetch is `unchanged`,
publishes one **TEST DATA** SCH notice via the manual flow, and runs multilingual queries. English/Indonesian queries against Korean content return the semantically nearest chunks
(e.g. "D-2 visa extension" → the D-2 visa chunk) but E5 similarities cluster at 0.79–0.88, so irrelevant queries still score ~0.80: keep `RETRIEVAL_MIN_SIMILARITY` tuned on a labelled set.

---

## Phase 2: unified intake

All inputs end in the same versioning path (`IngestionService.process_extracted`): normalize → SHA-256 →
duplicate check → new `draft`/`pending_review` version → chunk → embed → review → atomic approval.

| Input | Source type | How | Notes |
|---|---|---|---|
| Official web page | `website` | Admin registers the exact URL; Fetch now / scheduled | allowlist + SSRF guard + robots.txt; `blocked` status when the site refuses access |
| SCH notice board | `sch_board` | Listing → individual notices (`notice01.php?admin_mode=read&no=…`) | one `source_document` per notice (`external_id = <table>:<no>`), title/date/author/attachments kept, `max_items` (default 5, cap 30), 1 s between requests |
| PDF / DOCX / TXT / MD | `pdf` `docx` `text_file` | Intake upload (admin or supporter) | private bucket, SHA-256 duplicate block, page markers, headings, tables; image-only PDFs → OCR if configured, else `needs_ocr` |
| Screenshot | `screenshot` | Upload → OCR preview → human correction → submit | supporter must confirm authorization; raw OCR kept as immutable `raw_text`; approval requires `fields_confirmed` |
| Pasted staff announcement | `kakao_message` / `manual_text` | Intake form | `original_text` kept unchanged as `raw_text`; normalized text redacted by default; form fields stored as confirmed structured data |

### Structured fields
`services/ingestion/structured.py` detects dates, ranges (`2026. 10. 27.(월) ~ 11. 6.(목)` → deadline 2026-11-06),
times, places, fees, contacts, eligibility, required documents, application method and identifiers (D-2, ARC …).
Each value keeps its evidence snippet and `confirmed: false`. Dates without a year keep `year: null` and raise a
warning: values are never guessed. Only confirmed values are shown publicly (`key_facts`).

### OCR on Render
Render's native Python runtime has no Tesseract binary, and the free instance's ~512 MB already holds E5,
so no OCR model is loaded in-process. Options: `OCR_PROVIDER=none` (supporters type the text; default),
`OCR_PROVIDER=ocr_space` with a free `OCR_SPACE_API_KEY` (images leave our servers — supporters confirm
authorization first), or `OCR_PROVIDER=tesseract` on a Docker/paid instance with `tesseract-ocr` + `kor` data.
Tesseract output for Korean often splits syllables ("국 제 교 육"); the suggestion shown to the supporter is
cleaned, while `raw_text` keeps the exact OCR output.

### Jobs and scheduling
`JOB_EXECUTION=worker`: jobs are rows first; an in-process worker claims them with `claim_ingestion_job`
(`FOR UPDATE SKIP LOCKED`). After a restart or a free-tier sleep, queued jobs are picked up again and jobs
whose heartbeat stopped are re-queued (max 3 attempts). Every step is written to `ingestion_events`.
Scheduled checks: `.github/workflows/scheduled-sync.yml` (free) calls `POST /api/v1/internal/sync/run-due`
with `X-Cron-Secret` daily at 05:00 KST; the API queues due `daily`/`weekly` sources. Alternatives: Supabase
Cron (`pg_cron` + `pg_net` POST to the same URL) or a Render Cron Job (`python -m app.cli run-due`, paid).
A failed or blocked fetch never removes the last approved version; stale guidance is flagged by
`is_stale` (category thresholds in `core/constants.py`, per-source `stale_after_days`).

### Review safety
* Approved versions are immutable (text, hash, structured data); corrections create a new version.
* `raw_text` and `original_file` are immutable once written.
* Approval re-checks embeddings (`ensure_indexed`) and only then flips `current_version_id` in one
  transaction; if embedding fails the old version stays live and `indexing_status = failed`.
* Review warnings surface changed deadlines/fees/places versus the live version and non-official
  immigration content; both versions are kept, nothing is merged silently.

---

## Automatic RAG synchronization (migration 0007)

```
source added / changed ─► extracted ─► pending_review (chunked, NOT embedded; never searchable)
        │                                     │ admin: "Approve and index"
        │                                     ▼
        │                         index_version job (ingestion_jobs, durable)
        │                                     │ worker claims (FOR UPDATE SKIP LOCKED)
        │                                     ▼
        │            chunk ─► embed in batches of 8 (heartbeat + progress events) ─► validate
        │                                     │ replace_version_chunks()  (one transaction)
        │                                     ▼
        │            activate_document_version(): count + model + 384-dim check AND switch in one
        │            transaction → previous version 'superseded' (kept) → searchable on the next query
        └── failure at any step: previous approved version stays active; transient errors retry with
            backoff (30 s, 60 s …, max_attempts 3), then 'failed' + admin notification; Retry re-queues.
```

* **Durability**: every step is a row (`ingestion_jobs`, `ingestion_events`, `document_versions.indexing_status`).
  Nothing depends on FastAPI BackgroundTasks in production (`JOB_EXECUTION=worker`). Restarts / free-tier sleeps:
  queued jobs are claimed again on wake; running jobs whose heartbeat stopped are re-queued by the claim RPC.
* **No duplicates**: a unique index allows one open `index_version` job per version; chunks are replaced
  atomically (`unique (version_id, chunk_index)`), so retries never duplicate or half-write chunks.
* **Validation**: the worker checks that every chunk has a finite 384-d vector, then the database re-checks the
  expected chunk count, model id and dimensions inside the activation transaction.
* **Withdrawal**: `POST /admin/documents/{id}/cancel` removes a document from search and the Knowledge Center
  immediately (the `searchable_chunks` view excludes canceled documents).
* **Audit**: `version.approval_requested` (who approved), `version.approve` + `version.activate` (when it became
  active, chunk count, model), job events (when embeddings were generated), `ingestion_jobs` (when sources were
  checked, failures). Submitter = `document_versions.created_by` (+ `version.submit`). What changed = review diff.
* **Notifications** (`admin_notifications`): `review_needed` (sync found changes), `sync_failed`, `source_blocked`,
  `indexing_failed`, `version_activated`, `withdrawn`; unread state per admin (`notification_reads`).

### Scheduler (no paid resources)
Inspected: Render free web services (sleep after ~15 min idle, no free cron), Supabase project (pg_cron and
pg_net are available on the free plan but would need the scheduler secret stored in the database), and
GitHub Actions (already used for deploys, free for public repositories). Chosen: **GitHub Actions**
`.github/workflows/scheduled-sync.yml`, daily 05:00 KST, `POST /api/v1/internal/sync/run-due` with
`X-Cron-Secret`. The request wakes the instance, queues due daily/weekly website and board checks, and kicks
the worker so pending indexing jobs and retries are processed too. Configure `CRON_SECRET` on the backend and
the same value as a GitHub Actions secret. Index jobs triggered by admins run immediately (the admin's own
requests keep the instance awake).

### Embedding reuse, searchability verification and health checks (2026-11-23)

- **Reuse across versions.** When a new version is indexed at approval, chunks whose exact embedding input
  (title + heading + text, hashed) already exists in another version of the same document, embedded by the
  current model, reuse that vector. Only changed chunks are embedded. Pending versions chunked for review still get
  no vectors. The job statistics record `reused_embeddings` and `reused_from_other_versions`. Stored vectors returned as
  text by PostgREST are parsed rather than dropped.
- **Post-activation verification.** After `activate_document_version`, the index job checks the version the way
  students see it: its chunks must appear in `searchable_chunks` and carry an embedding from the current model. The
  result goes into the job statistics (`searchable_chunks`, `searchability_ok`, `hidden_reason`) and a `verify`
  step event. Announcement approval runs the same check.
- **Alerts.** A published document that is not fully searchable creates an `error` admin notification
  `not_searchable`, at most one per document per 24 h. Documents hidden on purpose (scheduled `valid_from`, expired
  `valid_until`, inactive source, archived, withdrawn) are reported as `hidden_reason` and not alerted. The check
  never undoes an activation and never re-indexes.
- **On demand.** `GET /api/v1/admin/rag/health` (admin, read-only) returns every published document's chunk,
  embedding and searchable counts plus lightweight statistics, computed live. `python -m app.cli check-rag
  [--notify]` prints the same report; `run-due` runs it with `--notify` after the scheduled syncs.
- Research benchmarks, answer evaluations and corpus snapshots are never started by the lifecycle. They live in
  `research/` and run only when a researcher starts them explicitly.

## Korean PDF body text, re-extraction and older sources (2026-11-23)

**Defect.** `extractors_files._body_font_size` estimated the body font size from the first 20 pages. In the 2021
NIIED guidebook (`guideBook_ko.pdf`, 94 pages) pages 14-18 are dense 6.2 pt contact tables, so the estimate was 6.2 pt
while the body text is 9.4 pt (the modal size on 39 pages). Every body line was then >= 1.2x "body size" and tagged
as a `##` heading (82 % of the characters); the chunker treats headings as section labels and consecutive labels
replace each other, so only 27 % of the guidebook's words reached chunk text.

**Fix.** The body size is the character-weighted modal span size over all pages (about +0.7 s for the 94-page
guidebook). PDF text also drops C0 control characters: InDesign exports put an invisible `\x07` "indent to here" mark
after list markers. Validated on all six production PDFs (`research/scripts/validate_pdf_fix.py`, report in
`research/reports/production_readiness/`): the five other PDFs produce identical text apart from the removed `\x07`
marks; the guidebook's chunk text goes from 27 % to 97 % of its words, with every checked line verbatim from the
cited page.

**Re-extraction (no re-upload).** Re-uploading the same file is refused as a duplicate, and "Reprocess" only re-indexes
the stored text. To apply an extractor fix to an existing document:

* `POST /api/v1/admin/versions/{version_id}/re-extract` (admin only) is a **dry run** by default: it downloads the
  original, extracts it (PDFs in the isolated child process) and chunks it in memory, and returns stored vs new
  statistics (characters, chunks, word coverage of chunk text, pages with/without chunks, image-only pages, heading
  share) and warnings, writing nothing.
* `POST .../re-extract?apply=true` (202) queues the normal ingest job with that version's stored original file. A
  changed result becomes a new `pending_review` version; the approved version stays live until a reviewer approves
  the new one (normal activation, embeddings reused where unchanged). Identical output creates nothing. Nothing is
  ever activated automatically. Audited as `version.reextract_requested`.
* `python -m app.cli reextract <version_id>` prints the same dry-run report; `--apply` creates the pending version.

**Older sources.** A new version whose publication date (PDF metadata or page) or declared edition ("2021 개정판")
is older than `SOURCE_REVIEW_AGE_DAYS` (default 3 years) gets a reviewer warning to verify time-sensitive guidance
(fees, deadlines, visa, work and insurance rules, contacts) before approving. It is a warning only: nothing is
hidden, changed or published automatically. The assistant already passes each source's publication date to the
model (`published: 2021-03-05`).

## PDF ingestion robustness (2026-11-22)

**Incident.** Uploaded PDFs stayed in `Running` after `[file] Loaded … from private storage`; the service restarted
during one job and a second upload of the same PDF created a second job. Root cause (reproduced locally):
`extract_pdf()` called PyMuPDF `page.find_tables()` on every page. Its first call alone grows the process by
~230 MB (10 pages: 51 → 410 MB peak) and its CPU time grows steeply with the number of vector line segments
(8,000 segments/page ≈ 3 s/page, 20,000 ≈ 12 s/page on a fast core — HWP-exported Korean PDFs draw tables and
underlines this way). This ran inside the single 512 MB / ~0.1 CPU web process that also hosts the job worker and
the ONNX E5 model, so it was killed for memory (restart) or ran for hours, without heartbeats, events or an error.
The `sentence-transformers is not installed` warning is the expected fallback to ONNX E5 and was not involved.

**Fix.**
* Text extraction runs in a short-lived child process (`pdf_isolation.py` / `pdf_child.py`) with a hard timeout;
  the child marks itself as the first OOM-kill candidate. Timeout → `extraction_timeout`, killed child →
  `extraction_crashed`, corrupt / encrypted / scanned PDFs → `corrupt_file` / `encrypted_file` / `needs_ocr` — always
  a `Failed` job with an actionable message; the API and worker keep running. Child peak memory ≈ 56 MB.
* Table layout detection is off by default (`PDF_TABLE_DETECTION=auto` enables it with a per-page budget).
  Table text is still extracted as plain lines.
* Page analysis reports pages with text, scanned pages (image coverage), vector-drawn text pages, the Hangul share
  and pages needing OCR; OCR renders one page image at a time.
* Every stage (download, validate, extract, ocr, process) is timed; durations and outcomes are logged as logfmt
  (`ingest stage=extract status=done job=… duration_ms=… pages=… chars=… hangul_ratio=…`, never document text) and
  stored in `ingestion_jobs.statistics.stages`.
* A background ticker writes the heartbeat + current stage/progress every 15 s (stops after
  `JOB_MAX_RUNTIME_SECONDS`, so a hung job still goes stale). Stale threshold 180 s; right after a restart the
  first claim uses 90 s, so orphaned jobs are re-queued within ~1.5 min (or failed with `interrupted` after
  `max_attempts`). A resumed attempt records which stage the previous one died in. A late result of a taken-over
  attempt is discarded (writes are conditional on the attempt number).
* Duplicates: an upload of a file whose job is still queued/running, or a second job for a busy source, returns
  409 `already_processing` with the existing job id; partial unique indexes (migration 0012) enforce it in the
  database. Re-processing is idempotent: versions are unique per content hash, chunks are replaced atomically.
* Admin → Knowledge Sources shows the active job's stage, page progress, last signal and a stale warning; the job
  panel adds stage timings, the PDF diagnosis and the resume note. Extracted documents still require review and
  approval; nothing is indexed for students before approval.

| Variable | Default | Purpose |
|---|---|---|
| `PDF_EXTRACTION_ISOLATION` | `subprocess` | `inline` only for tests/debugging |
| `PDF_EXTRACT_TIMEOUT_SECONDS` | `300` | hard limit per PDF |
| `PDF_EXTRACT_MEMORY_MB` | `0` | optional address-space cap for the child (Linux) |
| `PDF_TABLE_DETECTION` | `off` | `auto` = PyMuPDF table detection on pages with ≤ `PDF_MAX_TABLE_ITEMS` drawing operations (needs ≥ 1 GB RAM) |
| `PDF_MAX_PAGES` | `300` | larger PDFs are rejected with a "split the file" message |
| `JOB_HEARTBEAT_SECONDS` / `JOB_STALE_SECONDS` / `JOB_STARTUP_STALE_SECONDS` / `JOB_MAX_RUNTIME_SECONDS` | `15` / `180` / `90` / `1800` | liveness and recovery |
