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
