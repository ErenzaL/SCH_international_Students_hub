-- Behavioural checks for the migrations. Run against a scratch DB that has the
-- local shim + migrations + seed applied (see docs/database.md). Everything runs
-- in one transaction that is rolled back; any failed assert aborts with an error.
\set ON_ERROR_STOP on
begin;

create function pg_temp.vec(p_hot int) returns extensions.vector language sql as $$
  select ('[' || string_agg(case when i = p_hot then '1' else '0' end, ',') || ']')::extensions.vector
  from generate_series(1, 384) i $$;

insert into auth.users (id, email) values
  ('00000000-0000-0000-0000-0000000000a1', 'root@example.test'),
  ('00000000-0000-0000-0000-0000000000a2', 'student@example.test'),
  ('00000000-0000-0000-0000-0000000000a3', 'admin@example.test');
do $$ begin
  assert (select role from profiles where id = '00000000-0000-0000-0000-0000000000a2') = 'student', 'new users must be students';
end $$;
update profiles set role = 'super_admin' where id = '00000000-0000-0000-0000-0000000000a1';
update profiles set role = 'admin'       where id = '00000000-0000-0000-0000-0000000000a3';

insert into knowledge_sources (id, title, organization, source_type, authority_type, scope, category, language, is_test_data)
values ('10000000-0000-0000-0000-000000000001','T src','Org','manual_text','other','national','daily-living','en', true);
insert into source_documents (id, source_id, external_id, title) values
  ('20000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001','doc-1','Doc one');

-- v1 pending with chunk but NO embedding -> approval must fail (not_indexed)
insert into document_versions (id, document_id, version_number, extracted_text, content_hash) values
  ('30000000-0000-0000-0000-000000000001','20000000-0000-0000-0000-000000000001',1,'alien registration card application', repeat('a',64));
insert into document_chunks (id, version_id, chunk_index, content, content_hash)
values ('40000000-0000-0000-0000-000000000001','30000000-0000-0000-0000-000000000001',0,'alien registration card application','h1');

do $$ begin
  begin
    perform approve_document_version('30000000-0000-0000-0000-000000000001','00000000-0000-0000-0000-0000000000a3');
    raise exception 'FAIL: approve without embeddings succeeded';
  exception when sqlstate '55000' then null; end;
  begin
    perform approve_document_version('30000000-0000-0000-0000-000000000001','00000000-0000-0000-0000-0000000000a2');
    raise exception 'FAIL: student approved';
  exception when sqlstate '42501' then null; end;
end $$;

-- not searchable while pending
do $$ begin
  assert (select count(*) from search_knowledge(pg_temp.vec(1), array['alien'], 'm', null, 5, 'hybrid')) = 0, 'pending content must not be searchable';
end $$;

update document_chunks set embedding = pg_temp.vec(1), embedding_model = 'm' where id = '40000000-0000-0000-0000-000000000001';
select approve_document_version('30000000-0000-0000-0000-000000000001','00000000-0000-0000-0000-0000000000a3','ok');

do $$ begin
  assert (select count(*) from search_knowledge(pg_temp.vec(1), array['alien'], 'm', null, 5, 'hybrid')) = 1, 'approved content searchable';
  assert (select count(*) from search_knowledge(pg_temp.vec(1), array['alien'], 'other-model', null, 5, 'vector')) = 0, 'vectors of another model are ignored';
  assert (select count(*) from search_knowledge(null, array['registration'], 'm', 'visa-immigration', 5, 'keyword')) = 0, 'category filter';
  assert (select count(*) from search_knowledge(null, array['registration'], 'm', 'daily-living', 5, 'keyword')) = 1, 'keyword leg';
  assert (select count(*) from search_knowledge(null, array['card'], 'm', null, 5, 'keyword')) = 1, 'keyword leg 2';
end $$;

-- v2 arrives: new pending version must not touch the current approved version
insert into document_versions (id, document_id, version_number, extracted_text, content_hash) values
  ('30000000-0000-0000-0000-000000000002','20000000-0000-0000-0000-000000000001',2,'alien registration card renewal rules', repeat('b',64));
