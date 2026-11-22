-- Migration 0008 (support, conversations, translation review) behaviour + RLS checks. Scratch DB only; rolled back.
\set ON_ERROR_STOP on
begin;

-- A/B: signup stores the chosen language; role is ALWAYS student; invalid language falls back to 'en'
insert into auth.users (id, email, raw_user_meta_data) values
  ('00000000-0000-0000-0000-0000000000d1', 'ayu@example.test',  '{"preferred_language": "id", "display_name": "Ayu"}'),
  ('00000000-0000-0000-0000-0000000000d2', 'minh@example.test', '{"preferred_language": "vi", "role": "super_admin"}'),
  ('00000000-0000-0000-0000-0000000000d3', 'x@example.test',    '{"preferred_language": "fr"}'),
  ('00000000-0000-0000-0000-0000000000e1', 'sup-id@example.test', '{}'),
  ('00000000-0000-0000-0000-0000000000e2', 'sup-vi@example.test', '{}'),
  ('00000000-0000-0000-0000-0000000000e3', 'lead-id@example.test', '{}'),
  ('00000000-0000-0000-0000-0000000000e4', 'admin2@example.test', '{}'),
  ('00000000-0000-0000-0000-0000000000e5', 'super@example.test', '{}');
do $$ begin
  assert (select preferred_language || ':' || role || ':' || preferred_language_confirmed from profiles
           where id = '00000000-0000-0000-0000-0000000000d1') = 'id:student:true', 'Indonesian signup';
  assert (select preferred_language || ':' || role from profiles
           where id = '00000000-0000-0000-0000-0000000000d2') = 'vi:student', 'role in metadata is ignored';
  assert (select preferred_language || ':' || preferred_language_confirmed from profiles
           where id = '00000000-0000-0000-0000-0000000000d3') = 'en:false', 'invalid language -> en, unconfirmed';
end $$;
update profiles set role = 'supporter' where id in ('00000000-0000-0000-0000-0000000000e1', '00000000-0000-0000-0000-0000000000e2',
                                                     '00000000-0000-0000-0000-0000000000e3');
update profiles set role = 'admin' where id = '00000000-0000-0000-0000-0000000000e4';
update profiles set role = 'super_admin' where id = '00000000-0000-0000-0000-0000000000e5';
insert into supporter_languages (supporter_id, language_code, can_support, can_review_translations, is_team_lead) values
  ('00000000-0000-0000-0000-0000000000e1', 'id', true, true, false),
  ('00000000-0000-0000-0000-0000000000e2', 'vi', true, false, false),
  ('00000000-0000-0000-0000-0000000000e3', 'id', false, false, true);
insert into support_agent_status (supporter_id, is_available) values ('00000000-0000-0000-0000-0000000000e3', false);

-- conversations + tickets (written by the backend as service role)
insert into ai_conversations (id, user_id, language, title) values
  ('70000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-0000000000d1', 'id', 'Visa'),
  ('70000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-0000000000d2', 'vi', 'Ký túc xá');
insert into ai_messages (conversation_id, role, content, language) values
  ('70000000-0000-0000-0000-000000000001', 'user', 'pesan pribadi', 'id'),
  ('70000000-0000-0000-0000-000000000002', 'user', 'tin nhắn riêng', 'vi');
insert into support_tickets (id, student_id, language, subject, summary, consent_at) values
  ('71000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-0000000000d1', 'id', 'Visa D-2', 'ringkasan', now()),
  ('71000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-0000000000d2', 'vi', 'KTX', 'tóm tắt', now());
insert into support_ticket_messages (ticket_id, author_id, author_role, body) values
  ('71000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-0000000000d1', 'student', 'rahasia');

