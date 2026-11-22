-- =============================================================================
-- 0009  Document lifecycle: reversible archive / withdraw (restore), guarded permanent delete,
--       re-import suppression. ADDITIVE: no data is removed by this migration.
--
-- Safeguards
--  * source_documents and previously approved document_versions can ONLY be deleted through
--    public.delete_document() (BEFORE DELETE triggers refuse everything else, incl. cascades
--    from knowledge_sources and the service role).
--  * delete_document(): super_admin only; refuses announcement documents (FK is ON DELETE RESTRICT),
--    published documents (withdraw or archive first), documents with running jobs, and a wrong
--    confirmation title. It writes a tombstone to the append-only audit_log (which has no FK and
--    is never deleted), then removes versions + chunks; ingestion jobs keep their history
--    (document/version references become NULL).
--  * Deleted website/board documents are added to document_suppressions so syncs never re-import them.
-- =============================================================================

alter table public.source_documents
  add column if not exists archived_at    timestamptz,
  add column if not exists archived_by    uuid references public.profiles (id) on delete set null,
  add column if not exists archive_reason text,
  add column if not exists canceled_by    uuid references public.profiles (id) on delete set null;

create table if not exists public.document_suppressions (
  id            bigint generated always as identity primary key,
  source_id     uuid not null references public.knowledge_sources (id) on delete cascade,
  canonical_url text,
  external_id   text,
  title         text,
  reason        text,
  suppressed_by uuid references public.profiles (id) on delete set null,
  created_at    timestamptz not null default now(),
  constraint suppression_has_identity check (canonical_url is not null or external_id is not null)
);
create unique index if not exists document_suppressions_url_uniq
  on public.document_suppressions (source_id, canonical_url) where canonical_url is not null;
create unique index if not exists document_suppressions_ext_uniq
  on public.document_suppressions (source_id, external_id) where external_id is not null;

-- --------------------------------------------------------------- delete guards
create or replace function public.guard_document_delete()
returns trigger
language plpgsql
as $$
begin
  if coalesce(current_setting('app.document_delete_id', true), '') <> old.id::text then
    raise exception 'documents can only be deleted with delete_document() (archive or withdraw instead)'
      using errcode = '42501';
  end if;
  return old;
end;
$$;
drop trigger if exists source_documents_delete_guard on public.source_documents;
create trigger source_documents_delete_guard
  before delete on public.source_documents
  for each row execute function public.guard_document_delete();

create or replace function public.guard_version_delete()
returns trigger
language plpgsql
as $$
begin
  if old.was_approved
     and coalesce(current_setting('app.document_delete_id', true), '') <> old.document_id::text then
    raise exception 'previously approved versions are audit records and can only be removed with delete_document()'
      using errcode = '42501';
  end if;
  return old;
end;
$$;
drop trigger if exists document_versions_delete_guard on public.document_versions;
create trigger document_versions_delete_guard
  before delete on public.document_versions
  for each row execute function public.guard_version_delete();

-- ------------------------------------------------------------ archive / restore
create or replace function public.archive_document(p_document_id uuid, p_actor uuid, p_reason text)
returns public.source_documents
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare d public.source_documents;
begin
  perform public.assert_admin_actor(p_actor);
  if p_reason is null or length(btrim(p_reason)) < 3 then
    raise exception 'a reason is required' using errcode = '22023';
  end if;
  select * into d from public.source_documents where id = p_document_id for update;
  if not found then raise exception 'document not found' using errcode = 'P0002'; end if;
  if d.archived_at is not null then raise exception 'invalid_state: already archived' using errcode = '55000'; end if;
  update public.source_documents set archived_at = now(), archived_by = p_actor, archive_reason = p_reason
   where id = d.id returning * into d;
  insert into public.audit_log (action, entity_type, entity_id, actor_id, details)
  values ('document.archive', 'source_document', d.id, p_actor, jsonb_build_object('reason', p_reason, 'title', d.title));
  return d;
end;
$$;

