-- Rollback of 0017. Removes the new desks' sources with their candidates, their schedules and agent_controls, and restores the
-- claim function of 0014 and the checks of 0015. Items of kind 'event' become 'program'. Take a backup first.
begin;
delete from public.agent_tasks where task_type in ('guidance_discovery', 'event_discovery')
   or (agent_id = 'career' and task_type = 'opportunity_discovery');
delete from public.agent_schedules where task_type in ('guidance_discovery', 'event_discovery')
   or (agent_id = 'career' and task_type = 'opportunity_discovery');
delete from public.discovery_sources where agent_id in ('immigration', 'academic', 'topik') or kind in ('saramin_api', 'data_go_kr_jobs');
alter table public.discovery_sources drop constraint if exists discovery_sources_kind_check;
alter table public.discovery_sources add constraint discovery_sources_kind_check check (kind in ('sch_board', 'listing', 'page'));
update public.discovered_items set opportunity_kind = 'program' where opportunity_kind = 'event';
alter table public.discovered_items drop constraint if exists discovered_items_opportunity_kind_check;
alter table public.discovered_items add constraint discovered_items_opportunity_kind_check
  check (opportunity_kind in ('scholarship', 'competition', 'program', 'job'));
alter table public.discovery_sources drop constraint if exists discovery_sources_agent_id_check;
alter table public.discovery_sources add constraint discovery_sources_agent_id_check
  check (agent_id in ('announcement', 'scholarship', 'career', 'events'));
create or replace function public.claim_agent_task(p_worker text, p_stale_seconds integer default 300)
returns setof public.agent_tasks
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
  update public.agent_tasks
     set status = case when attempts < max_attempts then 'queued' else 'failed' end,
         locked_by = null, run_after = now(),
         error_code = case when attempts < max_attempts then error_code else 'interrupted' end,
         error_message = case when attempts < max_attempts then error_message
                              else 'The worker stopped while this task was running and the retry limit was reached.' end,
         completed_at = case when attempts < max_attempts then null else now() end
   where status = 'running' and coalesce(heartbeat_at, started_at, created_at) < now() - make_interval(secs => greatest(p_stale_seconds, 60));
  return query
  update public.agent_tasks t
     set status = 'running', attempts = t.attempts + 1, started_at = now(), heartbeat_at = now(), locked_by = p_worker
   where t.id = (select id from public.agent_tasks
                  where status = 'queued' and run_after <= now()
                  order by created_at
                  for update skip locked
                  limit 1)
  returning t.*;
end;
$$;
drop function if exists public.storage_overview();
drop table if exists public.agent_controls;
commit;
