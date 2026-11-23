-- =============================================================================
-- 0015  AI Support Office Phase 3: official-source discovery (monitoring) for the announcement and scholarship agents.
-- ADDITIVE. Discovered items are REVIEW CANDIDATES, not knowledge: nothing here is searched by RAG or shown as an
-- approved Hub source. An admin can send a candidate into the existing review pipeline (knowledge_sources +
-- ingestion job -> pending_review version), which stays the only way content becomes approved.
-- All fetching goes through the API's GuardedFetcher (domain allowlist, SSRF checks, robots.txt, size/time limits).
-- Only the service role reads or writes these tables; the API filters what students may see.
-- =============================================================================

create table if not exists public.discovery_sources (
  id                   uuid primary key default gen_random_uuid(),
  agent_id             text not null check (agent_id in ('announcement', 'scholarship', 'career', 'events')),
  name                 text not null check (length(name) between 2 and 200),
  kind                 text not null check (kind in ('sch_board', 'listing', 'page')),
  url                  text not null check (url ~ '^https?://' and length(url) <= 1000),
  config               jsonb not null default '{}'::jsonb check (length(config::text) <= 5000),
  category             text references public.categories (slug),
  language             text not null default 'ko' check (language in ('ko', 'en', 'id', 'vi', 'zh-CN')),
  enabled              boolean not null default true,      -- manual checks; scheduled checks need an enabled schedule
  last_checked_at      timestamptz,
  last_success_at      timestamptz,
  last_status          text check (last_status in ('ok', 'partial', 'failed', 'blocked')),
  last_error           text,
  consecutive_failures integer not null default 0,
  last_listing_hash    text,
  created_by           uuid references public.profiles (id) on delete set null,
  updated_by           uuid references public.profiles (id) on delete set null,
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now(),
  unique (agent_id, url)
);
drop trigger if exists discovery_sources_updated_at on public.discovery_sources;
create trigger discovery_sources_updated_at before update on public.discovery_sources
  for each row execute function public.set_updated_at();

create table if not exists public.discovered_items (
  id               uuid primary key default gen_random_uuid(),
  source_id        uuid not null references public.discovery_sources (id) on delete cascade,
  item_key         text not null unique check (length(item_key) <= 1200),   -- canonical URL (dedupe across sources)
  url              text not null check (url ~ '^https?://'),
  title            text not null check (length(title) <= 500),
  published_on     date,
  language         text,
  content_hash     text not null,
  previous_hash    text,
  text_excerpt     text check (length(text_excerpt) <= 6000),       -- untrusted external text, shown as plain text
  extracted        jsonb not null default '{}'::jsonb check (length(extracted::text) <= 20000),
  category         text,
  opportunity_kind text check (opportunity_kind in ('scholarship', 'competition', 'program', 'job')),
  open_status      text not null default 'unknown' check (open_status in ('open', 'closed', 'unknown')),
  change           text not null default 'new' check (change in ('new', 'updated', 'unchanged')),
  status           text not null default 'candidate' check (status in ('candidate', 'dismissed', 'imported')),
  duplicate_of     uuid references public.discovered_items (id) on delete set null,
  first_seen_at    timestamptz not null default now(),
  last_seen_at     timestamptz not null default now(),
  last_changed_at  timestamptz not null default now(),
  reviewed_by      uuid references public.profiles (id) on delete set null,
  reviewed_at      timestamptz,
  review_note      text check (length(review_note) <= 1000),
  imported_source_id uuid references public.knowledge_sources (id) on delete set null,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);
create index if not exists discovered_items_source_idx on public.discovered_items (source_id, last_seen_at desc);
create index if not exists discovered_items_review_idx on public.discovered_items (status, last_changed_at desc);
create index if not exists discovered_items_kind_idx on public.discovered_items (opportunity_kind, open_status)
  where status <> 'dismissed' and duplicate_of is null;
drop trigger if exists discovered_items_updated_at on public.discovered_items;
create trigger discovered_items_updated_at before update on public.discovered_items
  for each row execute function public.set_updated_at();

-- progress of a running agent task (sources checked, current source, items found) - shown live in the office
alter table public.agent_tasks add column if not exists progress jsonb not null default '{}'::jsonb;

-- ----------------------------------------------------------------------- RLS: service role only
alter table public.discovery_sources enable row level security;
alter table public.discovered_items enable row level security;
revoke all on public.discovery_sources, public.discovered_items from anon, authenticated;
grant all on public.discovery_sources, public.discovered_items to service_role;

-- the monitoring jobs (disabled; admins enable them individually, and AGENT_SCHEDULES_ENABLED must be on)
insert into public.agent_schedules (agent_id, task_type, interval_minutes, params) values
  ('announcement', 'announcement_discovery', 720,
   '{"max_items_per_source": 10, "max_sources": 5, "notify_admins": true, "summarize_new": false, "review": "admin"}'),
  ('scholarship', 'opportunity_discovery', 1440,
   '{"max_items_per_source": 10, "max_sources": 5, "notify_admins": true, "summarize_new": false, "review": "admin"}')
on conflict (agent_id, task_type) do nothing;
