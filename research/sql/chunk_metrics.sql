-- Per-chunk NUMERIC metrics (no text) for the chunk-analysis notebook. READ-ONLY.
-- Run: supabase db query --remote --read-only -f research/sql/chunk_metrics.sql --output-format json
-- overlap_with_previous: the first 60 characters of this chunk occur in the previous chunk of the same version
-- (detects the configured sliding-window overlap; NULL for the first chunk).
with active_versions as (
  select d.current_version_id as version_id, d.id as document_id, d.language, s.category, d.document_type
    from public.source_documents d join public.knowledge_sources s on s.id = d.source_id
    join public.document_versions v on v.id = d.current_version_id
   where v.verification_status = 'approved' and not d.is_canceled and d.archived_at is null and s.is_active)
select c.version_id, coalesce(a.document_id, v.document_id) as document_id, (a.version_id is not null) as active,
       a.language, a.category, a.document_type, c.chunk_index, length(c.content) as chars, c.token_count,
       c.page_start, c.page_end, (c.heading is not null) as has_heading, c.embedding is not null as has_embedding,
       c.chunk_strategy,
       case when c.chunk_index = 0 then null
            else position(left(c.content, 60) in coalesce(
                   (select p.content from public.document_chunks p where p.version_id = c.version_id
                     and p.chunk_index = c.chunk_index - 1), '')) > 0 end as overlap_with_previous
  from public.document_chunks c
  join public.document_versions v on v.id = c.version_id
  left join active_versions a on a.version_id = c.version_id
 order by document_id, c.chunk_index;
