-- READ-ONLY, one SELECT. Board notices whose stored public attachment list (or notice number) is not the one recorded with
-- their approved version. How to run it: docs/release/release-a-production-checks.md
--   why = 'differs'      : students may see other attachments than the approved ones (Release A shows the approved ones)
--   why = 'not recorded' : the approved version has no recorded list (very old import); compare it with the text by hand
select d.id as document_id, d.title, cv.version_number as approved_version,
       (select string_agg(a ->> 'name', ', ') from jsonb_array_elements(coalesce(nullif(d.metadata -> 'attachments', 'null'), '[]')) a) as public_attachments,
       (select string_agg(a ->> 'name', ', ') from jsonb_array_elements(coalesce(nullif(cv.extraction_meta -> 'attachments', 'null'), '[]')) a) as approved_attachments,
       d.metadata ->> 'notice_no' as public_notice_no, cv.extraction_meta ->> 'notice_no' as approved_notice_no,
       case when cv.extraction_meta ? 'attachments' then 'differs' else 'not recorded' end as why
  from public.source_documents d
  join public.document_versions cv on cv.id = d.current_version_id
  join public.knowledge_sources s on s.id = d.source_id
 where s.source_type = 'sch_board' and not d.is_canceled
   and (not (cv.extraction_meta ? 'attachments')
        or coalesce(nullif(d.metadata -> 'attachments', 'null'), '[]') is distinct from coalesce(nullif(cv.extraction_meta -> 'attachments', 'null'), '[]')
        or (d.metadata ->> 'notice_no') is distinct from (cv.extraction_meta ->> 'notice_no'))
 order by why, d.title;
