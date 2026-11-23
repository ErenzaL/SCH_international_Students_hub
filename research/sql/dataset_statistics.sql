-- SCH International Student Hub - RAG dataset statistics (READ-ONLY).
-- Run:  supabase db query --remote --read-only -f research/sql/dataset_statistics.sql --output-format json
-- "active" = the current approved version of a non-canceled, non-archived document of an active source
--            (exactly what public.searchable_chunks exposes to retrieval);
-- "historical" = every other version (superseded / pending / rejected / draft) that still has rows.
-- Unknown values are NULL, never 0. Chunk sizes: characters (exact) and token_count (the chunker's estimate).
with
docs as (
  select d.*, s.category, s.source_type, s.authority_type, s.is_active as source_active
    from public.source_documents d join public.knowledge_sources s on s.id = d.source_id),
cur as (
  select v.* from public.document_versions v join docs d on d.current_version_id = v.id),
active_docs as (
  select d.* from docs d join public.document_versions v on v.id = d.current_version_id
   where v.verification_status = 'approved' and not d.is_canceled and d.archived_at is null and d.source_active),
chunks as (
  select c.id, c.version_id, c.chunk_index, length(c.content) as chars, c.token_count, c.page_start, c.page_end,
         c.chunk_strategy, c.embedding_model, c.embedding is not null as has_embedding,
         case when c.embedding is not null then extensions.vector_dims(c.embedding) end as dims,
         c.content_hash, (c.version_id in (select current_version_id from active_docs)) as active
    from public.document_chunks c),
active_chunks as (select * from chunks where active),
searchable as (select chunk_id, document_id, document_language, category from public.searchable_chunks),
per_doc as (
  select d.id, d.title, d.language, d.category, d.document_type, d.source_type,
         (select count(*) from active_chunks c where c.version_id = d.current_version_id) as chunks,
         (select count(*) from active_chunks c where c.version_id = d.current_version_id and c.has_embedding) as embedded,
         nullif((v.extraction_meta ->> 'pages'), '')::int as meta_pages,
         (select max(c.page_end) from active_chunks c where c.version_id = d.current_version_id) as max_page_marker,
         length(v.extracted_text) as text_chars
    from active_docs d join public.document_versions v on v.id = d.current_version_id),
pct as (
  select percentile_cont(0.5) within group (order by chars) as med_chars,
         percentile_cont(0.5) within group (order by token_count) as med_tokens,
         percentile_cont(0.25) within group (order by chars) as p25_chars,
         percentile_cont(0.75) within group (order by chars) as p75_chars
    from active_chunks)
select jsonb_build_object(
  'generated_at', now(),
  'documents', jsonb_build_object(
     'total', (select count(*) from docs),
     'with_an_approved_current_version', (select count(*) from docs where current_version_id is not null),
     'active_searchable', (select count(*) from active_docs),
     'canceled', (select count(*) from docs where is_canceled),
     'archived', (select count(*) from docs where archived_at is not null),
     'indexed_active (all chunks embedded)', (select count(*) from per_doc where chunks > 0 and embedded = chunks),
     'active_without_chunks', (select count(*) from per_doc where chunks = 0),
     'by_language', (select jsonb_object_agg(language, n) from (select language, count(*) n from active_docs group by 1) x),
     'by_category', (select jsonb_object_agg(category, n) from (select category, count(*) n from active_docs group by 1) x),
     'by_document_type', (select jsonb_object_agg(document_type, n) from (select document_type, count(*) n from active_docs group by 1) x),
     'by_source_type', (select jsonb_object_agg(source_type, n) from (select source_type, count(*) n from active_docs group by 1) x),
     'with_valid_until', (select count(*) from active_docs d join public.document_versions v on v.id = d.current_version_id where v.valid_until is not null)),
  'announcements', (select jsonb_object_agg(publication_status, n) from (select publication_status, count(*) n from public.announcements group by 1) x),
  'versions', jsonb_build_object(
     'total', (select count(*) from public.document_versions),
     'by_status', (select jsonb_object_agg(verification_status, n) from (select verification_status, count(*) n from public.document_versions group by 1) x),
     'by_indexing_status', (select jsonb_object_agg(coalesce(indexing_status, 'null'), n) from (select indexing_status, count(*) n from public.document_versions group by 1) x)),
  'pages', jsonb_build_object(
     'documents_with_page_metadata', (select count(*) from per_doc where meta_pages is not null),
     'total_pages_from_extraction_metadata', (select sum(meta_pages) from per_doc),
     'documents_with_page_markers_on_chunks', (select count(*) from per_doc where max_page_marker is not null),
     'total_pages_from_chunk_page_markers', (select sum(max_page_marker) from per_doc)),
  'chunks', jsonb_build_object(
     'total_rows', (select count(*) from chunks),
     'active', (select count(*) from active_chunks),
     'historical', (select count(*) from chunks where not active),
     'active_with_embedding', (select count(*) from active_chunks where has_embedding),
     'active_without_embedding', (select count(*) from active_chunks where not has_embedding),
     'searchable_via_view', (select count(*) from searchable),
     'embedding_models', (select jsonb_object_agg(coalesce(embedding_model, 'none'), n) from (select embedding_model, count(*) n from chunks group by 1) x),
     'embedding_dimensions', (select jsonb_agg(distinct dims) from chunks where dims is not null),
     'chunk_strategy', (select jsonb_object_agg(chunk_strategy, n) from (select chunk_strategy, count(*) n from chunks group by 1) x),
     'duplicate_content_within_version', (select count(*) from (select version_id, content_hash from chunks group by 1, 2 having count(*) > 1) x),
     'duplicate_content_across_active_documents', (select count(*) from (select content_hash from active_chunks group by 1 having count(distinct version_id) > 1) x),
     'size_chars_active', jsonb_build_object('min', (select min(chars) from active_chunks), 'max', (select max(chars) from active_chunks),
        'mean', (select round(avg(chars), 1) from active_chunks), 'median', (select med_chars from pct),
        'p25', (select p25_chars from pct), 'p75', (select p75_chars from pct)),
     'size_estimated_tokens_active', jsonb_build_object('min', (select min(token_count) from active_chunks), 'max', (select max(token_count) from active_chunks),
        'mean', (select round(avg(token_count), 1) from active_chunks), 'median', (select med_tokens from pct)),
     'per_document_active', jsonb_build_object('min', (select min(chunks) from per_doc), 'max', (select max(chunks) from per_doc),
        'mean', (select round(avg(chunks), 2) from per_doc)),
     'by_language_active', (select jsonb_object_agg(document_language, n) from (select document_language, count(*) n from searchable group by 1) x),
     'by_category_active', (select jsonb_object_agg(category, n) from (select category, count(*) n from searchable group by 1) x),
     'size_histogram_chars_active', (select jsonb_object_agg(bucket, n) from (
        select case when chars < 250 then '0-249' when chars < 500 then '250-499' when chars < 1000 then '500-999'
                    when chars < 1500 then '1000-1499' when chars < 2000 then '1500-1999' else '2000+' end as bucket,
               count(*) n from active_chunks group by 1) x)),
  'jobs', (select jsonb_object_agg(job_type || ':' || status, n) from (select job_type, status, count(*) n from public.ingestion_jobs group by 1, 2) x),
  'per_document', (select jsonb_agg(jsonb_build_object('id', id, 'title', left(title, 80), 'language', language,
        'category', category, 'document_type', document_type, 'source_type', source_type, 'chunks', chunks,
        'embedded', embedded, 'pages_metadata', meta_pages, 'max_page_marker', max_page_marker, 'text_chars', text_chars)
        order by chunks desc) from per_doc),
  'vector_index', (select jsonb_agg(jsonb_build_object('name', indexname, 'definition', indexdef))
                     from pg_indexes where schemaname = 'public' and tablename = 'document_chunks'),
  'pgvector_version', (select extversion from pg_extension where extname = 'vector')
) as stats;
