-- =============================================================================
-- 0003  Announcements and announcement translations
-- An announcement wraps a source_document (original-language text lives in the
-- document's versions so it goes through the same review/versioning pipeline).
-- =============================================================================

create table public.announcements (
  id                 uuid primary key default gen_random_uuid(),
  document_id        uuid not null unique references public.source_documents (id) on delete restrict,
  title              text not null check (length(btrim(title)) > 0),
  category           text not null references public.categories (slug),
  target_audience    text,
  event_date         date,
  deadline           date,
  valid_from         date,
  publication_status text not null default 'draft'
                     check (publication_status in ('draft', 'pending_approval', 'published', 'rejected', 'canceled')),
  original_language  text not null default 'ko' check (original_language in ('ko', 'en', 'id', 'vi', 'zh-CN')),
  source_type        text not null default 'manual_text' check (source_type in ('manual_text', 'kakao_message')),
  evidence_note      text,
  evidence_url       text check (evidence_url is null or evidence_url ~* '^https?://'),
  is_test_data       boolean not null default false,
  created_by         uuid references public.profiles (id) on delete set null,
  submitted_at       timestamptz,
  approved_by        uuid references public.profiles (id) on delete set null,
  approved_at        timestamptz,
  rejection_reason   text,
  canceled_at        timestamptz,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  constraint deadline_after_start check (deadline is null or valid_from is null or deadline >= valid_from)
);

create index announcements_status_idx on public.announcements (publication_status);
create index announcements_category_idx on public.announcements (category);
create index announcements_deadline_idx on public.announcements (deadline);
create index announcements_created_by_idx on public.announcements (created_by);

create trigger announcements_updated_at
  before update on public.announcements
  for each row execute function public.set_updated_at();

create table public.announcement_translations (
  id                 uuid primary key default gen_random_uuid(),
  announcement_id    uuid not null references public.announcements (id) on delete cascade,
  language_code      text not null check (language_code in ('ko', 'en', 'id', 'vi', 'zh-CN')),
  title              text not null check (length(btrim(title)) > 0),
  body               text not null check (length(btrim(body)) > 0),
  translation_status text not null default 'machine_draft'
                     check (translation_status in ('machine_draft', 'in_review', 'human_approved', 'rejected')),
  reviewed_by        uuid references public.profiles (id) on delete set null,
  reviewed_at        timestamptz,
  updated_at         timestamptz not null default now(),
  unique (announcement_id, language_code),
  -- a translation can only be called human-approved if a human review is recorded
  constraint approved_has_reviewer check (
    translation_status <> 'human_approved' or reviewed_at is not null
  )
);

create index announcement_translations_status_idx
  on public.announcement_translations (translation_status, language_code);

create trigger announcement_translations_updated_at
  before update on public.announcement_translations
  for each row execute function public.set_updated_at();
