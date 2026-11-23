-- =============================================================================
-- 0014  AI Support Office agents: durable tasks, their step log, and (disabled) schedules.
-- ADDITIVE. Agent identities and tool permissions live in code (app/services/agents/registry.py) - the database
-- only stores work. Tasks are executed by the existing API worker (claim_agent_task, like claim_ingestion_job);
-- the API uses the service role and checks ownership; students can read only their own tasks through RLS.
-- No conversation transcripts are stored here: task params hold the request and the structured result holds
-- titles, links and extracted facts.
-- =============================================================================

create table if not exists public.agent_tasks (
  id               uuid primary key default gen_random_uuid(),
  agent_id         text not null check (agent_id ~ '^[a-z][a-z0-9-]{1,40}$'),
  task_type        text not null check (task_type ~ '^[a-z][a-z0-9_]{1,40}$'),
  requested_by     uuid references public.profiles (id) on delete cascade,   -- null = a scheduled (system) task
  parent_task_id   uuid references public.agent_tasks (id) on delete cascade,
  depth            smallint not null default 0 check (depth between 0 and 2),
  language         text check (language in ('ko', 'en', 'id', 'vi', 'zh-CN')),
  params           jsonb not null default '{}'::jsonb,
  status           text not null default 'queued'
                   check (status in ('queued', 'running', 'awaiting_approval', 'completed', 'failed', 'cancelled')),
  stage            text,
  cancel_requested boolean not null default false,
  idempotency_key  text,
  output           jsonb,
  citations        jsonb not null default '[]'::jsonb,
  error_code       text,
  error_message    text,
  attempts         integer not null default 0,
  max_attempts     integer not null default 3,
  run_after        timestamptz not null default now(),
  heartbeat_at     timestamptz,
  locked_by        text,
  schedule_id      uuid,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  started_at       timestamptz,
  completed_at     timestamptz,
  check (length(params::text) <= 20000)
);
create index if not exists agent_tasks_owner_idx on public.agent_tasks (requested_by, created_at desc);
create index if not exists agent_tasks_due_idx on public.agent_tasks (run_after) where status = 'queued';
create index if not exists agent_tasks_parent_idx on public.agent_tasks (parent_task_id);
-- the same request is never running twice for one student (or one schedule)
create unique index if not exists agent_tasks_active_dedupe_uidx
  on public.agent_tasks (coalesce(requested_by::text, 'system'), idempotency_key)
  where idempotency_key is not null and status in ('queued', 'running', 'awaiting_approval');

drop trigger if exists agent_tasks_updated_at on public.agent_tasks;
create trigger agent_tasks_updated_at before update on public.agent_tasks
  for each row execute function public.set_updated_at();

create table if not exists public.agent_task_events (
  id         bigint generated always as identity primary key,
  task_id    uuid not null references public.agent_tasks (id) on delete cascade,
  agent_id   text not null,                 -- which agent performed this step (delegation is visible)
  step       text not null,                 -- queued | start | tool | delegate | result | error | cancel | approval
  tool       text,
  message    text not null check (length(message) <= 2000),
  data       jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
create index if not exists agent_task_events_task_idx on public.agent_task_events (task_id, id);

create table if not exists public.agent_schedules (
  id               uuid primary key default gen_random_uuid(),
  agent_id         text not null,
  task_type        text not null,
  params           jsonb not null default '{}'::jsonb,
  enabled          boolean not null default false,          -- nothing runs until an admin enables it
  interval_minutes integer not null default 1440 check (interval_minutes between 60 and 10080),
  state            jsonb not null default '{}'::jsonb,       -- change detection (fingerprints of what was seen)
  last_run_at      timestamptz,
  last_success_at  timestamptz,
  next_run_at      timestamptz,
  last_error       text,
  updated_by       uuid references public.profiles (id) on delete set null,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  unique (agent_id, task_type)
);
drop trigger if exists agent_schedules_updated_at on public.agent_schedules;
create trigger agent_schedules_updated_at before update on public.agent_schedules
  for each row execute function public.set_updated_at();

-- ------------------------------------------------------------------ worker claim (like claim_ingestion_job)
create or replace function public.claim_agent_task(p_worker text, p_stale_seconds integer default 300)
returns setof public.agent_tasks
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
  -- tasks of a worker that died: re-queue (or fail after max_attempts)
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
revoke all on function public.claim_agent_task(text, integer) from public, anon, authenticated;
grant execute on function public.claim_agent_task(text, integer) to service_role;

-- ----------------------------------------------------------------------- RLS
alter table public.agent_tasks enable row level security;
alter table public.agent_task_events enable row level security;
alter table public.agent_schedules enable row level security;
revoke all on public.agent_tasks, public.agent_task_events, public.agent_schedules from anon, authenticated;

grant select on public.agent_tasks to authenticated;
drop policy if exists agent_tasks_own on public.agent_tasks;
create policy agent_tasks_own on public.agent_tasks for select to authenticated using (requested_by = auth.uid());

grant select on public.agent_task_events to authenticated;
drop policy if exists agent_task_events_own on public.agent_task_events;
create policy agent_task_events_own on public.agent_task_events for select to authenticated
  using (exists (select 1 from public.agent_tasks t where t.id = task_id and t.requested_by = auth.uid()));

grant all on public.agent_tasks, public.agent_task_events, public.agent_schedules to service_role;
grant usage, select on all sequences in schema public to service_role;

-- the proactive jobs that exist (all disabled; admins enable them individually)
insert into public.agent_schedules (agent_id, task_type, interval_minutes) values
  ('announcement', 'announcement_digest', 720),
  ('scholarship', 'scholarship_scan', 1440),
  ('events', 'event_digest', 720),
  ('career', 'career_scan', 1440)
on conflict (agent_id, task_type) do nothing;
