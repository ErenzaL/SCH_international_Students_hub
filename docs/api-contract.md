# API Contract (frontend ⇄ backend)

Single source of truth for the HTTP interface between `apps/web` and `backend`.
Interactive docs are also served by FastAPI at `/docs` (OpenAPI at `/openapi.json`).

* Base URL: `NEXT_PUBLIC_API_URL` (dev default `http://localhost:8000`; required in production builds)
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

---

## Phase 2 additions (knowledge intake, review workflow, monitoring)

New enum values: `source_type` adds `sch_board | text_file | screenshot`; `authority_type` adds `staff_communication`;
source `status` adds `blocked` (site refuses automated access; never bypassed); job `outcome` adds `partial | extracted`;
job `job_type`: `ingest | board_sync | ocr_intake`; version `indexing_status`: `not_indexed | indexing | indexed | failed`.
`sync_frequency` daily/weekly is allowed for `website` and `sch_board`.

### Source additions
`Source` gains `config` (`{max_items, max_pages}` for boards), `stale_after_days`, `last_success_at`, `last_change_at`.
* `GET /admin/sources` adds filters `category`, `active`, `sort` (`title|organization|created_at|updated_at|last_checked_at|last_success_at|status|category|source_type`), `order` (`asc|desc`). Supporters may call it and only see sources they created.
* `POST /admin/sources` accepts `source_type: "sch_board"` (URL must be an SCH `notice01.php` list page), `config`, `stale_after_days`.
* `PATCH /admin/sources/{id}` also accepts `language`, `scope`, `authority_type`, `config`, `stale_after_days`.
* `POST /admin/sources/validate-url` body `{url, source_type?: "website"|"sch_board", language?}` → `{ok, url, checks: [{name: "allowlist"|"network"|"robots"|"board"|"duplicate", ok, message}]}`. Nothing stored.
* `POST /admin/sources/preview` same body → website: `{kind:"page", final_url, title, text (≤20k chars), truncated, content_chars, content_hash, source_published_at, links, warnings, extractor, estimated_chunks, structured}`; board: `{kind:"board", notices:[{notice_no,title,url,posted,author,pinned}], notice_count, sample_notice:{title,text,posted_at,attachments,warnings}|null}`. Nothing stored. Blocked sites → 409 with `details.blocked = true`.
* `POST /admin/sources/{id}/ingest` now also for `sch_board` (409 if a job is already queued/running).
* `POST /admin/sources/{id}/upload` accepts pdf / docx / text_file sources (staff; supporters only their own). Duplicate file (same SHA-256) → 409 `conflict` with `details {document_id, version_id, version_number, verification_status}`.
* `GET /admin/sources/{id}/history` → `{jobs: [Job], audit: [{id, action, actor_id, details, created_at}]}`.

`Job` gains `job_type`, `attempts`, `max_attempts`, `file: {filename, mime_type, size}|null`, `heartbeat_at`.
Board jobs put per-notice results in `statistics`: `items_found, items_new, items_unchanged, items_failed, failures[], notices[{notice_no,title,outcome,document_id,version_id}]`.
* `GET /admin/ingestion-jobs?job_type=` filter; `GET /admin/ingestion-jobs/{id}/events` → `{items: [{id, level: info|warning|error, step, message, data, created_at}]}` (the step-by-step ingestion log).

### Intake (admins and supporters; `/api/v1/admin/intake`)
* `GET /ocr-status` → `{provider: none|tesseract|ocr_space, available, reason, languages, external_processing}`.
* `POST /document` multipart: `file`, and either `metadata` (JSON string `SourceMeta` = `{title, organization, category, scope, authority_type, language, original_url?}`) to create a source, or `source_id` → 202 `{source, job_id, status}`. Extensions: .pdf .docx .txt .md (≤ `max_upload_mb`).
* `POST /screenshot` multipart: `file` (png/jpg/jpeg/webp ≤ 8 MB), `metadata` or `source_id`, `authorized_for_distribution=true` (required) → 201 `{source, job, ocr: {provider, available, text, mean_confidence, uncertain_lines:[{text,confidence}], warnings, model, extracted_at}, detected: Structured|null, image}`. No version yet.
* `GET /screenshot/{job_id}` (same shape), `GET /screenshot/{job_id}/image` (the stored image, streamed; send the bearer token), `POST /screenshot/{job_id}/retry-ocr`.
* `POST /screenshot/{job_id}/submit` body `{title, text (corrected), submit: bool, redact_personal_info: bool, source_published_at?, fields: {deadline?, event_date?, time?, location?, fee?, contact?, eligibility?, required_documents?, application_method?, target_audience?, notes?}}` → `Job` (creates a **draft** unless `submit`; raw OCR kept as `raw_text`; approval needs `fields_confirmed`).
* `POST /announcement` body `{original_text, normalized_text?, title, organization, category, language, scope, authority_type (staff_communication default), received_via: kakaotalk|email|other, target_audience?, event_date?, deadline?, location?, application_method?, notes?, original_url?, source_published_at?, source_id?, redact_personal_info (default true), authorized_by_supporter: true (required), submit: bool}` → `Job`. `original_text` is stored unchanged as evidence.
* `GET /mine` (paginated) → versions created by the caller `{id, document_id, document_title, version_number, verification_status, review_note, ...}`.

