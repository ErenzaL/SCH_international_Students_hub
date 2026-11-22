-- =============================================================================
-- 0004  Transactional review/publish functions + hybrid search RPC
-- All functions here are executable by service_role only (see 0005). The Python
-- backend verifies the caller's JWT first, then passes the verified actor id;
-- each function re-checks the actor's role inside the transaction.
-- =============================================================================

create or replace function public.assert_admin_actor(p_actor uuid)
returns void
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
  if p_actor is null or not exists (
    select 1 from public.profiles where id = p_actor and role in ('super_admin', 'admin')
  ) then
    raise exception 'forbidden: admin role required' using errcode = '42501';
  end if;
end;
$$;

-- ---------------------------------------------------------------------------
-- Recompute the human-facing status of a source from its documents' versions.
-- ---------------------------------------------------------------------------
create or replace function public.refresh_source_status(p_source_id uuid)
returns void
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_active boolean;
  v_new text;
begin
  select is_active into v_active from public.knowledge_sources where id = p_source_id;
  if not found then return; end if;

  if not v_active then
    v_new := 'inactive';
  elsif exists (
    select 1 from public.document_versions v join public.source_documents d on d.id = v.document_id
    where d.source_id = p_source_id and v.verification_status = 'pending_review'
  ) then
    v_new := 'pending_review';
  elsif exists (
    select 1 from public.source_documents d where d.source_id = p_source_id and d.current_version_id is not null
  ) then
    v_new := 'approved';
  else
    v_new := 'registered';
  end if;

  update public.knowledge_sources
     set status = v_new
   where id = p_source_id and status <> v_new
     and status not in ('fetching', 'processing');
end;
$$;

-- ---------------------------------------------------------------------------
-- approve_document_version: atomic publish. Previous current version is kept as
-- 'superseded' (never overwritten). Requires embedded chunks.
-- ---------------------------------------------------------------------------
create or replace function public.approve_document_version(p_version_id uuid, p_actor uuid, p_note text default null)
returns public.document_versions
language plpgsql
security definer
set search_path = public, extensions, pg_temp
as $$
declare
  v public.document_versions;
  d public.source_documents;
  v_missing integer;
  v_total integer;
begin
  perform public.assert_admin_actor(p_actor);

  select * into v from public.document_versions where id = p_version_id for update;
  if not found then raise exception 'version not found' using errcode = 'P0002'; end if;
  if v.verification_status <> 'pending_review' then
    raise exception 'invalid_state: only pending_review versions can be approved (is %)', v.verification_status
      using errcode = '55000';
  end if;

  select * into d from public.source_documents where id = v.document_id for update;
  if d.is_canceled then
    raise exception 'invalid_state: document is canceled' using errcode = '55000';
  end if;

  select count(*), count(*) filter (where embedding is null)
    into v_total, v_missing
    from public.document_chunks where version_id = p_version_id;
  if v_total = 0 or v_missing > 0 then
    raise exception 'not_indexed: version has % chunks, % without embeddings', v_total, v_missing
      using errcode = '55000';
  end if;

  if d.current_version_id is not null and d.current_version_id <> v.id then
    update public.document_versions
       set verification_status = 'superseded'
     where id = d.current_version_id and verification_status = 'approved';
  end if;

  update public.document_versions
     set verification_status = 'approved', was_approved = true,
         approved_by = p_actor, approved_at = now(),
         rejected_by = null, rejected_at = null, rejected_reason = null
   where id = v.id
   returning * into v;

  update public.source_documents set current_version_id = v.id where id = d.id;
  perform public.refresh_source_status(d.source_id);

  insert into public.audit_log (action, entity_type, entity_id, actor_id, details)
  values ('version.approve', 'document_version', v.id, p_actor,
          jsonb_build_object('document_id', d.id, 'version_number', v.version_number,
                             'note', p_note, 'content_hash', v.content_hash));
  return v;
end;
$$;

create or replace function public.reject_document_version(p_version_id uuid, p_actor uuid, p_reason text)
returns public.document_versions
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v public.document_versions;
  d public.source_documents;
