-- Rollback of 0018. Removes the AI usage tables and functions: the daily counters, the usage history and the admin switches
-- (including an active emergency stop). The application falls back to in-process budgets. Take a backup first.
begin;
drop function if exists public.llm_usage_add(date, text, text, text, text, boolean, bigint, bigint, bigint, numeric, boolean);
drop function if exists public.llm_counter_take(date, text, integer);
drop table if exists public.app_runtime_flags;
drop table if exists public.llm_usage_daily;
drop table if exists public.llm_daily_counters;
commit;
