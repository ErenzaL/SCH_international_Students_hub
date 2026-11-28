-- Rollback of 0019. Seeded schedules that are still untouched (updated_by is null) and disabled get their intervals of 0014/0015/0017
-- back and lose the stagger; Work24 sources are removed with their candidates. Take a backup first.
begin;
update public.agent_schedules s set interval_minutes = v.minutes, params = s.params - 'stagger_minutes'
from (values
  ('announcement', 'announcement_discovery', 720), ('scholarship', 'opportunity_discovery', 1440), ('career', 'opportunity_discovery', 1440),
  ('events', 'event_discovery', 1440), ('immigration', 'guidance_discovery', 2880), ('academic', 'guidance_discovery', 1440),
  ('topik', 'guidance_discovery', 2880), ('announcement', 'announcement_digest', 720), ('scholarship', 'scholarship_scan', 1440),
  ('events', 'event_digest', 720), ('career', 'career_scan', 1440)
) as v (agent_id, task_type, minutes)
where s.agent_id = v.agent_id and s.task_type = v.task_type and s.updated_by is null and not s.enabled;
delete from public.discovery_sources where kind = 'work24_api';
alter table public.discovery_sources drop constraint if exists discovery_sources_kind_check;
alter table public.discovery_sources add constraint discovery_sources_kind_check
  check (kind in ('sch_board', 'listing', 'page', 'saramin_api', 'data_go_kr_jobs'));
commit;
