-- =============================================================================
-- 0008  Language-based student support, persistent AI conversations, human handoff,
--       per-user notifications, and language-scoped translation review.
--
-- ADDITIVE ONLY: no table/column/data is dropped. Check constraints are widened and one
-- RLS write policy is tightened (supporter_languages: super_admin only).
-- Private student data (conversations, tickets) lives in its own tables and is NEVER
-- part of the shared RAG index (document_* tables).
-- =============================================================================

-- ------------------------------------------------------------------ profiles / signup
alter table public.profiles
  add column if not exists preferred_language_confirmed boolean not null default false,
  add column if not exists updated_at timestamptz not null default now();

-- The profile is created inside the same transaction as the auth.users row (no race).
-- Role is ALWAYS 'student'; the language comes from signup metadata only if it is valid.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_lang text := new.raw_user_meta_data ->> 'preferred_language';
  v_ok boolean := v_lang in ('ko', 'en', 'id', 'vi', 'zh-CN');
begin
  insert into public.profiles (id, email, display_name, role, preferred_language, preferred_language_confirmed)
  values (
    new.id,
    new.email,
    coalesce(nullif(left(btrim(new.raw_user_meta_data ->> 'display_name'), 80), ''), split_part(new.email, '@', 1)),
    'student',                                   -- never trust client metadata for roles
    case when v_ok then v_lang else 'en' end,
    coalesce(v_ok, false)
  )
  on conflict (id) do nothing;
  return new;
end;
$$;

-- --------------------------------------------------------- language team permissions
alter table public.supporter_languages
  add column if not exists can_support             boolean not null default true,
  add column if not exists can_review_translations boolean not null default false,
  add column if not exists is_team_lead            boolean not null default false,  -- language-scoped admin
  add column if not exists assigned_by             uuid references public.profiles (id) on delete set null,
  add column if not exists created_at              timestamptz not null default now();
-- Phase 1 let every assigned supporter approve translations; keep that for the rows that exist now
-- (all rows present at this point predate the migration). New assignments default to false.
update public.supporter_languages set can_review_translations = true;

-- team membership is managed by super admins only (was: any admin)
drop policy if exists supporter_languages_admin_write on public.supporter_languages;
create policy supporter_languages_admin_write on public.supporter_languages for all to authenticated
  using (public.is_super_admin()) with check (public.is_super_admin());

create table if not exists public.support_agent_status (
  supporter_id       uuid primary key references public.profiles (id) on delete cascade,
  is_available       boolean not null default true,
  max_active_tickets integer not null default 10 check (max_active_tickets between 1 and 100),
  updated_at         timestamptz not null default now()
);

-- Permission helpers. A permission only counts while the user still has a staff role, so a
-- role change revokes access on the next request without touching the assignment rows.
create or replace function public.has_language_permission(p_user uuid, p_lang text, p_perm text)
returns boolean
language sql
stable
security definer
set search_path = public, pg_temp
as $$
  select coalesce(
    (select role = 'super_admin' from public.profiles where id = p_user), false)
    or exists (
      select 1 from public.supporter_languages sl join public.profiles p on p.id = sl.supporter_id
       where sl.supporter_id = p_user and sl.language_code = p_lang
         and p.role in ('supporter', 'admin')
         and case p_perm when 'support' then sl.can_support or sl.is_team_lead
                         when 'review'  then sl.can_review_translations or sl.is_team_lead
                         when 'lead'    then sl.is_team_lead
                         when 'any'     then true
                         else false end);
$$;

