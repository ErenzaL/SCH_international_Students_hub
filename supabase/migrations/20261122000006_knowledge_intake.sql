-- =============================================================================
-- 0006  Phase 2: unified knowledge intake, SCH notice board connector, OCR intake,
--       persistent job queue, review workflow (request changes / edit / submit),
--       admin-managed domain allowlist, hybrid search v2.
--
-- ADDITIVE ONLY: no table/column is dropped, no data is deleted. Check constraints
-- are widened (drop + re-add with a superset of values). Existing rows stay valid.
-- =============================================================================

-- ------------------------------------------------------------ knowledge_sources
alter table public.knowledge_sources drop constraint knowledge_sources_source_type_check;
alter table public.knowledge_sources add constraint knowledge_sources_source_type_check
  check (source_type in ('website', 'sch_board', 'pdf', 'docx', 'text_file', 'screenshot', 'manual_text', 'kakao_message'));

-- staff_communication = an SCH staff message relayed by an authorized supporter (approved by an admin)
alter table public.knowledge_sources drop constraint knowledge_sources_authority_type_check;
alter table public.knowledge_sources add constraint knowledge_sources_authority_type_check
  check (authority_type in ('official_university', 'official_government', 'staff_communication', 'supporter_submitted', 'other'));

-- 'blocked' = the site refused automated access (robots.txt / 401 / 403 / 429); never bypassed
alter table public.knowledge_sources drop constraint knowledge_sources_status_check;
alter table public.knowledge_sources add constraint knowledge_sources_status_check
  check (status in ('registered', 'fetching', 'processing', 'pending_review', 'approved', 'failed', 'blocked', 'inactive'));

alter table public.knowledge_sources drop constraint website_requires_url;
alter table public.knowledge_sources add constraint website_requires_url
  check (source_type not in ('website', 'sch_board') or original_url is not null);

alter table public.knowledge_sources drop constraint only_websites_sync;
alter table public.knowledge_sources add constraint only_websites_sync
  check (source_type in ('website', 'sch_board') or sync_frequency = 'manual');

alter table public.knowledge_sources
  add column if not exists config            jsonb not null default '{}'::jsonb,  -- e.g. board {max_items, max_pages}
  add column if not exists stale_after_days  integer check (stale_after_days is null or stale_after_days between 1 and 3650),
  add column if not exists last_success_at   timestamptz,   -- last fetch that completed without error
  add column if not exists last_change_at    timestamptz;   -- last time a new version was created

-- one registration per exact URL for website AND board sources
drop index if exists public.knowledge_sources_url_uniq;
create unique index knowledge_sources_url_uniq
  on public.knowledge_sources (source_type, original_url)
  where source_type in ('website', 'sch_board') and original_url is not null;

-- ------------------------------------------------------------- source_documents
alter table public.source_documents drop constraint source_documents_document_type_check;
alter table public.source_documents add constraint source_documents_document_type_check
  check (document_type in ('webpage', 'notice', 'pdf', 'docx', 'text', 'screenshot', 'announcement', 'manual_text'));

-- notice id / author / attachments / listing date etc. (never secrets)
alter table public.source_documents
  add column if not exists metadata jsonb not null default '{}'::jsonb;

-- ------------------------------------------------------------ document_versions
alter table public.document_versions
  add column if not exists raw_text         text,                                  -- unmodified evidence (paste / raw OCR / raw extraction)
  add column if not exists structured_data  jsonb not null default '{}'::jsonb,    -- detected + reviewer-confirmed fields
  add column if not exists extraction_meta  jsonb not null default '{}'::jsonb,    -- extractor, warnings, OCR provider/confidence, pages
  add column if not exists original_file    jsonb,                                 -- {storage_path, filename, mime_type, size, sha256}
  add column if not exists edited_by        uuid references public.profiles (id) on delete set null,
  add column if not exists edited_at        timestamptz,
  add column if not exists review_note      text,                                  -- reviewer feedback ("request changes")
  add column if not exists submitted_at     timestamptz,
  add column if not exists indexing_status  text not null default 'not_indexed'
                                            check (indexing_status in ('not_indexed', 'indexing', 'indexed', 'failed')),
  add column if not exists indexed_at       timestamptz,
  add column if not exists indexing_error   text;

