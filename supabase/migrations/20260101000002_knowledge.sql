-- =============================================================================
-- 0002  Knowledge sources, documents, versions, chunks, ingestion jobs, audit
-- =============================================================================

-- ---------------------------------------------------------------------------
-- knowledge_sources: a registered origin of content (website, upload, manual)
-- ---------------------------------------------------------------------------
create table public.knowledge_sources (
  id                    uuid primary key default gen_random_uuid(),
  title                 text not null check (length(btrim(title)) > 0),
  original_url          text,
  organization          text not null check (length(btrim(organization)) > 0),
  source_type           text not null
                        check (source_type in ('website', 'pdf', 'docx', 'manual_text', 'kakao_message')),
  authority_type        text not null
                        check (authority_type in ('official_university', 'official_government', 'supporter_submitted', 'other')),
  scope                 text not null check (scope in ('university', 'national')),
  category              text not null references public.categories (slug),
  language              text not null default 'ko' check (language in ('ko', 'en', 'id', 'vi', 'zh-CN')),
  sync_frequency        text not null default 'manual' check (sync_frequency in ('manual', 'daily', 'weekly')),
  is_active             boolean not null default true,
  status                text not null default 'registered'
                        check (status in ('registered', 'fetching', 'processing', 'pending_review', 'approved', 'failed', 'inactive')),
  is_test_data          boolean not null default false,
  last_ingestion_result jsonb,
  created_by            uuid references public.profiles (id) on delete set null,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now(),
  last_checked_at       timestamptz,
  constraint website_requires_url check (source_type <> 'website' or original_url is not null),
  constraint only_websites_sync check (source_type = 'website' or sync_frequency = 'manual'),
  constraint url_is_http check (original_url is null or original_url ~* '^https?://')
);

-- the exact registered URL is the dedup key for website sources
create unique index knowledge_sources_url_uniq
  on public.knowledge_sources (original_url)
  where source_type = 'website' and original_url is not null;
create index knowledge_sources_status_idx on public.knowledge_sources (status);
create index knowledge_sources_category_idx on public.knowledge_sources (category);
create index knowledge_sources_created_by_idx on public.knowledge_sources (created_by);

create trigger knowledge_sources_updated_at
  before update on public.knowledge_sources
  for each row execute function public.set_updated_at();

-- ---------------------------------------------------------------------------
-- source_documents: one logical document inside a source (stable identity)
-- ---------------------------------------------------------------------------
create table public.source_documents (
  id                 uuid primary key default gen_random_uuid(),
  source_id          uuid not null references public.knowledge_sources (id) on delete cascade,
  canonical_url      text,
  external_id        text,
  title              text not null,
  language           text not null default 'ko' check (language in ('ko', 'en', 'id', 'vi', 'zh-CN')),
  document_type      text not null default 'webpage'
                     check (document_type in ('webpage', 'pdf', 'docx', 'announcement', 'manual_text')),
  current_version_id uuid,  -- FK added below (circular); always an APPROVED version
  is_canceled        boolean not null default false,
  canceled_at        timestamptz,
  canceled_reason    text,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  constraint document_has_identity check (canonical_url is not null or external_id is not null)
);

-- stable identifiers prevent duplicate documents inside a source
create unique index source_documents_url_uniq
  on public.source_documents (source_id, canonical_url) where canonical_url is not null;
create unique index source_documents_ext_uniq
  on public.source_documents (source_id, external_id) where external_id is not null;
create index source_documents_source_idx on public.source_documents (source_id);

create trigger source_documents_updated_at
  before update on public.source_documents
  for each row execute function public.set_updated_at();

-- ---------------------------------------------------------------------------
-- document_versions: immutable extracted content snapshots
-- ---------------------------------------------------------------------------
create table public.document_versions (
  id                  uuid primary key default gen_random_uuid(),
  document_id         uuid not null references public.source_documents (id) on delete cascade,
  version_number      integer not null check (version_number > 0),
  extracted_text      text not null check (length(btrim(extracted_text)) > 0),
  content_hash        text not null check (content_hash ~ '^[0-9a-f]{64}$'),
  -- source timestamps (what the publisher says) are separate from ingestion timestamps
  source_published_at timestamptz,
  fetched_at          timestamptz not null default now(),
  valid_from          timestamptz,
  valid_until         timestamptz,
  verification_status text not null default 'pending_review'
                      check (verification_status in ('draft', 'pending_review', 'approved', 'rejected', 'superseded')),
  was_approved        boolean not null default false,   -- ever approved => eligible for rollback
  approved_by         uuid references public.profiles (id) on delete set null,
  approved_at         timestamptz,
  rejected_by         uuid references public.profiles (id) on delete set null,
  rejected_at         timestamptz,
  rejected_reason     text,
  created_by          uuid references public.profiles (id) on delete set null,
  created_at          timestamptz not null default now(),
  unique (document_id, version_number),
  unique (document_id, content_hash),
  constraint valid_window check (valid_until is null or valid_from is null or valid_until > valid_from),
  constraint approved_has_approval check (verification_status <> 'approved' or (approved_at is not null and was_approved))
);

