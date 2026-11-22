# API Contract (frontend ⇄ backend)

Single source of truth for the HTTP interface between `apps/web` and `backend`.
Interactive docs are also served by FastAPI at `/docs` (OpenAPI at `/openapi.json`).

* Base URL: `NEXT_PUBLIC_API_BASE_URL` (default `http://localhost:8000`)
* Auth: `Authorization: Bearer <Supabase access token>` for `/api/v1/me` and `/api/v1/admin/*`. Public endpoints need no token.
* All JSON. Dates are ISO-8601 (`date` fields are `YYYY-MM-DD`, timestamps are UTC with offset).
* Language codes: `ko`, `en`, `id`, `vi`, `zh-CN`.

## Errors

Every non-2xx response:

```json
{ "error": { "code": "snake_case_code", "message": "Human readable", "details": null }, "request_id": "abc123" }
```

| HTTP | Typical `code` |
|------|----------------|
| 401 | `not_authenticated`, `invalid_token` |
| 403 | `forbidden` |
| 404 | `not_found` |
| 409 | `conflict`, `invalid_state` |
| 413 | `file_too_large`, `request_too_large` |
| 415 | `unsupported_file_type` |
| 422 | `validation_error` (details = list of `{field, message}`), `url_not_allowed` |
| 429 | `rate_limited` |
| 502 | `upstream_error` |
| 503 | `supabase_not_configured`, `embedding_unavailable` |

When Supabase is not configured on the backend, every data endpoint returns 503 `supabase_not_configured`
(the frontend must show setup instructions, never fake data). `/health` always works.

## Pagination

Query: `page` (1-based, default 1), `page_size` (default 20, max 100).
Response: `{ "items": [...], "total": 123, "page": 1, "page_size": 20 }`

## Enumerations

* `source_type`: `website | pdf | docx | manual_text | kakao_message`
* `authority_type`: `official_university | official_government | supporter_submitted | other`
* `scope`: `university | national`
* `sync_frequency`: `manual | daily | weekly`   (only `website` may be non-manual)
* source `status`: `registered | fetching | processing | pending_review | approved | failed | inactive`
* version `verification_status`: `draft | pending_review | approved | rejected | superseded`
* job `status`: `queued | running | succeeded | failed`
* job `outcome` (on success): `new_version | unchanged`
* announcement `publication_status`: `draft | pending_approval | published | rejected | canceled`
* computed announcement `status`: `active | upcoming | expired`
* translation_status: `machine_draft | in_review | human_approved | rejected`
* roles: `super_admin | admin | supporter | student`
* category slugs: `visa-immigration, part-time-employment, academic-life, scholarships, dormitory-housing, health-insurance, topik-korean, employment-internships, banking-taxes, daily-living, university-announcements`

## Public endpoints

### `GET /health`
`{ "status": "ok", "version": "0.1.0", "supabase": "configured|not_configured", "embedding_provider": "e5|hash", "embedding_model": "intfloat/multilingual-e5-small" }`

### `GET /api/v1/categories`
`{ "items": [{ "slug", "name", "description", "sort_order", "document_count": int|null, "announcement_count": int|null }] }`
Counts are `null` when Supabase is not configured (list itself is static constants).

### `GET /api/v1/announcements`
Query: `q`, `category`, `language`, `status` (`active|upcoming|expired`), `page`, `page_size`. Only approved + published.
Item (`AnnouncementSummary`):
```
{ id, title, category, target_audience, event_date, deadline, published_at, status,
  original_language, available_languages: ["ko", ...], excerpt, is_test_data: bool,
  source: { title, organization, url, authority_type, scope } }
```

### `GET /api/v1/announcements/{id}`
`AnnouncementSummary` +
```
{ body, source_published_at, verified_at, version_id,
  translations: [{ language, title, body, translation_status: "human_approved", reviewed_at }] }
```
Only human-approved translations are ever returned publicly. `body` is the original-language text.

### `GET /api/v1/assistant/status`
`{ "answer_generation": "disabled|enabled", "retrieval": "available|unavailable", "reason": string|null }`

