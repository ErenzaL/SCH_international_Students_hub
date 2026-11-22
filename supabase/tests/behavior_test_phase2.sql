-- Phase 2 behavioural checks (migration 0006). Same rules as behavior_test.sql: scratch DB only,
-- one transaction, rolled back; any failed assert aborts.
\set ON_ERROR_STOP on
begin;

create function pg_temp.vec(p_hot int) returns extensions.vector language sql as $$
  select ('[' || string_agg(case when i = p_hot then '1' else '0' end, ',') || ']')::extensions.vector
  from generate_series(1, 384) i $$;

insert into auth.users (id, email) values
  ('00000000-0000-0000-0000-0000000000b1', 'admin2@example.test'),
  ('00000000-0000-0000-0000-0000000000b2', 'supporter2@example.test'),
  ('00000000-0000-0000-0000-0000000000b3', 'supporter3@example.test');
update profiles set role = 'admin'     where id = '00000000-0000-0000-0000-0000000000b1';
update profiles set role = 'supporter' where id in ('00000000-0000-0000-0000-0000000000b2', '00000000-0000-0000-0000-0000000000b3');

-- new enum values accepted; board needs URL; boards may sync daily
insert into knowledge_sources (id, title, original_url, organization, source_type, authority_type, scope, category, sync_frequency, config)
values ('11000000-0000-0000-0000-000000000001', 'SCH board', 'https://sgee.sch.ac.kr/notice/notice01.php?table_name=noti_fore',
        'SCH', 'sch_board', 'official_university', 'university', 'university-announcements', 'daily', '{"max_items": 5}');
insert into knowledge_sources (id, title, organization, source_type, authority_type, scope, category)
values ('11000000-0000-0000-0000-000000000002', 'Shot', 'SCH staff', 'screenshot', 'staff_communication', 'university', 'topik-korean');
do $$ begin
  begin
    insert into knowledge_sources (title, organization, source_type, authority_type, scope, category)
    values ('no url', 'x', 'sch_board', 'official_university', 'university', 'university-announcements');
    raise exception 'FAIL: board without URL accepted';
  exception when check_violation then null; end;
  begin
    insert into knowledge_sources (title, organization, source_type, authority_type, scope, category, sync_frequency)
    values ('daily shot', 'x', 'screenshot', 'staff_communication', 'university', 'topik-korean', 'daily');
    raise exception 'FAIL: non-fetchable daily sync accepted';
  exception when check_violation then null; end;
  begin
    insert into knowledge_sources (title, original_url, organization, source_type, authority_type, scope, category)
    values ('dup', 'https://sgee.sch.ac.kr/notice/notice01.php?table_name=noti_fore', 'SCH', 'sch_board',
            'official_university', 'university', 'university-announcements');
    raise exception 'FAIL: duplicate board URL accepted';
  exception when unique_violation then null; end;
end $$;

-- notice documents (one per notice) + versions
insert into source_documents (id, source_id, canonical_url, external_id, title, document_type, metadata) values
  ('21000000-0000-0000-0000-000000000001', '11000000-0000-0000-0000-000000000001',
   'https://sgee.sch.ac.kr/notice/notice01.php?admin_mode=read&no=1&table_name=noti_fore', 'noti_fore:1', 'D-2 visa notice', 'notice',
   '{"notice_no": "1"}'),
  ('21000000-0000-0000-0000-000000000002', '11000000-0000-0000-0000-000000000001',
   'https://sgee.sch.ac.kr/notice/notice01.php?admin_mode=read&no=2&table_name=noti_fore', 'noti_fore:2', 'D-4 notice', 'notice', '{}'),
  ('21000000-0000-0000-0000-000000000003', '11000000-0000-0000-0000-000000000002', null, 'screenshot:abc', 'TOPIK shot', 'screenshot', '{}');

insert into document_versions (id, document_id, version_number, extracted_text, content_hash, created_by) values
  ('31000000-0000-0000-0000-000000000001', '21000000-0000-0000-0000-000000000001', 1, 'D-2 visa holders must extend before expiry', repeat('1', 64), null),
  ('31000000-0000-0000-0000-000000000002', '21000000-0000-0000-0000-000000000002', 1, 'D-4 language trainees schedule', repeat('2', 64), null);
insert into document_versions (id, document_id, version_number, extracted_text, content_hash, created_by, verification_status,
                               raw_text, extraction_meta, original_file) values
  ('31000000-0000-0000-0000-000000000003', '21000000-0000-0000-0000-000000000003', 1, 'TOPIK 설명회 12월 3일', repeat('3', 64),
   '00000000-0000-0000-0000-0000000000b2', 'draft', 'TOPIK 설명회 12윌 3일 (raw OCR)', '{"requires_field_confirmation": true}',
   '{"storage_path": "screenshots/x.png", "sha256": "abc"}');
