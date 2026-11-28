-- behaviour of migration 0019 (weekly discovery)
\set ON_ERROR_STOP on
begin;
do $$
declare n int;
begin
  select count(*) into n from public.agent_schedules where interval_minutes = 10080 and params ? 'stagger_minutes';
  if n <> 11 then raise exception 'expected 11 weekly schedules, got %', n; end if;
  select count(*) into n from public.agent_schedules where enabled;
  if n <> 0 then raise exception 'a schedule is enabled'; end if;
  select count(distinct params->>'stagger_minutes') into n from public.agent_schedules;
  if n <> 11 then raise exception 'staggers are not distinct (% values)', n; end if;
  insert into public.discovery_sources (agent_id, name, kind, url) values ('career', 'Work24', 'work24_api', 'https://www.work24.go.kr/');
  begin
    insert into public.discovery_sources (agent_id, name, kind, url) values ('career', 'Scraper', 'jobkorea_scrape', 'https://www.jobkorea.co.kr/');
    raise exception 'unknown kind accepted';
  exception when check_violation then null; end;
end $$;
rollback;
select 'behavior_test_weekly_discovery: ok';