### `POST /api/v1/knowledge/search`
Body: `{ query: string(1..500), language?: lang, category?: slug, top_k?: int(1..20, default 5), mode?: "hybrid"|"vector"|"keyword" }`
```
{ query,
  results: [{ chunk_id, document_id, version_id, document_title, passage, heading, page: int|null,
              similarity: number|null, keyword_rank: number|null, score: number,
              source_url, organization, authority_type, scope, category,
              source_published_at, verified_at, language }],
  retrieval: { mode: "hybrid|vector|keyword", embedding_model, total, warning: string|null } }
```
Empty `results` when there is no approved evidence. Never fabricated.

### `GET /api/v1/knowledge/documents`
Query: `q`, `category`, `scope`, `page`, `page_size`. Approved current versions only.
Item: `{ id, title, category, organization, scope, authority_type, language, source_url, source_published_at, verified_at, excerpt }`

### `GET /api/v1/knowledge/documents/{id}`
Item + `{ content, version_id, version_number }`

## Authenticated

### `GET /api/v1/me`
`{ id, email, display_name, role, preferred_language, languages: ["id"], is_staff: bool }` — `is_staff` true for super_admin/admin/supporter.

## Admin endpoints (`/api/v1/admin/*`)

Roles: `admin` and `super_admin` unless noted. `supporter` may use announcement create/submit/edit-own and translations for their assigned languages. `Users` role change: `super_admin` only.

### Overview / settings / audit
* `GET /admin/overview` → `{ sources_total, sources_failed, versions_pending, announcements_pending, documents_approved, recent_jobs: [Job], recent_audit: [AuditEntry] }`
* `GET /admin/settings` → `{ supabase_configured, embedding_provider, embedding_model, embedding_dimensions, allowed_domains: [str], max_upload_mb, max_response_mb, llm_provider: "none", answer_generation: "disabled", rate_limits: {...} }`
* `GET /admin/audit-log` (paginated) → `AuditEntry { id, action, entity_type, entity_id, actor_id, actor_name, details, created_at }`

### Sources
`Source`:
```
{ id, title, original_url, organization, source_type, authority_type, scope, category, language,
  sync_frequency, is_active, status, created_by, created_by_name, created_at, updated_at, last_checked_at,
  last_ingestion_result: { job_id, status, outcome, message, completed_at } | null,
  is_test_data, document_count }
```
* `GET /admin/sources` (paginated; filters `status`, `source_type`, `q`)
* `POST /admin/sources` body `{ title, original_url?, organization, source_type, authority_type, scope, category, language, sync_frequency?, is_active? }` → 201 `Source`. Website URL must be http(s) and on the domain allowlist else 422 `url_not_allowed`.
* `GET /admin/sources/{id}` → `Source` + `documents: [{ id, title, canonical_url, current_version_id, latest_version: { id, version_number, verification_status, created_at } | null }]`
* `PATCH /admin/sources/{id}` body any of `{ title, organization, category, sync_frequency }`
* `POST /admin/sources/{id}/disable` / `POST /admin/sources/{id}/enable` → `Source`
* `POST /admin/sources/{id}/ingest` → **202** `{ job_id, status: "queued" }` (website sources; others → 409 `invalid_state` with instruction to upload/submit instead)
* `POST /admin/sources/{id}/upload` multipart field `file` (pdf/docx sources) → **202** `{ job_id, status }`
* `POST /admin/sources/{id}/submit-text` body `{ title, text(10..200000), source_published_at?, external_id?, authorized_by_supporter?: bool }` (manual_text / kakao_message; kakao requires `authorized_by_supporter: true`) → 201 `Job`
* `GET /admin/ingestion-jobs` (paginated; filters `source_id`, `status`), `GET /admin/ingestion-jobs/{id}`, `POST /admin/ingestion-jobs/{id}/retry` → 202 `{job_id,status}`

