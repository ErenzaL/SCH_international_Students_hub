-- Migration 0007 (automatic RAG sync) behavioural checks. Scratch DB only; rolled back.
\set ON_ERROR_STOP on
begin;

create function pg_temp.vec(p_hot int) returns extensions.vector language sql as $$
  select ('[' || string_agg(case when i = p_hot then '1' else '0' end, ',') || ']')::extensions.vector
  from generate_series(1, 384) i $$;
create function pg_temp.vjson(p_hot int) returns jsonb language sql as $$
  select to_jsonb(array(select case when i = p_hot then 1.0 else 0.0 end from generate_series(1, 384) i)) $$;

insert into auth.users (id, email) values ('00000000-0000-0000-0000-0000000000c1', 'rag-admin@example.test');
update profiles set role = 'admin' where id = '00000000-0000-0000-0000-0000000000c1';
insert into knowledge_sources (id, title, organization, source_type, authority_type, scope, category)
values ('12000000-0000-0000-0000-000000000001', 'RAG src', 'Org', 'manual_text', 'official_university', 'university',
        'academic-life');
insert into source_documents (id, source_id, external_id, title)
values ('22000000-0000-0000-0000-000000000001', '12000000-0000-0000-0000-000000000001', 'rag-1', 'RAG doc');
insert into document_versions (id, document_id, version_number, extracted_text, content_hash) values
  ('32000000-0000-0000-0000-000000000001', '22000000-0000-0000-0000-000000000001', 1, 'first text', repeat('c', 64));

do $$
declare n integer;
begin
  -- replace: writes a full chunk set
  n := replace_version_chunks('32000000-0000-0000-0000-000000000001', jsonb_build_array(
         jsonb_build_object('chunk_index', 0, 'content', 'alpha', 'content_hash', 'h0', 'embedding', pg_temp.vjson(1), 'embedding_model', 'm'),
         jsonb_build_object('chunk_index', 1, 'content', 'beta', 'content_hash', 'h1', 'embedding', pg_temp.vjson(2), 'embedding_model', 'm')));
  assert n = 2, 'two chunks written';
  -- a failing replacement (duplicate chunk_index) rolls back completely: the old set survives
  begin
    perform replace_version_chunks('32000000-0000-0000-0000-000000000001', jsonb_build_array(
      jsonb_build_object('chunk_index', 0, 'content', 'x', 'content_hash', 'x'),
      jsonb_build_object('chunk_index', 0, 'content', 'y', 'content_hash', 'y')));
    raise exception 'FAIL: duplicate chunk set accepted';
  exception when unique_violation then null; end;
  assert (select string_agg(content, ',' order by chunk_index) from document_chunks
           where version_id = '32000000-0000-0000-0000-000000000001') = 'alpha,beta', 'old chunks intact after failure';
  -- null embedding -> stored without model
  perform replace_version_chunks('32000000-0000-0000-0000-000000000001', jsonb_build_array(
    jsonb_build_object('chunk_index', 0, 'content', 'alpha', 'content_hash', 'h0', 'embedding', null, 'embedding_model', 'm'),
    jsonb_build_object('chunk_index', 1, 'content', 'beta', 'content_hash', 'h1', 'embedding', pg_temp.vjson(2), 'embedding_model', 'm')));
  assert (select count(*) from document_chunks where version_id = '32000000-0000-0000-0000-000000000001'
           and embedding is null and embedding_model is null) = 1, 'unembedded chunk stored without model';

  -- activation validates the complete index in the same transaction
  begin
    perform activate_document_version('32000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-0000000000c1', null, 2, 'm');
    raise exception 'FAIL: activated with a missing embedding';
  exception when sqlstate '55000' then null; end;
  perform replace_version_chunks('32000000-0000-0000-0000-000000000001', jsonb_build_array(
    jsonb_build_object('chunk_index', 0, 'content', 'alpha', 'content_hash', 'h0', 'embedding', pg_temp.vjson(1), 'embedding_model', 'm'),
    jsonb_build_object('chunk_index', 1, 'content', 'beta', 'content_hash', 'h1', 'embedding', pg_temp.vjson(2), 'embedding_model', 'm')));
  begin
    perform activate_document_version('32000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-0000000000c1', null, 3, 'm');
    raise exception 'FAIL: activated with wrong expected count';
  exception when sqlstate '55000' then null; end;
  begin
    perform activate_document_version('32000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-0000000000c1', null, 2, 'other-model');
    raise exception 'FAIL: activated with vectors from another model';
  exception when sqlstate '55000' then null; end;
  perform activate_document_version('32000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-0000000000c1', 'ok', 2, 'm');
  assert (select current_version_id from source_documents where id = '22000000-0000-0000-0000-000000000001')
         = '32000000-0000-0000-0000-000000000001', 'activated';
  assert exists (select 1 from audit_log where action = 'version.activate'
                  and entity_id = '32000000-0000-0000-0000-000000000001'), 'activation audited';
