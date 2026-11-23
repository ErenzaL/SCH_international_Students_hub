-- Snapshot identity (READ-ONLY): every chunk id with its version and document, active flag and embedding model/dims.
select c.id as chunk_id, c.version_id, v.document_id, v.version_number, c.chunk_index, c.embedding_model,
       case when c.embedding is not null then extensions.vector_dims(c.embedding) end as dims,
       exists (select 1 from public.searchable_chunks sc where sc.chunk_id = c.id) as active
  from public.document_chunks c join public.document_versions v on v.id = c.version_id
 order by v.document_id, c.chunk_index;
