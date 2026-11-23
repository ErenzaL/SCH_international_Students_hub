-- Full document inventory (READ-ONLY): one row per document with its current version and chunk/embedding counts.
-- Run: supabase db query --remote --read-only -f research/sql/document_inventory.sql --output-format json
select d.id as document_id, d.title, d.language, d.document_type, d.created_at as document_created_at,
       d.is_canceled, d.archived_at, s.source_type, s.category, s.authority_type, s.is_active as source_active,
       coalesce(d.canonical_url, s.original_url) as source_url,
       d.current_version_id, cv.version_number as current_version_number, cv.verification_status as current_status,
       cv.approved_at, cv.indexing_status, cv.valid_until, cv.content_hash,
       nullif(cv.extraction_meta ->> 'pages', '')::int as pages_metadata, length(cv.extracted_text) as text_chars,
       (select count(*) from public.document_versions v where v.document_id = d.id) as versions,
       (select v.verification_status from public.document_versions v where v.document_id = d.id
         order by v.version_number desc limit 1) as latest_version_status,
       (select count(*) from public.document_chunks c where c.version_id = d.current_version_id) as current_chunks,
       (select count(*) from public.document_chunks c where c.version_id = d.current_version_id and c.embedding is not null) as current_embedded,
       (select count(*) from public.searchable_chunks sc where sc.document_id = d.id) as searchable_chunks,
       (select count(*) from public.document_chunks c join public.document_versions v on v.id = c.version_id
         where v.document_id = d.id and v.id is distinct from d.current_version_id) as historical_chunks,
       (select count(*) from public.document_versions v2 join public.source_documents d2 on d2.id = v2.document_id
         where v2.content_hash = cv.content_hash and d2.id <> d.id) as same_hash_other_documents,
       (select count(*) from public.source_documents d3 where lower(d3.title) = lower(d.title) and d3.id <> d.id) as same_title_other_documents,
       (select max(j.created_at) from public.ingestion_jobs j where j.source_id = d.source_id) as last_job_at,
       (select count(*) from public.ingestion_jobs j where j.source_id = d.source_id and j.status = 'failed') as failed_jobs_for_source
  from public.source_documents d
  join public.knowledge_sources s on s.id = d.source_id
  left join public.document_versions cv on cv.id = d.current_version_id
 order by d.created_at;
