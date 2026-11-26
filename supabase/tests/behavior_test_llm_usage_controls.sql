-- behaviour of migration 0018 (AI usage controls)
\set ON_ERROR_STOP on
begin;
do $$
declare ok boolean; n int; r record;
begin
  -- a budget of 2: two units, then refused (nothing consumed)
  select public.llm_counter_take('2026-01-01', 'background', 2) into ok; if not ok then raise exception 'first unit refused'; end if;
  select public.llm_counter_take('2026-01-01', 'background', 2) into ok; if not ok then raise exception 'second unit refused'; end if;
  select public.llm_counter_take('2026-01-01', 'background', 2) into ok; if ok then raise exception 'third unit accepted'; end if;
  select used into n from public.llm_daily_counters where day = '2026-01-01' and key = 'background';
  if n <> 2 then raise exception 'counter is %, expected 2', n; end if;
  -- a new day starts at zero; keys are independent; limit 0 = no limit
  select public.llm_counter_take('2026-01-02', 'background', 2) into ok; if not ok then raise exception 'new day refused'; end if;
  select public.llm_counter_take('2026-01-01', 'global', 1) into ok; if not ok then raise exception 'other key refused'; end if;
  for i in 1..5 loop
    select public.llm_counter_take('2026-01-01', 'unlimited', 0) into ok; if not ok then raise exception 'unlimited refused'; end if;
  end loop;
  -- a limit of 1 on a fresh key: exactly one unit
  select public.llm_counter_take('2026-01-03', 'one', 1) into ok; if not ok then raise exception 'limit 1 refused'; end if;
  select public.llm_counter_take('2026-01-03', 'one', 1) into ok; if ok then raise exception 'limit 1 exceeded'; end if;
  -- malformed keys are rejected
  begin
    perform public.llm_counter_take('2026-01-01', 'Bad Key!', 1);
    raise exception 'malformed key accepted';
  exception when check_violation then null; end;
  -- usage adds up; an unpriced attempt marks the row as not fully priced
  perform public.llm_usage_add('2026-01-01', 'chat', 'gemini', 'm1', 'stream', true, 100, 20, 5, 0.0010, true);
  perform public.llm_usage_add('2026-01-01', 'chat', 'gemini', 'm1', 'stream', false, 50, 0, 0, 0.0002, true);
  perform public.llm_usage_add('2026-01-01', 'chat', 'gemini', 'm1', 'stream', true, 10, 1, 0, 0, false);
  select * into r from public.llm_usage_daily where day = '2026-01-01' and model = 'm1';
  if r.attempts <> 3 or r.ok <> 2 or r.failed <> 1 or r.input_tokens <> 160 or r.output_tokens <> 21
     or r.thinking_tokens <> 5 or r.est_cost_usd <> 0.0012 or r.priced then
    raise exception 'usage row wrong: %', row_to_json(r);
  end if;
  begin
    perform public.llm_usage_add('2026-01-01', 'other', 'gemini', 'm1', 'stream', true, 1, 1, 0, 0, true);
    raise exception 'unknown lane accepted';
  exception when check_violation then null; end;
  insert into public.app_runtime_flags (key, value) values ('ai_background_stop', 'true');
end $$;
-- browser roles see and change nothing
set local role anon;
do $$ begin
  begin perform 1 from public.llm_daily_counters; raise exception 'anon reads counters'; exception when insufficient_privilege then null; end;
  begin perform 1 from public.llm_usage_daily; raise exception 'anon reads usage'; exception when insufficient_privilege then null; end;
  begin perform public.llm_counter_take('2026-01-01', 'background', 0); raise exception 'anon takes budget'; exception when insufficient_privilege then null; end;
end $$;
reset role;
set local role authenticated;
do $$ begin
  begin perform 1 from public.app_runtime_flags; raise exception 'student reads flags'; exception when insufficient_privilege then null; end;
  begin update public.app_runtime_flags set value = 'false'; raise exception 'student clears the stop'; exception when insufficient_privilege then null; end;
  begin perform public.llm_usage_add('2026-01-01', 'chat', 'g', 'm', 'p', true, 1, 1, 0, 0, true); raise exception 'student adds usage'; exception when insufficient_privilege then null; end;
  begin perform public.llm_counter_take('2026-01-01', 'background', 0); raise exception 'student takes budget'; exception when insufficient_privilege then null; end;
end $$;
reset role;
rollback;
select 'behavior_test_llm_usage_controls: ok';
