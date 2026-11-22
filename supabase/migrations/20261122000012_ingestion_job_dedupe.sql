-- =============================================================================
-- 0012  Ingestion job de-duplication (no data deleted).
-- At most ONE active (queued/running) ingest job per uploaded file (sha256) and per source, enforced by partial
-- unique indexes so two simultaneous uploads cannot both start processing the same PDF. Already-active
-- duplicates are resolved first: the newest job of each group is kept, older ones are marked failed with an
-- explanation (their rows and events stay for the audit trail).
-- =============================================================================

with ranked as (
  select id, row_number() over (partition by payload ->> 'sha256' order by created_at desc) as rn
    from public.ingestion_jobs
   where job_type = 'ingest' and status in ('queued', 'running') and payload ? 'sha256'
)
update public.ingestion_jobs j
   set status = 'failed', completed_at = now(), locked_by = null, error_code = 'duplicate_job',
       error_message = 'Superseded: a newer ingestion job for the same file was active. That job continues.'
  from ranked r
 where r.id = j.id and r.rn > 1;

with ranked as (
  select id, row_number() over (partition by source_id order by created_at desc) as rn
    from public.ingestion_jobs
   where job_type in ('ingest', 'board_sync') and status in ('queued', 'running') and source_id is not null
)
update public.ingestion_jobs j
   set status = 'failed', completed_at = now(), locked_by = null, error_code = 'duplicate_job',
       error_message = 'Superseded: a newer ingestion job for this source was active. That job continues.'
  from ranked r
 where r.id = j.id and r.rn > 1;

create unique index if not exists ingestion_jobs_active_file_uniq
  on public.ingestion_jobs ((payload ->> 'sha256'))
  where job_type = 'ingest' and status in ('queued', 'running') and payload ? 'sha256';

create unique index if not exists ingestion_jobs_active_source_uniq
  on public.ingestion_jobs (source_id)
  where job_type in ('ingest', 'board_sync') and status in ('queued', 'running') and source_id is not null;
