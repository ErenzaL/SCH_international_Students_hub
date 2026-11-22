-- Migration 0010 (source archive / restore / guarded delete) checks. Scratch DB only; rolled back.
\set ON_ERROR_STOP on
begin;

create function pg_temp.vec(p_hot int) returns extensions.vector language sql as $$
  select ('[' || string_agg(case when i = p_hot then '1' else '0' end, ',') || ']')::extensions.vector
  from generate_series(1, 384) i $$;

insert into auth.users (id, email) values
  ('00000000-0000-0000-0000-0000000001f1', 'super10@example.test'),
  ('00000000-0000-0000-0000-0000000001f2', 'admin10@example.test');
update profiles set role = 'super_admin' where id = '00000000-0000-0000-0000-0000000001f1';
update profiles set role = 'admin' where id = '00000000-0000-0000-0000-0000000001f2';

-- S1: a source with one approved, indexed document and an uploaded file
-- S2: an empty source (never used)
-- S3: another source whose job references S1's file (shared file must survive)
insert into knowledge_sources (id, title, original_url, organization, source_type, authority_type, scope, category)
values ('15000000-0000-0000-0000-000000000001', 'Guide', null, 'NHIS', 'pdf', 'official_government', 'national',
        'health-insurance'),
       ('15000000-0000-0000-0000-000000000002', 'Empty', null, 'SCH', 'text_file', 'official_university', 'university',
        'academic-life'),
       ('15000000-0000-0000-0000-000000000003', 'Other', null, 'SCH', 'pdf', 'official_university', 'university',
        'academic-life');
insert into source_documents (id, source_id, external_id, title) values
  ('25000000-0000-0000-0000-000000000001', '15000000-0000-0000-0000-000000000001', 'primary', 'Guide doc');
insert into document_versions (id, document_id, version_number, extracted_text, content_hash, original_file) values
  ('35000000-0000-0000-0000-000000000001', '25000000-0000-0000-0000-000000000001', 1, 'insurance rules', repeat('f', 64),
   '{"storage_path": "sources/s1/own.pdf"}');
insert into document_chunks (version_id, chunk_index, content, content_hash, embedding, embedding_model)
values ('35000000-0000-0000-0000-000000000001', 0, 'insurance rules', 'h', pg_temp.vec(7), 'm');
insert into ingestion_jobs (id, source_id, status, document_id, version_id, outcome, payload) values
  ('55000000-0000-0000-0000-000000000001', '15000000-0000-0000-0000-000000000001', 'succeeded',
   '25000000-0000-0000-0000-000000000001', '35000000-0000-0000-0000-000000000001', 'new_version',
   '{"storage_path": "sources/s1/own.pdf"}'),
  ('55000000-0000-0000-0000-000000000002', '15000000-0000-0000-0000-000000000001', 'succeeded', null, null, 'unchanged',
   '{"storage_path": "sources/shared/both.pdf"}'),
  ('55000000-0000-0000-0000-000000000003', '15000000-0000-0000-0000-000000000003', 'failed', null, null, null,
   '{"storage_path": "sources/shared/both.pdf"}');
do $$ begin
  perform approve_document_version('35000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-0000000001f2');
end $$;

