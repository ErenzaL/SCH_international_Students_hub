-- =============================================================================
-- 0005  Row-level security, grants, and private storage
--
-- Model:
--   * The FastAPI backend uses the service_role key (bypasses RLS) after it has
--     verified the caller's JWT + role. Browsers only ever hold the anon key.
--   * RLS is defense in depth: even direct PostgREST access with the anon key
--     or a student token can only read approved, current, public content.
--   * KakaoTalk / supporter-private submissions are never readable publicly.
-- =============================================================================

-- Start from zero privileges for client roles, then grant narrowly.
revoke all on all tables    in schema public from anon, authenticated;
revoke all on all functions in schema public from anon, authenticated, public;
revoke all on all sequences in schema public from anon, authenticated;

-- service_role keeps full access (server-side only)
grant usage on schema public, extensions to service_role;
grant all on all tables    in schema public to service_role;
grant all on all sequences in schema public to service_role;
grant execute on all functions in schema public to service_role;

grant usage on schema public to anon, authenticated;
-- RLS policies call these helpers, so client roles need to execute them
grant execute on function public.current_app_role(), public.is_admin(),
                          public.is_super_admin(), public.is_staff() to anon, authenticated;

-- Keep future objects locked down as well
alter default privileges in schema public revoke all on tables from anon, authenticated;
alter default privileges in schema public revoke execute on functions from anon, authenticated, public;

alter table public.categories                enable row level security;
alter table public.profiles                  enable row level security;
alter table public.supporter_languages       enable row level security;
alter table public.knowledge_sources         enable row level security;
alter table public.source_documents          enable row level security;
alter table public.document_versions         enable row level security;
alter table public.document_chunks           enable row level security;
alter table public.ingestion_jobs            enable row level security;
alter table public.audit_log                 enable row level security;
alter table public.announcements             enable row level security;
alter table public.announcement_translations enable row level security;

-- ---------------------------------------------------------------- categories
grant select on public.categories to anon, authenticated;
create policy categories_public_read on public.categories for select using (true);
create policy categories_admin_write on public.categories for all to authenticated
  using (public.is_admin()) with check (public.is_admin());
grant insert, update, delete on public.categories to authenticated;

-- ------------------------------------------------------------------ profiles
grant select on public.profiles to authenticated;
grant update (display_name, preferred_language) on public.profiles to authenticated;
grant update (role) on public.profiles to authenticated;      -- additionally guarded by trigger + policy
create policy profiles_read_own_or_admin on public.profiles for select to authenticated
  using (id = auth.uid() or public.is_admin());
create policy profiles_update_own on public.profiles for update to authenticated
  using (id = auth.uid()) with check (id = auth.uid());
create policy profiles_update_by_super_admin on public.profiles for update to authenticated
  using (public.is_super_admin()) with check (public.is_super_admin());

grant select on public.supporter_languages to authenticated;
grant insert, delete on public.supporter_languages to authenticated;
create policy supporter_languages_read on public.supporter_languages for select to authenticated
  using (supporter_id = auth.uid() or public.is_admin());
create policy supporter_languages_admin_write on public.supporter_languages for all to authenticated
  using (public.is_admin()) with check (public.is_admin());

-- ---------------------------------------------------------- knowledge_sources
-- Public may see metadata of active, non-private sources (needed for citations).
grant select on public.knowledge_sources to anon, authenticated;
create policy sources_public_read on public.knowledge_sources for select
  using (is_active and source_type <> 'kakao_message' and authority_type <> 'supporter_submitted');
create policy sources_admin_all on public.knowledge_sources for all to authenticated
  using (public.is_admin()) with check (public.is_admin());
create policy sources_supporter_own on public.knowledge_sources for select to authenticated
  using (public.is_staff() and created_by = auth.uid());
grant insert, update, delete on public.knowledge_sources to authenticated;

-- ---------------------------------------------------------- source_documents
grant select on public.source_documents to anon, authenticated;
create policy documents_public_read on public.source_documents for select
  using (
    current_version_id is not null and not is_canceled
    and exists (
      select 1 from public.knowledge_sources s
      where s.id = source_documents.source_id and s.is_active
        and s.source_type <> 'kakao_message' and s.authority_type <> 'supporter_submitted'
    )
  );