begin
  perform public.assert_admin_actor(p_actor);
  if p_reason is null or length(btrim(p_reason)) = 0 then
    raise exception 'a rejection reason is required' using errcode = '22023';
  end if;

  select * into v from public.document_versions where id = p_version_id for update;
  if not found then raise exception 'version not found' using errcode = 'P0002'; end if;
  if v.verification_status not in ('pending_review', 'draft') then
    raise exception 'invalid_state: only draft/pending versions can be rejected (is %)', v.verification_status
      using errcode = '55000';
  end if;

  update public.document_versions
     set verification_status = 'rejected', rejected_by = p_actor, rejected_at = now(), rejected_reason = p_reason
   where id = v.id
   returning * into v;

  select * into d from public.source_documents where id = v.document_id;
  perform public.refresh_source_status(d.source_id);

  insert into public.audit_log (action, entity_type, entity_id, actor_id, details)
  values ('version.reject', 'document_version', v.id, p_actor,
          jsonb_build_object('document_id', d.id, 'version_number', v.version_number, 'reason', p_reason));
  return v;
end;
$$;

-- ---------------------------------------------------------------------------
-- rollback_document_version: re-point a document at a previously approved version
-- ---------------------------------------------------------------------------
create or replace function public.rollback_document_version(p_document_id uuid, p_version_id uuid, p_actor uuid, p_note text default null)
returns public.source_documents
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  d public.source_documents;
  v public.document_versions;
  v_prev uuid;
begin
  perform public.assert_admin_actor(p_actor);

  select * into d from public.source_documents where id = p_document_id for update;
  if not found then raise exception 'document not found' using errcode = 'P0002'; end if;
  if d.is_canceled then raise exception 'invalid_state: document is canceled' using errcode = '55000'; end if;

  select * into v from public.document_versions where id = p_version_id and document_id = p_document_id for update;
  if not found then raise exception 'version not found for document' using errcode = 'P0002'; end if;
  if not v.was_approved then
    raise exception 'invalid_state: only previously approved versions can be restored' using errcode = '55000';
  end if;
  if d.current_version_id = v.id then
    raise exception 'invalid_state: version is already current' using errcode = '55000';
  end if;
  if not exists (select 1 from public.document_chunks where version_id = v.id)
     or exists (select 1 from public.document_chunks where version_id = v.id and embedding is null) then
    raise exception 'not_indexed: restored version has no complete embeddings' using errcode = '55000';
  end if;

  v_prev := d.current_version_id;
  if v_prev is not null then
    update public.document_versions set verification_status = 'superseded' where id = v_prev;
  end if;
  update public.document_versions
     set verification_status = 'approved', approved_by = p_actor, approved_at = now()
   where id = v.id;
  update public.source_documents set current_version_id = v.id where id = d.id returning * into d;
  perform public.refresh_source_status(d.source_id);

  insert into public.audit_log (action, entity_type, entity_id, actor_id, details)
  values ('document.rollback', 'source_document', d.id, p_actor,
          jsonb_build_object('from_version', v_prev, 'to_version', v.id, 'note', p_note));
  return d;
end;
$$;

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
     set is_canceled = true, canceled_at = now(), canceled_reason = p_reason
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

-- ---------------------------------------------------------------------------
-- Announcement workflow (atomic; keeps announcement + version states in sync)
-- ---------------------------------------------------------------------------
create or replace function public.submit_announcement(p_announcement_id uuid, p_actor uuid)
returns public.announcements
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  a public.announcements;
  v_role text;
begin
  select role into v_role from public.profiles where id = p_actor;
  if v_role is null or v_role = 'student' then
    raise exception 'forbidden: staff role required' using errcode = '42501';
  end if;

  select * into a from public.announcements where id = p_announcement_id for update;
  if not found then raise exception 'announcement not found' using errcode = 'P0002'; end if;
  if v_role = 'supporter' and a.created_by is distinct from p_actor then
    raise exception 'forbidden: supporters may only submit their own announcements' using errcode = '42501';
  end if;
  if a.publication_status not in ('draft', 'rejected') then
    raise exception 'invalid_state: announcement is %', a.publication_status using errcode = '55000';
  end if;

  update public.document_versions
     set verification_status = 'pending_review'
   where document_id = a.document_id and verification_status = 'draft';
  if not found then
    raise exception 'invalid_state: no draft version to submit' using errcode = '55000';
  end if;

  update public.announcements
     set publication_status = 'pending_approval', submitted_at = now(), rejection_reason = null
   where id = a.id returning * into a;

  insert into public.audit_log (action, entity_type, entity_id, actor_id, details)
  values ('announcement.submit', 'announcement', a.id, p_actor, '{}'::jsonb);
  return a;
end;
$$;

