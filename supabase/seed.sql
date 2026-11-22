-- =============================================================================
-- Development seed data. Safe to re-run (idempotent).
--
--  * Categories: reference data used by the whole app.
--  * Candidate sources: REGISTRATIONS ONLY. No content has been fetched or
--    verified; they carry status 'registered' until an admin ingests + reviews.
--  * Sample announcement + sample pending document: clearly labelled TEST DATA.
--    They are NOT real SCH announcements and contain no real regulations.
-- =============================================================================

insert into public.categories (slug, name, description, sort_order) values
  ('visa-immigration',        'Visa & Immigration',          'Residence status, alien registration and immigration procedures', 10),
  ('part-time-employment',    'Part-Time Employment',        'Working while studying and labor rules',                          20),
  ('academic-life',           'Academic Life',               'Courses, registration, grades and academic regulations',          30),
  ('scholarships',            'Scholarships',                'Financial support and scholarship programs',                      40),
  ('dormitory-housing',       'Dormitory & Housing',         'On-campus dormitories and off-campus housing',                    50),
  ('health-insurance',        'Health & Insurance',          'National health insurance and medical care',                      60),
  ('topik-korean',            'TOPIK & Korean Language',     'TOPIK exams and Korean language learning',                        70),
  ('employment-internships',  'Employment & Internships',    'Jobs, internships and career support',                            80),
  ('banking-taxes',           'Banking & Taxes',             'Bank accounts, remittance and tax matters',                       90),
  ('daily-living',            'Daily Living',                'Transport, phones, shopping and everyday life',                  100),
  ('university-announcements','University Announcements',    'Official notices from the university',                           110)
on conflict (slug) do update
  set name = excluded.name, description = excluded.description, sort_order = excluded.sort_order;

-- Candidate official sources (registered only; nothing is crawled automatically).
insert into public.knowledge_sources
  (title, original_url, organization, source_type, authority_type, scope, category, language, sync_frequency)
values
  ('SCH Global Education - International notices (candidate)',
   'https://sgee.sch.ac.kr/notice/notice01.php?page=1&make=&search=&type=&table_name=noti_fore&loc_mnu=3',
   'Soonchunhyang University', 'website', 'official_university', 'university', 'university-announcements', 'ko', 'manual'),
  ('Study in Korea - Visa and Stay (candidate)',
   'https://www.studyinkorea.go.kr/en_US/plan/visaAndStay.do',
   'Study in Korea (NIIED)', 'website', 'official_government', 'national', 'visa-immigration', 'ko', 'manual'),  -- served in Korean when tested
  ('Hi Korea (candidate)',
   'https://www.hikorea.go.kr',
   'Hi Korea - Korea Immigration Service', 'website', 'official_government', 'national', 'visa-immigration', 'en', 'manual'),
  ('TOPIK official site (candidate)',
   'https://www.topik.go.kr',
   'TOPIK (NIIED)', 'website', 'official_government', 'national', 'topik-korean', 'en', 'manual'),
  ('National Health Insurance Service (candidate)',
   'https://www.nhis.or.kr',
   'National Health Insurance Service', 'website', 'official_government', 'national', 'health-insurance', 'ko', 'manual'),
  ('Ministry of Employment and Labor (candidate)',
   'https://www.moel.go.kr',
   'Ministry of Employment and Labor', 'website', 'official_government', 'national', 'part-time-employment', 'ko', 'manual')
on conflict do nothing;

-- ---------------------------------------------------------------------------
-- TEST DATA 1: one clearly-labelled sample announcement (published, no embedding)
-- ---------------------------------------------------------------------------
do $$
declare
  v_source uuid;
  v_doc uuid;
  v_ver uuid;
  v_text text := E'[샘플 / 테스트 데이터] 이 공지는 개발용 예시이며 실제 순천향대학교 공지가 아닙니다.\n\n## 안내\n이 항목은 공지 목록과 상세 화면 레이아웃을 확인하기 위한 테스트 데이터입니다. 신청 기간, 대상, 절차 등 어떠한 내용도 사실이 아닙니다.\n\n## SAMPLE / TEST DATA\nThis is development sample content to demonstrate the announcement layout. It is not an official SCH notice and contains no real dates, rules, or requirements.';
