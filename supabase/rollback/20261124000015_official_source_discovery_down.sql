-- Rollback of 0015 (official-source discovery). Removes ONLY what 0015 added: the discovery tables, the task progress
-- column and the two (disabled) monitoring schedules. Discovered candidates are lost; knowledge sources that an admin
-- created with "send to review" are ordinary knowledge sources and stay. Take a backup first.
begin;
delete from public.agent_tasks where task_type in ('announcement_discovery', 'opportunity_discovery');
delete from public.agent_schedules where task_type in ('announcement_discovery', 'opportunity_discovery');
drop table if exists public.discovered_items;
drop table if exists public.discovery_sources;
alter table public.agent_tasks drop column if exists progress;
commit;
