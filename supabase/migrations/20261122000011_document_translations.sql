-- =============================================================================
-- 0011  Multilingual Knowledge Center: version-linked translations of knowledge documents.
-- ADDITIVE. The original document / version is never modified; each translation row points at the exact
-- approved original version it was made from. A new approved original version gets new translation rows; the
-- old rows are kept (is_outdated) for audit. Only human-approved, current translations are public.
-- =============================================================================

create table if not exists public.document_translations (
  id                       uuid primary key default gen_random_uuid(),
  document_id              uuid not null references public.source_documents (id) on delete cascade,
  version_id               uuid not null references public.document_versions (id) on delete cascade,
  source_version_number    integer not null,
  source_content_hash      text not null,                 -- hash of the original text it was translated from
  language_code            text not null check (language_code in ('ko', 'en', 'id', 'vi', 'zh-CN')),
  title                    text not null default '',
  headings                 jsonb not null default '[]'::jsonb,   -- translated headings, in document order
  body                     text not null default '',
  translation_status       text not null default 'todo'
                           check (translation_status in ('todo', 'machine_draft', 'draft', 'in_review',
                                                         'changes_requested', 'human_approved', 'rejected')),
  provider                 text,                          -- e.g. 'anthropic' for AI drafts, null for human-only
  model                    text,
  generated_at             timestamptz,
  human_edited             boolean not null default false,
  warnings                 jsonb not null default '[]'::jsonb,   -- automated preservation checks (dates, codes, URLs ...)
  is_outdated              boolean not null default false,
  outdated_at              timestamptz,
  previous_translation_id  uuid references public.document_translations (id) on delete set null,
  review_note              text,
  reviewed_by              uuid references public.profiles (id) on delete set null,
  reviewed_at              timestamptz,
  original_verified        boolean not null default false,
  last_edited_by           uuid references public.profiles (id) on delete set null,
  last_edited_at           timestamptz,
  submitted_at             timestamptz,
  created_at               timestamptz not null default now(),
  updated_at               timestamptz not null default now(),
  unique (version_id, language_code),
  check (translation_status = 'todo' or (length(btrim(title)) > 0 and length(btrim(body)) > 0)),
  check (translation_status <> 'human_approved' or (reviewed_by is not null and reviewed_at is not null
                                                     and original_verified))
);
create index if not exists document_translations_doc_idx on public.document_translations (document_id, language_code);
create index if not exists document_translations_status_idx
  on public.document_translations (language_code, translation_status) where not is_outdated;

create table if not exists public.document_translation_revisions (
  id                  bigint generated always as identity primary key,
  translation_id      uuid not null references public.document_translations (id) on delete cascade,
  title               text,
  headings            jsonb,
  body                text,
  translation_status  text not null,
  source_content_hash text,
  action              text not null,   -- generate | save | submit | approve | reject | request_changes | outdated
  note                text,
  provider            text,
  model               text,
  actor_id            uuid references public.profiles (id) on delete set null,
  created_at          timestamptz not null default now()
);
create index if not exists document_translation_revisions_idx on public.document_translation_revisions (translation_id, id desc);

drop trigger if exists document_translations_updated_at on public.document_translations;
create trigger document_translations_updated_at before update on public.document_translations
  for each row execute function public.set_updated_at();

-- ------------------------------------------------------------- integrity guard
-- * the version must belong to the document and be the source the hash/number describe
-- * approval: only a reviewer with 'review' permission for THIS language (or a super admin), and only for the
--   document's current approved version, and never for an outdated row
create or replace function public.guard_document_translation()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare v public.document_versions; d public.source_documents;
begin
  select * into v from public.document_versions where id = new.version_id;
  if v.document_id is distinct from new.document_id then
    raise exception 'translation version does not belong to the document' using errcode = '23514';
  end if;
  if tg_op = 'UPDATE' and (new.version_id <> old.version_id or new.document_id <> old.document_id
                           or new.language_code <> old.language_code) then
    raise exception 'a translation stays linked to its original version; create a new translation instead'
      using errcode = '23514';
  end if;
  if new.translation_status = 'human_approved'
     and (tg_op = 'INSERT' or old.translation_status <> 'human_approved' or old.reviewed_by is distinct from new.reviewed_by) then
    if new.is_outdated then
      raise exception 'outdated translations cannot be approved' using errcode = '55000';
    end if;
    select * into d from public.source_documents where id = new.document_id;
    if v.verification_status <> 'approved' or d.current_version_id is distinct from v.id then
      raise exception 'invalid_state: only translations of the current approved original can be approved'
        using errcode = '55000';
    end if;
    if not public.has_language_permission(new.reviewed_by, new.language_code, 'review') then
      raise exception 'forbidden: the reviewer is not assigned to review % translations', new.language_code
        using errcode = '42501';
    end if;
  end if;
  return new;