-- existing versions whose chunks are all embedded are indexed
update public.document_versions v
   set indexing_status = 'indexed', indexed_at = coalesce(v.approved_at, v.created_at)
 where exists (select 1 from public.document_chunks c where c.version_id = v.id)
   and not exists (select 1 from public.document_chunks c where c.version_id = v.id and c.embedding is null);

create index if not exists document_versions_file_sha_idx
  on public.document_versions ((original_file ->> 'sha256')) where original_file is not null;

-- Reviewed versions stay immutable; the raw evidence text is immutable once written.
create or replace function public.guard_version_immutability()
returns trigger
language plpgsql
as $$
begin
  if old.verification_status in ('approved', 'superseded', 'rejected')
     and (new.extracted_text is distinct from old.extracted_text
          or new.content_hash is distinct from old.content_hash
          or new.document_id is distinct from old.document_id
          or new.version_number is distinct from old.version_number
          or new.structured_data is distinct from old.structured_data) then
    raise exception 'version % content is immutable once reviewed', old.id using errcode = '23000';
  end if;
  if old.raw_text is not null and new.raw_text is distinct from old.raw_text then
    raise exception 'version % original evidence (raw_text) is immutable', old.id using errcode = '23000';
  end if;
  if old.original_file is not null and new.original_file is distinct from old.original_file then
    raise exception 'version % original file reference is immutable', old.id using errcode = '23000';
  end if;
  return new;
end;
$$;

-- --------------------------------------------------------------- ingestion_jobs
alter table public.ingestion_jobs drop constraint ingestion_jobs_outcome_check;
alter table public.ingestion_jobs add constraint ingestion_jobs_outcome_check
  check (outcome in ('new_version', 'unchanged', 'partial', 'extracted'));

alter table public.ingestion_jobs
  add column if not exists job_type     text not null default 'ingest'
                                        check (job_type in ('ingest', 'board_sync', 'ocr_intake')),
  add column if not exists attempts     integer not null default 0,
  add column if not exists max_attempts integer not null default 3 check (max_attempts between 1 and 10),
  add column if not exists run_after    timestamptz not null default now(),
  add column if not exists heartbeat_at timestamptz,
  add column if not exists locked_by    text;

create index if not exists ingestion_jobs_queue_idx
  on public.ingestion_jobs (run_after, created_at) where status = 'queued';

