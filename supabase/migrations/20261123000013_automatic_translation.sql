-- =============================================================================
-- 0013  Automatic Korean <-> English machine translation (announcements + Knowledge Center documents).
-- ADDITIVE. Originals are never modified. Reuses the existing translation tables, review workflow and the durable
-- ingestion_jobs queue; adds only what automatic translation needs:
--   * status 'needs_review': a machine translation that failed the automated checks (never shown to students);
--   * document_translations.scope: 'full' or 'summary' (long documents: title + AI summary only, labelled);
--   * machine provenance on announcement translations (provider / model / generated_at / automated warnings);
--   * job type 'translate_announcement'.
-- Public RLS policies are unchanged (they still expose only human_approved rows); students see labelled machine
-- translations only through the API, and only when PUBLIC_MACHINE_TRANSLATIONS is enabled.
-- =============================================================================

alter table public.document_translations drop constraint if exists document_translations_translation_status_check;
alter table public.document_translations add constraint document_translations_translation_status_check
  check (translation_status in ('todo', 'machine_draft', 'needs_review', 'draft', 'in_review', 'changes_requested',
                                'human_approved', 'rejected'));
alter table public.document_translations
  add column if not exists scope text not null default 'full' check (scope in ('full', 'summary'));

alter table public.announcement_translations drop constraint if exists announcement_translations_translation_status_check;
alter table public.announcement_translations add constraint announcement_translations_translation_status_check
  check (translation_status in ('todo', 'machine_draft', 'needs_review', 'in_review', 'changes_requested',
                                'human_approved', 'rejected'));
alter table public.announcement_translations
  add column if not exists provider     text,
  add column if not exists model        text,
  add column if not exists generated_at timestamptz,
  add column if not exists warnings     jsonb not null default '[]'::jsonb;

alter table public.ingestion_jobs drop constraint if exists ingestion_jobs_job_type_check;
alter table public.ingestion_jobs add constraint ingestion_jobs_job_type_check
  check (job_type in ('ingest', 'board_sync', 'ocr_intake', 'index_version', 'translate_document',
                      'translate_announcement'));

-- at most ONE open (queued / running) job per translation row: a publication and a backfill queuing the same
-- translation at the same moment cannot create two jobs (the second insert gets the existing job instead)
create unique index if not exists ingestion_jobs_translation_open_uidx
  on public.ingestion_jobs ((payload->>'translation_id'))
  where job_type in ('translate_document', 'translate_announcement') and status in ('queued', 'running');
