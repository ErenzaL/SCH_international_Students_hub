-- READ-ONLY. Published documents whose public title may come from a version that was never approved (before Release A,
-- re-ingestion changed the public title at once). Run it before and after the deployment; it changes nothing.
--   newer_unapproved : a newer version exists that is waiting, rejected or was replaced without ever being approved
--   first_line       : first line of the approved text (usually "# <approved title>"), for comparison
begin transaction read only;
select d.id as document_id, d.title as public_title,
       regexp_replace(split_part(cv.extracted_text, E'\n', 1), '^#+\s*', '') as first_line,
       cv.version_number as approved_version,
       (select string_agg('v' || v.version_number || ':' || v.verification_status, ', ' order by v.version_number)
          from public.document_versions v
         where v.document_id = d.id and v.version_number > cv.version_number and not v.was_approved) as newer_unapproved
  from public.source_documents d
  join public.document_versions cv on cv.id = d.current_version_id
 where d.document_type <> 'announcement' and not d.is_canceled
   and (exists (select 1 from public.document_versions v
                 where v.document_id = d.id and v.version_number > cv.version_number and not v.was_approved)
        or (cv.extracted_text like '#%'
            and regexp_replace(split_part(cv.extracted_text, E'\n', 1), '^#+\s*', '') <> d.title))
 order by d.title;
rollback;
