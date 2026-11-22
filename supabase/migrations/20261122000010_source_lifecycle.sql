-- =============================================================================
-- 0010  Knowledge-source lifecycle: archive / restore, guarded permanent delete.
-- ADDITIVE: no data is removed by this migration. One FK is relaxed so ingestion-job
-- history survives a source deletion (source_id becomes NULL instead of the job row
-- being cascaded away).
-- =============================================================================

alter table public.knowledge_sources
  add column if not exists archived_at    timestamptz,
  add column if not exists archived_by    uuid references public.profiles (id) on delete set null,
  add column if not exists archive_reason text;

-- keep job history when a source is deleted
alter table public.ingestion_jobs alter column source_id drop not null;
-- drop whatever FK currently covers ingestion_jobs(source_id) -> knowledge_sources (whatever its name), so no
-- ON DELETE CASCADE constraint can survive next to the new one
do $$
declare c record;
begin
  for c in
    select con.conname
      from pg_constraint con
      join pg_attribute a on a.attrelid = con.conrelid and a.attnum = any (con.conkey)
     where con.conrelid = 'public.ingestion_jobs'::regclass and con.contype = 'f'
       and con.confrelid = 'public.knowledge_sources'::regclass and a.attname = 'source_id'
  loop
    execute format('alter table public.ingestion_jobs drop constraint %I', c.conname);
  end loop;
end $$;
alter table public.ingestion_jobs add constraint ingestion_jobs_source_id_fkey
  foreign key (source_id) references public.knowledge_sources (id) on delete set null;
alter table public.ingestion_jobs add column if not exists source_title text;   -- snapshot kept after deletion

-- --------------------------------------------------------------------- guard
-- A source that has documents or job history can only be deleted with delete_source().
-- (A brand-new empty source - e.g. an intake whose upload failed - may still be removed directly.)
create or replace function public.guard_source_delete()
returns trigger
language plpgsql
as $$
begin
  if coalesce(current_setting('app.source_delete_id', true), '') <> old.id::text
     and (exists (select 1 from public.source_documents d where d.source_id = old.id)
          or exists (select 1 from public.ingestion_jobs j where j.source_id = old.id)) then
    raise exception 'sources with documents or job history can only be deleted with delete_source()'
      using errcode = '42501';
  end if;
  return old;
end;
$$;
drop trigger if exists knowledge_sources_delete_guard on public.knowledge_sources;
create trigger knowledge_sources_delete_guard
  before delete on public.knowledge_sources
  for each row execute function public.guard_source_delete();

-- --------------------------------------------- files that are safe to remove
-- Storage paths referenced by the given versions/jobs that NO other version or job references.
create or replace function public.exclusive_storage_paths(p_version_ids uuid[], p_job_ids uuid[])
returns jsonb
language sql
stable
security definer
set search_path = public, pg_temp
as $$
  with mine as (
    select v.original_file ->> 'storage_path' as p from public.document_versions v
     where v.id = any (coalesce(p_version_ids, '{}')) and v.original_file ->> 'storage_path' is not null
    union
    select j.payload ->> 'storage_path' from public.ingestion_jobs j
     where j.id = any (coalesce(p_job_ids, '{}')) and j.payload ->> 'storage_path' is not null
  )
  select coalesce(jsonb_agg(m.p order by m.p), '[]'::jsonb) from mine m
   where not exists (select 1 from public.document_versions v
                      where v.original_file ->> 'storage_path' = m.p and not (v.id = any (coalesce(p_version_ids, '{}'))))
     and not exists (select 1 from public.ingestion_jobs j
                      where j.payload ->> 'storage_path' = m.p and not (j.id = any (coalesce(p_job_ids, '{}'))));
$$;

