-- =============================================================================
-- ROLLBACK of migration 0013 (automatic translation). NOT a migration: the Supabase CLI never runs this folder.
-- Run it by hand ONLY after the application is back on a release without automatic translation (commit
-- 671824c or earlier), e.g.  psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f supabase/rollback/20261123000013_automatic_translation_down.sql
-- Then remove the row for version 20261123000013 from supabase_migrations.schema_migrations (last statement).
--
-- Data: no original, version, chunk or human translation is touched.
--   * machine translations that FAILED the automated checks ('needs_review') become 'rejected' (never public in
--     any release) with a note; clean machine drafts stay 'machine_draft' (unreviewed, as before 0013);
--   * announcement translation jobs (job type introduced by 0013) are deleted with their event log; the audit_log
--     keeps the record of what was generated;
--   * the added columns are kept by default (older code ignores them); the optional block at the end drops them.
-- =============================================================================
begin;

update public.document_translations
   set translation_status = 'rejected',
       review_note = trim(coalesce(review_note, '') || ' [rollback of 0013: failed the automated translation checks]')
 where translation_status = 'needs_review';
update public.announcement_translations
   set translation_status = 'rejected',
       review_note = trim(coalesce(review_note, '') || ' [rollback of 0013: failed the automated translation checks]')
 where translation_status = 'needs_review';

delete from public.ingestion_jobs where job_type = 'translate_announcement';     -- events cascade

drop index if exists public.ingestion_jobs_translation_open_uidx;

alter table public.ingestion_jobs drop constraint if exists ingestion_jobs_job_type_check;
alter table public.ingestion_jobs add constraint ingestion_jobs_job_type_check
  check (job_type in ('ingest', 'board_sync', 'ocr_intake', 'index_version', 'translate_document'));

alter table public.document_translations drop constraint if exists document_translations_translation_status_check;
alter table public.document_translations add constraint document_translations_translation_status_check
  check (translation_status in ('todo', 'machine_draft', 'draft', 'in_review', 'changes_requested', 'human_approved',
                                'rejected'));
alter table public.announcement_translations drop constraint if exists announcement_translations_translation_status_check;
alter table public.announcement_translations add constraint announcement_translations_translation_status_check
  check (translation_status in ('todo', 'machine_draft', 'in_review', 'changes_requested', 'human_approved', 'rejected'));

-- optional: drop the added columns as well (uncomment; loses the scope / provenance / warnings of machine rows)
-- alter table public.document_translations drop column if exists scope;
-- alter table public.announcement_translations drop column if exists provider, drop column if exists model,
--   drop column if exists generated_at, drop column if exists warnings;

delete from supabase_migrations.schema_migrations where version = '20261123000013';
commit;