begin
  if exists (select 1 from public.source_documents where external_id = 'sample-announcement-001') then
    return;
  end if;

  insert into public.knowledge_sources
    (title, organization, source_type, authority_type, scope, category, language, is_test_data, status)
  values ('SAMPLE manual submissions (TEST DATA)', 'Development sample', 'manual_text', 'other',
          'university', 'university-announcements', 'ko', true, 'approved')
  returning id into v_source;

  insert into public.source_documents (source_id, external_id, title, language, document_type)
  values (v_source, 'sample-announcement-001', '[SAMPLE - TEST DATA] Announcement layout example', 'ko', 'announcement')
  returning id into v_doc;

  insert into public.document_versions
    (document_id, version_number, extracted_text, content_hash, verification_status, was_approved, approved_at,
     source_published_at, fetched_at)
  values (v_doc, 1, v_text, encode(sha256(convert_to(v_text, 'UTF8')), 'hex'), 'approved', true, now(), now(), now())
  returning id into v_ver;

  update public.source_documents set current_version_id = v_ver where id = v_doc;

  insert into public.document_chunks (version_id, chunk_index, heading, content, content_hash, token_count)
  values (v_ver, 0, null, v_text, encode(sha256(convert_to(v_text, 'UTF8')), 'hex'), 120);

  insert into public.announcements
    (document_id, title, category, target_audience, event_date, deadline, publication_status,
     original_language, source_type, evidence_note, is_test_data, submitted_at, approved_at)
  values (v_doc, '[SAMPLE - TEST DATA] Announcement layout example', 'university-announcements',
          'Nobody - sample only', current_date + 14, current_date + 30, 'published', 'ko', 'manual_text',
          'Development sample. Not an official source.', true, now(), now());
end $$;

-- ---------------------------------------------------------------------------
-- TEST DATA 2: one sample document waiting in the review queue (no embeddings yet:
-- an admin must press "Reprocess" before the backend lets it be approved)
-- ---------------------------------------------------------------------------
do $$
declare
  v_source uuid;
  v_doc uuid;
  v_ver uuid;
  v_text text := E'## SAMPLE pending document (TEST DATA)\nThis document exists only to demonstrate the review queue. It is not official guidance and contains no real regulations.\n\n## How to use\nOpen it in Admin > Review Queue, press Reprocess to chunk and embed it, then Approve or Reject.';
begin
  if exists (select 1 from public.source_documents where external_id = 'sample-pending-001') then
    return;
  end if;

  insert into public.knowledge_sources
    (title, organization, source_type, authority_type, scope, category, language, is_test_data, status)
  values ('SAMPLE pending review (TEST DATA)', 'Development sample', 'manual_text', 'other',
          'national', 'daily-living', 'en', true, 'pending_review')
  returning id into v_source;

  insert into public.source_documents (source_id, external_id, title, language, document_type)
  values (v_source, 'sample-pending-001', '[SAMPLE - TEST DATA] Pending review document', 'en', 'manual_text')
  returning id into v_doc;

  insert into public.document_versions
    (document_id, version_number, extracted_text, content_hash, verification_status)
  values (v_doc, 1, v_text, encode(sha256(convert_to(v_text, 'UTF8')), 'hex'), 'pending_review')
  returning id into v_ver;

  insert into public.document_chunks (version_id, chunk_index, heading, content, content_hash, token_count)
  values (v_ver, 0, 'SAMPLE pending document (TEST DATA)', v_text, encode(sha256(convert_to(v_text, 'UTF8')), 'hex'), 70);
end $$;