insert into document_chunks (id, version_id, chunk_index, content, content_hash, embedding, embedding_model)
values ('40000000-0000-0000-0000-000000000002','30000000-0000-0000-0000-000000000002',0,'alien registration card renewal rules','h2', pg_temp.vec(2), 'm');
do $$ begin
  assert (select current_version_id from source_documents where id='20000000-0000-0000-0000-000000000001') = '30000000-0000-0000-0000-000000000001';
  assert (select count(*) from search_knowledge(pg_temp.vec(2), array['renewal'], 'm', null, 5, 'hybrid')) = 1, 'only approved v1 is searchable';
  assert (select passage from search_knowledge(pg_temp.vec(2), array['renewal'], 'm', null, 5, 'hybrid') limit 1) like '%application', 'v1 text served';
  begin  -- immutability of approved text
    update document_versions set extracted_text = 'tampered' where id = '30000000-0000-0000-0000-000000000001';
    raise exception 'FAIL: approved text rewritten';
  exception when sqlstate '23000' then null; end;
  begin  -- a second open version is refused
    insert into document_versions (document_id, version_number, extracted_text, content_hash)
    values ('20000000-0000-0000-0000-000000000001',3,'x',repeat('c',64));
    raise exception 'FAIL: two open versions';
  exception when unique_violation then null; end;
end $$;

select approve_document_version('30000000-0000-0000-0000-000000000002','00000000-0000-0000-0000-0000000000a1');
do $$ begin
  assert (select verification_status from document_versions where id='30000000-0000-0000-0000-000000000001') = 'superseded';
  assert (select current_version_id from source_documents where id='20000000-0000-0000-0000-000000000001') = '30000000-0000-0000-0000-000000000002';
  assert (select passage from search_knowledge(pg_temp.vec(2), array['renewal'], 'm', null, 5, 'hybrid') limit 1) like '%renewal%';
end $$;

-- rollback to approved v1
select rollback_document_version('20000000-0000-0000-0000-000000000001','30000000-0000-0000-0000-000000000001','00000000-0000-0000-0000-0000000000a3');
do $$ begin
  assert (select current_version_id from source_documents where id='20000000-0000-0000-0000-000000000001') = '30000000-0000-0000-0000-000000000001';
  assert (select verification_status from document_versions where id='30000000-0000-0000-0000-000000000002') = 'superseded';
  assert (select count(*) from audit_log where entity_id = '20000000-0000-0000-0000-000000000001') = 1, 'rollback audited';
  begin
    update audit_log set action = 'x';
    raise exception 'FAIL: audit log mutable';
  exception when sqlstate '42501' then null; end;
end $$;

-- cancel -> no longer searchable
select cancel_document('20000000-0000-0000-0000-000000000001','00000000-0000-0000-0000-0000000000a3','test');
do $$ begin
  assert (select count(*) from search_knowledge(pg_temp.vec(1), array['alien'], 'm', null, 5, 'hybrid')) = 0, 'canceled content hidden';
end $$;

-- expired validity window hides content
insert into source_documents (id, source_id, external_id, title) values
  ('20000000-0000-0000-0000-000000000002','10000000-0000-0000-0000-000000000001','doc-2','Doc two');
insert into document_versions (id, document_id, version_number, extracted_text, content_hash, valid_until) values
  ('30000000-0000-0000-0000-000000000003','20000000-0000-0000-0000-000000000002',1,'expired thing', repeat('d',64), now() + interval '1 hour');
insert into document_chunks (version_id, chunk_index, content, content_hash, embedding, embedding_model)
values ('30000000-0000-0000-0000-000000000003',0,'expired thing','h3', pg_temp.vec(3), 'm');
select approve_document_version('30000000-0000-0000-0000-000000000003','00000000-0000-0000-0000-0000000000a3');
do $$ begin
  assert (select count(*) from search_knowledge(null, array['expired'], 'm', null, 5, 'keyword')) = 1;
end $$;
update document_versions set valid_until = now() - interval '1 minute', valid_from = now() - interval '2 days'
 where id = '30000000-0000-0000-0000-000000000003';
do $$ begin
  assert (select count(*) from search_knowledge(null, array['expired'], 'm', null, 5, 'keyword')) = 0, 'expired hidden';
end $$;

-- announcement workflow
insert into source_documents (id, source_id, external_id, title, document_type) values
  ('20000000-0000-0000-0000-000000000003','10000000-0000-0000-0000-000000000001','ann-1','Ann','announcement');