### Versions & review additions
`Version` gains `raw_text`, `has_raw_text`, `structured_data` (`{fields: {name: {value, evidence, confirmed, source}}, dates, links, identifiers, warnings, fields_confirmed}`), `extraction_meta`, `warnings`, `requires_field_confirmation`, `original_file {filename, mime_type, size, sha256}|null`, `created_by`, `edited_by`, `edited_at`, `review_note`, `submitted_at`, `indexing_status`, `indexed_at`, `indexing_error`.
`DocumentDetail` gains `metadata` (board notices: `notice_no, author, attachments`), `review_warnings: [{code, message}]`; document items gain `source_type`, `authority_type`, `pending_status`.
* `GET /admin/documents?review_status=pending_review|draft|open`.
* `GET /admin/documents/{id}/history` → `{items: [AuditEntry]}`.
* `PATCH /admin/versions/{id}` body any of `{extracted_text, title, fields: {name: value|null}, fields_confirmed, valid_from, valid_until, source_published_at}` (draft/pending only; supporters: own drafts; confirming fields = admin) → `Version`. Text changes re-chunk and re-embed.
* `POST /admin/versions/{id}/submit` (draft → pending_review), `POST /admin/versions/{id}/request-changes` body `{note}` (admin; pending → draft).
* `GET /admin/versions/{id}/original` → original file bytes (inline for images/PDF/text).
* Approve errors: 409 `fields_not_confirmed` (OCR content), 409 `invalid_state` "not_indexed", 503 `embedding_unavailable`.

### Knowledge overview, allowlist, scheduler
* `GET /admin/knowledge/stats` → `{sources_total, sources_active, sources_failed, versions_pending, versions_draft, documents_approved, jobs_failed, jobs_queued, searchable_chunks, latest_success_at, ocr_provider, ocr_available, ocr_reason, job_execution, embedding_model}`.
* `GET /admin/allowed-domains` → `{items: [{domain, origin: environment|admin, note, added_by, created_at, removable}]}`; `POST` `{domain, note?}` and `DELETE /admin/allowed-domains/{domain}` (super_admin).
* `POST /api/v1/internal/sync/run-due` header `X-Cron-Secret` (404 unless `CRON_SECRET` is set) → `{queued, skipped, job_ids}`.

### Public additions
* `POST /knowledge/search` body adds `scope?`, `authority?: [authority_type]`; each result adds `source_id, source_type, valid_until, exact_match, is_stale, verification_age_days, stale_after_days`; `retrieval.exact_terms`. `source_url` is the document's own URL (e.g. the individual notice) when it has one.
* `GET /knowledge/documents?authority=` filter; items add `source_type, valid_until, is_stale, verification_age_days, stale_after_days`. Detail adds `key_facts` (confirmed fields only), `attachments`, `notice_no`.

---

## RAG synchronization (migration 0007)

Lifecycle: source changed → extracted → `pending_review` (chunked, **not embedded**) → **Approve** → durable
`index_version` job (`queued` → `running`) → chunk → embed (batches) → validate → atomic activation
(`approved`, previous version `superseded`) → searchable on the next query. If indexing fails, the previously
approved version stays active.

* `POST /admin/versions/{id}/approve` now returns **202** with the `Version` plus `indexing_job_id`, `indexing_job_status`
  (`queued|running|succeeded|failed`). Production returns immediately (`queued`); poll `GET /admin/versions/{id}` or
  `GET /admin/ingestion-jobs/{job_id}`. Idempotent: approving again while queued returns the same job.
* `Version` gains `activation_requested_by`, `activation_requested_at`; `indexing_status` adds `queued`.
  UI states: `pending_review` + no `activation_requested_at` = "Pending review"; `pending_review` + requested +
  `indexing_status` `queued|indexing` = "Approved – indexing"; `failed` = "Indexing failed (previous version still live)";
  `approved` + `is_current` = "Active".
* Job `job_type` adds `index_version` (payload `{version_id, note}`), `outcome` adds `activated`. Transient failures
  (network, timeouts, HTTP 5xx, embedding unavailable) are re-queued automatically with backoff (`run_after`) up to
  `max_attempts`; then `failed`. `POST /admin/ingestion-jobs/{id}/retry` on a failed `index_version` job queues it again.