-- Step-by-step log of each job (what the admin sees under "Ingestion logs")
create table if not exists public.ingestion_events (
  id         bigint generated always as identity primary key,
  job_id     uuid not null references public.ingestion_jobs (id) on delete cascade,
  level      text not null default 'info' check (level in ('info', 'warning', 'error')),
  step       text not null,
  message    text not null,
  data       jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
create index if not exists ingestion_events_job_idx on public.ingestion_events (job_id, id);

-- Claim the next runnable job (safe across processes). Jobs left 'running' by a dead
-- worker (no heartbeat for p_stale_seconds) are re-queued until max_attempts, then failed.
create or replace function public.claim_ingestion_job(p_worker text, p_stale_seconds integer default 900)
returns setof public.ingestion_jobs
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_id uuid;
begin
  update public.ingestion_jobs
     set status        = case when attempts < max_attempts then 'queued' else 'failed' end,
         locked_by     = null,
         run_after     = now(),
         error_code    = case when attempts < max_attempts then error_code else 'interrupted' end,
         error_message = case when attempts < max_attempts then error_message
                              else 'The worker stopped while this job was running and the retry limit was reached.' end,
         completed_at  = case when attempts < max_attempts then null else now() end
   where status = 'running'
     and coalesce(heartbeat_at, started_at, created_at) < now() - make_interval(secs => greatest(p_stale_seconds, 60));

  select id into v_id
    from public.ingestion_jobs
   where status = 'queued' and run_after <= now()
   order by created_at
   limit 1
   for update skip locked;
  if v_id is null then
    return;
  end if;

  return query
  update public.ingestion_jobs
     set status = 'running', attempts = attempts + 1, started_at = now(), heartbeat_at = now(), locked_by = p_worker
   where id = v_id
  returning *;
end;
$$;

-- --------------------------------------------------- admin-managed domain allowlist
-- Merged with the ALLOWED_SOURCE_DOMAINS environment default by the backend.
create table if not exists public.allowed_source_domains (
  domain     text primary key
             check (domain ~ '^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$'),
  note       text,
  added_by   uuid references public.profiles (id) on delete set null,
  created_at timestamptz not null default now()
);

-- -------------------------------------------------------------- review workflow
-- Reviewer sends a pending version back to its submitter (status -> draft) with a note.
create or replace function public.request_version_changes(p_version_id uuid, p_actor uuid, p_note text)
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
  if p_note is null or length(btrim(p_note)) < 3 then
    raise exception 'a note explaining the requested changes is required' using errcode = '22023';
  end if;
  select * into v from public.document_versions where id = p_version_id for update;
  if not found then raise exception 'version not found' using errcode = 'P0002'; end if;
  if v.verification_status <> 'pending_review' then
    raise exception 'invalid_state: only pending_review versions can be sent back (is %)', v.verification_status
      using errcode = '55000';
  end if;
  update public.document_versions
     set verification_status = 'draft', review_note = p_note
   where id = v.id returning * into v;
  select * into d from public.source_documents where id = v.document_id;
  perform public.refresh_source_status(d.source_id);
  insert into public.audit_log (action, entity_type, entity_id, actor_id, details)
  values ('version.request_changes', 'document_version', v.id, p_actor,
          jsonb_build_object('document_id', d.id, 'version_number', v.version_number, 'note', p_note,
                             'previous_status', 'pending_review', 'new_status', 'draft'));
  return v;
end;
$$;

-- Staff submit a draft for review. Supporters may only submit versions they created.
create or replace function public.submit_version_for_review(p_version_id uuid, p_actor uuid)
returns public.document_versions
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v public.document_versions;
  d public.source_documents;
  v_role text;
begin
  select role into v_role from public.profiles where id = p_actor;
  if v_role is null or v_role = 'student' then
    raise exception 'forbidden: staff role required' using errcode = '42501';
  end if;
  select * into v from public.document_versions where id = p_version_id for update;
  if not found then raise exception 'version not found' using errcode = 'P0002'; end if;
  if v_role = 'supporter' and v.created_by is distinct from p_actor then
    raise exception 'forbidden: supporters may only submit their own submissions' using errcode = '42501';
  end if;
  if v.verification_status <> 'draft' then
    raise exception 'invalid_state: only draft versions can be submitted (is %)', v.verification_status
      using errcode = '55000';
  end if;
  update public.document_versions
     set verification_status = 'pending_review', submitted_at = now()
   where id = v.id returning * into v;
  select * into d from public.source_documents where id = v.document_id;
  perform public.refresh_source_status(d.source_id);
  insert into public.audit_log (action, entity_type, entity_id, actor_id, details)
  values ('version.submit', 'document_version', v.id, p_actor,
          jsonb_build_object('document_id', d.id, 'version_number', v.version_number,
                             'previous_status', 'draft', 'new_status', 'pending_review'));
  return v;
end;
$$;

-- Approval: unchanged semantics (atomic, requires complete embeddings) plus
--   * OCR-derived versions need explicit reviewer confirmation of key fields
--   * audit records previous/new status; indexing status is set on success
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
  v_prev uuid;
begin
  perform public.assert_admin_actor(p_actor);

  select * into v from public.document_versions where id = p_version_id for update;
  if not found then raise exception 'version not found' using errcode = 'P0002'; end if;
  if v.verification_status <> 'pending_review' then
    raise exception 'invalid_state: only pending_review versions can be approved (is %)', v.verification_status
      using errcode = '55000';
  end if;
  if coalesce((v.extraction_meta ->> 'requires_field_confirmation')::boolean, false)
     and not coalesce((v.structured_data ->> 'fields_confirmed')::boolean, false) then
    raise exception 'invalid_state: OCR-derived content needs the reviewer to confirm dates, places, fees and contacts first'
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

  v_prev := d.current_version_id;
  if v_prev is not null and v_prev <> v.id then
    update public.document_versions
       set verification_status = 'superseded'
     where id = v_prev and verification_status = 'approved';
  end if;

  update public.document_versions
     set verification_status = 'approved', was_approved = true,
         approved_by = p_actor, approved_at = now(),
         rejected_by = null, rejected_at = null, rejected_reason = null,
         indexing_status = 'indexed', indexed_at = coalesce(indexed_at, now()), indexing_error = null
   where id = v.id
   returning * into v;

  update public.source_documents set current_version_id = v.id where id = d.id;
  perform public.refresh_source_status(d.source_id);

  insert into public.audit_log (action, entity_type, entity_id, actor_id, details)
  values ('version.approve', 'document_version', v.id, p_actor,
          jsonb_build_object('document_id', d.id, 'version_number', v.version_number,
                             'note', p_note, 'content_hash', v.content_hash,
                             'previous_status', 'pending_review', 'new_status', 'approved',
                             'superseded_version', v_prev));
  return v;
end;
$$;

-- refresh_source_status: keep 'blocked' (set by the fetcher) like 'fetching'/'processing'
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

-- ------------------------------------------------------------------ search v2
-- Same visibility rules as v1 (approved + current + not canceled + active + in window),
-- with extra columns appended (create or replace view may only append).
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
   and s.is_active
   and (v.valid_from is null or v.valid_from <= now())
   and (v.valid_until is null or v.valid_until > now());

-- v2: + exact identifier terms (D-2, D-2-2, TOPIK II, ARC ...) matched on word boundaries,
--     + scope / authority filters, + small preference for official sources on ties,
--     + validity / source columns for stale warnings.
create or replace function public.search_knowledge_v2(
  p_query_embedding extensions.vector(384),
  p_query_tokens    text[],
  p_exact_terms     text[],
  p_model           text,
  p_category        text default null,
  p_scope           text default null,
  p_authority       text[] default null,
  p_match_count     integer default 5,
  p_mode            text default 'hybrid'
)
returns table (
  chunk_id uuid, document_id uuid, version_id uuid, source_id uuid, document_title text, heading text, passage text,
  page integer, similarity double precision, keyword_rank double precision, exact_match boolean, score double precision,
  source_url text, organization text, authority_type text, scope text, category text, source_type text,
  source_published_at timestamptz, verified_at timestamptz, valid_until timestamptz, stale_after_days integer,
  language text
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
  v_exact text[];
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
  -- only plain identifier characters are accepted, so the regex below cannot be injected
  if p_exact_terms is not null and p_mode <> 'vector' then
    v_exact := array(
      select '(^|[^[:alnum:]])' || t || '($|[^[:alnum:]])'
        from unnest(p_exact_terms) t where t ~ '^[A-Za-z0-9]+([ -][A-Za-z0-9]+)*$' and length(t) between 2 and 40);
    if cardinality(v_exact) = 0 then v_exact := null; end if;
  end if;

  return query
  with base as (
    select sc.* from public.searchable_chunks sc
     where (p_category is null or sc.category = p_category)
       and (p_scope is null or sc.scope = p_scope)
       and (p_authority is null or sc.authority_type = any (p_authority))
  ),
  vec as (
    select b.chunk_id as id,
           1 - (b.embedding <=> p_query_embedding) as sim,
           row_number() over (order by b.embedding <=> p_query_embedding) as rn
      from base b
     where p_mode <> 'keyword' and p_query_embedding is not null
       and b.embedding is not null and b.embedding_model = p_model
     order by b.embedding <=> p_query_embedding
     limit v_pool
  ),
  kw_raw as (
    select b.chunk_id as id,
           (coalesce(ts_rank_cd(b.search_tsv, v_tsq), 0)
            + case when v_patterns is not null and b.content ilike any (v_patterns) then 0.1 else 0 end
            + case when v_exact is not null and exists (
                     select 1 from unnest(v_exact) e where (coalesce(b.heading, '') || ' ' || b.content) ~* e)
                   then 1.0 else 0 end)::double precision as rank,
           (v_exact is not null and exists (
              select 1 from unnest(v_exact) e where (coalesce(b.heading, '') || ' ' || b.content) ~* e)) as exact
      from base b
     where p_mode <> 'vector'
       and ((v_tsq is not null and b.search_tsv @@ v_tsq)
            or (v_patterns is not null and b.content ilike any (v_patterns))
            or (v_exact is not null and exists (
                  select 1 from unnest(v_exact) e where (coalesce(b.heading, '') || ' ' || b.content) ~* e)))
  ),
  kw as (
    select k.id, k.rank, k.exact, row_number() over (order by k.rank desc, k.id) as rn
      from kw_raw k order by k.rank desc limit v_pool
  ),
  fused as (
    select coalesce(vec.id, kw.id) as id, vec.sim, kw.rank as kwr, coalesce(kw.exact, false) as ex,
           coalesce(1.0 / (60 + vec.rn), 0) + coalesce(1.0 / (60 + kw.rn), 0) as rrf
      from vec full join kw on kw.id = vec.id
  )
  select b.chunk_id, b.document_id, b.version_id, b.source_id, b.document_title, b.heading, b.content,
         b.page_start, f.sim::double precision, f.kwr::double precision, f.ex,
         (f.rrf + case when b.authority_type in ('official_government', 'official_university') then 0.001 else 0 end)
           ::double precision,
         coalesce(b.canonical_url, b.original_url), b.organization, b.authority_type, b.scope, b.category,
         b.source_type, b.source_published_at, b.verified_at, b.valid_until, b.stale_after_days, b.document_language
    from fused f
    join base b on b.chunk_id = f.id
   order by 12 desc, b.chunk_id
   limit v_limit;
end;
$$;

-- v1 keeps its signature for compatibility; it now prefers the document's own URL
-- (e.g. an individual notice) over the source's registration URL (e.g. the board list).
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
language sql
stable
security invoker
set search_path = public, extensions, pg_temp
as $$
  select r.chunk_id, r.document_id, r.version_id, r.document_title, r.heading, r.passage, r.page, r.similarity,
         r.keyword_rank, r.score, r.source_url, r.organization, r.authority_type, r.scope, r.category,
         r.source_published_at, r.verified_at, r.language
    from public.search_knowledge_v2(p_query_embedding, p_query_tokens, null, p_model, p_category, null, null,
                                    p_match_count, p_mode) r;
$$;

-- Admin overview counts in one round trip (real counts, never estimates).
create or replace function public.knowledge_stats()
returns jsonb
language sql
stable
security definer
set search_path = public, pg_temp
as $$
  select jsonb_build_object(
    'sources_total',        (select count(*) from public.knowledge_sources),
    'sources_active',       (select count(*) from public.knowledge_sources where is_active),
    'sources_failed',       (select count(*) from public.knowledge_sources where status in ('failed', 'blocked')),
    'versions_pending',     (select count(*) from public.document_versions where verification_status = 'pending_review'),
    'versions_draft',       (select count(*) from public.document_versions where verification_status = 'draft'),
    'documents_approved',   (select count(*) from public.source_documents where current_version_id is not null and not is_canceled),
    'jobs_failed',          (select count(*) from public.ingestion_jobs where status = 'failed'),
    'jobs_queued',          (select count(*) from public.ingestion_jobs where status in ('queued', 'running')),
    'searchable_chunks',    (select count(*) from public.searchable_chunks),
    'latest_success_at',    (select max(last_success_at) from public.knowledge_sources)
  );
$$;

-- ------------------------------------------------------------ RLS and grants
alter table public.ingestion_events        enable row level security;
alter table public.allowed_source_domains  enable row level security;

-- server-only by default; admins may read through PostgREST as defense-in-depth tooling
revoke all on public.ingestion_events, public.allowed_source_domains from anon, authenticated;
grant select on public.ingestion_events, public.allowed_source_domains to authenticated;
drop policy if exists ingestion_events_admin_read on public.ingestion_events;
create policy ingestion_events_admin_read on public.ingestion_events for select to authenticated
  using (public.is_admin());
drop policy if exists allowed_domains_admin_read on public.allowed_source_domains;
create policy allowed_domains_admin_read on public.allowed_source_domains for select to authenticated
  using (public.is_admin());

grant all on public.ingestion_events, public.allowed_source_domains to service_role;
grant usage, select on all sequences in schema public to service_role;

revoke all on function public.claim_ingestion_job(text, integer),
                       public.request_version_changes(uuid, uuid, text),
                       public.submit_version_for_review(uuid, uuid),
                       public.search_knowledge_v2(extensions.vector, text[], text[], text, text, text, text[], integer, text),
                       public.knowledge_stats()
  from public, anon, authenticated;
grant execute on function public.claim_ingestion_job(text, integer),
                          public.request_version_changes(uuid, uuid, text),
                          public.submit_version_for_review(uuid, uuid),
                          public.search_knowledge_v2(extensions.vector, text[], text[], text, text, text, text[], integer, text),
                          public.knowledge_stats()
  to service_role;

-- searchable_chunks was recreated: keep it server-only
revoke all on public.searchable_chunks from anon, authenticated;
grant select on public.searchable_chunks to service_role;
