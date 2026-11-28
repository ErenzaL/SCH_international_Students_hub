-- =============================================================================
-- ROLLBACK of migration 0016 (GPU worker). NOT a migration: the Supabase CLI never runs this folder.
-- 1. Set GPU_WORKER_ENABLED=false (or deploy the previous release) and revoke every worker first.
-- 2. psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f supabase/rollback/20261124000016_gpu_worker_down.sql
-- Drafts already generated are kept (status needs_review). Open GPU jobs are failed visibly, so the same translation
-- can be requested again from the API's own worker. Dropping the columns is safe for older code, which ignores them.
-- =============================================================================
begin;

update public.ingestion_jobs
   set status = 'failed', completed_at = now(), locked_by = null, error_code = 'cancelled',
       error_message = 'The GPU worker was removed; request the translation again.'
 where executor = 'gpu' and status in ('queued', 'running');

drop function if exists public.claim_gpu_job(uuid, uuid, integer, text[], integer);
drop function if exists public.expire_gpu_leases();
drop table if exists public.gpu_workers;

-- claim_ingestion_job as in 0006
create or replace function public.claim_ingestion_job(p_worker text, p_stale_seconds integer default 900)
returns setof public.ingestion_jobs
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_id uuid;
begin
  update public.ingestion_jobs
     set status        = case when attempts < max_attempts then 'queued' else 'failed' end,
         locked_by     = null,
         run_after     = now(),
         error_code    = case when attempts < max_attempts then error_code else 'interrupted' end,
         error_message = case when attempts < max_attempts then error_message
                              else 'The worker stopped while this job was running and the retry limit was reached.' end,
         completed_at  = case when attempts < max_attempts then null else now() end
   where status = 'running'
     and coalesce(heartbeat_at, started_at, created_at) < now() - make_interval(secs => greatest(p_stale_seconds, 60));
  select id into v_id
    from public.ingestion_jobs
   where status = 'queued' and run_after <= now()
   order by created_at
   limit 1
   for update skip locked;
  if v_id is null then
    return;
  end if;
  return query
  update public.ingestion_jobs
     set status = 'running', attempts = attempts + 1, started_at = now(), heartbeat_at = now(), locked_by = p_worker
   where id = v_id
  returning *;
end;
$$;

drop index if exists public.ingestion_jobs_gpu_queue_idx;
drop index if exists public.ingestion_jobs_gpu_running_idx;
alter table public.ingestion_jobs drop constraint if exists ingestion_jobs_gpu_type_check;
alter table public.ingestion_jobs
  drop column if exists executor, drop column if exists lease_token, drop column if exists lease_expires_at,
  drop column if exists cancel_requested;

delete from supabase_migrations.schema_migrations where version = '20261124000016';
commit;
