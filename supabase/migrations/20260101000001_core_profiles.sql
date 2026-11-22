-- =============================================================================
-- 0001  Extensions, categories, profiles, roles, helper functions
-- SCH International Student Hub
-- =============================================================================

create schema if not exists extensions;
create extension if not exists vector  with schema extensions;   -- pgvector
create extension if not exists pg_trgm with schema extensions;   -- fast ILIKE for exact-term search

-- ---------------------------------------------------------------------------
-- Generic helpers
-- ---------------------------------------------------------------------------
create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

-- ---------------------------------------------------------------------------
-- categories (reference data; slugs are stable identifiers used by the API)
-- ---------------------------------------------------------------------------
create table public.categories (
  slug        text primary key check (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
  name        text not null,
  description text,
  sort_order  integer not null default 0
);

-- ---------------------------------------------------------------------------
-- profiles (1:1 with auth.users). Role defaults to 'student'; nobody becomes an
-- admin automatically. See docs/setup.md for the manual super_admin bootstrap.
-- ---------------------------------------------------------------------------
create table public.profiles (
  id                 uuid primary key references auth.users (id) on delete cascade,
  email              text,
  display_name       text,
  preferred_language text not null default 'en'
                     check (preferred_language in ('ko', 'en', 'id', 'vi', 'zh-CN')),
  role               text not null default 'student'
                     check (role in ('super_admin', 'admin', 'supporter', 'student')),
  created_at         timestamptz not null default now()
);

create index profiles_role_idx on public.profiles (role);

create table public.supporter_languages (
  supporter_id  uuid not null references public.profiles (id) on delete cascade,
  language_code text not null check (language_code in ('ko', 'en', 'id', 'vi', 'zh-CN')),
  primary key (supporter_id, language_code)
);

-- ---------------------------------------------------------------------------
-- Role helpers (SECURITY DEFINER so RLS policies can use them without recursion)
-- ---------------------------------------------------------------------------
create or replace function public.current_app_role()
returns text
language sql
stable
security definer
set search_path = public, pg_temp
as $$
  select p.role from public.profiles p where p.id = auth.uid();
$$;

create or replace function public.is_super_admin()
returns boolean
language sql stable security definer set search_path = public, pg_temp
as $$ select coalesce(public.current_app_role() = 'super_admin', false); $$;

create or replace function public.is_admin()
returns boolean
language sql stable security definer set search_path = public, pg_temp
as $$ select coalesce(public.current_app_role() in ('super_admin', 'admin'), false); $$;

create or replace function public.is_staff()
returns boolean
language sql stable security definer set search_path = public, pg_temp
as $$ select coalesce(public.current_app_role() in ('super_admin', 'admin', 'supporter'), false); $$;

-- ---------------------------------------------------------------------------
-- New auth user -> profile. The role is ALWAYS 'student'; user metadata is never
-- trusted for role assignment.
-- ---------------------------------------------------------------------------
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
  insert into public.profiles (id, email, display_name, role)
  values (
    new.id,
    new.email,
    coalesce(nullif(new.raw_user_meta_data ->> 'display_name', ''), split_part(new.email, '@', 1)),
    'student'
  )
  on conflict (id) do nothing;
  return new;
end;
$$;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- ---------------------------------------------------------------------------
-- Privilege-escalation guard: a signed-in end user (auth.uid() is not null) can
-- never change a role unless they are super_admin. Direct SQL (SQL editor /
-- service role, where auth.uid() is null) may bootstrap roles.
-- ---------------------------------------------------------------------------
create or replace function public.guard_profile_changes()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
  if new.role is distinct from old.role
     and auth.uid() is not null
     and not public.is_super_admin() then
    raise exception 'only a super_admin may change roles' using errcode = '42501';
  end if;
  if new.id is distinct from old.id then
    raise exception 'profile id is immutable' using errcode = '42501';
  end if;
  return new;
end;
$$;

create trigger profiles_guard
  before update on public.profiles
  for each row execute function public.guard_profile_changes();
