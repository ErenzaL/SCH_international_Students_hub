-- READ-ONLY, one SELECT. Published documents whose public title may come from a version that was never approved (before
-- Release A, a re-import changed the public title at once). How to run it: docs/release/release-a-production-checks.md
--   newer_unapproved : newer versions that wait, were rejected, or were replaced without ever being approved
--   approved_heading : first heading of the approved text (usually the approved title), for comparison
select d.id as document_id, d.title as public_title,
       case when cv.extracted_text like '#%'
            then regexp_replace(split_part(cv.extracted_text, E'\n', 1), '^#+\s*', '') end as approved_heading,
       cv.version_number as approved_version,
       (select string_agg('v' || v.version_number || ':' || v.verification_status, ', ' order by v.version_number)
          from public.document_versions v
         where v.document_id = d.id and v.version_number > cv.version_number and not v.was_approved) as newer_unapproved,
       case when cv.extracted_text like '#%'
             and regexp_replace(split_part(cv.extracted_text, E'\n', 1), '^#+\s*', '') <> d.title
            then 'title differs from the approved text' else 'a newer version was never approved' end as why
  from public.source_documents d
  join public.document_versions cv on cv.id = d.current_version_id
 where d.document_type <> 'announcement' and not d.is_canceled
   and (exists (select 1 from public.document_versions v
                 where v.document_id = d.id and v.version_number > cv.version_number and not v.was_approved)
        or (cv.extracted_text like '#%'
            and regexp_replace(split_part(cv.extracted_text, E'\n', 1), '^#+\s*', '') <> d.title))
 order by why desc, d.title;
