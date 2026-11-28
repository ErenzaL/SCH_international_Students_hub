-- READ-ONLY: is migration 0016 (GPU worker) completely present on this database, with the right permissions?
-- One SELECT in a READ ONLY transaction that is rolled back: nothing can be written. Run it as a whole in Supabase ->
-- SQL Editor. Every row must say ok = true before GPU_WORKER_ENABLED=true. Rows with ok = false (or empty) name what is
-- missing; then apply 0016 as described in docs/owner/GPU-ACTIVATION.md (backup first).
begin transaction read only;
with f as (
  select to_regprocedure('public.claim_gpu_job(uuid,uuid,integer,text[],integer)') as claim_gpu,
         to_regprocedure('public.expire_gpu_leases()')                            as expire,
         to_regprocedure('public.claim_ingestion_job(text,integer)')               as claim_local,
         to_regclass('public.gpu_workers')                                         as workers
)
select * from (
  select 1 as n, 'table public.gpu_workers' as check_name, (select workers is not null from f) as ok
  union all select 2, 'row level security on gpu_workers',
         coalesce((select c.relrowsecurity from pg_class c, f where c.oid = f.workers), false)
  union all select 3, 'no RLS policy on gpu_workers (browser roles see nothing)',
         (select workers is not null from f) and not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'gpu_workers')
  union all select 4, 'anon cannot read gpu_workers',          (select not has_table_privilege('anon', workers, 'select') from f)
  union all select 5, 'authenticated cannot read gpu_workers', (select not has_table_privilege('authenticated', workers, 'select') from f)
  union all select 6, 'service_role can use gpu_workers',      (select has_table_privilege('service_role', workers, 'select,insert,update') from f)
  union all select 7, 'column ingestion_jobs.executor',         exists (select 1 from information_schema.columns where table_schema = 'public' and table_name = 'ingestion_jobs' and column_name = 'executor')
  union all select 8, 'column ingestion_jobs.lease_token',      exists (select 1 from information_schema.columns where table_schema = 'public' and table_name = 'ingestion_jobs' and column_name = 'lease_token')
  union all select 9, 'column ingestion_jobs.lease_expires_at', exists (select 1 from information_schema.columns where table_schema = 'public' and table_name = 'ingestion_jobs' and column_name = 'lease_expires_at')
  union all select 10, 'column ingestion_jobs.cancel_requested', exists (select 1 from information_schema.columns where table_schema = 'public' and table_name = 'ingestion_jobs' and column_name = 'cancel_requested')
  union all select 11, 'only translation jobs can be GPU jobs (ingestion_jobs_gpu_type_check)',
         exists (select 1 from pg_constraint where conname = 'ingestion_jobs_gpu_type_check')
  union all select 12, 'index ingestion_jobs_gpu_queue_idx',   to_regclass('public.ingestion_jobs_gpu_queue_idx') is not null
  union all select 13, 'index ingestion_jobs_gpu_running_idx', to_regclass('public.ingestion_jobs_gpu_running_idx') is not null
  union all select 14, 'function claim_gpu_job',    (select claim_gpu is not null from f)
  union all select 15, 'function expire_gpu_leases', (select expire is not null from f)
  union all select 16, 'the API''s own worker leaves GPU jobs alone (claim_ingestion_job from 0016)',
         coalesce((select position('executor' in pg_get_functiondef(claim_local)) > 0 from f), false)
  union all select 17, 'anon cannot run claim_gpu_job',          (select not has_function_privilege('anon', claim_gpu, 'execute') from f)
  union all select 18, 'authenticated cannot run claim_gpu_job', (select not has_function_privilege('authenticated', claim_gpu, 'execute') from f)
  union all select 19, 'anon cannot run expire_gpu_leases',      (select not has_function_privilege('anon', expire, 'execute') from f)
  union all select 20, 'service_role can run claim_gpu_job',     (select has_function_privilege('service_role', claim_gpu, 'execute') from f)
) checks order by n;
rollback;

-- After 0016 exists: open GPU / local jobs by state (expected before activation: no 'gpu' rows)
-- begin transaction read only;
-- select executor, status, count(*) from public.ingestion_jobs group by 1, 2 order by 1, 2;
-- rollback;
