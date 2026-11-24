"""Agent Registry - the server-side source of truth for every AI Support Office agent.

An agent is an IDENTITY with a job description and a permission set, not a model: every agent uses the same
shared LLM provider and RAG services. What an agent may do is decided here (allowed tools, task types, which
agents it may delegate to); the frontend only displays it and can never grant a tool.
"""
from __future__ import annotations

from dataclasses import dataclass, field

LANGS = ("ko", "en", "id", "vi", "zh-CN")


@dataclass(frozen=True)
class AgentAction:
    """A ready-made request shown as a button: a read-only tool run now, or a background task."""
    id: str
    kind: str                     # "tool" | "task"
    target: str                   # tool name or task type
    params: dict[str, object] = field(default_factory=dict)
    #: shown only to these roles (e.g. admin-only monitoring); the backend enforces the same rule on the tool
    roles: tuple[str, ...] | None = None


ADMIN = ("super_admin", "admin")
SIGNED_IN = ("student", "supporter", "admin", "super_admin")
EVERYONE = ("visitor",) + SIGNED_IN

#: how a character's workspace looks (presentation only: permissions are the tools / actions above and below)
INTERFACE_TYPES = ("CHAT", "SERVICE", "DISCOVERY", "MONITORING", "TASK_WORKSPACE")


@dataclass(frozen=True)
class WorkspaceTab:
    id: str
    #: shown only to these viewer roles ("visitor" = not signed in); None = everyone
    roles: tuple[str, ...] | None = None


@dataclass(frozen=True)
class AgentInterface:
    """Presentation of an agent in the AI Office. The frontend chooses the workspace component by ``type`` and
    ``default_view``; it never grants anything: a tab only shows data the API already allows for the viewer, and
    admin tabs are both hidden here and protected by the admin endpoints."""
    type: str
    default_view: str
    tabs: tuple[WorkspaceTab, ...]
    #: what the workspace offers (codes the UI translates)
    capabilities: tuple[str, ...]
    #: ids of this agent's AgentActions shown in the workspace action bar (filtered by the action's own roles)
    task_actions: tuple[str, ...] = ()
    allowed_user_roles: tuple[str, ...] = EVERYONE
    #: where the shown data comes from (codes): rag, published_announcements, knowledge_center, discovery_sources,
    #: reviewed_discoveries, support_tickets, agent_tasks
    data_sources: tuple[str, ...] = ()

    def view_for(self, role: str) -> dict[str, object]:
        tabs = [t.id for t in self.tabs if t.roles is None or role in t.roles]
        return dict(type=self.type, default_view=self.default_view if self.default_view in tabs else tabs[0],
                    tabs=tabs, capabilities=list(self.capabilities), allowed_user_roles=list(self.allowed_user_roles),
                    data_sources=list(self.data_sources))


def _tabs(*ids: str, admin: tuple[str, ...] = ()) -> tuple[WorkspaceTab, ...]:
    return tuple(WorkspaceTab(i) for i in ids) + tuple(WorkspaceTab(i, ADMIN) for i in admin)


CHAT_INTERFACE = AgentInterface(
    "CHAT", "chat", _tabs("chat", "work", "about"),
    capabilities=("grounded_chat", "citations", "delegation", "task_results"),
    task_actions=("latest_notices",), data_sources=("rag", "published_announcements", "knowledge_center", "agent_tasks"))


@dataclass(frozen=True)
class AgentDefinition:
    id: str
    character_id: str             # the AI Office character showing this agent
    name: str
    title: str
    department: str
    description: str
    scope: str
    languages: tuple[str, ...]
    allowed_tools: frozenset[str]
    task_types: tuple[str, ...] = ()
    can_delegate_to: tuple[str, ...] = ()
    restricted_actions: tuple[str, ...] = ()
    actions: tuple[AgentAction, ...] = ()
    #: supporters answer in one language; None = the request's / site language
    fixed_language: str | None = None
    interface: AgentInterface = CHAT_INTERFACE


READ_COMMON = frozenset({"rag_search", "knowledge_document_lookup", "announcement_search", "announcement_detail",
                         "get_agent_task_status"})
SPECIALISTS = ("immigration", "academic", "topik", "scholarship", "events", "career", "announcement",
               "support-coordinator")
