-- =============================================================================
-- 0017  Agent operations. ADDITIVE; nothing is enabled.
--   * official sources and (disabled) schedules for the other desks: immigration, academic, topik, events, career;
--   * 'event' as a kind of a discovered item; two official recruitment APIs as kinds of a source (keys stay in the API's environment);
--   * agent_controls: an admin can pause a desk (its tasks wait, nothing new is started);
--   * storage_overview(): sizes of the Hub's tables, service role only.
-- Independent of 0016. The application works without this migration (the new desks then have no sources).
-- =============================================================================

alter table public.discovery_sources drop constraint if exists discovery_sources_agent_id_check;
alter table public.discovery_sources add constraint discovery_sources_agent_id_check
  check (agent_id in ('announcement', 'scholarship', 'career', 'events', 'immigration', 'academic', 'topik'));
alter table public.discovery_sources drop constraint if exists discovery_sources_kind_check;
alter table public.discovery_sources add constraint discovery_sources_kind_check
  check (kind in ('sch_board', 'listing', 'page', 'saramin_api', 'data_go_kr_jobs'));
alter table public.discovered_items drop constraint if exists discovered_items_opportunity_kind_check;
alter table public.discovered_items add constraint discovered_items_opportunity_kind_check
  check (opportunity_kind in ('scholarship', 'competition', 'program', 'job', 'event'));

create table if not exists public.agent_controls (
  agent_id   text primary key check (agent_id ~ '^[a-z][a-z0-9-]{1,40}$'),
  paused     boolean not null default false,
  note       text check (length(note) <= 500),
  updated_by uuid references public.profiles (id) on delete set null,
  updated_at timestamptz not null default now()
);
drop trigger if exists agent_controls_updated_at on public.agent_controls;
create trigger agent_controls_updated_at before update on public.agent_controls
  for each row execute function public.set_updated_at();
alter table public.agent_controls enable row level security;     -- no policies: browser roles see nothing
revoke all on public.agent_controls from public, anon, authenticated;
grant all on public.agent_controls to service_role;

-- as in 0014, but queued tasks of a paused desk wait
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
   where t.id = (select q.id from public.agent_tasks q
                  where q.status = 'queued' and q.run_after <= now()
                    and not exists (select 1 from public.agent_controls c where c.agent_id = q.agent_id and c.paused)
                  order by q.created_at
                  for update skip locked
                  limit 1)
  returning t.*;
end;
$$;
revoke all on function public.claim_agent_task(text, integer) from public, anon, authenticated;
grant execute on function public.claim_agent_task(text, integer) to service_role;

-- sizes only (no content): for the admin storage page and its warnings
create or replace function public.storage_overview()
returns table (table_name text, total_bytes bigint, table_bytes bigint, index_bytes bigint, row_estimate bigint)
language sql
stable
security definer
set search_path = public, pg_catalog, pg_temp
as $$
  select c.relname::text, pg_total_relation_size(c.oid), pg_table_size(c.oid), pg_indexes_size(c.oid),
         greatest(c.reltuples, 0)::bigint
    from pg_class c join pg_namespace n on n.oid = c.relnamespace
   where n.nspname = 'public' and c.relkind = 'r'
  union all
  select '(database)', pg_database_size(current_database()), null, null, null
$$;
revoke all on function public.storage_overview() from public, anon, authenticated;
grant execute on function public.storage_overview() to service_role;

-- monitoring schedules of the other desks: all disabled, and AGENT_SCHEDULES_ENABLED is off as well
insert into public.agent_schedules (agent_id, task_type, interval_minutes, params) values
  ('immigration', 'guidance_discovery', 2880, '{"max_items_per_source": 10, "max_sources": 5, "notify_admins": true, "summarize_new": false, "review": "admin"}'),
  ('academic',    'guidance_discovery', 1440, '{"max_items_per_source": 10, "max_sources": 5, "notify_admins": true, "summarize_new": false, "review": "admin"}'),
  ('topik',       'guidance_discovery', 2880, '{"max_items_per_source": 10, "max_sources": 5, "notify_admins": true, "summarize_new": false, "review": "admin"}'),
  ('events',      'event_discovery',    1440, '{"max_items_per_source": 10, "max_sources": 5, "notify_admins": true, "summarize_new": false, "review": "admin"}'),
  ('career',      'opportunity_discovery', 1440, '{"max_items_per_source": 10, "max_sources": 5, "notify_admins": true, "summarize_new": false, "review": "admin"}')
on conflict (agent_id, task_type) do nothing;
