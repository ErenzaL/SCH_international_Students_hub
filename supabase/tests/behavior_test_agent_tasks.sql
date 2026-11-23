-- Migration 0014 (AI Support Office agent tasks) checks: constraints, one active task per idempotency key,
-- claim_agent_task (skip locked, stale recovery, retry limit), owner-only RLS, schedules seeded disabled,
-- cascade on delete, and the migration re-runs cleanly. Scratch DB only.
\set ON_ERROR_STOP on
begin;

insert into auth.users (id, email) values
  ('00000000-0000-0000-0000-0000000014a1', 'student14a@example.test'),
  ('00000000-0000-0000-0000-0000000014a2', 'student14b@example.test');

do $$
declare n int; t uuid; r record;
begin
  -- schedules exist and are all disabled
  select count(*) into n from agent_schedules
   where task_type in ('announcement_digest', 'scholarship_scan', 'event_digest', 'career_scan');
  if n <> 4 then raise exception 'FAIL: expected 4 seeded schedules, got %', n; end if;
  select count(*) into n from agent_schedules where enabled;
  if n <> 0 then raise exception 'FAIL: a schedule is enabled by default'; end if;

  -- constraints
  begin
    insert into agent_tasks (agent_id, task_type, status) values ('events', 'event_digest', 'done');
    raise exception 'FAIL: unknown status accepted';
  exception when check_violation then null; end;
  begin
    insert into agent_tasks (agent_id, task_type, depth) values ('events', 'event_digest', 3);
    raise exception 'FAIL: depth 3 accepted';
  exception when check_violation then null; end;
  begin
    insert into agent_tasks (agent_id, task_type) values ('Events; drop table x', 'event_digest');
    raise exception 'FAIL: malformed agent id accepted';
  exception when check_violation then null; end;
  begin
    insert into agent_tasks (agent_id, task_type, params)
    values ('events', 'event_digest', jsonb_build_object('x', repeat('a', 20001)));
    raise exception 'FAIL: oversized params accepted';
  exception when check_violation then null; end;
  begin
    update agent_schedules set interval_minutes = 5 where agent_id = 'events';
    raise exception 'FAIL: 5-minute schedule accepted';
  exception when check_violation then null; end;

  -- idempotency: one ACTIVE task per (owner, key); a finished one does not block a new one
  insert into agent_tasks (id, agent_id, task_type, requested_by, idempotency_key, created_at)
  values ('71400000-0000-0000-0000-000000000001', 'events', 'event_digest', '00000000-0000-0000-0000-0000000014a1', 'k1',
          now() - interval '1 minute');
  begin
    insert into agent_tasks (agent_id, task_type, requested_by, idempotency_key)
    values ('events', 'event_digest', '00000000-0000-0000-0000-0000000014a1', 'k1');
    raise exception 'FAIL: duplicate active task accepted';
  exception when unique_violation then null; end;
  insert into agent_tasks (agent_id, task_type, requested_by, idempotency_key, created_at)   -- another student, same key: fine
  values ('events', 'event_digest', '00000000-0000-0000-0000-0000000014a2', 'k1', now() + interval '1 second');

  -- claim: the oldest due queued task, attempts + 1, worker recorded
  select * into r from claim_agent_task('w1', 300);
  if r.id <> '71400000-0000-0000-0000-000000000001' or r.status <> 'running' or r.attempts <> 1 or r.locked_by <> 'w1' then
    raise exception 'FAIL: claim returned %', r;
  end if;
  -- a task of a dead worker is re-queued, and fails once max_attempts is reached
  update agent_tasks set heartbeat_at = now() - interval '1 hour' where id = '71400000-0000-0000-0000-000000000001';
  select * into r from claim_agent_task('w2', 300);   -- re-queues the stale one; claims the oldest due (the same one)
  if r.id <> '71400000-0000-0000-0000-000000000001' or r.attempts <> 2 or r.locked_by <> 'w2' then
    raise exception 'FAIL: stale recovery returned %', r;
  end if;
  update agent_tasks set heartbeat_at = now() - interval '1 hour', attempts = 3
   where id = '71400000-0000-0000-0000-000000000001';
  perform claim_agent_task('w3', 300);
  select status into r from agent_tasks where id = '71400000-0000-0000-0000-000000000001';
  if r.status <> 'failed' then raise exception 'FAIL: stale task past retry limit is %', r.status; end if;
  insert into agent_tasks (agent_id, task_type, requested_by, idempotency_key)    -- key free again once finished
  values ('events', 'event_digest', '00000000-0000-0000-0000-0000000014a1', 'k1');

  -- future run_after is not claimed
  update agent_tasks set run_after = now() + interval '1 hour' where status = 'queued';
  select count(*) into n from claim_agent_task('w4', 300);
  if n <> 0 then raise exception 'FAIL: claimed a task that is not due'; end if;

  -- events + children cascade with their task
  insert into agent_tasks (id, agent_id, task_type, requested_by)
  values ('71400000-0000-0000-0000-000000000009', 'reception', 'delegated_search', '00000000-0000-0000-0000-0000000014a1');
  insert into agent_tasks (agent_id, task_type, requested_by, parent_task_id, depth)
  values ('scholarship', 'lookup', '00000000-0000-0000-0000-0000000014a1', '71400000-0000-0000-0000-000000000009', 1);
  insert into agent_task_events (task_id, agent_id, step, message)
  values ('71400000-0000-0000-0000-000000000009', 'reception', 'queued', 'Queued');
  delete from agent_tasks where id = '71400000-0000-0000-0000-000000000009';
  select count(*) into n from agent_tasks where parent_task_id = '71400000-0000-0000-0000-000000000009';
  if n <> 0 then raise exception 'FAIL: child task survived its parent'; end if;
  select count(*) into n from agent_task_events where task_id = '71400000-0000-0000-0000-000000000009';
  if n <> 0 then raise exception 'FAIL: events survived their task'; end if;
  insert into agent_task_events (task_id, agent_id, step, message)
  select id, agent_id, 'queued', 'Queued' from agent_tasks;