insert into document_chunks (version_id, chunk_index, content, content_hash, embedding, embedding_model) values
  ('31000000-0000-0000-0000-000000000001', 0, 'D-2 visa holders must extend before expiry', 'c1', pg_temp.vec(1), 'm'),
  ('31000000-0000-0000-0000-000000000002', 0, 'D-4 language trainees schedule', 'c2', pg_temp.vec(2), 'm'),
  ('31000000-0000-0000-0000-000000000003', 0, 'TOPIK 설명회 12월 3일', 'c3', pg_temp.vec(3), 'm');

do $$ begin
  -- evidence is immutable even while the version is open
  begin
    update document_versions set raw_text = 'tampered' where id = '31000000-0000-0000-0000-000000000003';
    raise exception 'FAIL: raw_text changed';
  exception when sqlstate '23000' then null; end;
  begin
    update document_versions set original_file = '{"storage_path": "other"}' where id = '31000000-0000-0000-0000-000000000003';
    raise exception 'FAIL: original_file changed';
  exception when sqlstate '23000' then null; end;

  -- submit: other supporter refused, owner ok
  begin
    perform submit_version_for_review('31000000-0000-0000-0000-000000000003', '00000000-0000-0000-0000-0000000000b3');
    raise exception 'FAIL: supporter submitted someone else''s version';
  exception when sqlstate '42501' then null; end;
  perform submit_version_for_review('31000000-0000-0000-0000-000000000003', '00000000-0000-0000-0000-0000000000b2');
  assert (select verification_status from document_versions where id = '31000000-0000-0000-0000-000000000003') = 'pending_review';

  -- OCR-derived content cannot be approved until fields are confirmed
  begin
    perform approve_document_version('31000000-0000-0000-0000-000000000003', '00000000-0000-0000-0000-0000000000b1');
    raise exception 'FAIL: unconfirmed OCR approved';
  exception when sqlstate '55000' then null; end;

  -- request changes -> draft with note; supporters cannot do it
  begin
    perform request_version_changes('31000000-0000-0000-0000-000000000003', '00000000-0000-0000-0000-0000000000b2', 'fix it');
    raise exception 'FAIL: supporter requested changes';
  exception when sqlstate '42501' then null; end;
  perform request_version_changes('31000000-0000-0000-0000-000000000003', '00000000-0000-0000-0000-0000000000b1', 'Fix the date');
  assert (select verification_status || ':' || review_note from document_versions
           where id = '31000000-0000-0000-0000-000000000003') = 'draft:Fix the date';
  update document_versions set structured_data = '{"fields_confirmed": true}' where id = '31000000-0000-0000-0000-000000000003';
  perform submit_version_for_review('31000000-0000-0000-0000-000000000003', '00000000-0000-0000-0000-0000000000b2');
  perform approve_document_version('31000000-0000-0000-0000-000000000003', '00000000-0000-0000-0000-0000000000b1');
  assert (select indexing_status from document_versions where id = '31000000-0000-0000-0000-000000000003') = 'indexed';
  assert (select details ->> 'previous_status' from audit_log where action = 'version.approve'
           and entity_id = '31000000-0000-0000-0000-000000000003') = 'pending_review', 'approve audit has statuses';
  assert exists (select 1 from audit_log where action = 'version.request_changes'), 'request changes audited';
  begin
    update document_versions set structured_data = '{}' where id = '31000000-0000-0000-0000-000000000003';
    raise exception 'FAIL: approved structured_data changed';
  exception when sqlstate '23000' then null; end;

  perform approve_document_version('31000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-0000000000b1');
  perform approve_document_version('31000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-0000000000b1');
end $$;

-- search v2: exact identifier on word boundaries, citation = notice URL, scope / authority filters
do $$
declare r record;
begin
  select * into r from search_knowledge_v2(null, array['visa'], array['D-2'], 'm', null, null, null, 5, 'keyword') limit 1;
  assert r.document_title = 'D-2 visa notice' and r.exact_match, 'D-2 ranks first with exact match';
  assert r.source_url like '%admin_mode=read&no=1%', 'citation is the individual notice URL';
  assert not exists (select 1 from search_knowledge_v2(null, null, array['D-2'], 'm', null, null, null, 5, 'keyword')
                      where document_title = 'D-4 notice'), 'D-4 does not match D-2';
  assert (select count(*) from search_knowledge_v2(null, array['visa'], array['D-2'], 'm', null, 'national', null, 5, 'keyword')) = 0,
    'scope filter';
  assert (select count(*) from search_knowledge_v2(pg_temp.vec(3), null, null, 'm', null, null,
                                                    array['staff_communication'], 5, 'vector')) = 1, 'authority filter';
  assert (select count(*) from search_knowledge_v2(null, null, array['x''; drop table x; --'], 'm', null, null, null, 5,
                                                    'keyword')) = 0, 'unsafe exact term ignored';
  -- v1 keeps working (compat) and also cites the notice URL
  select * into r from search_knowledge(pg_temp.vec(1), array['visa'], 'm', null, 3, 'hybrid') limit 1;
  assert r.document_title = 'D-2 visa notice' and r.source_url like '%no=1%', 'v1 compatibility';
  assert (knowledge_stats() ->> 'documents_approved')::int = (select count(*) from source_documents where current_version_id is not null and not is_canceled), 'stats count approved docs';
  assert (knowledge_stats() ->> 'searchable_chunks')::int = (select count(*) from searchable_chunks) and (select count(*) from searchable_chunks where source_id = '11000000-0000-0000-0000-000000000001') = 2, 'stats count searchable chunks';
