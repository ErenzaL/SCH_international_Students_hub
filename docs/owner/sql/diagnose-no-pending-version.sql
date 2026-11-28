-- READ-ONLY diagnostic: announcements shown as "Pending approval" whose approval fails with "no pending version".
-- Every statement is a SELECT inside a READ ONLY transaction that is rolled back: nothing can be written.
-- Run in Supabase -> SQL Editor, one numbered query at a time (the editor shows the result of the last statement).
-- Background: docs/final-release/INCIDENT-NO-PENDING-VERSION.md

-- 1. The reported announcement, its document and the state of its newest text version --------------------------------
begin transaction read only;
select a.id                         as announcement_id,
       a.title,
       a.publication_status,
       a.submitted_at,
       a.approved_by                as announcement_approved_by,
       a.approved_at                as announcement_approved_at,
       a.rejection_reason,
       a.updated_at,
       d.id                         as document_id,
       d.document_type,
       d.current_version_id,
       d.is_canceled,
       d.archived_at,
       v.id                         as latest_version_id,
       v.version_number             as latest_version_number,
       v.verification_status        as latest_version_status,
       v.approved_by                as version_approved_by,
       v.approved_at                as version_approved_at,
       v.review_note,
       v.rejected_reason,
       (v.id = d.current_version_id) as latest_is_current,
       (select count(*) from public.document_versions p
         where p.document_id = d.id and p.verification_status = 'pending_review') as pending_versions,
       (select count(*) from public.searchable_chunks c where c.document_id = d.id) as searchable_chunks,
       case
         when a.publication_status <> 'pending_approval' then 'not stuck (status ' || a.publication_status || ')'
         when exists (select 1 from public.document_versions p
                       where p.document_id = d.id and p.verification_status = 'pending_review') then 'not stuck (has a pending version)'
         when v.verification_status = 'approved' and v.id = d.current_version_id and not d.is_canceled
           then 'A: text approved in document review (already searchable)'
         when v.verification_status = 'draft'    then 'B: text sent back for changes in document review'
         when v.verification_status = 'rejected' then 'C: text rejected in document review'
         else 'D: other (' || coalesce(v.verification_status, 'no version') || ')'
       end as diagnosis
  from public.announcements a
  join public.source_documents d on d.id = a.document_id
  left join lateral (select * from public.document_versions x where x.document_id = a.document_id
                      order by x.version_number desc limit 1) v on true
 where a.id = '5597d191-b38a-401c-9c29-210550a6a2d6';
rollback;

-- 2. All versions of that announcement's text (no text bodies, only their length and hash) ---------------------------
begin transaction read only;
select v.id, v.version_number, v.verification_status, v.was_approved, v.created_at, v.submitted_at,
       v.approved_by, v.approved_at, v.rejected_by, v.rejected_at, v.rejected_reason, v.review_note,
       length(v.extracted_text) as text_length, left(v.content_hash, 12) as hash_prefix
  from public.document_versions v
 where v.document_id = (select document_id from public.announcements
                         where id = '5597d191-b38a-401c-9c29-210550a6a2d6')
 order by v.version_number;
rollback;

-- 3. Audit trail: who did what to the announcement, its document and its versions, in order ---------------------------
--    Expect 'announcement.submit' followed by a 'version.approve' / 'version.request_changes' / 'version.reject' that
--    came from DOCUMENT review (Admin -> Review), and no 'announcement.approve'.
begin transaction read only;
select l.created_at, l.action, l.entity_type, l.entity_id, l.actor_id, p.role as actor_role, l.details
  from public.audit_log l
  left join public.profiles p on p.id = l.actor_id
 where l.entity_id = '5597d191-b38a-401c-9c29-210550a6a2d6'
    or l.entity_id = (select document_id from public.announcements where id = '5597d191-b38a-401c-9c29-210550a6a2d6')
    or l.entity_id in (select v.id from public.document_versions v
                        where v.document_id = (select document_id from public.announcements
                                                where id = '5597d191-b38a-401c-9c29-210550a6a2d6'))
 order by l.created_at, l.id;
rollback;

-- 4. Every announcement in the same state (not only the reported one) ---------------------------------------------------
begin transaction read only;
select a.id, a.title, a.submitted_at, v.version_number, v.verification_status, v.approved_at, v.review_note,
       v.rejected_reason, (v.id = d.current_version_id) as latest_is_current, d.is_canceled,
       (select count(*) from public.searchable_chunks c where c.document_id = d.id) as searchable_chunks
  from public.announcements a
  join public.source_documents d on d.id = a.document_id
  left join lateral (select * from public.document_versions x where x.document_id = a.document_id
                      order by x.version_number desc limit 1) v on true
 where a.publication_status = 'pending_approval'
   and not exists (select 1 from public.document_versions p
                    where p.document_id = a.document_id and p.verification_status = 'pending_review')
 order by a.submitted_at;
rollback;

-- 5. The migration level of production (expected: the newest is 20261124000015 before the release's optional 0016-0019)
begin transaction read only;
select version from supabase_migrations.schema_migrations order by version desc limit 5;
rollback;