-- Restores an archived and/or withdrawn document (announcements stay canceled: create a new one instead).
create or replace function public.restore_document(p_document_id uuid, p_actor uuid, p_note text default null)
returns public.source_documents
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare d public.source_documents;
begin
  perform public.assert_admin_actor(p_actor);
  select * into d from public.source_documents where id = p_document_id for update;
  if not found then raise exception 'document not found' using errcode = 'P0002'; end if;
  if d.archived_at is null and not d.is_canceled then
    raise exception 'invalid_state: document is neither archived nor withdrawn' using errcode = '55000';
  end if;
  if exists (select 1 from public.announcements a where a.document_id = d.id) then
    raise exception 'invalid_state: announcement documents cannot be restored; publish a new announcement'
      using errcode = '55000';
  end if;
  update public.source_documents
     set archived_at = null, archived_by = null, archive_reason = null,
         is_canceled = false, canceled_at = null, canceled_reason = null, canceled_by = null
   where id = d.id returning * into d;
  perform public.refresh_source_status(d.source_id);
  insert into public.audit_log (action, entity_type, entity_id, actor_id, details)
  values ('document.restore', 'source_document', d.id, p_actor, jsonb_build_object('note', p_note));
  return d;
end;
$$;

-- withdraw (cancel) now also records who did it
create or replace function public.cancel_document(p_document_id uuid, p_actor uuid, p_reason text)
returns public.source_documents
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare d public.source_documents;
begin
  perform public.assert_admin_actor(p_actor);
  if p_reason is null or length(btrim(p_reason)) = 0 then
    raise exception 'a reason is required' using errcode = '22023';
  end if;
  update public.source_documents
     set is_canceled = true, canceled_at = now(), canceled_reason = p_reason, canceled_by = p_actor
   where id = p_document_id
   returning * into d;
  if not found then raise exception 'document not found' using errcode = 'P0002'; end if;
  update public.announcements
     set publication_status = 'canceled', canceled_at = now()
   where document_id = p_document_id and publication_status = 'published';
  insert into public.audit_log (action, entity_type, entity_id, actor_id, details)
  values ('document.cancel', 'source_document', d.id, p_actor, jsonb_build_object('reason', p_reason));
  return d;
end;
$$;

-- -------------------------------------------------------------- permanent delete
create or replace function public.document_delete_check(p_document_id uuid)
returns jsonb
language plpgsql
stable
security definer
set search_path = public, pg_temp
as $$
declare
  d public.source_documents;
  s public.knowledge_sources;
  v_blockers text[] := '{}';
  v_versions integer;
  v_approved integer;
  v_chunks integer;
  v_files jsonb;
begin
  select * into d from public.source_documents where id = p_document_id;
  if not found then raise exception 'document not found' using errcode = 'P0002'; end if;
  select * into s from public.knowledge_sources where id = d.source_id;
  if exists (select 1 from public.announcements a where a.document_id = d.id) then
    v_blockers := array_append(v_blockers, 'announcement: this document backs an announcement; cancel the announcement instead');
  end if;
  if d.current_version_id is not null and not d.is_canceled and d.archived_at is null then
    v_blockers := array_append(v_blockers, 'published: withdraw or archive the document first');
  end if;
  if exists (select 1 from public.ingestion_jobs j
              where j.status in ('queued', 'running')
                and (j.document_id = d.id
                     or (j.job_type = 'index_version' and (j.payload ->> 'version_id') in
                         (select v.id::text from public.document_versions v where v.document_id = d.id)))) then
    v_blockers := array_append(v_blockers, 'busy: an ingestion or indexing job for this document is queued or running');
  end if;
  select count(*), count(*) filter (where was_approved) into v_versions, v_approved
    from public.document_versions where document_id = d.id;
  select count(*) into v_chunks
    from public.document_chunks c join public.document_versions v on v.id = c.version_id where v.document_id = d.id;
  select coalesce(jsonb_agg(distinct v.original_file ->> 'storage_path') filter (where v.original_file ->> 'storage_path' is not null), '[]')
    into v_files from public.document_versions v where v.document_id = d.id;
  return jsonb_build_object(
    'eligible', cardinality(v_blockers) = 0, 'blockers', to_jsonb(v_blockers),
    'title', d.title, 'source_id', d.source_id, 'source_type', s.source_type,
    'versions', v_versions, 'approved_versions', v_approved, 'chunks', v_chunks, 'storage_files', v_files,
    'is_published', d.current_version_id is not null and not d.is_canceled and d.archived_at is null,
    'is_archived', d.archived_at is not null, 'is_withdrawn', d.is_canceled,
    'suppress_reimport', d.canonical_url is not null or d.external_id is not null);
end;
$$;

create or replace function public.delete_document(p_document_id uuid, p_actor uuid, p_reason text, p_confirm_title text)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  d public.source_documents;
  v_check jsonb;
  v_versions jsonb;