-- at most one in-flight (draft / pending) version per document
create unique index document_versions_one_open_uniq
  on public.document_versions (document_id)
  where verification_status in ('draft', 'pending_review');
create index document_versions_status_idx on public.document_versions (verification_status);

alter table public.source_documents
  add constraint source_documents_current_version_fk
  foreign key (current_version_id) references public.document_versions (id) on delete set null;

-- Extracted text of a version is never rewritten once it has left review.
create or replace function public.guard_version_immutability()
returns trigger
language plpgsql
as $$
begin
  if old.verification_status in ('approved', 'superseded', 'rejected')
     and (new.extracted_text is distinct from old.extracted_text
          or new.content_hash is distinct from old.content_hash
          or new.document_id is distinct from old.document_id
          or new.version_number is distinct from old.version_number) then
    raise exception 'version % content is immutable once reviewed', old.id using errcode = '23000';
  end if;
  return new;
end;
$$;

create trigger document_versions_immutable
  before update on public.document_versions
  for each row execute function public.guard_version_immutability();

-- documents.current_version_id must point at an approved version of THAT document.
create or replace function public.guard_current_version()
returns trigger
language plpgsql
as $$
begin
  if new.current_version_id is not null
     and new.current_version_id is distinct from old.current_version_id then
    if not exists (
      select 1 from public.document_versions v
      where v.id = new.current_version_id
        and v.document_id = new.id
        and v.verification_status = 'approved'
    ) then
      raise exception 'current_version_id must reference an approved version of the same document'
        using errcode = '23514';
    end if;
  end if;
  return new;
end;
$$;

create trigger source_documents_current_guard
  before update on public.source_documents
  for each row execute function public.guard_current_version();

-- ---------------------------------------------------------------------------
-- document_chunks: retrieval units with pgvector embeddings (384-d, E5-small)
-- ---------------------------------------------------------------------------
create table public.document_chunks (
  id              uuid primary key default gen_random_uuid(),
  version_id      uuid not null references public.document_versions (id) on delete cascade,
  chunk_index     integer not null check (chunk_index >= 0),
  heading         text,
  content         text not null check (length(btrim(content)) > 0),
  content_hash    text not null,                    -- hash of the exact embedded input; lets us skip re-embedding
  token_count     integer,
  page_start      integer,
  page_end        integer,
  chunk_strategy  text not null default 'v1',
  embedding       extensions.vector(384),
  embedding_model text,
  search_tsv      tsvector generated always as (
                    to_tsvector('simple', coalesce(heading, '') || ' ' || content)
                  ) stored,
  created_at      timestamptz not null default now(),
  unique (version_id, chunk_index),
  constraint embedding_has_model check (embedding is null or embedding_model is not null)
);

create index document_chunks_version_idx on public.document_chunks (version_id);
create index document_chunks_tsv_idx on public.document_chunks using gin (search_tsv);
create index document_chunks_trgm_idx on public.document_chunks using gin (content extensions.gin_trgm_ops);
create index document_chunks_embedding_idx
  on public.document_chunks using hnsw (embedding extensions.vector_cosine_ops);

-- ---------------------------------------------------------------------------
-- ingestion_jobs: persisted job state (survives restarts; no in-memory queue)
-- ---------------------------------------------------------------------------
create table public.ingestion_jobs (
  id            uuid primary key default gen_random_uuid(),
  source_id     uuid not null references public.knowledge_sources (id) on delete cascade,
  status        text not null default 'queued' check (status in ('queued', 'running', 'succeeded', 'failed')),
  trigger       text not null default 'manual' check (trigger in ('manual', 'schedule', 'retry')),
  outcome       text check (outcome in ('new_version', 'unchanged')),
  document_id   uuid references public.source_documents (id) on delete set null,
  version_id    uuid references public.document_versions (id) on delete set null,
  payload       jsonb not null default '{}'::jsonb,   -- e.g. stored file path for uploads (never secrets)
  error_code    text,
  error_message text,
  statistics    jsonb not null default '{}'::jsonb,
  requested_by  uuid references public.profiles (id) on delete set null,
  created_at    timestamptz not null default now(),
  started_at    timestamptz,
  completed_at  timestamptz
);

create index ingestion_jobs_source_idx on public.ingestion_jobs (source_id, created_at desc);
create index ingestion_jobs_status_idx on public.ingestion_jobs (status);

-- ---------------------------------------------------------------------------
-- audit_log: administrative approvals and changes (append-only)
-- ---------------------------------------------------------------------------
create table public.audit_log (
  id          bigint generated always as identity primary key,
  action      text not null,
  entity_type text not null,
  entity_id   uuid,
  actor_id    uuid references public.profiles (id) on delete set null,
  details     jsonb not null default '{}'::jsonb,
  created_at  timestamptz not null default now()
);

create index audit_log_entity_idx on public.audit_log (entity_type, entity_id, created_at desc);
create index audit_log_created_idx on public.audit_log (created_at desc);

create or replace function public.audit_log_append_only()
returns trigger
language plpgsql
as $$
begin
  raise exception 'audit_log is append-only' using errcode = '42501';
end;
$$;

create trigger audit_log_no_update
  before update or delete on public.audit_log
  for each row execute function public.audit_log_append_only();
