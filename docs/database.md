# Database

Migrations (`supabase/migrations`, applied in order):

| File | Content |
|---|---|
| `…0001_core_profiles.sql` | extensions (`vector`, `pg_trgm`), `categories`, `profiles`, `supporter_languages`, role helpers, signup trigger (always `student`), role-escalation guard |
| `…0002_knowledge.sql` | `knowledge_sources`, `source_documents`, `document_versions`, `document_chunks` (vector(384)), `ingestion_jobs`, `audit_log` + integrity triggers |
| `…0003_announcements.sql` | `announcements`, `announcement_translations` |
| `…0004_functions.sql` | `approve/reject/rollback/cancel_document*`, announcement workflow functions, `searchable_chunks` view, `search_knowledge` RPC |
| `…0005_rls_and_grants.sql` | RLS on every table, narrow grants, private storage bucket |

## Model

`knowledge_sources 1─* source_documents 1─* document_versions 1─* document_chunks`; `announcements 1─1 source_documents`;
`announcements 1─* announcement_translations`. Required tables from the spec exist with their columns; extras added:
`categories`, `audit_log`, source `status/scope/is_test_data/last_ingestion_result/updated_at`, version `was_approved/rejected_*/created_by`,
chunk `content_hash/token_count/page_*/chunk_strategy`, job `trigger/outcome/payload/requested_by`, announcement workflow columns.

## Lifecycle rules (enforced in SQL)

* Versions: `draft → pending_review → approved → superseded` (or `rejected`). One open (draft/pending) version per document.
* `(source_id, canonical_url)` and `(source_id, external_id)` are unique → no duplicate documents; `(document_id, content_hash)` unique → no duplicate versions; website `original_url` unique.
* Approved/superseded/rejected text and hash are immutable (trigger). The last approved version is never overwritten: approving a new version marks the old one `superseded` and moves `current_version_id`.
* `current_version_id` must reference an approved version of the same document (trigger).
* Approval requires chunks that all have embeddings (`not_indexed` otherwise) and an admin actor; it is one transaction that also writes `audit_log`.
* Rollback only to versions with `was_approved = true`. Cancel removes a document (and its announcement) from search.
* Source timestamps (`source_published_at`) are separate from ingestion timestamps (`fetched_at`, `created_at`).
* Searchable = approved ∧ current ∧ not canceled ∧ source active ∧ `valid_from ≤ now < valid_until` (announcement deadlines set `valid_until`, so expired notices stop being evidence but stay listed).
* `audit_log` is append-only.

## Search

`search_knowledge(query_embedding, query_tokens[], model, category, count, mode)`: vector leg (cosine, only chunks embedded
with the same model id), keyword leg (`simple` full-text OR-match + `ILIKE`, so Korean particles/CJK work), fused with
RRF (k = 60). `security invoker`, executable only by `service_role`; it reads the `searchable_chunks` view. The query
`language` is accepted but does not filter (cross-lingual retrieval over one corpus).

## Security

RLS on all tables; `anon` can read only categories, published announcements, active non-private source metadata and
approved/current document rows; chunks/embeddings, jobs, audit and profiles are not readable by anon. Roles: see
`docs/architecture.md`. Bootstrap the first super_admin with SQL (docs/setup.md).

## Verified how

`supabase/tests/behavior_test.sql` (approval, immutability, rollback, expiry, announcements, RLS for anon/student/admin) and the
backend integration test run against local PostgreSQL 18 + pgvector. See docs/setup.md. Hosted Supabase was not available.