create or replace function public.approve_announcement(p_announcement_id uuid, p_actor uuid, p_note text default null)
returns public.announcements
language plpgsql
security definer
set search_path = public, extensions, pg_temp
as $$
declare
  a public.announcements;
  v_version uuid;
begin
  perform public.assert_admin_actor(p_actor);
  select * into a from public.announcements where id = p_announcement_id for update;
  if not found then raise exception 'announcement not found' using errcode = 'P0002'; end if;
  if a.publication_status <> 'pending_approval' then
    raise exception 'invalid_state: announcement is %', a.publication_status using errcode = '55000';
  end if;

  select id into v_version from public.document_versions
   where document_id = a.document_id and verification_status = 'pending_review';
  if v_version is null then
    raise exception 'invalid_state: no pending version' using errcode = '55000';
  end if;

  perform public.approve_document_version(v_version, p_actor, p_note);

  update public.announcements
     set publication_status = 'published', approved_by = p_actor, approved_at = now()
   where id = a.id returning * into a;

  insert into public.audit_log (action, entity_type, entity_id, actor_id, details)
  values ('announcement.approve', 'announcement', a.id, p_actor, jsonb_build_object('note', p_note));
  return a;
end;
$$;

create or replace function public.reject_announcement(p_announcement_id uuid, p_actor uuid, p_reason text)
returns public.announcements
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  a public.announcements;
  v_version uuid;
begin
  perform public.assert_admin_actor(p_actor);
  if p_reason is null or length(btrim(p_reason)) = 0 then
    raise exception 'a rejection reason is required' using errcode = '22023';
  end if;
  select * into a from public.announcements where id = p_announcement_id for update;
  if not found then raise exception 'announcement not found' using errcode = 'P0002'; end if;
  if a.publication_status <> 'pending_approval' then
    raise exception 'invalid_state: announcement is %', a.publication_status using errcode = '55000';
  end if;

  select id into v_version from public.document_versions
   where document_id = a.document_id and verification_status = 'pending_review';
  if v_version is not null then
    perform public.reject_document_version(v_version, p_actor, p_reason);
  end if;

  update public.announcements
     set publication_status = 'rejected', rejection_reason = p_reason
   where id = a.id returning * into a;

  insert into public.audit_log (action, entity_type, entity_id, actor_id, details)
  values ('announcement.reject', 'announcement', a.id, p_actor, jsonb_build_object('reason', p_reason));
  return a;
end;
$$;

create or replace function public.cancel_announcement(p_announcement_id uuid, p_actor uuid, p_reason text)
returns public.announcements
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare a public.announcements;
begin
  perform public.assert_admin_actor(p_actor);
  if p_reason is null or length(btrim(p_reason)) = 0 then
    raise exception 'a reason is required' using errcode = '22023';
  end if;
  select * into a from public.announcements where id = p_announcement_id for update;
  if not found then raise exception 'announcement not found' using errcode = 'P0002'; end if;
  if a.publication_status = 'canceled' then
    raise exception 'invalid_state: already canceled' using errcode = '55000';
  end if;

  update public.source_documents
     set is_canceled = true, canceled_at = now(), canceled_reason = p_reason
   where id = a.document_id;
  update public.announcements
     set publication_status = 'canceled', canceled_at = now()
   where id = a.id returning * into a;

  insert into public.audit_log (action, entity_type, entity_id, actor_id, details)
  values ('announcement.cancel', 'announcement', a.id, p_actor, jsonb_build_object('reason', p_reason));
  return a;
end;
$$;

-- ---------------------------------------------------------------------------
-- Predicate: is this chunk's version publicly searchable right now?
-- (approved + current + not canceled + source active + within validity window)
-- ---------------------------------------------------------------------------
create or replace view public.searchable_chunks
with (security_invoker = on)
as
select c.id as chunk_id, c.version_id, c.chunk_index, c.heading, c.content, c.page_start,
       c.embedding, c.embedding_model, c.search_tsv,
       v.document_id, v.source_published_at, v.approved_at as verified_at,
       d.title as document_title, d.language as document_language, d.canonical_url,
       s.id as source_id, s.original_url, s.organization, s.authority_type, s.scope, s.category
  from public.document_chunks c
  join public.document_versions v on v.id = c.version_id
  join public.source_documents d on d.id = v.document_id and d.current_version_id = v.id
  join public.knowledge_sources s on s.id = d.source_id
 where v.verification_status = 'approved'
   and not d.is_canceled
   and s.is_active
   and (v.valid_from is null or v.valid_from <= now())
   and (v.valid_until is null or v.valid_until > now());