* `POST /admin/documents/{id}/cancel` = **Withdraw**: removed from search and the Knowledge Center immediately.
* `GET /admin/rag/status` →
  `{counts: {sources_registered, sources_active, sources_failed_or_blocked, pending_review, waiting_for_indexing, indexing_now,
  indexing_failed, active_versions, searchable_chunks, chunks_with_current_model, failed_jobs}, last_sync_at,
  embedding: {model, dimensions, provider, loaded}, job_execution,
  queue: [{job_id, status, attempts, max_attempts, error_code, error_message, run_after, created_at, started_at, completed_at,
  version_id, version_number, version_status, indexing_status, document_id, document_title, statistics}],
  recent_activations: [{at, document_id, document_title, version_number, chunks}],
  sources: [{id, title, source_type, status, sync_frequency, last_checked_at, last_success_at, last_change_at, is_active}]}`
* `GET /admin/notifications?limit=50` → `{items: [{id, kind, severity, title, message, entity_type, entity_id, link,
  created_at, unread}], unread, last_read_at}`; kinds: `review_needed, sync_failed, source_blocked, indexing_failed,
  version_activated, withdrawn`. `POST /admin/notifications/read` (204) marks all as read for the caller.

---

## Student support, AI history, translation review (migration 0008)

### Account
* Signup: `supabase.auth.signUp({email, password, options: {data: {preferred_language, display_name?}}})`. The DB trigger
  stores the language only if it is one of the 5 codes (else `en`, `preferred_language_confirmed=false`); role is always `student`.
* `GET /me` adds `preferred_language_confirmed`. `PATCH /me` `{preferred_language?, display_name?}` → profile. Changing the
  language affects UI default, assistant default and routing of NEW tickets only.
* `GET /me/notifications?unread_only&limit&before_id` → `{items: [{id, kind, title, body, entity_type, entity_id, link, read_at, created_at}], unread}`;
  `POST /me/notifications/read` `{ids?}` → `{marked}`. Realtime: subscribe to `postgres_changes` INSERT on `public.user_notifications`
  filter `user_id=eq.<uid>` (RLS limits rows to the owner). Kinds: `ticket_created, ticket_waiting, ticket_queued, ticket_assigned,
  ticket_accepted, supporter_reply, student_reply, ticket_escalated, ticket_unassigned, ticket_resolved, ticket_reopened,
  ticket_reassigned, context_withdrawn, translation_task, translation_review, translation_approved, translation_rejected,
  translation_changes_requested, translation_outdated`. Titles never contain private message bodies.

### AI conversations (own only; 404 for anyone else)
* `GET /conversations?q&page` → `{items: [{id, title, language, is_private, message_count, last_message_at, last_message_preview, created_at, updated_at}]}`
* `POST /conversations` `{language?, title?}` → conversation (default language = preferred).
* `GET /conversations/{id}` → conversation + `messages: [{id, role: user|assistant, content, language, citations: [{n, document_id, version_id, chunk_id, document_title, heading, source_url, organization, authority_type, verified_at, is_stale, page, similarity}], metadata: {offer_handoff, handoff_reasons: [no_evidence|asked_for_human|individual_decision|disputed_answer], evidence, retrieval_mode, answer_generation: "disabled", warning}, created_at}]`
* `PATCH /conversations/{id}` `{title?, is_private?, language?}`; `DELETE /conversations/{id}` (hard delete).
* `POST /conversations/{id}/messages` `{content, language?}` → `{user_message, assistant_message, conversation}`. The assistant
  replies with approved passages + citations (no LLM yet) in the given/conversation language framing; `language` does not
  change the profile. Private conversations (`is_private`) cannot be attached to tickets.

### Student tickets (`/support/tickets`)
* `POST` `{language?, subject, summary, conversation_id?, message_ids: [], additional_message?, consent: true}` → Ticket (201).
  Only the selected messages are copied into `shared_context`. Status after routing: `assigned` or `waiting` (+ `status_message`).
* Ticket (student view): `{id, ticket_number, language, subject, summary, priority, status: waiting|assigned|open|waiting_for_student|resolved,
  status_message, assigned_supporter: {display_name}|null, team, shared_context: [{role, content, created_at, citations}], consent_at,
  context_withdrawn_at, escalated, created_at, updated_at, last_message_at, resolved_at, satisfaction, satisfaction_comment,
  messages?: [{id, author_role: student|supporter|admin|system, kind: message|info_request|status|system, body, author_name, created_at}]}`.
* `GET /support/tickets` (mine, paginated), `GET /support/tickets/{id}`, `POST /{id}/messages` `{body}`, `POST /{id}/resolve`,
  `POST /{id}/reopen`, `POST /{id}/feedback` `{rating 1-5, comment?}` (resolved only), `POST /{id}/withdraw-context`.