end $$;

-- persistent job queue: claim, skip locked, stale re-queue, attempts limit
-- (one active ingest job per source since 0012, so the stale jobs belong to their own sources)
insert into knowledge_sources (id, title, organization, source_type, authority_type, scope, category) values
  ('11000000-0000-0000-0000-0000000000a2', 'Queue A', 'SCH', 'pdf', 'official_university', 'university', 'academic-life'),
  ('11000000-0000-0000-0000-0000000000a3', 'Queue B', 'SCH', 'pdf', 'official_university', 'university', 'academic-life');
insert into ingestion_jobs (id, source_id, status, job_type) values
  ('51000000-0000-0000-0000-000000000001', '11000000-0000-0000-0000-000000000001', 'queued', 'board_sync');
insert into ingestion_jobs (id, source_id, status, attempts, max_attempts, heartbeat_at, started_at) values
  ('51000000-0000-0000-0000-000000000002', '11000000-0000-0000-0000-0000000000a2', 'running', 1, 3, now() - interval '2 hours', now() - interval '2 hours'),
  ('51000000-0000-0000-0000-000000000003', '11000000-0000-0000-0000-0000000000a3', 'running', 3, 3, now() - interval '2 hours', now() - interval '2 hours');
do $$
declare j ingestion_jobs;
begin
  select * into j from claim_ingestion_job('worker-a', 900);
  assert j.id = '51000000-0000-0000-0000-000000000001' and j.status = 'running' and j.attempts = 1 and j.locked_by = 'worker-a',
    'claims the oldest queued job';
  assert (select status from ingestion_jobs where id = '51000000-0000-0000-0000-000000000002') = 'queued', 'stale job re-queued';
  assert (select status || ':' || error_code from ingestion_jobs where id = '51000000-0000-0000-0000-000000000003') = 'failed:interrupted',
    'stale job over the attempt limit fails';
  select * into j from claim_ingestion_job('worker-b', 900);
  assert j.id = '51000000-0000-0000-0000-000000000002' and j.attempts = 2, 're-queued job claimed again';
  assert (select count(*) from claim_ingestion_job('worker-c', 900)) = 0, 'nothing left';
end $$;

-- grants: new objects are server-only for anon/student
insert into ingestion_events (job_id, step, message) values ('51000000-0000-0000-0000-000000000001', 'start', 'x');
insert into allowed_source_domains (domain) values ('example.go.kr');
do $$ begin
  begin insert into allowed_source_domains (domain) values ('not a domain');
        raise exception 'FAIL: invalid domain accepted';
  exception when check_violation then null; end;
end $$;
set local role anon;
do $$ begin
  begin perform * from ingestion_events; raise exception 'FAIL anon read events';
  exception when insufficient_privilege then null; end;
  begin perform claim_ingestion_job('x', 60); raise exception 'FAIL anon claimed job';
  exception when insufficient_privilege then null; end;
  begin perform search_knowledge_v2(null, array['visa'], null, 'm'); raise exception 'FAIL anon called search v2';
  exception when insufficient_privilege then null; end;
  begin perform knowledge_stats(); raise exception 'FAIL anon stats';
  exception when insufficient_privilege then null; end;
end $$;
reset role;
set local role authenticated;
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-0000000000b2', true);   -- supporter
do $$ begin
  assert (select count(*) from ingestion_events) = 0, 'supporter sees no events via PostgREST';
  assert (select count(*) from allowed_source_domains) = 0, 'supporter sees no allowlist via PostgREST';
end $$;
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-0000000000b1', true);   -- admin
do $$ begin
  assert (select count(*) from ingestion_events) = 1, 'admin reads events';
end $$;
reset role;

select 'ALL PHASE 2 SQL BEHAVIOUR TESTS PASSED' as result;
rollback;
