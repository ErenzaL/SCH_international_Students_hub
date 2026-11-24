-- Migration 0016 (GPU worker) checks: routing, leases, limits, revocation, permissions, idempotent re-run. Scratch DB only.
\set ON_ERROR_STOP on
begin;
insert into knowledge_sources (id, title, organization, source_type, authority_type, scope, category)
values ('18000000-0000-0000-0000-000000000001', 'Notices', 'SCH', 'manual_text', 'official_university', 'university', 'scholarships');
insert into gpu_workers (id, name, token_hash, expires_at) values
  ('19000000-0000-0000-0000-000000000001', 'gpu-a', repeat('a', 64), now() + interval '1 day'),
  ('19000000-0000-0000-0000-000000000002', 'gpu-b', repeat('b', 64), now() + interval '1 day'),
  ('19000000-0000-0000-0000-000000000003', 'gpu-old', repeat('c', 64), now() - interval '1 second');
update ingestion_jobs set status = 'failed' where status in ('queued', 'running');
insert into ingestion_jobs (id, source_id, job_type, payload, executor, created_at) values
  ('1a000000-0000-0000-0000-000000000001', '18000000-0000-0000-0000-000000000001', 'translate_announcement', '{"translation_id": "t1"}', 'gpu', now() - interval '3 min'),
  ('1a000000-0000-0000-0000-000000000002', '18000000-0000-0000-0000-000000000001', 'translate_document', '{"translation_id": "t2"}', 'gpu', now() - interval '2 min');
insert into ingestion_jobs (id, source_id, job_type, created_at) values
  ('1a000000-0000-0000-0000-000000000003', '18000000-0000-0000-0000-000000000001', 'ocr_intake', now() - interval '1 min');

do $$
declare
  j public.ingestion_jobs; n int;
  a constant uuid := '19000000-0000-0000-0000-000000000001'; b constant uuid := '19000000-0000-0000-0000-000000000002';
  l1 constant uuid := gen_random_uuid(); l2 constant uuid := gen_random_uuid();
  types constant text[] := array['translate_announcement', 'translate_document'];
begin
  -- only translation drafts can be given to a GPU worker
  begin insert into ingestion_jobs (source_id, job_type, executor) values ('18000000-0000-0000-0000-000000000001', 'ingest', 'gpu');
        raise exception 'FAIL: gpu ingest job accepted';
  exception when check_violation then null; end;
  -- the API's own worker takes its own job although the GPU jobs are older
  select * into j from claim_ingestion_job('api', 60);
  if j.id <> '1a000000-0000-0000-0000-000000000003' then raise exception 'FAIL: local claim took %', j.id; end if;
  if exists (select 1 from claim_ingestion_job('api', 60)) then raise exception 'FAIL: local claim took a gpu job'; end if;
  -- expired worker, unknown worker, type not allowed
  if exists (select 1 from claim_gpu_job('19000000-0000-0000-0000-000000000003', l1, 180, types)) then raise exception 'FAIL: expired worker'; end if;
  if exists (select 1 from claim_gpu_job(gen_random_uuid(), l1, 180, types)) then raise exception 'FAIL: unknown worker'; end if;
  if exists (select 1 from claim_gpu_job(a, l1, 180, array['ocr_intake'])) then raise exception 'FAIL: type'; end if;
  -- claim, repeat, limit of one
  select * into j from claim_gpu_job(a, l1, 180, types);
  if j.id <> '1a000000-0000-0000-0000-000000000001' or j.attempts <> 1 or j.lease_token <> l1 or j.locked_by <> 'gpu:' || a::text
    then raise exception 'FAIL: claim %', j; end if;
  select * into j from claim_gpu_job(a, l1, 180, types);
  if j.id <> '1a000000-0000-0000-0000-000000000001' or j.attempts <> 1 then raise exception 'FAIL: repeated claim'; end if;
  if exists (select 1 from claim_gpu_job(b, l1, 180, types)) then raise exception 'FAIL: other worker used the lease'; end if;
  if exists (select 1 from claim_gpu_job(b, l2, 180, types)) then raise exception 'FAIL: concurrency limit'; end if;
  -- the API worker's stale recovery does not touch it
  update ingestion_jobs set heartbeat_at = now() - interval '1 day' where id = j.id;
  perform claim_ingestion_job('api', 60);
  select count(*) into n from ingestion_jobs where id = j.id and status = 'running';
  if n <> 1 then raise exception 'FAIL: stale recovery took a leased job'; end if;
  -- lease ends: queued again for anybody
  update ingestion_jobs set lease_expires_at = now() - interval '1 second' where id = j.id;
  select * into j from claim_gpu_job(b, l2, 180, types);
  if j.id <> '1a000000-0000-0000-0000-000000000001' or j.attempts <> 2 or j.lease_token <> l2 then raise exception 'FAIL: reclaim'; end if;
  -- attempt limit
  update ingestion_jobs set attempts = 3, lease_expires_at = now() - interval '1 second' where id = j.id;
  perform expire_gpu_leases();
  select * into j from ingestion_jobs where id = j.id;
  if j.status <> 'failed' or j.error_code <> 'interrupted' or j.lease_token is not null then raise exception 'FAIL: attempt limit'; end if;
  -- cancelled while running, worker gone
  select * into j from claim_gpu_job(a, l1, 180, types);
  update ingestion_jobs set cancel_requested = true, lease_expires_at = now() - interval '1 second' where id = j.id;
  perform expire_gpu_leases();
  select * into j from ingestion_jobs where id = j.id;
  if j.status <> 'failed' or j.error_code <> 'cancelled' then raise exception 'FAIL: cancel'; end if;
  -- paused and revoked workers get nothing
  insert into ingestion_jobs (source_id, job_type, payload, executor) values
    ('18000000-0000-0000-0000-000000000001', 'translate_document', '{"translation_id": "t3"}', 'gpu');
  update gpu_workers set status = 'paused' where id = a;
  if exists (select 1 from claim_gpu_job(a, l1, 180, types)) then raise exception 'FAIL: paused'; end if;
  update gpu_workers set status = 'revoked' where id = a;
  if exists (select 1 from claim_gpu_job(a, l1, 180, types)) then raise exception 'FAIL: revoked'; end if;
  begin update gpu_workers set token_hash = 'plain-token' where id = a; raise exception 'FAIL: plain token stored';
  exception when check_violation then null; end;
end $$;

-- browser roles: no table, no functions
do $$ declare r text; begin
  foreach r in array array['anon', 'authenticated'] loop
    if has_table_privilege(r, 'public.gpu_workers', 'select, insert, update, delete')
       or has_function_privilege(r, 'public.claim_gpu_job(uuid, uuid, integer, text[], integer)', 'execute')
       or has_function_privilege(r, 'public.expire_gpu_leases()', 'execute')
       or has_function_privilege(r, 'public.claim_ingestion_job(text, integer)', 'execute')
      then raise exception 'FAIL: % has access', r; end if;
  end loop;
end $$;

\i supabase/migrations/20261124000016_gpu_worker.sql
do $$ declare n int; begin
  select count(*) into n from gpu_workers where name like 'gpu-%';
  if n <> 3 then raise exception 'FAIL: data changed by re-running 0016'; end if;
end $$;
select 'ALL GPU WORKER SQL BEHAVIOUR TESTS PASSED' as result;
rollback;