### Supporter inbox (staff)
* `GET /support/inbox?view=queue|mine|assigned|open|waiting|resolved|team&language?&page` → `{items: [{id, ticket_number, language, subject,
  priority, status, created_at, last_message_at, escalated, assigned_to, assigned_to_name, is_mine, can_open}], total, counts: {queue,
  assigned, open, waiting_for_student, resolved}, languages: [..support], lead_languages: [..]}`. `queue` = waiting tickets of my
  languages (metadata only, `can_open=false`). `team` = team leads only.
* `GET /support/tickets/{id}` for staff (assignee / team lead / super admin; audited) adds `assigned_to, assigned_at, accepted_at,
  escalation_reason, student_display_name, student_preferred_language, is_mine, can_manage`. Otherwise 404.
* `POST /support/tickets/{id}/accept` (assigned → open; or claim a waiting ticket of my language; 409 if taken first),
  `/messages` `{body}` (reply), `/request-info` `{body}`, `/waiting`, `/resolve`, `/reopen`, `/escalate` `{reason}`,
  `/transfer` `{to_supporter_id|null, reason?}`, `/priority` `{priority}`, `GET /transfer-targets` → `{items: [{id, display_name, is_available}]}`.
* `PUT /support/me/availability` `{is_available, max_active_tickets?}`.

### Language teams
* `GET /admin/language-teams` (super admin: all; team leads: their languages) → `{items: [{language, members: [{user_id, display_name,
  email, role, can_support, can_review_translations, is_team_lead, is_available}], waiting, active}], can_manage_members}`.
* `PUT /admin/users/{id}/team` (super admin) `{assignments: [{language, can_support, can_review_translations, is_team_lead}], is_available?, max_active_tickets?}`.
  `PUT /admin/users/{id}/languages` is now super-admin only.

### Translation review
* `GET /admin/translations?status&language&outdated&page` → tasks in my languages: `{items: [{...Translation, is_outdated, published,
  review_note, last_edited_by_name, last_edited_at, submitted_at, original_verified_at, announcement_title, announcement_status,
  original_language, can_edit, can_review}]}`. Statuses: `todo, machine_draft (draft), in_review, changes_requested, human_approved, rejected`.
* `GET /admin/announcements/{id}/translations/{lang}` → `{original: {title, body, language, publication_status, content_hash, deadline,
  event_date, ...}, translation: Translation|null, revisions: [{id, action, translation_status, title, body, note, actor_name, created_at}],
  permissions: {can_edit, can_review}, language}`.
* `PUT .../translations/{lang}` `{title, body, translation_status: machine_draft (save draft) | in_review (submit)}`.
* `POST .../approve` `{original_verified: true, note?}` (reviewer; original must be published; not outdated → else 409
  `translation_outdated`), `POST .../reject` `{reason}`, `POST .../request-changes` `{reason}`,
  `GET .../share-text` → `{text}` for KakaoTalk copy (approved + current only).

---

## Document lifecycle (migration 0009)

States: `published` (current approved version) · `unpublished` (never approved) · `archived` (reversible, history kept) ·
`withdrawn` (reversible). Archived and withdrawn documents are excluded from search, the assistant, the Knowledge
Center and automatic syncs (new fetches are skipped until restored).

* `GET /admin/documents?lifecycle=active|archived|withdrawn`; items/detail add `lifecycle, archived_at, archive_reason, canceled_at, canceled_reason`.
* `POST /admin/documents/{id}/archive` `{reason}` · `POST /admin/documents/{id}/cancel` `{reason}` (withdraw) ·
  `POST /admin/documents/{id}/restore` `{note?}` (not for announcement documents) — admin.
* `GET /admin/documents/{id}/deletion-check` → `{eligible, blockers: [..], title, versions, approved_versions, chunks,
  storage_files, is_published, is_archived, is_withdrawn, suppress_reimport, recommended_action}`.
* `POST /admin/documents/{id}/delete` `{reason (≥5), confirm_title (= title)}` — **super_admin** → `{deleted, title, versions, chunks,
  files_removed, files_failed, reimport_blocked}`; 409 when blocked (published → withdraw/archive first; backs an
  announcement; a job is queued/running), 422 wrong title / short reason, 403 others.
  Effects: versions + chunks/embeddings removed; ingestion jobs kept with `document_id/version_id = null`; private Storage
  originals removed after commit; an audit tombstone (`document.delete`: title, URL/notice id, version numbers,
  content hashes, approvers) is kept forever; website/board documents are added to the re-import block list.
* `GET /admin/sources/{id}/suppressions` → `{items}` · `DELETE /admin/sources/{id}/suppressions/{suppression_id}` (allow re-import).
* Database safeguards: `source_documents` and previously approved `document_versions` cannot be deleted except through
  `delete_document()` (triggers refuse direct deletes, cascades from sources, and the service role).