do $$
declare t support_tickets;
begin
  -- router: Indonesian ticket -> the available Indonesian supporter (the lead is unavailable / not can_support)
  t := route_support_ticket('71000000-0000-0000-0000-000000000001');
  assert t.status = 'assigned' and t.assigned_to = '00000000-0000-0000-0000-0000000000e1', 'routed to sup-id';
  t := route_support_ticket('71000000-0000-0000-0000-000000000002');
  assert t.assigned_to = '00000000-0000-0000-0000-0000000000e2', 'routed to sup-vi';
  -- cross-language transfer is refused
  begin
    perform assign_support_ticket('71000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-0000000000e2',
                                  '00000000-0000-0000-0000-0000000000e5', 'x', false);
    raise exception 'FAIL: transferred to another language team';
  exception when sqlstate '42501' then null; end;
  -- claiming a ticket that is no longer waiting is a conflict (no double assignment)
  begin
    perform assign_support_ticket('71000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-0000000000e1',
                                  '00000000-0000-0000-0000-0000000000e1', 'claim', true);
    raise exception 'FAIL: double claim accepted';
  exception when sqlstate '55000' then null; end;
  -- invariant: an active status needs an assignee
  begin
    update support_tickets set status = 'open', assigned_to = null where id = '71000000-0000-0000-0000-000000000002';
    raise exception 'FAIL: open ticket without assignee';
  exception when check_violation then null; end;
  begin
    update support_tickets set satisfaction = 5 where id = '71000000-0000-0000-0000-000000000002';
    raise exception 'FAIL: feedback before resolution';
  exception when check_violation then null; end;
end $$;

insert into user_notifications (user_id, kind, title) values
  ('00000000-0000-0000-0000-0000000000d1', 'supporter_reply', 'New reply'),
  ('00000000-0000-0000-0000-0000000000d2', 'supporter_reply', 'New reply');

-- ----------------------------------------------------------------- RLS as clients
set local role authenticated;
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-0000000000d1', true);   -- Indonesian student
do $$ begin
  assert (select count(*) from ai_conversations) = 1, 'student sees only own conversations';
  assert (select count(*) from ai_messages) = 1 and (select content from ai_messages) = 'pesan pribadi', 'own messages only';
  assert (select count(*) from support_tickets) = 1, 'own tickets only';
  assert (select count(*) from support_ticket_messages) = 1, 'own thread only';
  assert (select count(*) from user_notifications) = 1, 'own notifications only';
  update user_notifications set read_at = now();
  assert (select count(*) from user_notifications where read_at is not null) = 1, 'can mark own as read';
  begin insert into support_tickets (student_id, language, subject, summary, consent_at)
        values ('00000000-0000-0000-0000-0000000000d1', 'id', 'xxx', 'y', now()); raise exception 'FAIL student insert ticket';
  exception when insufficient_privilege then null; end;
  begin update profiles set role = 'super_admin' where id = '00000000-0000-0000-0000-0000000000d1';
        raise exception 'FAIL self-promotion';
  exception when sqlstate '42501' then null; end;
end $$;

select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-0000000000e1', true);   -- Indonesian supporter (assigned)
do $$ begin
  assert (select count(*) from ai_conversations) = 0 and (select count(*) from ai_messages) = 0, 'no AI histories for staff';
  assert (select count(*) from support_tickets) = 1 and (select language from support_tickets) = 'id', 'assigned id ticket only';
  assert (select count(*) from support_ticket_messages) = 1, 'thread of assigned ticket';
  assert (select count(*) from user_notifications) = 0, 'no one else''s notifications';
  begin insert into supporter_languages (supporter_id, language_code) values ('00000000-0000-0000-0000-0000000000e1', 'vi');
        raise exception 'FAIL supporter self-assigned a language';
  exception when insufficient_privilege or sqlstate '42501' then null; end;
end $$;

select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-0000000000e2', true);   -- Vietnamese supporter
do $$ begin
  assert not exists (select 1 from support_tickets where language = 'id'), 'no Indonesian ticket even by id';
  assert not exists (select 1 from support_ticket_messages
                      where ticket_id = '71000000-0000-0000-0000-000000000001'), 'no Indonesian thread';
end $$;

select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-0000000000e3', true);   -- Indonesian team lead
do $$ begin
  assert (select count(*) from support_tickets) = 1 and (select language from support_tickets) = 'id', 'lead: own language only';
  assert (select count(*) from ai_conversations) = 0, 'lead: no AI histories';
end $$;