insert into document_versions (id, document_id, version_number, extracted_text, content_hash, verification_status) values
  ('30000000-0000-0000-0000-000000000004','20000000-0000-0000-0000-000000000003',1,'scholarship notice', repeat('e',64),'draft');
insert into document_chunks (version_id, chunk_index, content, content_hash, embedding, embedding_model)
values ('30000000-0000-0000-0000-000000000004',0,'scholarship notice','h4', pg_temp.vec(4), 'm');
insert into announcements (id, document_id, title, category, created_by)
values ('50000000-0000-0000-0000-000000000001','20000000-0000-0000-0000-000000000003','Ann','scholarships','00000000-0000-0000-0000-0000000000a3');
select submit_announcement('50000000-0000-0000-0000-000000000001','00000000-0000-0000-0000-0000000000a3');
do $$ begin
  assert (select publication_status from announcements where id='50000000-0000-0000-0000-000000000001')='pending_approval';
  assert (select count(*) from search_knowledge(null, array['scholarship'], 'm', null, 5, 'keyword')) = 0, 'pending announcement hidden';
end $$;
select approve_announcement('50000000-0000-0000-0000-000000000001','00000000-0000-0000-0000-0000000000a3');
do $$ begin
  assert (select publication_status from announcements where id='50000000-0000-0000-0000-000000000001')='published';
  assert (select count(*) from search_knowledge(null, array['scholarship'], 'm', null, 5, 'keyword')) = 1;
end $$;

-- translations: human_approved needs a review timestamp
insert into announcement_translations (announcement_id, language_code, title, body)
values ('50000000-0000-0000-0000-000000000001','id','Judul','Isi');
do $$ begin
  begin
    update announcement_translations set translation_status='human_approved';
    raise exception 'FAIL: approved without review';
  exception when check_violation then null; end;
end $$;

-- ---------------------------------------------------------------- RLS checks
set local role anon;
do $$ begin
  assert (select count(*) from document_versions where document_id::text like '20000000%') = 1, 'anon sees only the one published+current fixture version (canceled/expired/superseded/pending hidden)';
  begin perform 1 from profiles; raise exception 'FAIL anon profiles'; exception when insufficient_privilege then null; end;
  begin perform 1 from audit_log; raise exception 'FAIL anon audit'; exception when insufficient_privilege then null; end;
  begin perform 1 from ingestion_jobs; raise exception 'FAIL anon jobs'; exception when insufficient_privilege then null; end;
  assert (select count(*) from announcements where publication_status <> 'published') = 0;
  assert (select count(*) from categories) = 11;
  begin perform * from document_chunks limit 1; raise exception 'FAIL anon chunk read'; exception when insufficient_privilege then null; end;
  begin perform search_knowledge(null, array['x'], 'm', null, 5, 'keyword'); raise exception 'FAIL anon rpc'; exception when insufficient_privilege then null; end;
  begin perform approve_document_version('30000000-0000-0000-0000-000000000002', null); raise exception 'FAIL anon approve'; exception when insufficient_privilege then null; end;
end $$;
reset role;

set local role authenticated;
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-0000000000a2', true);   -- the student
do $$ begin
  assert (select count(*) from profiles) = 1, 'student sees only own profile';
  assert (select count(*) from knowledge_sources where is_test_data is not null and created_by is not null) = 0;
  begin update profiles set role = 'admin' where id = '00000000-0000-0000-0000-0000000000a2';
        assert (select role from profiles where id='00000000-0000-0000-0000-0000000000a2') = 'student', 'FAIL: student self-promoted';
  exception when others then null; end;
  begin insert into knowledge_sources (title, organization, source_type, authority_type, scope, category) values ('x','y','manual_text','other','national','daily-living');
        raise exception 'FAIL student insert source';
  exception when insufficient_privilege or sqlstate '42501' then null; end;
end $$;
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-0000000000a3', true);   -- admin
do $$ begin
  assert (select count(*) from profiles) = 3, 'admin sees all profiles';
  assert (select count(*) from document_versions) >= 4, 'admin sees versions';
  begin update profiles set role='super_admin' where id='00000000-0000-0000-0000-0000000000a3';
        raise exception 'FAIL admin self-promoted to super_admin';
  exception when sqlstate '42501' then null; end;
end $$;
reset role;

select 'ALL SQL BEHAVIOUR TESTS PASSED' as result;
rollback;
