-- Migration 0009 (archive / restore / guarded delete / suppression) checks. Scratch DB only; rolled back.
\set ON_ERROR_STOP on
begin;

create function pg_temp.vec(p_hot int) returns extensions.vector language sql as $$
  select ('[' || string_agg(case when i = p_hot then '1' else '0' end, ',') || ']')::extensions.vector
  from generate_series(1, 384) i $$;

insert into auth.users (id, email) values
  ('00000000-0000-0000-0000-0000000000f1', 'super9@example.test'),
  ('00000000-0000-0000-0000-0000000000f2', 'admin9@example.test');
update profiles set role = 'super_admin' where id = '00000000-0000-0000-0000-0000000000f1';
update profiles set role = 'admin' where id = '00000000-0000-0000-0000-0000000000f2';

insert into knowledge_sources (id, title, original_url, organization, source_type, authority_type, scope, category)
values ('14000000-0000-0000-0000-000000000001', 'Web', 'https://www.hikorea.go.kr/x', 'KIS', 'website',
        'official_government', 'national', 'visa-immigration');
insert into source_documents (id, source_id, canonical_url, title) values
  ('24000000-0000-0000-0000-000000000001', '14000000-0000-0000-0000-000000000001', 'https://www.hikorea.go.kr/x', 'Visa page');
insert into document_versions (id, document_id, version_number, extracted_text, content_hash, original_file) values
  ('34000000-0000-0000-0000-000000000001', '24000000-0000-0000-0000-000000000001', 1, 'visa rules', repeat('e', 64),
   '{"storage_path": "sources/x/file.pdf"}');
insert into document_chunks (version_id, chunk_index, content, content_hash, embedding, embedding_model)
values ('34000000-0000-0000-0000-000000000001', 0, 'visa rules', 'h', pg_temp.vec(5), 'm');
insert into ingestion_jobs (id, source_id, status, document_id, version_id, outcome)
values ('54000000-0000-0000-0000-000000000001', '14000000-0000-0000-0000-000000000001', 'succeeded',
        '24000000-0000-0000-0000-000000000001', '34000000-0000-0000-0000-000000000001', 'new_version');
do $$ begin
  perform approve_document_version('34000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-0000000000f2');
end $$;

do $$
declare r jsonb;
begin
  -- guards: no direct deletes, not even as the table owner / service role, and no cascades from the source
  begin delete from source_documents where id = '24000000-0000-0000-0000-000000000001';
        raise exception 'FAIL: direct document delete';
  exception when sqlstate '42501' then null; end;
  begin delete from document_versions where id = '34000000-0000-0000-0000-000000000001';
        raise exception 'FAIL: direct delete of an approved version';
  exception when sqlstate '42501' then null; end;
  begin delete from knowledge_sources where id = '14000000-0000-0000-0000-000000000001';
        raise exception 'FAIL: cascade delete through the source';
  exception when sqlstate '42501' then null; end;

  -- archive excludes from retrieval, restore brings it back
  assert (select count(*) from searchable_chunks where document_id = '24000000-0000-0000-0000-000000000001') = 1;
  perform archive_document('24000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-0000000000f2', 'Outdated');
  assert (select count(*) from searchable_chunks where document_id = '24000000-0000-0000-0000-000000000001') = 0,
    'archived is not searchable';
  perform restore_document('24000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-0000000000f2', null);
  assert (select count(*) from searchable_chunks where document_id = '24000000-0000-0000-0000-000000000001') = 1, 'restored';

  -- delete: published -> refused; admin -> refused; wrong title -> refused
  begin perform delete_document('24000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-0000000000f1',
                                'duplicate entry', 'Visa page');
        raise exception 'FAIL: deleted a published document';
  exception when sqlstate '55000' then null; end;
  perform cancel_document('24000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-0000000000f2', 'wrong');
  begin perform delete_document('24000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-0000000000f2',
                                'duplicate entry', 'Visa page');
        raise exception 'FAIL: admin deleted';
  exception when sqlstate '42501' then null; end;
  begin perform delete_document('24000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-0000000000f1',
                                'duplicate entry', 'Other title');
        raise exception 'FAIL: wrong confirmation accepted';
  exception when sqlstate '22023' then null; end;

  r := delete_document('24000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-0000000000f1',
                       'duplicate entry', 'Visa page');
  assert (r ->> 'deleted')::boolean and r -> 'storage_files' = '["sources/x/file.pdf"]'::jsonb, 'files reported for cleanup';
  assert not exists (select 1 from source_documents where id = '24000000-0000-0000-0000-000000000001');
  assert not exists (select 1 from document_chunks where version_id = '34000000-0000-0000-0000-000000000001');
  assert (select document_id is null and version_id is null from ingestion_jobs
           where id = '54000000-0000-0000-0000-000000000001'), 'job history kept, references cleared';
  assert exists (select 1 from audit_log where action = 'document.delete'
                  and entity_id = '24000000-0000-0000-0000-000000000001'
                  and details -> 'versions' -> 0 ->> 'content_hash' = repeat('e', 64)), 'tombstone with hashes';
  assert exists (select 1 from audit_log where action = 'version.approve'
                  and entity_id = '34000000-0000-0000-0000-000000000001'), 'earlier audit kept';
  assert exists (select 1 from document_suppressions where source_id = '14000000-0000-0000-0000-000000000001'
                  and canonical_url = 'https://www.hikorea.go.kr/x'), 're-import suppressed';
  -- the guard permission does not leak out of the function
  assert coalesce(current_setting('app.document_delete_id', true), '') = '', 'guard permission reset';
end $$;

-- clients cannot call the lifecycle functions
set local role authenticated;
do $$ begin
  begin perform document_delete_check('24000000-0000-0000-0000-000000000001'); raise exception 'FAIL client check';
  exception when insufficient_privilege then null; end;
end $$;
reset role;

select 'ALL DOCUMENT LIFECYCLE SQL BEHAVIOUR TESTS PASSED' as result;
rollback;