end $$;

-- RLS: a student reads only their own tasks and events; cannot write; cannot claim; anon sees nothing
set local role authenticated;
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-0000000014a1', true);
do $$
declare n int;
begin
  select count(*) into n from agent_tasks where requested_by <> '00000000-0000-0000-0000-0000000014a1';
  if n <> 0 then raise exception 'FAIL: student sees another student''s tasks'; end if;
  select count(*) into n from agent_tasks;
  if n <> 2 then raise exception 'FAIL: student should see own 2 tasks, saw %', n; end if;
  select count(*) into n from agent_task_events e join agent_tasks t on t.id = e.task_id;
  if n <> 2 then raise exception 'FAIL: student should see own 2 events, saw %', n; end if;
  begin
    insert into agent_tasks (agent_id, task_type, requested_by)
    values ('events', 'event_digest', '00000000-0000-0000-0000-0000000014a1');
    raise exception 'FAIL: student inserted a task directly';
  exception when insufficient_privilege then null; end;
  begin
    update agent_tasks set status = 'completed';
    raise exception 'FAIL: student updated a task directly';
  exception when insufficient_privilege then null; end;
  begin
    perform claim_agent_task('student', 300);
    raise exception 'FAIL: student could claim tasks';
  exception when insufficient_privilege then null; end;
  begin
    perform 1 from agent_schedules;
    raise exception 'FAIL: student can read schedules';
  exception when insufficient_privilege then null; end;
end $$;
reset role;
set local role anon;
do $$
begin
  begin
    perform 1 from agent_tasks;
    raise exception 'FAIL: anon can read tasks';
  exception when insufficient_privilege then null; end;
end $$;
reset role;

-- re-running the migration changes nothing (and keeps schedules disabled)
\ir ../migrations/20261124000014_agent_tasks.sql
do $$
declare n int;
begin
  select count(*) into n from agent_schedules
   where task_type in ('announcement_digest', 'scholarship_scan', 'event_digest', 'career_scan');
  if n <> 4 then raise exception 'FAIL: re-running 0014 changed schedules'; end if;
  select count(*) into n from agent_tasks;
  if n <> 3 then raise exception 'FAIL: re-running 0014 changed tasks (%)', n; end if;
end $$;

select 'ALL AGENT TASK SQL BEHAVIOUR TESTS PASSED' as result;
rollback;