do $$
declare r jsonb; v_job uuid;
begin
  -- raw deletes of a used source are refused, even for the table owner / service role
  begin delete from knowledge_sources where id = '15000000-0000-0000-0000-000000000001';
        raise exception 'FAIL: direct delete of a used source';
  exception when sqlstate '42501' then null; end;

  -- the check reports what would be removed
  r := source_delete_check('15000000-0000-0000-0000-000000000001');
  assert not (r ->> 'eligible')::boolean and (r ->> 'published_documents')::int = 1, 'published blocks';
  assert (r ->> 'approved_versions')::int = 1 and (r ->> 'indexed_chunks')::int = 1 and (r ->> 'is_searchable')::boolean;
  assert r ->> 'recommended_action' = 'archive' and (r ->> 'requires_destructive_confirmation')::boolean;
  assert r -> 'storage_files' = '["sources/s1/own.pdf"]'::jsonb, 'shared file excluded: ' || (r -> 'storage_files')::text;
  assert r ->> 'organization' = 'NHIS';

  -- admin cannot delete; super admin is blocked while content is published
  begin perform delete_source('15000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-0000000001f2',
                              'cleanup test', 'Guide', true);
        raise exception 'FAIL: admin deleted a source';
  exception when sqlstate '42501' then null; end;
  begin perform delete_source('15000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-0000000001f1',
                              'cleanup test', 'Guide', true);
        raise exception 'FAIL: deleted a source with published content';
  exception when sqlstate '55000' then null; end;

  -- archive: inactive + documents archived -> nothing searchable; restore reverses it
  perform archive_source('15000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-0000000001f2', 'Replaced');
  assert (select count(*) from searchable_chunks where source_id = '15000000-0000-0000-0000-000000000001') = 0;
  assert (select archived_at is not null from source_documents where id = '25000000-0000-0000-0000-000000000001');
  perform restore_source('15000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-0000000001f2');
  assert (select count(*) from searchable_chunks where source_id = '15000000-0000-0000-0000-000000000001') = 1, 'restored';
  perform archive_source('15000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-0000000001f2', 'Replaced');

  -- a running job blocks; a queued job is canceled by the delete
  insert into ingestion_jobs (source_id, status) values ('15000000-0000-0000-0000-000000000001', 'running')
    returning id into v_job;
  begin perform delete_source('15000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-0000000001f1',
                              'cleanup test', 'Guide', true);
        raise exception 'FAIL: deleted while a job is running';
  exception when sqlstate '55000' then null; end;
  update ingestion_jobs set status = 'queued' where id = v_job;

  -- second confirmation and exact title are required
  begin perform delete_source('15000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-0000000001f1',
                              'cleanup test', 'Guide', false);
        raise exception 'FAIL: destructive delete without the second confirmation';
  exception when sqlstate '22023' then null; end;
  begin perform delete_source('15000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-0000000001f1',
                              'cleanup test', 'Wrong', true);
        raise exception 'FAIL: wrong title accepted';
  exception when sqlstate '22023' then null; end;

  r := delete_source('15000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-0000000001f1',
                     'cleanup test', 'Guide', true);
  assert (r ->> 'deleted')::boolean and (r ->> 'queued_jobs_canceled')::int = 1;
  assert r -> 'storage_files' = '["sources/s1/own.pdf"]'::jsonb;
  assert not exists (select 1 from knowledge_sources where id = '15000000-0000-0000-0000-000000000001');
  assert not exists (select 1 from source_documents where id = '25000000-0000-0000-0000-000000000001');
  assert not exists (select 1 from document_versions where id = '35000000-0000-0000-0000-000000000001');
  assert not exists (select 1 from document_chunks where version_id = '35000000-0000-0000-0000-000000000001'),
    'chunks and embeddings removed';
  assert (select count(*) from ingestion_jobs where source_title = 'Guide' and source_id is null) = 3, 'job history kept';
  assert (select status = 'failed' and error_code = 'source_deleted' from ingestion_jobs where id = v_job);
  assert exists (select 1 from ingestion_jobs where id = '55000000-0000-0000-0000-000000000003'
                  and source_id = '15000000-0000-0000-0000-000000000003'), 'other source untouched';
  assert exists (select 1 from audit_log where action = 'source.delete'
                  and entity_id = '15000000-0000-0000-0000-000000000001'
                  and details -> 'documents' -> 0 -> 'versions' -> 0 ->> 'content_hash' = repeat('f', 64)), 'tombstone';
  assert exists (select 1 from audit_log where action = 'version.approve'
                  and entity_id = '35000000-0000-0000-0000-000000000001'), 'earlier audit kept';
  assert exists (select 1 from audit_log where action = 'source.archive'
                  and entity_id = '15000000-0000-0000-0000-000000000001'), 'archive audit kept';
  assert coalesce(current_setting('app.source_delete_id', true), '') = '', 'guard permission reset';
  assert coalesce(current_setting('app.document_delete_id', true), '') = '', 'guard permission reset';

  -- repeated delete -> not found
  begin perform delete_source('15000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-0000000001f1',
                              'cleanup test', 'Guide', true);
        raise exception 'FAIL: deleted twice';
  exception when sqlstate 'P0002' then null; end;

  -- an unused source is deleted without the destructive confirmation
  r := source_delete_check('15000000-0000-0000-0000-000000000002');
  assert (r ->> 'eligible')::boolean and r ->> 'recommended_action' = 'delete'
     and not (r ->> 'requires_destructive_confirmation')::boolean;
  perform delete_source('15000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-0000000001f1',
                        'created by mistake', 'Empty', false);
  assert not exists (select 1 from knowledge_sources where id = '15000000-0000-0000-0000-000000000002');
end $$;

-- clients cannot call the source lifecycle functions
set local role authenticated;
do $$ begin
  begin perform source_delete_check('15000000-0000-0000-0000-000000000003'); raise exception 'FAIL client check';
  exception when insufficient_privilege then null; end;
  begin perform delete_source('15000000-0000-0000-0000-000000000003', '00000000-0000-0000-0000-0000000001f1',
                              'client attempt', 'Other', true);
        raise exception 'FAIL client delete';
  exception when insufficient_privilege then null; end;
end $$;
reset role;

select 'ALL SOURCE LIFECYCLE SQL BEHAVIOUR TESTS PASSED' as result;
rollback;