end;
$$;
drop trigger if exists document_translations_guard on public.document_translations;
create trigger document_translations_guard before insert or update on public.document_translations
  for each row execute function public.guard_document_translation();

-- ------------------------------------------------------- translation jobs (durable)
alter table public.ingestion_jobs drop constraint if exists ingestion_jobs_job_type_check;
alter table public.ingestion_jobs add constraint ingestion_jobs_job_type_check
  check (job_type in ('ingest', 'board_sync', 'ocr_intake', 'index_version', 'translate_document'));
alter table public.ingestion_jobs drop constraint if exists ingestion_jobs_outcome_check;
alter table public.ingestion_jobs add constraint ingestion_jobs_outcome_check
  check (outcome in ('new_version', 'unchanged', 'partial', 'extracted', 'activated', 'translated'));

-- ----------------------------------------------------------------------- RLS
alter table public.document_translations          enable row level security;
alter table public.document_translation_revisions enable row level security;
revoke all on public.document_translations, public.document_translation_revisions from anon, authenticated;

-- public: human-approved, not outdated, made from the document's CURRENT approved version of a public document
grant select on public.document_translations to anon, authenticated;
drop policy if exists document_translations_public_read on public.document_translations;
create policy document_translations_public_read on public.document_translations for select
  using (translation_status = 'human_approved' and not is_outdated
         and exists (select 1 from public.source_documents d
                       join public.document_versions v on v.id = d.current_version_id
                       join public.knowledge_sources s on s.id = d.source_id
                      where d.id = document_translations.document_id
                        and d.current_version_id = document_translations.version_id
                        and v.verification_status = 'approved'
                        and not d.is_canceled and d.archived_at is null
                        and s.is_active and s.authority_type <> 'supporter_submitted'));
-- staff with any permission for the language can read that language's drafts (never other languages)
drop policy if exists document_translations_language_staff_read on public.document_translations;
create policy document_translations_language_staff_read on public.document_translations for select to authenticated
  using (public.my_language_permission(language_code, 'any'));

grant select on public.document_translation_revisions to authenticated;
drop policy if exists document_translation_revisions_language_staff on public.document_translation_revisions;
create policy document_translation_revisions_language_staff on public.document_translation_revisions
  for select to authenticated
  using (exists (select 1 from public.document_translations t where t.id = translation_id
                  and public.my_language_permission(t.language_code, 'any')));

grant all on public.document_translations, public.document_translation_revisions to service_role;
grant usage, select on all sequences in schema public to service_role;
revoke all on function public.guard_document_translation() from public, anon, authenticated;

-- ------------------------------------------------- original-language label correction
-- Originals labelled Korean (the source default / a site-wide HTML lang attribute) whose approved text contains
-- no Hangul at all and is clearly English are relabelled 'en' - only the label changes, never the text. Audited.
with fixed as (
  update public.source_documents d
     set language = 'en'
    from public.document_versions v
   where v.id = d.current_version_id and d.language = 'ko'
     and v.extracted_text !~ '[가-힣]'
     and array_length(regexp_split_to_array(lower(v.extracted_text), '\m(the|and|of|to|for|is|are|with|your|must)\M'), 1) > 25
  returning d.id
)
insert into public.audit_log (action, entity_type, entity_id, actor_id, details)
select 'document.language_changed', 'source_document', f.id, null,
       jsonb_build_object('from', 'ko', 'to', 'en', 'reason', 'migration 0011: text contains no Korean; detected English')
  from fixed f;

-- ---------------------------------------------------------------------- backfill
-- translation tasks for documents that are already approved and public (originals untouched)
insert into public.document_translations (document_id, version_id, source_version_number, source_content_hash,
                                          language_code, translation_status)
select d.id, v.id, v.version_number, v.content_hash, l.code, 'todo'
  from public.source_documents d
  join public.document_versions v on v.id = d.current_version_id and v.verification_status = 'approved'
  join public.knowledge_sources s on s.id = d.source_id
  cross join (values ('ko'), ('en'), ('id'), ('vi'), ('zh-CN')) as l(code)
 where not d.is_canceled and d.archived_at is null and d.document_type <> 'announcement'
   and s.authority_type <> 'supporter_submitted'
   and l.code <> coalesce(d.language, 'ko')
on conflict (version_id, language_code) do nothing;
