-- LAST-RESORT manual repair for diagnosis "A: text approved in document review" ONLY. Not needed once the release with
-- the fix is deployed: then an administrator simply presses Approve (or Cancel) under Admin -> Announcements.
--
-- What it does: marks the announcement published on top of the text approval that already exists. It changes ONE row
-- of public.announcements (publication_status, approved_by, approved_at) and adds ONE audit_log row that stores the
-- previous values. It does not touch the text, its versions, their approvals or the search index.
-- What it does NOT do (the app does these after Approve): create the translation tasks for the other languages and
-- notify their reviewers. That is the main reason to prefer deploying the fix.
--
-- Before: take a backup (docs/owner/FINAL-PRODUCTION-CHECKLIST.md section 2) and run diagnose-no-pending-version.sql;
-- continue only if query 1 says "A: ...". Replace <ADMIN_PROFILE_UUID> (twice) with the id of the administrator who
-- takes the decision (public.profiles.id). Run the block as a whole; it must report exactly one row, else ROLLBACK.

begin;
with target as (
  select a.id, a.publication_status, a.approved_by, a.approved_at, v.id as text_version_id
    from public.announcements a
    join public.source_documents d on d.id = a.document_id
    join lateral (select x.id, x.verification_status from public.document_versions x
                   where x.document_id = a.document_id order by x.version_number desc limit 1) v on true
   where a.id = '5597d191-b38a-401c-9c29-210550a6a2d6'
     and a.publication_status = 'pending_approval'
     and v.verification_status = 'approved' and v.id = d.current_version_id
     and not d.is_canceled and d.archived_at is null
     and not exists (select 1 from public.document_versions p
                      where p.document_id = a.document_id and p.verification_status = 'pending_review')
     for update of a
), upd as (
  update public.announcements a
     set publication_status = 'published', approved_by = '<ADMIN_PROFILE_UUID>', approved_at = now()
    from target t
   where a.id = t.id
  returning a.id
)
insert into public.audit_log (action, entity_type, entity_id, actor_id, details)
select 'announcement.approve', 'announcement', t.id, '<ADMIN_PROFILE_UUID>',
       jsonb_build_object('manual_repair', 'no pending version (ref 9cdb45f3bd55)',
                          'text_version_id', t.text_version_id, 'text_already_approved', true,
                          'previous', jsonb_build_object('publication_status', t.publication_status,
                                                         'approved_by', t.approved_by, 'approved_at', t.approved_at))
  from target t join upd u on u.id = t.id
returning id as audit_id, entity_id as announcement_id, details;
-- exactly 1 row returned -> COMMIT;   0 rows -> ROLLBACK; (the announcement was not in state A)
commit;


-- UNDO (only if the repair above must be reversed): restores the previous values stored in the repair's audit entry
-- and records the undo. Replace <ADMIN_PROFILE_UUID>. The announcement returns to "Pending approval".
--
-- begin;
-- with last as (
--   select l.entity_id, l.details -> 'previous' as prev
--     from public.audit_log l
--    where l.entity_id = '5597d191-b38a-401c-9c29-210550a6a2d6' and l.action = 'announcement.approve'
--      and l.details ? 'manual_repair'
--    order by l.created_at desc, l.id desc limit 1
-- ), upd as (
--   update public.announcements a
--      set publication_status = last.prev ->> 'publication_status',
--          approved_by = (last.prev ->> 'approved_by')::uuid,
--          approved_at = (last.prev ->> 'approved_at')::timestamptz
--     from last
--    where a.id = last.entity_id and a.publication_status = 'published'
--   returning a.id
-- )
-- insert into public.audit_log (action, entity_type, entity_id, actor_id, details)
-- select 'announcement.repair_undo', 'announcement', u.id, '<ADMIN_PROFILE_UUID>',
--        jsonb_build_object('undoes', 'manual_repair no pending version (ref 9cdb45f3bd55)')
--   from upd u
-- returning id as audit_id, entity_id as announcement_id;
-- -- exactly 1 row -> COMMIT; otherwise ROLLBACK;
-- commit;
