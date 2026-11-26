-- =============================================================================
-- 0019  Weekly discovery. ADDITIVE; nothing is enabled.
--   * every seeded agent schedule that no administrator has touched (updated_by is null) and that is still disabled
--     becomes WEEKLY (10080 minutes) with a stagger (params.stagger_minutes) so the official sources are not all
--     asked at the same moment; schedules an administrator changed are left exactly as they are;
--   * 'work24_api' (고용24 Open API, official job postings; the key stays in the API's environment) as a kind of source.
-- When enabled, a weekly schedule first runs at the next weekly slot (DISCOVERY_WEEKLY_ANCHOR, Korea time) plus its stagger.
-- =============================================================================

update public.agent_schedules s set
  interval_minutes = 10080,
  params = coalesce(s.params, '{}'::jsonb) || jsonb_build_object('stagger_minutes', v.stagger)
from (values
  ('announcement', 'announcement_discovery', 0),
  ('scholarship',  'opportunity_discovery',  20),
  ('career',       'opportunity_discovery',  40),
  ('events',       'event_discovery',        60),
  ('immigration',  'guidance_discovery',     80),
  ('academic',     'guidance_discovery',     100),
  ('topik',        'guidance_discovery',     120),
  ('announcement', 'announcement_digest',    180),
  ('scholarship',  'scholarship_scan',       200),
  ('events',       'event_digest',           220),
  ('career',       'career_scan',            240)
) as v (agent_id, task_type, stagger)
where s.agent_id = v.agent_id and s.task_type = v.task_type and s.updated_by is null and not s.enabled;

alter table public.discovery_sources drop constraint if exists discovery_sources_kind_check;
alter table public.discovery_sources add constraint discovery_sources_kind_check
  check (kind in ('sch_board', 'listing', 'page', 'saramin_api', 'data_go_kr_jobs', 'work24_api'));