begin
  if p_actor is null or not exists (select 1 from public.profiles where id = p_actor and role = 'super_admin') then
    raise exception 'forbidden: only a super_admin can permanently delete documents' using errcode = '42501';
  end if;
  if p_reason is null or length(btrim(p_reason)) < 5 then
    raise exception 'a deletion reason (at least 5 characters) is required' using errcode = '22023';
  end if;
  select * into d from public.source_documents where id = p_document_id for update;
  if not found then raise exception 'document not found' using errcode = 'P0002'; end if;
  if btrim(coalesce(p_confirm_title, '')) <> btrim(d.title) then
    raise exception 'confirmation does not match the document title' using errcode = '22023';
  end if;
  v_check := public.document_delete_check(p_document_id);
  if not (v_check ->> 'eligible')::boolean then
    raise exception 'invalid_state: %', array_to_string(array(select jsonb_array_elements_text(v_check -> 'blockers')), '; ')
      using errcode = '55000';
  end if;

  -- tombstone: what existed, who approved it, content hashes (never the content itself)
  select coalesce(jsonb_agg(jsonb_build_object('version', version_number, 'status', verification_status,
                                               'content_hash', content_hash, 'approved_by', approved_by,
                                               'approved_at', approved_at, 'created_at', created_at)
                            order by version_number), '[]')
    into v_versions from public.document_versions where document_id = d.id;
  insert into public.audit_log (action, entity_type, entity_id, actor_id, details)
  values ('document.delete', 'source_document', d.id, p_actor,
          jsonb_build_object('reason', p_reason, 'title', d.title, 'source_id', d.source_id,
                             'canonical_url', d.canonical_url, 'external_id', d.external_id,
                             'versions', v_versions, 'chunks', v_check -> 'chunks',
                             'storage_files', v_check -> 'storage_files'));

  if d.canonical_url is not null or d.external_id is not null then
    insert into public.document_suppressions (source_id, canonical_url, external_id, title, reason, suppressed_by)
    values (d.source_id, d.canonical_url, d.external_id, d.title, p_reason, p_actor)
    on conflict do nothing;
  end if;

  perform set_config('app.document_delete_id', d.id::text, true);   -- transaction-local permission for the guards
  update public.source_documents set current_version_id = null where id = d.id;
  delete from public.source_documents where id = d.id;               -- versions + chunks cascade; jobs keep history
  perform set_config('app.document_delete_id', '', true);
  perform public.refresh_source_status(d.source_id);
  return v_check || jsonb_build_object('deleted', true);
end;
$$;

-- ------------------------------------------------ retrieval excludes archived docs
create or replace view public.searchable_chunks
with (security_invoker = on)
as
select c.id as chunk_id, c.version_id, c.chunk_index, c.heading, c.content, c.page_start,
       c.embedding, c.embedding_model, c.search_tsv,
       v.document_id, v.source_published_at, v.approved_at as verified_at,
       d.title as document_title, d.language as document_language, d.canonical_url,
       s.id as source_id, s.original_url, s.organization, s.authority_type, s.scope, s.category,
       v.valid_until, s.source_type, s.stale_after_days
  from public.document_chunks c
  join public.document_versions v on v.id = c.version_id
  join public.source_documents d on d.id = v.document_id and d.current_version_id = v.id
  join public.knowledge_sources s on s.id = d.source_id
 where v.verification_status = 'approved'
   and not d.is_canceled
   and d.archived_at is null
   and s.is_active
   and (v.valid_from is null or v.valid_from <= now())
   and (v.valid_until is null or v.valid_until > now());

-- ----------------------------------------------------------------------- grants
alter table public.document_suppressions enable row level security;
revoke all on public.document_suppressions from anon, authenticated;
grant select on public.document_suppressions to authenticated;
drop policy if exists document_suppressions_admin_read on public.document_suppressions;
create policy document_suppressions_admin_read on public.document_suppressions for select to authenticated
  using (public.is_admin());
grant all on public.document_suppressions to service_role;
grant usage, select on all sequences in schema public to service_role;

revoke all on public.searchable_chunks from anon, authenticated;
grant select on public.searchable_chunks to service_role;

revoke all on function public.archive_document(uuid, uuid, text), public.restore_document(uuid, uuid, text),
                       public.document_delete_check(uuid), public.delete_document(uuid, uuid, text, text),
                       public.cancel_document(uuid, uuid, text)
  from public, anon, authenticated;
grant execute on function public.archive_document(uuid, uuid, text), public.restore_document(uuid, uuid, text),
                          public.document_delete_check(uuid), public.delete_document(uuid, uuid, text, text),
                          public.cancel_document(uuid, uuid, text)
  to service_role;