#: codes of things an agent never does (the UI shows them in the student's language)
NO_DECISIONS = ("eligibility_decisions", "submit_applications", "publish_content", "send_without_confirmation")


def _supporter(lang: str, name: str, char: str) -> AgentDefinition:
    return AgentDefinition(
        id=f"supporter-{lang.split('-')[0]}", character_id=char, name=name,
        title=f"{lang} language supporter", department="Global Supporters",
        description="Answers in one language from approved sources, explains university procedures and Korean "
                    "documents, and hands specialist work to the right desk.",
        scope="All student-life topics, in one language. Specialist searches are delegated.",
        languages=(lang,), fixed_language=lang,
        allowed_tools=READ_COMMON | {"summarize_document", "translate_text", "create_agent_task"},
        task_types=("summarize_announcement", "explain_document", "delegated_search"),
        can_delegate_to=SPECIALISTS, restricted_actions=NO_DECISIONS,
        actions=(AgentAction("latest_notices", "tool", "announcement_search", {"limit": 6}),),
        interface=CHAT_INTERFACE,
    )


AGENTS: dict[str, AgentDefinition] = {a.id: a for a in [
    AgentDefinition(
        id="reception", character_id="reception", name="Hana", title="Reception coordinator",
        department="AI Support Center",
        description="Understands a request, sends it to the right specialist, tracks the work and returns the "
                    "combined result.",
        scope="Routing and general questions. Never uses a specialist's tools directly: it delegates.",
        languages=LANGS, allowed_tools=READ_COMMON | {"create_agent_task"},
        task_types=("delegated_search",), can_delegate_to=SPECIALISTS, restricted_actions=NO_DECISIONS,
        actions=(AgentAction("latest_notices", "tool", "announcement_search", {"status": "active", "limit": 6}),),
        interface=AgentInterface("CHAT", "chat", _tabs("chat", "work", "desks", "about"),
                                 capabilities=("grounded_chat", "citations", "delegation", "task_results", "directory"),
                                 task_actions=("latest_notices",),
                                 data_sources=("rag", "published_announcements", "knowledge_center", "agent_tasks")),
    ),
    _supporter("ko", "Minji", "supporter-ko"),
    _supporter("en", "Alex", "supporter-en"),
    _supporter("id", "Sari", "supporter-id"),
    _supporter("vi", "Minh", "supporter-vi"),
    _supporter("zh-CN", "Mei", "supporter-zh"),
    AgentDefinition(
        id="immigration", character_id="visa", name="Yuna", title="Immigration agent",
        department="Visa & Immigration",
        description="Finds approved immigration guidance (D-2, D-4, extensions, residence card, address changes, "
                    "part-time work permission), builds procedural checklists with sources and flags guidance "
                    "that may be outdated.",
        scope="Visa and residence procedures. Explains requirements; never decides eligibility.",
        languages=LANGS,
        allowed_tools=READ_COMMON | {"deadline_extraction", "source_verification", "visa_checklist"},
        task_types=("visa_checklist",),
        restricted_actions=NO_DECISIONS + ("visa_decisions", "file_immigration"),
        actions=(AgentAction("d2_extension", "tool", "visa_checklist", {"topic": "extension"}),
                 AgentAction("residence_card", "tool", "visa_checklist", {"topic": "residence_card"}),
                 AgentAction("address_change", "tool", "visa_checklist", {"topic": "address"}),
                 AgentAction("part_time_permission", "tool", "visa_checklist", {"topic": "part_time"})),
        interface=AgentInterface("SERVICE", "checklists", _tabs("checklists", "chat", "guides", "work", "about"),
                                 capabilities=("procedure_checklists", "grounded_chat", "citations", "outdated_flags"),
                                 task_actions=("d2_extension", "residence_card", "address_change", "part_time_permission"),
                                 data_sources=("knowledge_center", "rag")),
    ),
    AgentDefinition(
        id="academic", character_id="academic", name="Joon", title="Academic agent", department="Academic & TOPIK",
        description="Finds academic guidance and university notices, explains procedures such as course "
                    "registration and prepares checklists with links.",
        scope="University academic procedures and notices.", languages=LANGS,
        allowed_tools=READ_COMMON | {"deadline_extraction", "academic_checklist"},
        task_types=("academic_checklist",), restricted_actions=NO_DECISIONS,
        actions=(AgentAction("course_registration", "tool", "academic_checklist", {"topic": "registration"}),
                 AgentAction("leave_of_absence", "tool", "academic_checklist", {"topic": "leave"}),
                 AgentAction("graduation", "tool", "academic_checklist", {"topic": "graduation"}),
                 AgentAction("academic_notices", "tool", "announcement_search",
                             {"category": "university-announcements", "limit": 6})),
        interface=AgentInterface("SERVICE", "procedures", _tabs("procedures", "notices", "guides", "chat", "work", "about"),
                                 capabilities=("procedure_checklists", "academic_notices", "knowledge_resources",
                                               "grounded_chat"),
                                 task_actions=("course_registration", "leave_of_absence", "graduation", "academic_notices"),
                                 data_sources=("knowledge_center", "published_announcements", "rag")),
    ),
    AgentDefinition(
        id="topik", character_id="topik", name="Seo", title="TOPIK agent", department="Academic & TOPIK",
        description="Finds TOPIK guides and published TOPIK notices and extracts announced dates and deadlines.",
        scope="TOPIK registration, dates and approved study resources.", languages=LANGS,
        allowed_tools=READ_COMMON | {"deadline_extraction", "topik_dates"},
        task_types=("topik_dates",), restricted_actions=NO_DECISIONS,
        actions=(AgentAction("topik_dates", "tool", "topik_dates", {}),),
        interface=AgentInterface("SERVICE", "topik", _tabs("topik", "guides", "chat", "work", "about"),
                                 capabilities=("test_dates", "registration_notices", "knowledge_resources",
                                               "grounded_chat"),
                                 task_actions=("topik_dates",),
                                 data_sources=("published_announcements", "knowledge_center", "rag")),
    ),
    AgentDefinition(
        id="scholarship", character_id="opportunities", name="Leo", title="Scholarship agent",
        department="Scholarships & Opportunities",
        description="Searches approved announcements and guides for scholarships, extracts eligibility, benefits "
                    "and deadlines as quoted from the source, removes duplicates and flags expired or unverified "
                    "items. Can check allowlisted official pages when sources are configured.",
        scope="Scholarships, competitions and programs. Never claims a student is eligible.", languages=LANGS,
        allowed_tools=READ_COMMON | {"scholarship_search", "deadline_extraction", "source_verification",
                                     "official_page_fetch", "official_web_search", "opportunity_search",
                                     "official_source_check", "review_candidates"},
        task_types=("scholarship_scan", "opportunity_discovery"),
        restricted_actions=NO_DECISIONS + ("scholarship_eligibility", "claim_open_without_source"),
        actions=(AgentAction("find_scholarships", "tool", "scholarship_search", {}),
                 AgentAction("official_opportunities", "tool", "opportunity_search", {}),
                 AgentAction("scan_sources", "task", "scholarship_scan", {}),
                 AgentAction("check_official_sources", "task", "opportunity_discovery", {}, roles=ADMIN),
                 AgentAction("review_queue", "tool", "review_candidates", {}, roles=ADMIN)),
        interface=AgentInterface("DISCOVERY", "opportunities",
                                 _tabs("opportunities", "work", "chat", "about", admin=("review", "sources")),
                                 capabilities=("approved_opportunities", "deadlines", "eligibility_quotes",
                                               "official_links", "verification_status", "filters", "own_checks"),
                                 task_actions=("scan_sources", "check_official_sources"),
                                 data_sources=("published_announcements", "knowledge_center", "reviewed_discoveries",
                                               "discovery_sources", "agent_tasks")),
    ),
    AgentDefinition(
        id="events", character_id="events", name="Mia", title="Event agent", department="Events & Campus Life",
        description="Finds published events, extracts dates, places and deadlines, keeps only upcoming ones and "
                    "detects new or changed announcements.",
        scope="Campus events, dormitory notices and deadlines.", languages=LANGS,
        allowed_tools=READ_COMMON | {"event_search", "deadline_extraction"},
        task_types=("event_digest",), restricted_actions=NO_DECISIONS,
        actions=(AgentAction("upcoming_events", "tool", "event_search", {}),
                 AgentAction("what_changed", "task", "event_digest", {})),
        interface=AgentInterface("DISCOVERY", "events", _tabs("events", "work", "chat", "about"),
                                 capabilities=("published_events", "event_dates", "registration_deadlines",
                                               "official_links", "upcoming_past_filter", "change_digest"),
                                 task_actions=("what_changed",),
                                 data_sources=("published_announcements", "agent_tasks")),
    ),
    AgentDefinition(
        id="career", character_id="career", name="Daniel", title="Career agent",
        department="Career & Internships",
        description="Finds approved career guidance and internship or job announcements, extracts application "
                    "requirements and flags where visa work rules must be checked.",
        scope="Careers, internships and work permission guidance. Never promises a student may legally work.",
        languages=LANGS,
        allowed_tools=READ_COMMON | {"career_opportunity_search", "deadline_extraction", "source_verification",
                                     "official_page_fetch", "official_web_search", "opportunity_search"},
        task_types=("career_scan",),
        restricted_actions=NO_DECISIONS + ("work_legality",),
        actions=(AgentAction("find_opportunities", "tool", "career_opportunity_search", {}),
                 AgentAction("official_jobs", "tool", "opportunity_search", {"kind": "job"})),
        interface=AgentInterface("DISCOVERY", "careers", _tabs("careers", "guides", "work", "chat", "about"),
                                 capabilities=("published_career_notices", "employment_guidance", "application_dates",
                                               "official_links", "work_permission_reminder"),
                                 task_actions=("find_opportunities", "official_jobs"),
                                 data_sources=("published_announcements", "knowledge_center", "reviewed_discoveries")),
    ),
    AgentDefinition(
        id="announcement", character_id="guide-bot", name="Robo", title="Announcement agent",
        department="AI Support Center",
        description="Watches published university announcements, detects new or updated ones, sorts them by "
                    "category, extracts deadlines and prepares summaries or translations for review.",
        scope="Published announcements and configured official sources. Never publishes anything.",
        languages=LANGS,
        allowed_tools=READ_COMMON | {"deadline_extraction", "summarize_document", "translate_text",
                                     "official_page_fetch", "source_verification", "official_source_check",
                                     "review_candidates"},
        task_types=("announcement_digest", "summarize_announcement", "announcement_discovery"),
        restricted_actions=NO_DECISIONS + ("publish_announcements",),
        actions=(AgentAction("latest_notices", "tool", "announcement_search", {"limit": 8}),
                 AgentAction("digest", "task", "announcement_digest", {}),
                 AgentAction("check_official_sources", "task", "announcement_discovery", {}, roles=ADMIN),
                 AgentAction("review_queue", "tool", "review_candidates", {}, roles=ADMIN)),
        interface=AgentInterface("MONITORING", "monitoring",
                                 _tabs("monitoring", "notices", "work", "about", admin=("review", "sources")),
                                 capabilities=("source_status", "last_check", "activity_status", "recent_announcements",
                                               "change_detection", "own_digests"),
                                 task_actions=("digest", "check_official_sources"),
                                 data_sources=("discovery_sources", "published_announcements", "agent_tasks")),
    ),
    AgentDefinition(
        id="support-coordinator", character_id="supporter-lead", name="Sumin", title="Support coordinator",
        department="Global Supporters",
        description="Prepares a request to a human Global Supporter, sorts it by topic and language, sends it only "
                    "after the student confirms, and shows the status of the student's requests.",
        scope="Human support requests of the signed-in student.", languages=LANGS,
        allowed_tools=READ_COMMON | {"create_support_request", "get_support_request_status"},
        task_types=("support_request",), restricted_actions=("send_without_confirmation",
                                                             "show_others_requests"),
        actions=(AgentAction("my_requests", "tool", "get_support_request_status", {}),),
        interface=AgentInterface("TASK_WORKSPACE", "request", _tabs("request", "requests", "chat", "about"),
                                 capabilities=("request_form", "issue_category", "request_preview",
                                               "explicit_confirmation", "own_request_history", "request_status"),
                                 task_actions=("my_requests",),
                                 data_sources=("support_tickets", "agent_tasks")),
    ),
]}

CHARACTER_TO_AGENT = {a.character_id: a.id for a in AGENTS.values()}


def get_agent(agent_id: str) -> AgentDefinition | None:
    return AGENTS.get(agent_id)
