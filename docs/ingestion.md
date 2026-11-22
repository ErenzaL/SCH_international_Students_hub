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