create policy documents_admin_all on public.source_documents for all to authenticated
  using (public.is_admin()) with check (public.is_admin());
create policy documents_supporter_own on public.source_documents for select to authenticated
  using (public.is_staff() and exists (
    select 1 from public.knowledge_sources s where s.id = source_documents.source_id and s.created_by = auth.uid()));
grant insert, update, delete on public.source_documents to authenticated;

-- ---------------------------------------------------------- document_versions
-- Public sees ONLY the current, approved, in-window version (never partial/pending).
grant select on public.document_versions to anon, authenticated;
create policy versions_public_read on public.document_versions for select
  using (
    verification_status = 'approved'
    and (valid_from is null or valid_from <= now())
    and (valid_until is null or valid_until > now())
    and exists (
      select 1 from public.source_documents d
      join public.knowledge_sources s on s.id = d.source_id
      where d.id = document_versions.document_id
        and d.current_version_id = document_versions.id
        and not d.is_canceled and s.is_active
        and s.source_type <> 'kakao_message' and s.authority_type <> 'supporter_submitted'
    )
  );
create policy versions_admin_all on public.document_versions for all to authenticated
  using (public.is_admin()) with check (public.is_admin());
create policy versions_supporter_own on public.document_versions for select to authenticated
  using (public.is_staff() and created_by = auth.uid());
grant insert, update, delete on public.document_versions to authenticated;

-- ------------------------------------------------------------ document_chunks
-- No direct client access except admins; public retrieval goes through the API.
grant select on public.document_chunks to authenticated;
create policy chunks_admin_read on public.document_chunks for select to authenticated
  using (public.is_admin());
create policy chunks_supporter_own on public.document_chunks for select to authenticated
  using (public.is_staff() and exists (
    select 1 from public.document_versions v where v.id = document_chunks.version_id and v.created_by = auth.uid()));

-- ------------------------------------------------- jobs & audit (admin read)
grant select on public.ingestion_jobs to authenticated;
create policy jobs_admin_read on public.ingestion_jobs for select to authenticated using (public.is_admin());
grant select on public.audit_log to authenticated;
create policy audit_admin_read on public.audit_log for select to authenticated using (public.is_admin());

-- -------------------------------------------------------------- announcements
grant select on public.announcements to anon, authenticated;
-- Only admin-approved + published announcements are public. (Body text lives in
-- document_versions, which stays RLS-protected; the API serves the approved body.)
create policy announcements_public_read on public.announcements for select
  using (publication_status = 'published');
create policy announcements_admin_all on public.announcements for all to authenticated
  using (public.is_admin()) with check (public.is_admin());
create policy announcements_supporter_own on public.announcements for select to authenticated
  using (public.is_staff() and created_by = auth.uid());
create policy announcements_supporter_insert on public.announcements for insert to authenticated
  with check (public.is_staff() and created_by = auth.uid() and publication_status = 'draft');
grant insert, update, delete on public.announcements to authenticated;

grant select on public.announcement_translations to anon, authenticated;
create policy translations_public_read on public.announcement_translations for select
  using (
    translation_status = 'human_approved'
    and exists (select 1 from public.announcements a
                where a.id = announcement_translations.announcement_id and a.publication_status = 'published')
  );
create policy translations_admin_all on public.announcement_translations for all to authenticated
  using (public.is_admin()) with check (public.is_admin());
create policy translations_supporter_assigned on public.announcement_translations for select to authenticated
  using (public.is_staff() and exists (
    select 1 from public.supporter_languages sl
    where sl.supporter_id = auth.uid() and sl.language_code = announcement_translations.language_code));
grant insert, update, delete on public.announcement_translations to authenticated;

-- Server-only objects
revoke all on public.searchable_chunks from anon, authenticated;
grant select on public.searchable_chunks to service_role;

-- ------------------------------------------------------------------- storage
-- Private bucket for original PDF/DOCX uploads. No storage.objects policies are
-- created for anon/authenticated, so only the backend (service_role) can read or
-- write; downloads must use short-lived signed URLs created server-side.
insert into storage.buckets (id, name, public, file_size_limit)
values ('source-files', 'source-files', false, 20971520)
on conflict (id) do update set public = false;
