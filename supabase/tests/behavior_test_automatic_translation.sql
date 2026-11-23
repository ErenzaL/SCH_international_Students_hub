-- Migration 0013 (automatic translation) checks: new statuses / scope / provenance columns, one open job per
-- translation row, students never see machine or needs_review rows through RLS, and the migration re-runs cleanly.
-- Scratch DB only.
\set ON_ERROR_STOP on
begin;

insert into auth.users (id, email) values ('00000000-0000-0000-0000-0000000013a1', 'admin13@example.test');
update profiles set role = 'admin' where id = '00000000-0000-0000-0000-0000000013a1';
insert into knowledge_sources (id, title, organization, source_type, authority_type, scope, category)
values ('17000000-0000-0000-0000-000000000001', 'Notices', 'SCH', 'manual_text', 'official_university', 'university',
        'scholarships');
insert into source_documents (id, source_id, external_id, title, language) values
  ('27000000-0000-0000-0000-000000000001', '17000000-0000-0000-0000-000000000001', 'notice-13', '장학금 안내', 'ko');
insert into document_versions (id, document_id, version_number, extracted_text, content_hash) values
  ('37000000-0000-0000-0000-000000000001', '27000000-0000-0000-0000-000000000001', 1, '장학금 신청', repeat('b', 64));
insert into document_chunks (version_id, chunk_index, content, content_hash, embedding, embedding_model)
select '37000000-0000-0000-0000-000000000001', 0, '장학금 신청', 'h13',
       ('[' || string_agg(case when i = 1 then '1' else '0' end, ',') || ']')::extensions.vector, 'm'
  from generate_series(1, 384) i;
do $$ begin
  perform approve_document_version('37000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-0000000013a1');
end $$;
insert into announcements (id, document_id, title, category, publication_status)
values ('47000000-0000-0000-0000-000000000001', '27000000-0000-0000-0000-000000000001', '장학금 안내', 'scholarships',
        'published');

-- machine translation that failed the automated checks; a summary-only document translation
insert into announcement_translations (id, announcement_id, language_code, title, body, translation_status,
                                       source_content_hash, provider, model, generated_at, warnings)
values ('57000000-0000-0000-0000-000000000001', '47000000-0000-0000-0000-000000000001', 'en', 'Scholarship', 'Apply',
        'needs_review', repeat('c', 64), 'gemini', 'some-model', now(), '[{"type": "number", "value": "15"}]');
insert into document_translations (id, document_id, version_id, source_version_number, source_content_hash,
                                   language_code, title, body, translation_status, scope, provider, model)
values ('67000000-0000-0000-0000-000000000001', '27000000-0000-0000-0000-000000000001',
        '37000000-0000-0000-0000-000000000001', 1, repeat('b', 64), 'en', 'Scholarship notice', '- summary',
        'needs_review', 'summary', 'gemini', 'some-model');

do $$
declare n int;
begin
  -- defaults for rows written by code that predates 0013
  insert into announcement_translations (announcement_id, language_code, title, body, translation_status)
  values ('47000000-0000-0000-0000-000000000001', 'vi', '', '', 'todo');
  select count(*) into n from announcement_translations where language_code = 'vi' and warnings = '[]'::jsonb and provider is null;
  if n <> 1 then raise exception 'FAIL: announcement translation defaults'; end if;
  select count(*) into n from document_translations where scope = 'full';
  if n <> 0 then raise exception 'FAIL: unexpected full rows'; end if;
  -- unknown status / scope are rejected
  begin update announcement_translations set translation_status = 'published' where language_code = 'vi';
        raise exception 'FAIL: unknown announcement translation status accepted';
  exception when check_violation then null; end;
  begin update document_translations set scope = 'partial' where id = '67000000-0000-0000-0000-000000000001';
        raise exception 'FAIL: unknown scope accepted';
  exception when check_violation then null; end;
  -- one open job per translation row
  insert into ingestion_jobs (source_id, status, job_type, payload)
  values ('17000000-0000-0000-0000-000000000001', 'queued', 'translate_announcement',
          '{"translation_id": "57000000-0000-0000-0000-000000000001"}');
  begin
    insert into ingestion_jobs (source_id, status, job_type, payload)
    values ('17000000-0000-0000-0000-000000000001', 'queued', 'translate_announcement',
            '{"translation_id": "57000000-0000-0000-0000-000000000001"}');
    raise exception 'FAIL: two open jobs for one translation';
  exception when unique_violation then null; end;
  -- a finished job does not block the next one
  update ingestion_jobs set status = 'succeeded', outcome = 'translated'
   where payload->>'translation_id' = '57000000-0000-0000-0000-000000000001';
  insert into ingestion_jobs (source_id, status, job_type, payload)
  values ('17000000-0000-0000-0000-000000000001', 'queued', 'translate_announcement',
          '{"translation_id": "57000000-0000-0000-0000-000000000001"}');
  begin insert into ingestion_jobs (source_id, status, job_type) values
        ('17000000-0000-0000-0000-000000000001', 'queued', 'translate_everything');
        raise exception 'FAIL: unknown job type accepted';
  exception when check_violation then null; end;
end $$;

-- students (anon) never see machine / needs_review rows directly: only human-approved, current ones
set local role anon;
do $$ declare n int; begin
  select count(*) into n from announcement_translations;
  if n <> 0 then raise exception 'FAIL: anon sees unreviewed announcement translations'; end if;
  select count(*) into n from document_translations;
  if n <> 0 then raise exception 'FAIL: anon sees unreviewed document translations'; end if;
end $$;
reset role;

-- re-running the migration is harmless (idempotent) and keeps the data
\i supabase/migrations/20261123000013_automatic_translation.sql
do $$ declare n int; begin
  select count(*) into n from announcement_translations where translation_status = 'needs_review' and provider = 'gemini';
  if n <> 1 then raise exception 'FAIL: data changed by re-running 0013'; end if;
end $$;

select 'ALL AUTOMATIC TRANSLATION SQL BEHAVIOUR TESTS PASSED' as result;
rollback;