-- document deletion: only report files no other document/job uses (redefines 0009's check)
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
  v_vids uuid[];
  v_jids uuid[];
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
  select array_agg(id) into v_vids from public.document_versions where document_id = d.id;
  if exists (select 1 from public.ingestion_jobs j
              where j.status in ('queued', 'running')
                and (j.document_id = d.id
                     or (j.job_type = 'index_version' and (j.payload ->> 'version_id')::uuid = any (coalesce(v_vids, '{}'))))) then
    v_blockers := array_append(v_blockers, 'busy: an ingestion or indexing job for this document is queued or running');
  end if;
  select count(*), count(*) filter (where was_approved) into v_versions, v_approved
    from public.document_versions where document_id = d.id;
  select count(*) into v_chunks from public.document_chunks where version_id = any (coalesce(v_vids, '{}'));
  -- the document's own ingestion jobs (they reference the uploaded file too)
  select array_agg(id) into v_jids from public.ingestion_jobs
   where document_id = d.id or version_id = any (coalesce(v_vids, '{}'));
  return jsonb_build_object(
    'eligible', cardinality(v_blockers) = 0, 'blockers', to_jsonb(v_blockers),
    'title', d.title, 'source_id', d.source_id, 'source_type', s.source_type,
    'versions', v_versions, 'approved_versions', v_approved, 'chunks', v_chunks,
    'storage_files', public.exclusive_storage_paths(v_vids, v_jids),
    'is_published', d.current_version_id is not null and not d.is_canceled and d.archived_at is null,
    'is_archived', d.archived_at is not null, 'is_withdrawn', d.is_canceled,
    'suppress_reimport', d.canonical_url is not null or d.external_id is not null);
end;
$$;

-- ----------------------------------------------------------- archive / restore
create or replace function public.archive_source(p_source_id uuid, p_actor uuid, p_reason text)
returns public.knowledge_sources
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare s public.knowledge_sources; v_docs integer;
begin
  perform public.assert_admin_actor(p_actor);
  if p_reason is null or length(btrim(p_reason)) < 3 then
    raise exception 'a reason is required' using errcode = '22023';
  end if;
  select * into s from public.knowledge_sources where id = p_source_id for update;
  if not found then raise exception 'source not found' using errcode = 'P0002'; end if;
  if s.archived_at is not null then raise exception 'invalid_state: already archived' using errcode = '55000'; end if;
  update public.source_documents
     set archived_at = now(), archived_by = p_actor, archive_reason = 'Source archived: ' || p_reason
   where source_id = s.id and archived_at is null;
  get diagnostics v_docs = row_count;
  update public.knowledge_sources
     set archived_at = now(), archived_by = p_actor, archive_reason = p_reason, is_active = false, status = 'inactive'
   where id = s.id returning * into s;
  insert into public.audit_log (action, entity_type, entity_id, actor_id, details)
  values ('source.archive', 'knowledge_source', s.id, p_actor,
          jsonb_build_object('reason', p_reason, 'title', s.title, 'documents_archived', v_docs));
  return s;
end;
$$;

-- Restores the source and the documents that were archived together with it (same timestamp).
create or replace function public.restore_source(p_source_id uuid, p_actor uuid)
returns public.knowledge_sources
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare s public.knowledge_sources; v_docs integer;
begin
  perform public.assert_admin_actor(p_actor);
  select * into s from public.knowledge_sources where id = p_source_id for update;
  if not found then raise exception 'source not found' using errcode = 'P0002'; end if;
  if s.archived_at is null then raise exception 'invalid_state: source is not archived' using errcode = '55000'; end if;
  update public.source_documents
     set archived_at = null, archived_by = null, archive_reason = null
   where source_id = s.id and archived_at = s.archived_at;
  get diagnostics v_docs = row_count;
  update public.knowledge_sources
     set archived_at = null, archived_by = null, archive_reason = null, is_active = true
   where id = s.id returning * into s;
  perform public.refresh_source_status(s.id);
  insert into public.audit_log (action, entity_type, entity_id, actor_id, details)
  values ('source.restore', 'knowledge_source', s.id, p_actor, jsonb_build_object('documents_restored', v_docs));
  select * into s from public.knowledge_sources where id = s.id;
  return s;
end;
$$;

-- -------------------------------------------------------------- delete check
create or replace function public.source_delete_check(p_source_id uuid)
returns jsonb
language plpgsql
stable
security definer
set search_path = public, pg_temp
as $$
declare
  s public.knowledge_sources;
  v_blockers text[] := '{}';
  v_docs integer; v_published integer; v_ann integer; v_versions integer; v_approved integer;
  v_chunks integer; v_indexed integer; v_searchable integer; v_running integer; v_queued integer; v_jobs integer;
  v_vids uuid[]; v_jids uuid[];
begin
  select * into s from public.knowledge_sources where id = p_source_id;
  if not found then raise exception 'source not found' using errcode = 'P0002'; end if;
  select count(*), count(*) filter (where current_version_id is not null and not is_canceled and archived_at is null)
    into v_docs, v_published from public.source_documents where source_id = s.id;
  select count(*) into v_ann from public.announcements a join public.source_documents d on d.id = a.document_id
   where d.source_id = s.id;
  select array_agg(v.id), count(*), count(*) filter (where v.was_approved)
    into v_vids, v_versions, v_approved
    from public.document_versions v join public.source_documents d on d.id = v.document_id where d.source_id = s.id;
  select count(*), count(*) filter (where embedding is not null) into v_chunks, v_indexed
    from public.document_chunks where version_id = any (coalesce(v_vids, '{}'));
  select count(*) into v_searchable from public.searchable_chunks where source_id = s.id;
  select array_agg(id), count(*), count(*) filter (where status = 'running'), count(*) filter (where status = 'queued')
    into v_jids, v_jobs, v_running, v_queued from public.ingestion_jobs where source_id = s.id;
  if v_published > 0 then
    v_blockers := array_append(v_blockers, format('published: %s document(s) are live; withdraw or archive them (or archive the source) first', v_published));
  end if;
  if v_ann > 0 then
    v_blockers := array_append(v_blockers, 'announcement: this source backs announcements; cancel those announcements instead');
  end if;
  if v_running > 0 then
    v_blockers := array_append(v_blockers, 'busy: a job for this source is running; try again when it finishes');
  end if;
  return jsonb_build_object(
    'eligible', cardinality(v_blockers) = 0, 'blockers', to_jsonb(v_blockers),
    'title', s.title, 'organization', s.organization, 'source_type', s.source_type,
    'is_active', s.is_active, 'is_archived', s.archived_at is not null,
    'documents', v_docs, 'published_documents', v_published, 'versions', v_versions, 'approved_versions', v_approved,
    'chunks', v_chunks, 'indexed_chunks', v_indexed, 'searchable_chunks', v_searchable, 'is_searchable', v_searchable > 0,
    'jobs', v_jobs, 'queued_jobs', v_queued, 'running_jobs', v_running,
    'storage_files', public.exclusive_storage_paths(v_vids, v_jids),
    'requires_destructive_confirmation', v_docs > 0,
    'recommended_action', case when v_docs > 0 then 'archive' else 'delete' end);
end;
$$;

-- ------------------------------------------------------------- permanent delete
create or replace function public.delete_source(p_source_id uuid, p_actor uuid, p_reason text, p_confirm_title text,
                                                p_confirm_destructive boolean default false)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  s public.knowledge_sources;
  v_check jsonb;
  v_docs jsonb;
  v_canceled integer;
  r_doc record;
begin
  if p_actor is null or not exists (select 1 from public.profiles where id = p_actor and role = 'super_admin') then
    raise exception 'forbidden: only a super_admin can permanently delete sources' using errcode = '42501';
  end if;
  if p_reason is null or length(btrim(p_reason)) < 5 then
    raise exception 'a deletion reason (at least 5 characters) is required' using errcode = '22023';
  end if;
  select * into s from public.knowledge_sources where id = p_source_id for update;   -- serializes concurrent deletes
  if not found then raise exception 'source not found' using errcode = 'P0002'; end if;
  if btrim(coalesce(p_confirm_title, '')) <> btrim(s.title) then
    raise exception 'confirmation does not match the source title' using errcode = '22023';
  end if;
  -- lock this source's jobs so a worker cannot claim a queued one while we delete (claim uses SKIP LOCKED)
  perform 1 from public.ingestion_jobs where source_id = s.id and status in ('queued', 'running') for update;
  v_check := public.source_delete_check(p_source_id);
  if not (v_check ->> 'eligible')::boolean then
    raise exception 'invalid_state: %', array_to_string(array(select jsonb_array_elements_text(v_check -> 'blockers')), '; ')
      using errcode = '55000';
  end if;
  if (v_check ->> 'requires_destructive_confirmation')::boolean and not coalesce(p_confirm_destructive, false) then
    raise exception 'confirmation_required: this source has % document(s); confirm the destructive cleanup explicitly',
      v_check ->> 'documents' using errcode = '22023';
  end if;

  select coalesce(jsonb_agg(jsonb_build_object(
           'document_id', d.id, 'title', d.title, 'canonical_url', d.canonical_url, 'external_id', d.external_id,
           'versions', (select jsonb_agg(jsonb_build_object('version', v.version_number, 'status', v.verification_status,
                                                            'content_hash', v.content_hash, 'approved_by', v.approved_by,
                                                            'approved_at', v.approved_at) order by v.version_number)
                          from public.document_versions v where v.document_id = d.id))), '[]')
    into v_docs from public.source_documents d where d.source_id = s.id;
  insert into public.audit_log (action, entity_type, entity_id, actor_id, details)
  values ('source.delete', 'knowledge_source', s.id, p_actor,
          jsonb_build_object('reason', p_reason, 'title', s.title, 'organization', s.organization,
                             'source_type', s.source_type, 'original_url', s.original_url,
                             'documents', v_docs, 'chunks', v_check -> 'chunks', 'jobs', v_check -> 'jobs',
                             'storage_files', v_check -> 'storage_files'));

  -- stop queued work for this source (history kept; the worker skips jobs whose source is gone)
  update public.ingestion_jobs
     set status = 'failed', error_code = 'source_deleted', error_message = 'The source was deleted.',
         completed_at = now(), locked_by = null
   where source_id = s.id and status = 'queued';
  get diagnostics v_canceled = row_count;
  update public.ingestion_jobs set source_title = s.title where source_id = s.id;

  -- documents one by one through the existing guarded path (versions + chunks/embeddings cascade)
  for r_doc in select id from public.source_documents where source_id = s.id loop
    perform set_config('app.document_delete_id', r_doc.id::text, true);
    update public.source_documents set current_version_id = null where id = r_doc.id;
    delete from public.source_documents where id = r_doc.id;
  end loop;
  perform set_config('app.document_delete_id', '', true);
  perform set_config('app.source_delete_id', s.id::text, true);
  delete from public.knowledge_sources where id = s.id;   -- jobs keep their rows (source_id -> NULL)
  perform set_config('app.source_delete_id', '', true);
  return v_check || jsonb_build_object('deleted', true, 'queued_jobs_canceled', v_canceled);
end;
$$;

-- ----------------------------------------------------------------------- grants
revoke all on function public.exclusive_storage_paths(uuid[], uuid[]), public.archive_source(uuid, uuid, text),
                       public.restore_source(uuid, uuid), public.source_delete_check(uuid),
                       public.delete_source(uuid, uuid, text, text, boolean), public.document_delete_check(uuid)
  from public, anon, authenticated;
grant execute on function public.exclusive_storage_paths(uuid[], uuid[]), public.archive_source(uuid, uuid, text),
                          public.restore_source(uuid, uuid), public.source_delete_check(uuid),
                          public.delete_source(uuid, uuid, text, text, boolean), public.document_delete_check(uuid)
  to service_role;
