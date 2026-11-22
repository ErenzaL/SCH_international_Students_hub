-- Migration 0012: one active ingest job per uploaded file and per source; history rows unaffected. Rolled back.
\set ON_ERROR_STOP on
begin;
insert into knowledge_sources (id, title, organization, source_type, authority_type, scope, category) values
  ('17000000-0000-0000-0000-000000000001', 'PDF A', 'SCH', 'pdf', 'official_university', 'university', 'visa-immigration'),
  ('17000000-0000-0000-0000-000000000002', 'PDF B', 'SCH', 'pdf', 'official_university', 'university', 'visa-immigration');
insert into ingestion_jobs (source_id, status, job_type, payload) values
  ('17000000-0000-0000-0000-000000000001', 'running', 'ingest', '{"sha256": "aaa"}');
do $$ begin
  -- the same file again (another source) while the first job is active
  begin insert into ingestion_jobs (source_id, status, job_type, payload)
        values ('17000000-0000-0000-0000-000000000002', 'queued', 'ingest', '{"sha256": "aaa"}');
        raise exception 'FAIL: second active job for the same file';
  exception when unique_violation then null; end;
  -- a second active job for the same source
  begin insert into ingestion_jobs (source_id, status, job_type, payload)
        values ('17000000-0000-0000-0000-000000000001', 'queued', 'ingest', '{"sha256": "bbb"}');
        raise exception 'FAIL: second active job for the same source';
  exception when unique_violation then null; end;
  -- finished jobs are history and never block anything
  insert into ingestion_jobs (source_id, status, job_type, payload) values
    ('17000000-0000-0000-0000-000000000002', 'failed', 'ingest', '{"sha256": "aaa"}'),
    ('17000000-0000-0000-0000-000000000002', 'succeeded', 'ingest', '{"sha256": "aaa"}');
  -- other job types (indexing, translations) are not affected by the per-source rule
  insert into ingestion_jobs (source_id, status, job_type, payload) values
    ('17000000-0000-0000-0000-000000000001', 'queued', 'index_version', '{"version_id": "00000000-0000-0000-0000-000000000000"}');
  -- after the active job finishes, the file can be processed again (e.g. a retry)
  update ingestion_jobs set status = 'failed' where source_id = '17000000-0000-0000-0000-000000000001' and job_type = 'ingest';
  insert into ingestion_jobs (source_id, status, job_type, payload)
  values ('17000000-0000-0000-0000-000000000002', 'queued', 'ingest', '{"sha256": "aaa"}');
end $$;
select 'ALL INGESTION JOB SQL BEHAVIOUR TESTS PASSED' as result;
rollback;
