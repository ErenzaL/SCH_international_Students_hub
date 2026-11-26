-- behaviour of migration 0017 (agent operations)
\set ON_ERROR_STOP on
begin;
do $$
declare n int; t record;
begin
  -- new desks may have sources, unknown ones may not
  insert into public.discovery_sources (agent_id, name, kind, url) values ('immigration', 'Test source', 'page', 'https://www.hikorea.go.kr/t17');
  begin
    insert into public.discovery_sources (agent_id, name, kind, url) values ('reception', 'Test source', 'page', 'https://www.hikorea.go.kr/x');
    raise exception 'unknown agent accepted';
  exception when check_violation then null; end;
  -- events are a kind
  insert into public.discovered_items (source_id, item_key, url, title, content_hash, opportunity_kind)
    select id, 'https://x/17', 'https://x/17', 'Festival', 'h', 'event' from public.discovery_sources where url like '%t17';
  -- every new schedule is disabled
  select count(*) into n from public.agent_schedules where enabled;
  if n <> 0 then raise exception 'a schedule is enabled'; end if;
  select count(*) into n from public.agent_schedules where task_type in ('guidance_discovery', 'event_discovery');
  if n <> 4 then raise exception 'expected 4 new schedules, got %', n; end if;
  -- a paused desk's tasks wait, others run
  insert into public.agent_tasks (agent_id, task_type, created_at) values ('career', 'career_scan', now() - interval '2 hours'), ('events', 'event_digest', now() - interval '1 hour');
  insert into public.agent_controls (agent_id, paused) values ('career', true);
  select * into t from public.claim_agent_task('w1', 300);
  if t.agent_id <> 'events' then raise exception 'claimed % instead of events', t.agent_id; end if;
  select count(*) into n from public.claim_agent_task('w1', 300);
  if n <> 0 then raise exception 'a paused task was claimed'; end if;
  update public.agent_controls set paused = false where agent_id = 'career';
  select * into t from public.claim_agent_task('w1', 300);
  if t.agent_id <> 'career' then raise exception 'resumed task not claimed'; end if;
  -- sizes
  select count(*) into n from public.storage_overview() where table_name = '(database)' and total_bytes > 0;
  if n <> 1 then raise exception 'no database size'; end if;
end $$;
-- browser roles cannot read or pause anything
set local role anon;
do $$ begin
  begin perform 1 from public.agent_controls; raise exception 'anon reads agent_controls'; exception when insufficient_privilege then null; end;
  begin perform 1 from public.storage_overview(); raise exception 'anon calls storage_overview'; exception when insufficient_privilege then null; end;
end $$;
reset role;
set local role authenticated;
do $$ begin
  begin update public.agent_controls set paused = true; raise exception 'student pauses an agent'; exception when insufficient_privilege then null; end;
  begin perform 1 from public.storage_overview(); raise exception 'student calls storage_overview'; exception when insufficient_privilege then null; end;
  begin perform 1 from public.claim_agent_task('x'); raise exception 'student claims'; exception when insufficient_privilege then null; end;
end $$;
reset role;
rollback;
select 'behavior_test_agent_operations: ok';
