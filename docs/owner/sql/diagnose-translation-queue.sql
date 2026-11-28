-- READ-ONLY diagnostic: why announcement translations show "To do" / "Queued" with no draft.
-- Every statement is a SELECT inside a READ ONLY transaction that is rolled back: nothing can be written.
-- Run in Supabase -> SQL Editor, one numbered query at a time. Background: docs/final-release/ANNOUNCEMENT-TRANSLATION.md
-- Queries 1-4 work on the production schema (0015). Query 5 needs migration 0016 (skip it if query 4 says it is missing).

-- 1. Translation tasks by language and state, and whether ANY machine-translation job exists for them --------------------
--    Expected for the reported problem: many 'todo' rows and jobs_for_task = 0 (nothing was ever queued).
begin transaction read only;
select t.language_code,
       t.translation_status,
       count(*)                                                          as tasks,
       count(*) filter (where j.n is null)                               as tasks_without_any_job,
       coalesce(sum(j.n), 0)                                             as jobs_for_these_tasks
  from public.announcement_translations t
  left join lateral (select count(*) as n from public.ingestion_jobs x
                      where x.job_type = 'translate_announcement' and x.payload->>'translation_id' = t.id::text) j
         on j.n > 0
 group by t.language_code, t.translation_status
 order by t.language_code, t.translation_status;
rollback;

-- 2. Machine-translation jobs: how many in which state, with which error, the oldest and newest --------------------------
--    'queued' with error_code llm_quota / translation_daily_limit / llm_background_budget = waiting for a budget;
--    'queued' with no error and an old created_at = nothing picks them up; 'failed' = see error_code / error_message.
begin transaction read only;
select status, coalesce(error_code, '-') as error_code, count(*) as jobs, min(created_at) as oldest, max(created_at) as newest,
       max(run_after) as latest_run_after
  from public.ingestion_jobs
 where job_type = 'translate_announcement'
 group by status, coalesce(error_code, '-')
 order by status, jobs desc;
rollback;

-- 3. The last 20 machine-translation jobs with their announcement (titles only, no text) ---------------------------------
begin transaction read only;
select j.created_at, j.status, j.attempts, j.max_attempts, j.run_after, j.started_at, j.heartbeat_at, j.completed_at,
       j.error_code, left(j.error_message, 160) as error_message, j.payload->>'language' as language,
       a.title as announcement, a.publication_status, a.original_language
  from public.ingestion_jobs j
  left join public.announcements a on a.id::text = j.payload->>'announcement_id'
 where j.job_type = 'translate_announcement'
 order by j.created_at desc
 limit 20;
rollback;

-- 4. Which optional migrations exist (0016 GPU worker, 0017 agent operations, 0018 AI budgets, 0019 weekly discovery) ----
begin transaction read only;
select to_regclass('public.gpu_workers')      is not null as has_0016_gpu_worker,
       to_regclass('public.agent_controls')   is not null as has_0017_agent_operations,
       to_regclass('public.llm_usage_daily')  is not null as has_0018_ai_budgets,
       (select count(*) from information_schema.columns
         where table_schema = 'public' and table_name = 'ingestion_jobs' and column_name = 'executor') = 1
                                               as ingestion_jobs_has_executor;
rollback;

-- 5. ONLY WITH 0016: GPU workers (no token hashes) and GPU jobs -----------------------------------------------------------
-- begin transaction read only;
-- select name, status, expires_at, last_seen_at, now() - last_seen_at as since_last_contact from public.gpu_workers
--  order by created_at;
-- select executor, status, count(*) as jobs, min(created_at) as oldest
--   from public.ingestion_jobs where job_type = 'translate_announcement' group by executor, status order by 1, 2;
-- rollback;