select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-0000000000e4', true);   -- plain admin, no language
do $$ begin
  assert (select count(*) from support_tickets) = 0, 'plain admin has no support access without a language';
  begin insert into supporter_languages (supporter_id, language_code) values ('00000000-0000-0000-0000-0000000000e4', 'id');
        raise exception 'FAIL admin managed team membership';
  exception when insufficient_privilege or sqlstate '42501' then null; end;
end $$;

select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-0000000000e5', true);   -- super admin
do $$ begin
  assert (select count(*) from support_tickets) = 2, 'super admin sees all tickets';
  assert (select count(*) from ai_conversations) = 0, 'not even super admins read private AI histories';
end $$;
reset role;

-- J: reassignment revokes the previous assignee immediately; demotion revokes too
do $$ begin
  insert into supporter_languages (supporter_id, language_code) values ('00000000-0000-0000-0000-0000000000e2', 'id');
  perform assign_support_ticket('71000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-0000000000e2',
                                '00000000-0000-0000-0000-0000000000e3', 'workload', false);
  assert not can_view_ticket_content('00000000-0000-0000-0000-0000000000e1', '71000000-0000-0000-0000-000000000001'),
    'old assignee lost access';
  assert can_view_ticket_content('00000000-0000-0000-0000-0000000000e2', '71000000-0000-0000-0000-000000000001'),
    'new assignee has access';
  update profiles set role = 'student' where id = '00000000-0000-0000-0000-0000000000e3';
  assert not can_view_ticket_content('00000000-0000-0000-0000-0000000000e3', '71000000-0000-0000-0000-000000000001'),
    'demoted lead lost access';
  assert not has_language_permission('00000000-0000-0000-0000-0000000000e3', 'id', 'lead'), 'demoted lead lost permission';
end $$;

-- translation review: outdated translations are hidden publicly; staff read only their languages
insert into knowledge_sources (id, title, organization, source_type, authority_type, scope, category)
values ('13000000-0000-0000-0000-000000000001', 'Ann src', 'SCH', 'manual_text', 'official_university', 'university',
        'university-announcements');
insert into source_documents (id, source_id, external_id, title, document_type)
values ('23000000-0000-0000-0000-000000000001', '13000000-0000-0000-0000-000000000001', 'ann-1', 'Ann', 'announcement');
insert into announcements (id, document_id, title, category, publication_status, original_language)
values ('81000000-0000-0000-0000-000000000001', '23000000-0000-0000-0000-000000000001', '안내', 'university-announcements',
        'published', 'ko');
insert into announcement_translations (announcement_id, language_code, title, body, translation_status, reviewed_at, is_outdated) values
  ('81000000-0000-0000-0000-000000000001', 'id', 'Pengumuman', 'Isi', 'human_approved', now(), false),
  ('81000000-0000-0000-0000-000000000001', 'vi', 'Thông báo', 'Nội dung', 'human_approved', now(), true),
  ('81000000-0000-0000-0000-000000000001', 'en', '', '', 'todo', null, false);
set local role anon;
do $$ begin
  assert (select string_agg(language_code, ',') from announcement_translations) = 'id', 'only approved + current are public';
end $$;
reset role;
set local role authenticated;
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-0000000000e1', true);   -- id supporter
do $$ begin
  assert (select count(*) from announcement_translations where language_code = 'vi' and is_outdated) = 0,
    'no access to Vietnamese drafts';
  assert (select count(*) from announcement_translations where language_code = 'id') = 1, 'own language visible';
end $$;
reset role;

-- grants: the probing-capable helpers are server-only
set local role authenticated;
do $$ begin
  begin perform has_language_permission('00000000-0000-0000-0000-0000000000e1', 'id', 'lead');
        raise exception 'FAIL client probed another user''s permissions';
  exception when insufficient_privilege then null; end;
  begin perform route_support_ticket('71000000-0000-0000-0000-000000000002'); raise exception 'FAIL client routed';
  exception when insufficient_privilege then null; end;
end $$;
reset role;

select 'ALL SUPPORT SQL BEHAVIOUR TESTS PASSED' as result;
rollback;
