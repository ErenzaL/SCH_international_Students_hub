-- =============================================================================
-- 0016  Outbound-only GPU worker (university server) for translation drafts. ADDITIVE, off until GPU_WORKER_ENABLED.
-- Reuses ingestion_jobs; adds only
--   * ingestion_jobs.executor: 'local' (the API's own worker, default) or 'gpu' (leased to a GPU worker);
--   * a lease (token + expiry) and a cancel flag for 'gpu' jobs;
--   * gpu_workers: one revocable, expiring credential per worker (SHA-256 of a random token, never the token);
--   * claim_gpu_job / expire_gpu_leases; claim_ingestion_job now leaves 'gpu' jobs alone (otherwise unchanged).
-- Workers never reach the database: only the API (service role) calls these functions.
-- =============================================================================

alter table public.ingestion_jobs
  add column if not exists executor         text not null default 'local' check (executor in ('local', 'gpu')),
  add column if not exists lease_token      uuid,
  add column if not exists lease_expires_at timestamptz,
  add column if not exists cancel_requested boolean not null default false;

-- only translation drafts can ever be handed to a GPU worker
alter table public.ingestion_jobs drop constraint if exists ingestion_jobs_gpu_type_check;
alter table public.ingestion_jobs add constraint ingestion_jobs_gpu_type_check
  check (executor = 'local' or job_type in ('translate_announcement', 'translate_document'));
create index if not exists ingestion_jobs_gpu_queue_idx
  on public.ingestion_jobs (run_after, created_at) where executor = 'gpu' and status = 'queued';
create index if not exists ingestion_jobs_gpu_running_idx
  on public.ingestion_jobs (lease_expires_at) where executor = 'gpu' and status = 'running';

create table if not exists public.gpu_workers (
  id                   uuid primary key default gen_random_uuid(),
  name                 text not null unique check (name ~ '^[a-z0-9][a-z0-9-]{1,40}$'),
  status               text not null default 'active' check (status in ('active', 'paused', 'revoked')),
  token_hash           text not null check (token_hash ~ '^[0-9a-f]{64}$'),
  previous_token_hash  text check (previous_token_hash ~ '^[0-9a-f]{64}$'),
  previous_valid_until timestamptz,
  expires_at           timestamptz not null,
  last_seen_at         timestamptz,
  created_by           uuid references public.profiles (id) on delete set null,
  created_at           timestamptz not null default now(),
  rotated_at           timestamptz,
  revoked_at           timestamptz
);
alter table public.gpu_workers enable row level security;      -- no policies: browser roles see nothing
revoke all on public.gpu_workers from public, anon, authenticated;
grant all on public.gpu_workers to service_role;

-- same as 0006, restricted to the API's own jobs
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
   where status = 'running' and executor = 'local'
     and coalesce(heartbeat_at, started_at, created_at) < now() - make_interval(secs => greatest(p_stale_seconds, 60));

  select id into v_id
    from public.ingestion_jobs
   where status = 'queued' and executor = 'local' and run_after <= now()
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

-- leases that ran out (school server offline, crash): re-queue, or fail after max_attempts / when cancelled
create or replace function public.expire_gpu_leases()
returns integer
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  n integer;
begin
  update public.ingestion_jobs
     set status        = case when not cancel_requested and attempts < max_attempts then 'queued' else 'failed' end,
         locked_by     = null, lease_token = null, lease_expires_at = null, run_after = now(),
         error_code    = case when cancel_requested then 'cancelled'
                              when attempts < max_attempts then 'lease_expired' else 'interrupted' end,
         error_message = case when cancel_requested then 'Cancelled by an administrator.'
                              when attempts < max_attempts then 'The GPU worker went offline; the job waits for it.'
                              else 'The GPU worker stopped while this job was running and the retry limit was reached.' end,
         completed_at  = case when not cancel_requested and attempts < max_attempts then null else now() end
   where executor = 'gpu' and status = 'running' and lease_expires_at < now();
  get diagnostics n = row_count;
  return n;
end;
$$;

-- p_lease_token is chosen by the worker: repeating a claim whose response was lost returns the same job.
create or replace function public.claim_gpu_job(p_worker uuid, p_lease_token uuid, p_lease_seconds integer,
                                                p_job_types text[], p_max_running integer default 1)
returns setof public.ingestion_jobs
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_id uuid;
begin
  perform pg_advisory_xact_lock(hashtext('claim_gpu_job'));      -- one claim at a time: the limit below is exact
  perform public.expire_gpu_leases();
  if not exists (select 1 from public.gpu_workers
                  where id = p_worker and status = 'active' and expires_at > now()) then
    return;
  end if;

  return query select * from public.ingestion_jobs
   where executor = 'gpu' and status = 'running' and lease_token = p_lease_token and locked_by = 'gpu:' || p_worker;
  if found then
    return;
  end if;
  if (select count(*) from public.ingestion_jobs where executor = 'gpu' and status = 'running') >= p_max_running then
    return;
  end if;

  select id into v_id
    from public.ingestion_jobs
   where executor = 'gpu' and status = 'queued' and run_after <= now() and job_type = any (p_job_types)
     and not cancel_requested
   order by created_at
   limit 1
   for update skip locked;
  if v_id is null then
    return;
  end if;
  return query
  update public.ingestion_jobs
     set status = 'running', attempts = attempts + 1, started_at = now(), heartbeat_at = now(),
         locked_by = 'gpu:' || p_worker, lease_token = p_lease_token,
         lease_expires_at = now() + make_interval(secs => greatest(p_lease_seconds, 30))
   where id = v_id
  returning *;
end;
$$;

revoke all on function public.claim_ingestion_job(text, integer) from public, anon, authenticated;
revoke all on function public.expire_gpu_leases() from public, anon, authenticated;
revoke all on function public.claim_gpu_job(uuid, uuid, integer, text[], integer) from public, anon, authenticated;
grant execute on function public.claim_ingestion_job(text, integer) to service_role;
grant execute on function public.expire_gpu_leases() to service_role;
grant execute on function public.claim_gpu_job(uuid, uuid, integer, text[], integer) to service_role;