end $$;

-- v2 replaces v1 atomically; v1 superseded but kept
insert into document_versions (id, document_id, version_number, extracted_text, content_hash) values
  ('32000000-0000-0000-0000-000000000002', '22000000-0000-0000-0000-000000000001', 2, 'second text', repeat('d', 64));
insert into document_chunks (version_id, chunk_index, content, content_hash, embedding, embedding_model)
values ('32000000-0000-0000-0000-000000000002', 0, 'gamma', 'g0', pg_temp.vec(3), 'm');
do $$ begin
  assert (select count(*) from searchable_chunks where document_id = '22000000-0000-0000-0000-000000000001') = 2,
    'only v1 chunks are searchable before activation';
  perform activate_document_version('32000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-0000000000c1', null, 1, 'm');
  assert (select string_agg(content, ',') from searchable_chunks where document_id = '22000000-0000-0000-0000-000000000001') = 'gamma',
    'v2 is the only searchable version after activation';
  assert (select verification_status from document_versions where id = '32000000-0000-0000-0000-000000000001') = 'superseded';
  assert (select count(*) from document_chunks where version_id = '32000000-0000-0000-0000-000000000001') = 2,
    'superseded version kept for audit/rollback';
end $$;

-- one open index job per version
insert into ingestion_jobs (source_id, job_type, status, payload)
values ('12000000-0000-0000-0000-000000000001', 'index_version', 'queued', '{"version_id": "32000000-0000-0000-0000-000000000002"}');
do $$ begin
  begin
    insert into ingestion_jobs (source_id, job_type, status, payload)
    values ('12000000-0000-0000-0000-000000000001', 'index_version', 'queued', '{"version_id": "32000000-0000-0000-0000-000000000002"}');
    raise exception 'FAIL: duplicate open index job accepted';
  exception when unique_violation then null; end;
end $$;
update ingestion_jobs set status = 'failed' where job_type = 'index_version';
insert into ingestion_jobs (source_id, job_type, status, payload)   -- a retry after failure is allowed
values ('12000000-0000-0000-0000-000000000001', 'index_version', 'queued', '{"version_id": "32000000-0000-0000-0000-000000000002"}');

-- notifications + function grants
insert into admin_notifications (kind, title) values ('version_activated', 'x');
set local role anon;
do $$ begin
  begin perform replace_version_chunks('32000000-0000-0000-0000-000000000002', '[]'); raise exception 'FAIL anon replace';
  exception when insufficient_privilege then null; end;
  begin perform activate_document_version('32000000-0000-0000-0000-000000000002', null, null, 1, 'm'); raise exception 'FAIL anon activate';
  exception when insufficient_privilege then null; end;
  begin perform * from admin_notifications; raise exception 'FAIL anon notifications';
  exception when insufficient_privilege then null; end;
end $$;
reset role;

select 'ALL RAG SYNC SQL BEHAVIOUR TESTS PASSED' as result;
rollback;