-- ---------------------------------------------------------------------------
-- search_knowledge: hybrid retrieval with reciprocal rank fusion (RRF, k = 60).
--   * vector leg: cosine distance via pgvector (only rows embedded by p_model)
--   * keyword leg: simple-config full-text OR-match + ILIKE for exact terms
--     (works for Korean where whitespace tokens carry particles)
-- Returns only approved, currently applicable content. Executable by
-- service_role only; the API layer is the public entry point.
-- ---------------------------------------------------------------------------
create or replace function public.search_knowledge(
  p_query_embedding extensions.vector(384),
  p_query_tokens    text[],
  p_model           text,
  p_category        text default null,
  p_match_count     integer default 5,
  p_mode            text default 'hybrid'
)
returns table (
  chunk_id uuid, document_id uuid, version_id uuid, document_title text, heading text, passage text,
  page integer, similarity double precision, keyword_rank double precision, score double precision,
  source_url text, organization text, authority_type text, scope text, category text,
  source_published_at timestamptz, verified_at timestamptz, language text
)
language plpgsql
stable
security invoker
set search_path = public, extensions, pg_temp
as $$
declare
  v_limit integer := least(greatest(coalesce(p_match_count, 5), 1), 50);
  v_pool  integer := least(greatest(coalesce(p_match_count, 5), 1), 50) * 4;
  v_tsq   tsquery;
  v_patterns text[];
begin
  if p_mode not in ('hybrid', 'vector', 'keyword') then
    raise exception 'invalid mode %', p_mode using errcode = '22023';
  end if;

  if p_query_tokens is not null and cardinality(p_query_tokens) > 0 and p_mode <> 'vector' then
    v_tsq := to_tsquery('simple', array_to_string(
      array(select '''' || replace(t, '''', '''''') || '''' from unnest(p_query_tokens) t), ' | '));
    v_patterns := array(
      select '%' || replace(replace(replace(t, '\', '\\'), '%', '\%'), '_', '\_') || '%'
        from unnest(p_query_tokens) t where length(t) >= 2);
  end if;

  return query
  with vec as (
    select sc.chunk_id as id,
           1 - (sc.embedding <=> p_query_embedding) as sim,
           row_number() over (order by sc.embedding <=> p_query_embedding) as rn
      from public.searchable_chunks sc
     where p_mode <> 'keyword' and p_query_embedding is not null
       and sc.embedding is not null and sc.embedding_model = p_model
       and (p_category is null or sc.category = p_category)
     order by sc.embedding <=> p_query_embedding
     limit v_pool
  ),
  kw as (
    select sc.chunk_id as id,
           (coalesce(ts_rank_cd(sc.search_tsv, v_tsq), 0)
            + case when v_patterns is not null and sc.content ilike any (v_patterns) then 0.1 else 0 end)::double precision as rank,
           row_number() over (
             order by coalesce(ts_rank_cd(sc.search_tsv, v_tsq), 0)
                      + case when v_patterns is not null and sc.content ilike any (v_patterns) then 0.1 else 0 end desc) as rn
      from public.searchable_chunks sc
     where p_mode <> 'vector' and v_tsq is not null
       and (sc.search_tsv @@ v_tsq or (v_patterns is not null and sc.content ilike any (v_patterns)))
       and (p_category is null or sc.category = p_category)
     order by 2 desc
     limit v_pool
  ),
  fused as (
    select coalesce(vec.id, kw.id) as id, vec.sim, kw.rank as kwr,
           coalesce(1.0 / (60 + vec.rn), 0) + coalesce(1.0 / (60 + kw.rn), 0) as rrf
      from vec full join kw on kw.id = vec.id
  )
  select sc.chunk_id, sc.document_id, sc.version_id, sc.document_title, sc.heading, sc.content,
         sc.page_start, f.sim::double precision, f.kwr::double precision, f.rrf::double precision,
         coalesce(sc.original_url, sc.canonical_url), sc.organization, sc.authority_type, sc.scope, sc.category,
         sc.source_published_at, sc.verified_at, sc.document_language
    from fused f
    join public.searchable_chunks sc on sc.chunk_id = f.id
   order by f.rrf desc, sc.chunk_id
   limit v_limit;
end;
$$;