-- Caller-only wrappers for RLS (no probing of other users' permissions).
create or replace function public.my_language_permission(p_lang text, p_perm text)
returns boolean language sql stable security definer set search_path = public, pg_temp
as $$ select public.has_language_permission(auth.uid(), p_lang, p_perm); $$;

-- --------------------------------------------------------------- AI conversations
create table if not exists public.ai_conversations (
  id              uuid primary key default gen_random_uuid(),
  user_id         uuid not null references public.profiles (id) on delete cascade,
  title           text not null default 'New conversation' check (length(btrim(title)) between 1 and 200),
  language        text not null check (language in ('ko', 'en', 'id', 'vi', 'zh-CN')),
  is_private      boolean not null default false,   -- private: can never be attached to a support request
  message_count   integer not null default 0,
  last_message_at timestamptz,
  last_message_preview text,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);
create index if not exists ai_conversations_user_idx on public.ai_conversations (user_id, coalesce(last_message_at, created_at) desc);

create table if not exists public.ai_messages (
  id              uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references public.ai_conversations (id) on delete cascade,
  role            text not null check (role in ('user', 'assistant')),
  content         text not null check (length(content) between 1 and 8000),
  language        text not null check (language in ('ko', 'en', 'id', 'vi', 'zh-CN')),
  citations       jsonb not null default '[]'::jsonb,   -- approved-source references only
  metadata        jsonb not null default '{}'::jsonb,   -- evidence count, handoff offer, retrieval mode
  created_at      timestamptz not null default now()
);
create index if not exists ai_messages_conv_idx on public.ai_messages (conversation_id, created_at);

-- ------------------------------------------------------------------ support tickets
create table if not exists public.support_tickets (
  id                      uuid primary key default gen_random_uuid(),
  ticket_number           bigint generated always as identity unique,
  student_id              uuid not null references public.profiles (id) on delete cascade,
  language                text not null check (language in ('ko', 'en', 'id', 'vi', 'zh-CN')),
  subject                 text not null check (length(btrim(subject)) between 3 and 200),
  summary                 text not null check (length(btrim(summary)) between 1 and 4000),
  priority                text not null default 'normal' check (priority in ('low', 'normal', 'high', 'urgent')),
  status                  text not null default 'waiting'
                          check (status in ('waiting', 'assigned', 'open', 'waiting_for_student', 'resolved')),
  assigned_to             uuid references public.profiles (id) on delete set null,
  assigned_at             timestamptz,
  accepted_at             timestamptz,
  source_conversation_id  uuid references public.ai_conversations (id) on delete set null,
  shared_context          jsonb not null default '[]'::jsonb,  -- copy of the messages the student chose to share
  consent_at              timestamptz not null,
  context_withdrawn_at    timestamptz,
  escalated               boolean not null default false,
  escalation_reason       text,
  escalated_at            timestamptz,
  last_message_at         timestamptz,
  last_student_message_at timestamptz,
  last_staff_message_at   timestamptz,
  resolved_at             timestamptz,
  satisfaction            smallint check (satisfaction between 1 and 5),
  satisfaction_comment    text check (satisfaction_comment is null or length(satisfaction_comment) <= 2000),
  created_at              timestamptz not null default now(),
  updated_at              timestamptz not null default now(),
  constraint assigned_status_has_assignee check (status not in ('assigned', 'open', 'waiting_for_student')
                                                 or assigned_to is not null),
  constraint feedback_after_resolution check (satisfaction is null or status = 'resolved')
);
create index if not exists support_tickets_queue_idx on public.support_tickets (language, status, created_at);
create index if not exists support_tickets_assignee_idx on public.support_tickets (assigned_to, status);
create index if not exists support_tickets_student_idx on public.support_tickets (student_id, created_at desc);

create table if not exists public.support_ticket_messages (
  id          uuid primary key default gen_random_uuid(),
  ticket_id   uuid not null references public.support_tickets (id) on delete cascade,
  author_id   uuid references public.profiles (id) on delete set null,
  author_role text not null check (author_role in ('student', 'supporter', 'admin', 'system')),
  kind        text not null default 'message' check (kind in ('message', 'info_request', 'status', 'system')),
  body        text not null check (length(btrim(body)) between 1 and 8000),
  created_at  timestamptz not null default now()
);
create index if not exists support_ticket_messages_idx on public.support_ticket_messages (ticket_id, created_at);

create table if not exists public.support_ticket_assignments (
  id            bigint generated always as identity primary key,
  ticket_id     uuid not null references public.support_tickets (id) on delete cascade,
  supporter_id  uuid references public.profiles (id) on delete set null,
  assigned_by   uuid references public.profiles (id) on delete set null,   -- null = automatic router
  reason        text,
  assigned_at   timestamptz not null default now(),
  ended_at      timestamptz
);
create index if not exists support_ticket_assignments_idx on public.support_ticket_assignments (ticket_id, assigned_at desc);

-- Content access: the student, the CURRENT assignee, a team lead of the ticket's language, super admins.
-- Queue visibility (subject/priority/time) is a separate, weaker check done by the API.
create or replace function public.can_view_ticket_content(p_user uuid, p_ticket uuid)
returns boolean
language sql
stable
security definer
set search_path = public, pg_temp
as $$
  select exists (
    select 1 from public.support_tickets t
     where t.id = p_ticket
       and (t.student_id = p_user
            or (t.assigned_to = p_user and exists (
                  select 1 from public.profiles p where p.id = p_user and p.role in ('supporter', 'admin', 'super_admin')))
            or public.has_language_permission(p_user, t.language, 'lead')));
$$;

-- Router: assign a waiting ticket to the least-loaded available supporter of its language.
-- Serialized per language (advisory lock) + row lock, so concurrent requests never double-assign.
create or replace function public.route_support_ticket(p_ticket_id uuid)
returns public.support_tickets
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  t public.support_tickets;
  v_sup uuid;
begin
  select * into t from public.support_tickets where id = p_ticket_id for update;
  if not found then raise exception 'ticket not found' using errcode = 'P0002'; end if;
  if t.status <> 'waiting' then return t; end if;
  perform pg_advisory_xact_lock(hashtext('support-route:' || t.language));

  select sl.supporter_id into v_sup
    from public.supporter_languages sl
    join public.profiles p on p.id = sl.supporter_id and p.role in ('supporter', 'admin')
    left join public.support_agent_status s on s.supporter_id = sl.supporter_id
   where sl.language_code = t.language and sl.can_support
     and coalesce(s.is_available, true)
     and sl.supporter_id <> t.student_id
     and (select count(*) from public.support_tickets x
           where x.assigned_to = sl.supporter_id and x.status in ('assigned', 'open', 'waiting_for_student'))
         < coalesce(s.max_active_tickets, 10)
   order by (select count(*) from public.support_tickets x
              where x.assigned_to = sl.supporter_id and x.status in ('assigned', 'open', 'waiting_for_student')),
            (select max(a.assigned_at) from public.support_ticket_assignments a where a.supporter_id = sl.supporter_id)
              nulls first,
            sl.supporter_id
   limit 1;
  if v_sup is null then
    return t;   -- stays in the waiting queue
  end if;

  update public.support_tickets
     set status = 'assigned', assigned_to = v_sup, assigned_at = now(), accepted_at = null, updated_at = now()
   where id = t.id returning * into t;
  insert into public.support_ticket_assignments (ticket_id, supporter_id, assigned_by, reason)
  values (t.id, v_sup, null, 'automatic routing');
  insert into public.audit_log (action, entity_type, entity_id, actor_id, details)
  values ('ticket.assign', 'support_ticket', t.id, null,
          jsonb_build_object('to', v_sup, 'language', t.language, 'by', 'router'));
  return t;
end;
$$;

-- Manual assignment / transfer / claim. The API checks who may do it; this enforces the
-- invariants: target must be allowed to support the language, and only one assignee at a time.
create or replace function public.assign_support_ticket(p_ticket_id uuid, p_supporter uuid, p_actor uuid,
                                                        p_reason text default null, p_expect_waiting boolean default false)
returns public.support_tickets
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  t public.support_tickets;
  v_prev uuid;
begin
  select * into t from public.support_tickets where id = p_ticket_id for update;
  if not found then raise exception 'ticket not found' using errcode = 'P0002'; end if;
  if p_expect_waiting and t.status <> 'waiting' then
    raise exception 'conflict: ticket was already taken' using errcode = '55000';
  end if;
  if t.status = 'resolved' then
    raise exception 'invalid_state: reopen the ticket before assigning it' using errcode = '55000';
  end if;
  v_prev := t.assigned_to;
  update public.support_ticket_assignments set ended_at = now()
   where ticket_id = t.id and ended_at is null;
  if p_supporter is null then   -- back to the waiting queue
    update public.support_tickets set status = 'waiting', assigned_to = null, assigned_at = null, accepted_at = null,
           updated_at = now() where id = t.id returning * into t;
  else
    if not exists (select 1 from public.supporter_languages sl join public.profiles p on p.id = sl.supporter_id
                    where sl.supporter_id = p_supporter and sl.language_code = t.language
                      and (sl.can_support or sl.is_team_lead) and p.role in ('supporter', 'admin', 'super_admin'))
       and not exists (select 1 from public.profiles where id = p_supporter and role = 'super_admin') then
      raise exception 'forbidden: target is not authorized for % support', t.language using errcode = '42501';
    end if;
    if p_supporter = t.student_id then
      raise exception 'forbidden: a ticket cannot be assigned to its own student' using errcode = '42501';
    end if;
    update public.support_tickets
       set status = 'assigned', assigned_to = p_supporter, assigned_at = now(), accepted_at = null, updated_at = now()
     where id = t.id returning * into t;
    insert into public.support_ticket_assignments (ticket_id, supporter_id, assigned_by, reason)
    values (t.id, p_supporter, p_actor, p_reason);
  end if;
  insert into public.audit_log (action, entity_type, entity_id, actor_id, details)
  values (case when v_prev is null then 'ticket.assign' else 'ticket.transfer' end, 'support_ticket', t.id, p_actor,
          jsonb_build_object('from', v_prev, 'to', p_supporter, 'reason', p_reason, 'language', t.language));
  return t;
end;
$$;

create or replace function public.can_i_view_ticket(p_ticket uuid)
returns boolean language sql stable security definer set search_path = public, pg_temp
as $$ select public.can_view_ticket_content(auth.uid(), p_ticket); $$;

-- --------------------------------------------------------------- user notifications
create table if not exists public.user_notifications (
  id          bigint generated always as identity primary key,
  user_id     uuid not null references public.profiles (id) on delete cascade,
  kind        text not null,
  title       text not null check (length(title) <= 300),
  body        text check (body is null or length(body) <= 1000),   -- never a private message body
  entity_type text,
  entity_id   uuid,
  link        text,
  read_at     timestamptz,
  created_at  timestamptz not null default now()
);
create index if not exists user_notifications_user_idx on public.user_notifications (user_id, created_at desc);

-- -------------------------------------------------------------- translation review
alter table public.announcement_translations drop constraint if exists announcement_translations_translation_status_check;
alter table public.announcement_translations add constraint announcement_translations_translation_status_check
  check (translation_status in ('todo', 'machine_draft', 'in_review', 'changes_requested', 'human_approved', 'rejected'));
alter table public.announcement_translations drop constraint if exists announcement_translations_title_check;
alter table public.announcement_translations add constraint announcement_translations_title_check
  check (translation_status = 'todo' or length(btrim(title)) > 0);
alter table public.announcement_translations drop constraint if exists announcement_translations_body_check;
alter table public.announcement_translations add constraint announcement_translations_body_check
  check (translation_status = 'todo' or length(btrim(body)) > 0);
alter table public.announcement_translations
  add column if not exists source_content_hash  text,          -- hash of the original it was translated from
  add column if not exists is_outdated          boolean not null default false,
  add column if not exists review_note          text,
  add column if not exists original_verified_by uuid references public.profiles (id) on delete set null,
  add column if not exists original_verified_at timestamptz,
  add column if not exists last_edited_by       uuid references public.profiles (id) on delete set null,
  add column if not exists last_edited_at       timestamptz,
  add column if not exists submitted_at         timestamptz,
  add column if not exists created_at           timestamptz not null default now();

create table if not exists public.translation_revisions (
  id                  bigint generated always as identity primary key,
  translation_id      uuid not null references public.announcement_translations (id) on delete cascade,
  title               text,
  body                text,
  translation_status  text not null,
  source_content_hash text,
  action              text not null,   -- save | submit | approve | reject | request_changes | outdated
  note                text,
  actor_id            uuid references public.profiles (id) on delete set null,
  created_at          timestamptz not null default now()
);
create index if not exists translation_revisions_idx on public.translation_revisions (translation_id, id desc);

-- public: only human-approved translations that are not outdated
drop policy if exists translations_public_read on public.announcement_translations;
create policy translations_public_read on public.announcement_translations for select
  using (translation_status = 'human_approved' and not is_outdated
         and exists (select 1 from public.announcements a
                      where a.id = announcement_translations.announcement_id and a.publication_status = 'published'));
-- staff with a permission for the language can read drafts of that language
drop policy if exists translations_language_staff_read on public.announcement_translations;
create policy translations_language_staff_read on public.announcement_translations for select to authenticated
  using (public.my_language_permission(language_code, 'any'));

-- ------------------------------------------------------------------- RLS + grants
alter table public.support_agent_status        enable row level security;
alter table public.ai_conversations            enable row level security;
alter table public.ai_messages                 enable row level security;
alter table public.support_tickets             enable row level security;
alter table public.support_ticket_messages     enable row level security;
alter table public.support_ticket_assignments  enable row level security;
alter table public.user_notifications          enable row level security;
alter table public.translation_revisions       enable row level security;

revoke all on public.support_agent_status, public.ai_conversations, public.ai_messages, public.support_tickets,
              public.support_ticket_messages, public.support_ticket_assignments, public.user_notifications,
              public.translation_revisions from anon, authenticated;

-- students read their own conversations (writes go through the API)
grant select on public.ai_conversations, public.ai_messages to authenticated;
drop policy if exists ai_conversations_own on public.ai_conversations;
create policy ai_conversations_own on public.ai_conversations for select to authenticated using (user_id = auth.uid());
drop policy if exists ai_messages_own on public.ai_messages;
create policy ai_messages_own on public.ai_messages for select to authenticated
  using (exists (select 1 from public.ai_conversations c where c.id = ai_messages.conversation_id and c.user_id = auth.uid()));

-- tickets / messages: content check (no language-wide access to private content)
grant select on public.support_tickets, public.support_ticket_messages to authenticated;
drop policy if exists support_tickets_content on public.support_tickets;
create policy support_tickets_content on public.support_tickets for select to authenticated
  using (public.can_i_view_ticket(id));
drop policy if exists support_ticket_messages_content on public.support_ticket_messages;
create policy support_ticket_messages_content on public.support_ticket_messages for select to authenticated
  using (public.can_i_view_ticket(ticket_id));

grant select on public.support_ticket_assignments to authenticated;
drop policy if exists support_assignments_read on public.support_ticket_assignments;
create policy support_assignments_read on public.support_ticket_assignments for select to authenticated
  using (supporter_id = auth.uid() or exists (
    select 1 from public.support_tickets t where t.id = ticket_id and public.my_language_permission(t.language, 'lead')));

grant select on public.support_agent_status to authenticated;
drop policy if exists support_agent_status_read on public.support_agent_status;
create policy support_agent_status_read on public.support_agent_status for select to authenticated
  using (supporter_id = auth.uid() or public.is_super_admin());

-- notifications: own rows only; may mark them read (Realtime uses this policy too)
grant select, update (read_at) on public.user_notifications to authenticated;
drop policy if exists user_notifications_own on public.user_notifications;
create policy user_notifications_own on public.user_notifications for select to authenticated using (user_id = auth.uid());
drop policy if exists user_notifications_mark_read on public.user_notifications;
create policy user_notifications_mark_read on public.user_notifications for update to authenticated
  using (user_id = auth.uid()) with check (user_id = auth.uid());

grant select on public.translation_revisions to authenticated;
drop policy if exists translation_revisions_language_staff on public.translation_revisions;
create policy translation_revisions_language_staff on public.translation_revisions for select to authenticated
  using (exists (select 1 from public.announcement_translations t where t.id = translation_id
                  and public.my_language_permission(t.language_code, 'any')));

grant all on public.support_agent_status, public.ai_conversations, public.ai_messages, public.support_tickets,
             public.support_ticket_messages, public.support_ticket_assignments, public.user_notifications,
             public.translation_revisions to service_role;
grant usage, select on all sequences in schema public to service_role;

revoke all on function public.has_language_permission(uuid, text, text),
                       public.can_view_ticket_content(uuid, uuid),
                       public.route_support_ticket(uuid),
                       public.assign_support_ticket(uuid, uuid, uuid, text, boolean)
  from public, anon, authenticated;
grant execute on function public.route_support_ticket(uuid),
                          public.assign_support_ticket(uuid, uuid, uuid, text, boolean),
                          public.has_language_permission(uuid, text, text),
                          public.can_view_ticket_content(uuid, uuid)
  to service_role;
-- RLS policies evaluate these as the calling role; they only ever answer for auth.uid()
revoke all on function public.my_language_permission(text, text), public.can_i_view_ticket(uuid) from public, anon;
grant execute on function public.my_language_permission(text, text), public.can_i_view_ticket(uuid)
  to authenticated, service_role;

-- Realtime: push new notifications to the owner (RLS applies to postgres_changes)
do $$
begin
  if exists (select 1 from pg_publication where pubname = 'supabase_realtime')
     and not exists (select 1 from pg_publication_tables
                      where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = 'user_notifications') then
    alter publication supabase_realtime add table public.user_notifications;
  end if;
end $$;
