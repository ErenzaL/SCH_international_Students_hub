-- =============================================================================
-- 0007  Automatic RAG synchronization
--   approval -> durable index_version job -> chunk -> embed -> validate -> atomic activation
--   + atomic chunk replacement, admin notifications.
-- ADDITIVE ONLY: no data is dropped. Check constraints are widened.
-- =============================================================================

-- --------------------------------------------------------- versions: approval request
alter table public.document_versions
  add column if not exists activation_requested_by uuid references public.profiles (id) on delete set null,
  add column if not exists activation_requested_at timestamptz,
  add column if not exists activation_note         text;

alter table public.document_versions drop constraint if exists document_versions_indexing_status_check;
alter table public.document_versions add constraint document_versions_indexing_status_check
  check (indexing_status in ('not_indexed', 'queued', 'indexing', 'indexed', 'failed'));

-- --------------------------------------------------------------- jobs: index_version
alter table public.ingestion_jobs drop constraint if exists ingestion_jobs_job_type_check;
alter table public.ingestion_jobs add constraint ingestion_jobs_job_type_check
  check (job_type in ('ingest', 'board_sync', 'ocr_intake', 'index_version'));
alter table public.ingestion_jobs drop constraint ingestion_jobs_outcome_check;
alter table public.ingestion_jobs add constraint ingestion_jobs_outcome_check
  check (outcome in ('new_version', 'unchanged', 'partial', 'extracted', 'activated'));

-- at most one open indexing job per version (prevents concurrent duplicate processing)
create unique index if not exists ingestion_jobs_open_index_uniq
  on public.ingestion_jobs ((payload ->> 'version_id'))
  where job_type = 'index_version' and status in ('queued', 'running');

-- ---------------------------------------------------- atomic chunk replacement
-- Replaces ALL chunks of a version in one transaction: a failed insert rolls back and the
-- previous chunks stay intact (no partial sets, no duplicates on retry).
create or replace function public.replace_version_chunks(p_version_id uuid, p_chunks jsonb)
returns integer
language plpgsql
security definer
set search_path = public, extensions, pg_temp
as $$
declare
  v_count integer;
begin
  if not exists (select 1 from public.document_versions where id = p_version_id) then
    raise exception 'version not found' using errcode = 'P0002';
  end if;
  if jsonb_typeof(p_chunks) <> 'array' then
    raise exception 'p_chunks must be a JSON array' using errcode = '22023';
  end if;
  delete from public.document_chunks where version_id = p_version_id;
  insert into public.document_chunks (version_id, chunk_index, heading, content, content_hash, token_count,
                                      page_start, page_end, chunk_strategy, embedding, embedding_model)
  select p_version_id, (c ->> 'chunk_index')::integer, c ->> 'heading', c ->> 'content', c ->> 'content_hash',
         (c ->> 'token_count')::integer, (c ->> 'page_start')::integer, (c ->> 'page_end')::integer,
         coalesce(c ->> 'chunk_strategy', 'v1'),
         case when jsonb_typeof(c -> 'embedding') = 'array' then (c ->> 'embedding')::extensions.vector(384) end,
         case when jsonb_typeof(c -> 'embedding') = 'array' then c ->> 'embedding_model' end
    from jsonb_array_elements(p_chunks) c;
  get diagnostics v_count = row_count;
  return v_count;
end;
$$;

-- ------------------------------------------------------- validated activation
-- Called by the indexing worker after embedding. Validates the complete index inside the same
-- transaction as the switch: expected chunk count, every chunk embedded by p_model, 384 dims.
create or replace function public.activate_document_version(
  p_version_id uuid, p_actor uuid, p_note text, p_expected_chunks integer, p_model text)
returns public.document_versions
language plpgsql
security definer
set search_path = public, extensions, pg_temp
as $$
declare
  v public.document_versions;
  v_total integer;
  v_ok integer;
begin
  select count(*),
         count(*) filter (where embedding is not null and embedding_model = p_model
                            and extensions.vector_dims(embedding) = 384)
    into v_total, v_ok
    from public.document_chunks where version_id = p_version_id;
  if p_expected_chunks is null or v_total <> p_expected_chunks or v_ok <> v_total or v_total = 0 then
    raise exception 'not_indexed: expected % chunks, found %, % valid embeddings with %',
      p_expected_chunks, v_total, v_ok, p_model using errcode = '55000';
  end if;
  v := public.approve_document_version(p_version_id, p_actor, p_note);  -- atomic switch + supersede + audit
  insert into public.audit_log (action, entity_type, entity_id, actor_id, details)
  values ('version.activate', 'document_version', v.id, p_actor,
          jsonb_build_object('document_id', v.document_id, 'version_number', v.version_number,
                             'chunks', v_total, 'embedding_model', p_model,
                             'requested_at', v.activation_requested_at));
  return v;
end;
$$;

-- ------------------------------------------------------------- notifications
create table if not exists public.admin_notifications (
  id          bigint generated always as identity primary key,
  kind        text not null,      -- review_needed | sync_failed | source_blocked | indexing_failed | version_activated | withdrawn | submission
  severity    text not null default 'info' check (severity in ('info', 'warning', 'error')),
  title       text not null,
  message     text,
  entity_type text,
  entity_id   uuid,
  link        text,               -- admin path, e.g. /admin/documents/<id>
  created_at  timestamptz not null default now()
);
create index if not exists admin_notifications_created_idx on public.admin_notifications (created_at desc);

create table if not exists public.notification_reads (
  user_id      uuid primary key references public.profiles (id) on delete cascade,
  last_read_at timestamptz not null default now()
);

alter table public.admin_notifications enable row level security;
alter table public.notification_reads  enable row level security;
revoke all on public.admin_notifications, public.notification_reads from anon, authenticated;
grant select on public.admin_notifications to authenticated;
drop policy if exists admin_notifications_admin_read on public.admin_notifications;
create policy admin_notifications_admin_read on public.admin_notifications for select to authenticated
  using (public.is_admin());
grant all on public.admin_notifications, public.notification_reads to service_role;
grant usage, select on all sequences in schema public to service_role;

revoke all on function public.replace_version_chunks(uuid, jsonb),
                       public.activate_document_version(uuid, uuid, text, integer, text)
  from public, anon, authenticated;
grant execute on function public.replace_version_chunks(uuid, jsonb),
                          public.activate_document_version(uuid, uuid, text, integer, text)
  to service_role;
