-- Migration 0011 (document translations) checks: integrity guard, language-scoped approval, RLS. Scratch DB only.
\set ON_ERROR_STOP on
begin;

create function pg_temp.vec(p_hot int) returns extensions.vector language sql as $$
  select ('[' || string_agg(case when i = p_hot then '1' else '0' end, ',') || ']')::extensions.vector
  from generate_series(1, 384) i $$;

insert into auth.users (id, email) values
  ('00000000-0000-0000-0000-0000000011a1', 'admin11@example.test'),
  ('00000000-0000-0000-0000-0000000011b1', 'idsup11@example.test'),
  ('00000000-0000-0000-0000-0000000011b2', 'visup11@example.test'),
  ('00000000-0000-0000-0000-0000000011c1', 'student11@example.test');
update profiles set role = 'admin' where id = '00000000-0000-0000-0000-0000000011a1';
update profiles set role = 'supporter' where id in ('00000000-0000-0000-0000-0000000011b1', '00000000-0000-0000-0000-0000000011b2');
insert into supporter_languages (supporter_id, language_code, can_support, can_review_translations) values
  ('00000000-0000-0000-0000-0000000011b1', 'id', true, true),
  ('00000000-0000-0000-0000-0000000011b2', 'vi', true, false);   -- vi: may edit, may NOT approve

insert into knowledge_sources (id, title, original_url, organization, source_type, authority_type, scope, category)
values ('16000000-0000-0000-0000-000000000001', 'Study in Korea', 'https://www.studyinkorea.go.kr/v', 'NIIED',
        'website', 'official_government', 'national', 'visa-immigration');
insert into source_documents (id, source_id, canonical_url, title, language) values
  ('26000000-0000-0000-0000-000000000001', '16000000-0000-0000-0000-000000000001', 'https://www.studyinkorea.go.kr/v',
   'Visa and Stay', 'en');
insert into document_versions (id, document_id, version_number, extracted_text, content_hash) values
  ('36000000-0000-0000-0000-000000000001', '26000000-0000-0000-0000-000000000001', 1, 'visa rules v1', repeat('a', 64));
insert into document_chunks (version_id, chunk_index, content, content_hash, embedding, embedding_model)
values ('36000000-0000-0000-0000-000000000001', 0, 'visa rules v1', 'h1', pg_temp.vec(3), 'm');
do $$ begin
  perform approve_document_version('36000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-0000000011a1');
end $$;
insert into document_translations (id, document_id, version_id, source_version_number, source_content_hash,
                                   language_code, title, body, translation_status) values
  ('46000000-0000-0000-0000-000000000001', '26000000-0000-0000-0000-000000000001',
   '36000000-0000-0000-0000-000000000001', 1, repeat('a', 64), 'id', 'Visa dan Izin Tinggal', 'aturan visa', 'in_review'),
  ('46000000-0000-0000-0000-000000000002', '26000000-0000-0000-0000-000000000001',
   '36000000-0000-0000-0000-000000000001', 1, repeat('a', 64), 'vi', 'Thị thực', 'quy định', 'machine_draft');

