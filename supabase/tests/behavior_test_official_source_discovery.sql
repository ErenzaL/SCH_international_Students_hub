-- Migration 0015 (official-source discovery) checks: constraints, one item per canonical URL, cascade, the two
-- monitoring schedules seeded disabled with admin review, task progress column, service-role-only access, re-run.
-- Scratch DB only.
\set ON_ERROR_STOP on
begin;

do $$
declare n int; s uuid;
begin
  select count(*) into n from agent_schedules
   where task_type in ('announcement_discovery', 'opportunity_discovery') and not enabled and params->>'review' = 'admin';
  if n <> 2 then raise exception 'FAIL: monitoring schedules not seeded disabled with admin review (%)', n; end if;

  insert into discovery_sources (id, agent_id, name, kind, url)
  values ('81500000-0000-0000-0000-000000000001', 'announcement', 'SCH notices', 'sch_board',
          'https://sgee.sch.ac.kr/notice/notice01.php?table_name=noti_fore');
  begin
    insert into discovery_sources (agent_id, name, kind, url) values ('reception', 'x', 'page', 'https://sch.ac.kr/');
    raise exception 'FAIL: discovery source for an agent without monitoring accepted';
  exception when check_violation then null; end;
  begin
    insert into discovery_sources (agent_id, name, kind, url) values ('announcement', 'x', 'script', 'https://sch.ac.kr/');
    raise exception 'FAIL: unknown connector kind accepted';
  exception when check_violation then null; end;
  begin
    insert into discovery_sources (agent_id, name, kind, url) values ('announcement', 'x', 'page', 'file:///etc/passwd');
    raise exception 'FAIL: non-http URL accepted';
  exception when check_violation then null; end;
  begin
    insert into discovery_sources (agent_id, name, kind, url)
    values ('announcement', 'Again', 'sch_board', 'https://sgee.sch.ac.kr/notice/notice01.php?table_name=noti_fore');
    raise exception 'FAIL: same URL twice for one agent accepted';
  exception when unique_violation then null; end;

  insert into discovered_items (id, source_id, item_key, url, title, content_hash)
  values ('91500000-0000-0000-0000-000000000001', '81500000-0000-0000-0000-000000000001',
          'https://sgee.sch.ac.kr/notice/notice01.php?admin_mode=read&no=1', 'https://sgee.sch.ac.kr/x', '장학금 안내', 'h1');
  begin
    insert into discovered_items (source_id, item_key, url, title, content_hash)
    values ('81500000-0000-0000-0000-000000000001', 'https://sgee.sch.ac.kr/notice/notice01.php?admin_mode=read&no=1',
            'https://sgee.sch.ac.kr/x', 'copy', 'h2');
    raise exception 'FAIL: duplicate item_key accepted';
  exception when unique_violation then null; end;
  begin
    update discovered_items set status = 'published' where id = '91500000-0000-0000-0000-000000000001';
    raise exception 'FAIL: a discovered item could be marked published';
  exception when check_violation then null; end;
  begin
    update discovered_items set open_status = 'probably' where id = '91500000-0000-0000-0000-000000000001';
    raise exception 'FAIL: unknown open status accepted';
  exception when check_violation then null; end;

  select count(*) into n from information_schema.columns where table_name = 'agent_tasks' and column_name = 'progress';
  if n <> 1 then raise exception 'FAIL: agent_tasks.progress missing'; end if;

  delete from discovery_sources where id = '81500000-0000-0000-0000-000000000001';
  select count(*) into n from discovered_items where id = '91500000-0000-0000-0000-000000000001';
  if n <> 0 then raise exception 'FAIL: items survived their source'; end if;
end $$;

-- students and visitors can read nothing here (the API decides what students see)
set local role authenticated;
do $$
begin
  begin
    perform 1 from discovered_items;
    raise exception 'FAIL: authenticated users can read discovered items';
  exception when insufficient_privilege then null; end;
  begin
    perform 1 from discovery_sources;
    raise exception 'FAIL: authenticated users can read discovery sources';
  exception when insufficient_privilege then null; end;
end $$;
reset role;
set local role anon;
do $$
begin
  begin
    perform 1 from discovered_items;
    raise exception 'FAIL: anon can read discovered items';
  exception when insufficient_privilege then null; end;
end $$;
reset role;

\ir ../migrations/20261124000015_official_source_discovery.sql
do $$
declare n int;
begin
  select count(*) into n from agent_schedules where task_type in ('announcement_discovery', 'opportunity_discovery');
  if n <> 2 then raise exception 'FAIL: re-running 0015 changed schedules'; end if;
end $$;

select 'ALL OFFICIAL-SOURCE DISCOVERY SQL BEHAVIOUR TESTS PASSED' as result;
rollback;
