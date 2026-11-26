-- =============================================================================
-- 0018  AI usage controls. ADDITIVE; nothing is enabled and nothing is deleted.
--   * llm_daily_counters: the daily AI budgets (background attempts, generated chat answers) survive restarts
--     and are shared by every API process; llm_counter_take() consumes one unit atomically or refuses;
--   * llm_usage_daily: per day, provider, model, purpose and lane (chat | background): attempts, outcomes, token
--     counts reported by the provider and an ESTIMATED cost (only when the owner configured prices);
--   * app_runtime_flags: switches an admin can flip without a redeploy (ai_background_stop).
-- No prompts, answers, student messages or personal data are stored here. Service role only.
-- The application works without this migration (budgets then stay in-process, as before).
-- =============================================================================

create table if not exists public.llm_daily_counters (
  day        date not null,
  key        text not null check (key ~ '^[a-z][a-z0-9_:.-]{0,79}$'),
  used       integer not null default 0 check (used >= 0),
  updated_at timestamptz not null default now(),
  primary key (day, key)
);
alter table public.llm_daily_counters enable row level security;    -- no policies: browser roles see nothing
revoke all on public.llm_daily_counters from public, anon, authenticated;
grant all on public.llm_daily_counters to service_role;

create table if not exists public.llm_usage_daily (
  day             date not null,
  lane            text not null check (lane in ('chat', 'background')),
  provider        text not null check (length(provider) between 1 and 40),
  model           text not null check (length(model) between 1 and 120),
  purpose         text not null check (length(purpose) between 1 and 60),
  attempts        integer not null default 0 check (attempts >= 0),
  ok              integer not null default 0 check (ok >= 0),
  failed          integer not null default 0 check (failed >= 0),
  input_tokens    bigint not null default 0 check (input_tokens >= 0),
  output_tokens   bigint not null default 0 check (output_tokens >= 0),
  thinking_tokens bigint not null default 0 check (thinking_tokens >= 0),
  est_cost_usd    numeric(14, 6) not null default 0 check (est_cost_usd >= 0),
  priced          boolean not null default true,          -- false once an attempt of an unpriced model was added
  updated_at      timestamptz not null default now(),
  primary key (day, lane, provider, model, purpose)
);
alter table public.llm_usage_daily enable row level security;
revoke all on public.llm_usage_daily from public, anon, authenticated;
grant all on public.llm_usage_daily to service_role;

create table if not exists public.app_runtime_flags (
  key        text primary key check (key ~ '^[a-z][a-z0-9_]{1,60}$'),
  value      jsonb not null,
  updated_by uuid references public.profiles (id) on delete set null,
  updated_at timestamptz not null default now()
);
drop trigger if exists app_runtime_flags_updated_at on public.app_runtime_flags;
create trigger app_runtime_flags_updated_at before update on public.app_runtime_flags
  for each row execute function public.set_updated_at();
alter table public.app_runtime_flags enable row level security;
revoke all on public.app_runtime_flags from public, anon, authenticated;
grant all on public.app_runtime_flags to service_role;

-- one unit of a daily budget; false (nothing consumed) when the key already reached p_limit. p_limit <= 0 = no limit.
create or replace function public.llm_counter_take(p_day date, p_key text, p_limit integer)
returns boolean
language plpgsql
set search_path = public
as $$
declare took boolean;
begin
  insert into public.llm_daily_counters as c (day, key, used) values (p_day, p_key, 1)
  on conflict (day, key) do update set used = c.used + 1, updated_at = now()
    where p_limit <= 0 or c.used < p_limit
  returning true into took;
  return coalesce(took, false);
end;
$$;
revoke all on function public.llm_counter_take(date, text, integer) from public, anon, authenticated;
grant execute on function public.llm_counter_take(date, text, integer) to service_role;

create or replace function public.llm_usage_add(p_day date, p_lane text, p_provider text, p_model text, p_purpose text,
                                                p_ok boolean, p_input bigint, p_output bigint, p_thinking bigint,
                                                p_cost numeric, p_priced boolean)
returns void
language sql
set search_path = public
as $$
  insert into public.llm_usage_daily as u (day, lane, provider, model, purpose, attempts, ok, failed, input_tokens,
                                           output_tokens, thinking_tokens, est_cost_usd, priced)
  values (p_day, p_lane, p_provider, p_model, p_purpose, 1, case when p_ok then 1 else 0 end,
          case when p_ok then 0 else 1 end, greatest(coalesce(p_input, 0), 0), greatest(coalesce(p_output, 0), 0),
          greatest(coalesce(p_thinking, 0), 0), greatest(coalesce(p_cost, 0), 0), coalesce(p_priced, false))
  on conflict (day, lane, provider, model, purpose) do update set
    attempts = u.attempts + 1,
    ok = u.ok + excluded.ok,
    failed = u.failed + excluded.failed,
    input_tokens = u.input_tokens + excluded.input_tokens,
    output_tokens = u.output_tokens + excluded.output_tokens,
    thinking_tokens = u.thinking_tokens + excluded.thinking_tokens,
    est_cost_usd = u.est_cost_usd + excluded.est_cost_usd,
    priced = u.priced and excluded.priced,
    updated_at = now();
$$;
revoke all on function public.llm_usage_add(date, text, text, text, text, boolean, bigint, bigint, bigint, numeric, boolean)
  from public, anon, authenticated;
grant execute on function public.llm_usage_add(date, text, text, text, text, boolean, bigint, bigint, bigint, numeric, boolean)
  to service_role;