do $$
begin
  -- a translation must point at a version of its own document
  begin insert into document_translations (document_id, version_id, source_version_number, source_content_hash, language_code)
        values ('26000000-0000-0000-0000-000000000001', '36000000-0000-0000-0000-000000000001', 1, 'x', 'id');
        raise exception 'FAIL: duplicate (version, language)';
  exception when unique_violation then null; end;
  -- non-todo rows need content; approval needs reviewer + original check
  begin update document_translations set title = '' where id = '46000000-0000-0000-0000-000000000001';
        raise exception 'FAIL: empty title accepted';
  exception when check_violation then null; end;
  begin update document_translations set translation_status = 'human_approved', reviewed_by = '00000000-0000-0000-0000-0000000011b1',
               reviewed_at = now() where id = '46000000-0000-0000-0000-000000000001';
        raise exception 'FAIL: approval without original verification';
  exception when check_violation then null; end;
  -- the vi supporter has support but not review permission: cannot approve
  begin update document_translations set translation_status = 'human_approved', original_verified = true,
               reviewed_by = '00000000-0000-0000-0000-0000000011b2', reviewed_at = now()
         where id = '46000000-0000-0000-0000-000000000002';
        raise exception 'FAIL: unassigned reviewer approved';
  exception when sqlstate '42501' then null; end;
  -- the id supporter cannot approve vi either
  begin update document_translations set translation_status = 'human_approved', original_verified = true,
               reviewed_by = '00000000-0000-0000-0000-0000000011b1', reviewed_at = now()
         where id = '46000000-0000-0000-0000-000000000002';
        raise exception 'FAIL: reviewer of another language approved';
  exception when sqlstate '42501' then null; end;
  -- ...but can approve id
  update document_translations set translation_status = 'human_approved', original_verified = true,
         reviewed_by = '00000000-0000-0000-0000-0000000011b1', reviewed_at = now()
   where id = '46000000-0000-0000-0000-000000000001';
  -- a translation stays linked to its version
  begin update document_translations set version_id = '36000000-0000-0000-0000-000000000002'
         where id = '46000000-0000-0000-0000-000000000001';
        raise exception 'FAIL: relinked to another version';
  exception when check_violation then null; end;
end $$;

-- RLS: anonymous visitors see only the approved, current translation; never drafts
set local role anon;
do $$ begin
  assert (select count(*) from document_translations) = 1, 'anon sees only the approved translation';
  assert (select language_code from document_translations) = 'id';
  begin perform 1 from document_translation_revisions; raise exception 'FAIL: anon read revisions';
  exception when insufficient_privilege then null; end;
  begin update document_translations set title = 'x'; raise exception 'FAIL: anon write';
  exception when insufficient_privilege then null; end;
end $$;
reset role;

set local role authenticated;
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-0000000011c1', true);   -- student
do $$ begin
  assert (select count(*) from document_translations) = 1, 'students see only the approved translation';
end $$;
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-0000000011b2', true);   -- vi supporter
do $$ begin
  assert (select count(*) from document_translations where language_code = 'vi') = 1, 'vi supporter sees vi draft';
  assert (select count(*) from document_translations) = 2, 'and the public id translation, nothing else';
  begin update document_translations set title = 'x' where language_code = 'vi'; raise exception 'FAIL: client write';
  exception when insufficient_privilege then null; end;
end $$;
reset role;

-- a new approved original version: the old translation is not public any more and can no longer be approved
insert into document_versions (id, document_id, version_number, extracted_text, content_hash) values
  ('36000000-0000-0000-0000-000000000002', '26000000-0000-0000-0000-000000000001', 2, 'visa rules v2', repeat('b', 64));
insert into document_chunks (version_id, chunk_index, content, content_hash, embedding, embedding_model)
values ('36000000-0000-0000-0000-000000000002', 0, 'visa rules v2', 'h2', pg_temp.vec(4), 'm');
do $$ begin
  perform approve_document_version('36000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-0000000011a1');
  update document_translations set is_outdated = true, outdated_at = now()
   where version_id = '36000000-0000-0000-0000-000000000001';
  begin update document_translations set translation_status = 'human_approved', original_verified = true,
               reviewed_by = '00000000-0000-0000-0000-0000000011b1', reviewed_at = now(), is_outdated = false
         where id = '46000000-0000-0000-0000-000000000002';
        raise exception 'FAIL: approved a translation of a superseded version';
  exception when sqlstate '55000' then null; end;
end $$;
set local role anon;
do $$ begin
  assert (select count(*) from document_translations) = 0, 'old translation no longer served';
end $$;
reset role;

-- jobs: the new type and outcome are accepted
insert into ingestion_jobs (source_id, status, job_type, outcome, payload)
values ('16000000-0000-0000-0000-000000000001', 'succeeded', 'translate_document', 'translated',
        '{"translation_id": "46000000-0000-0000-0000-000000000002"}');

select 'ALL DOCUMENT TRANSLATION SQL BEHAVIOUR TESTS PASSED' as result;
rollback;
