-- Rollback of 0014 (AI Support Office agent tasks). Removes ONLY what 0014 added: the agent task tables, their step
-- log, the schedules and the claim function. No other table references them. Task history is lost; take a backup
-- first (docs/ai-office/agents.md, "Rollback").
begin;
drop function if exists public.claim_agent_task(text, integer);
drop table if exists public.agent_task_events;
drop table if exists public.agent_tasks;
drop table if exists public.agent_schedules;
commit;