`Job`:
```
{ id, source_id, source_title, status, trigger: "manual|schedule|retry", outcome: "new_version|unchanged"|null,
  document_id, version_id, error_code, error_message,
  statistics: { fetched_bytes, content_chars, chunk_count, embedded_chunks, redactions, duration_ms, ... },
  created_at, started_at, completed_at }
```

### Documents & versions
* `GET /admin/documents` (paginated; filters `source_id`, `has_pending=true`, `q`)
  Item: `{ id, source_id, source_title, title, canonical_url, language, document_type, organization, category, current_version_id, pending_version_id, latest_version_number, is_canceled, created_at }`
* `GET /admin/documents/{id}` → `{ ...DocumentItem, source: Source, current_version: Version|null, pending_version: Version|null, versions: [VersionSummary], diff: Diff|null }`
  `Diff` (pending vs current approved, null if either missing): `{ added_count, removed_count, added_lines: [str], removed_lines: [str], unified: str }`
* `GET /admin/versions/{id}` → `Version`; `GET /admin/versions/{id}/chunks` → `{ items: [{ chunk_index, heading, content, page, has_embedding, embedding_model }] }`
* `POST /admin/versions/{id}/approve` body `{ note? }` → `Version` (atomic; previous current → `superseded`)
* `POST /admin/versions/{id}/reject` body `{ reason }` → `Version`
* `POST /admin/versions/{id}/reprocess` → `Version` (re-chunk + re-embed, reusing unchanged embeddings)
* `POST /admin/documents/{id}/rollback` body `{ version_id, note? }` → `DocumentDetail` (version must have been approved before)
* `POST /admin/documents/{id}/cancel` body `{ reason }` → document no longer searchable

`Version`:
```
{ id, document_id, version_number, extracted_text, content_hash, content_length, source_published_at, fetched_at,
  valid_from, valid_until, verification_status, approved_by, approved_at, rejected_reason, created_at,
  chunk_count, embedded_chunk_count, embedding_model, is_current }
```
`VersionSummary` = `Version` without `extracted_text`.

### Announcements
`AdminAnnouncement`:
```
{ id, document_id, version_id, title, category, target_audience, event_date, deadline, valid_from,
  publication_status, original_language, body, source_type, evidence_note, evidence_url,
  created_by, created_by_name, created_at, submitted_at, approved_by, approved_at, rejection_reason,
  is_test_data, translations: [Translation] }
```
`Translation`: `{ id, announcement_id, language_code, title, body, translation_status, reviewed_by, reviewed_by_name, reviewed_at, is_machine_translated: bool }`

* `GET /admin/announcements` (paginated; filter `status`, `q`; supporters see only their own)
* `POST /admin/announcements` body `{ title, body, category, target_audience?, event_date?, deadline?, valid_from?, source_type: "manual_text"|"kakao_message", source_published_at?, evidence_note?, evidence_url?, original_language?: "ko", submit?: false, authorized_by_supporter?: bool }` → 201 `AdminAnnouncement`
* `GET /admin/announcements/{id}`, `PATCH /admin/announcements/{id}` (draft/rejected only)
* `POST /admin/announcements/{id}/submit` → `AdminAnnouncement` (pending_approval)
* `POST /admin/announcements/{id}/approve` body `{ note? }` (admin only) → published
* `POST /admin/announcements/{id}/reject` body `{ reason }` (admin only)
* `POST /admin/announcements/{id}/cancel` body `{ reason }` (admin only)
* `GET /admin/announcements/{id}/history` → `{ items: [AuditEntry] }`
* `PUT /admin/announcements/{id}/translations/{language}` body `{ title, body, translation_status: "machine_draft"|"in_review" }`
* `POST /admin/announcements/{id}/translations/{language}/approve` → `Translation` (admin, or supporter assigned that language)
* `GET /admin/translations` (paginated; filters `status`, `language`) → items `Translation + { announcement_title }`

### Users
* `GET /admin/users` (paginated) → `{ id, email, display_name, role, preferred_language, languages, created_at }`
* `PATCH /admin/users/{id}/role` body `{ role }` (super_admin only)
* `PUT /admin/users/{id}/languages` body `{ languages: [lang] }`
