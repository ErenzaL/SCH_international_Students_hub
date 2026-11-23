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
    ),
    AgentDefinition(
        id="academic", character_id="academic", name="Joon", title="Academic agent", department="Academic & TOPIK",
        description="Finds academic guidance and university notices, explains procedures such as course "
                    "registration and prepares checklists with links.",
        scope="University academic procedures and notices.", languages=LANGS,
        allowed_tools=READ_COMMON | {"deadline_extraction", "academic_checklist"},
        task_types=("academic_checklist",), restricted_actions=NO_DECISIONS,
        actions=(AgentAction("course_registration", "tool", "academic_checklist", {"topic": "registration"}),
                 AgentAction("academic_notices", "tool", "announcement_search",
                             {"category": "university-announcements", "limit": 6})),
    ),
    AgentDefinition(
        id="topik", character_id="topik", name="Seo", title="TOPIK agent", department="Academic & TOPIK",
        description="Finds TOPIK guides and published TOPIK notices and extracts announced dates and deadlines.",
        scope="TOPIK registration, dates and approved study resources.", languages=LANGS,
        allowed_tools=READ_COMMON | {"deadline_extraction", "topik_dates"},
        task_types=("topik_dates",), restricted_actions=NO_DECISIONS,
        actions=(AgentAction("topik_dates", "tool", "topik_dates", {}),),
    ),
    AgentDefinition(
        id="scholarship", character_id="opportunities", name="Leo", title="Scholarship agent",
        department="Scholarships & Opportunities",
        description="Searches approved announcements and guides for scholarships, extracts eligibility, benefits "
                    "and deadlines as quoted from the source, removes duplicates and flags expired or unverified "
                    "items. Can check allowlisted official pages when sources are configured.",
        scope="Scholarships, competitions and programs. Never claims a student is eligible.", languages=LANGS,
        allowed_tools=READ_COMMON | {"scholarship_search", "deadline_extraction", "source_verification",
                                     "official_page_fetch", "official_web_search"},
        task_types=("scholarship_scan",), restricted_actions=NO_DECISIONS + ("scholarship_eligibility",),
        actions=(AgentAction("find_scholarships", "tool", "scholarship_search", {}),
                 AgentAction("scan_sources", "task", "scholarship_scan", {})),
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
    ),
    AgentDefinition(
        id="career", character_id="career", name="Daniel", title="Career agent",
        department="Career & Internships",
        description="Finds approved career guidance and internship or job announcements, extracts application "
                    "requirements and flags where visa work rules must be checked.",
        scope="Careers, internships and work permission guidance. Never promises a student may legally work.",
        languages=LANGS,
        allowed_tools=READ_COMMON | {"career_opportunity_search", "deadline_extraction", "source_verification",
                                     "official_page_fetch", "official_web_search"},
        task_types=("career_scan",),
        restricted_actions=NO_DECISIONS + ("work_legality",),
        actions=(AgentAction("find_opportunities", "tool", "career_opportunity_search", {}),),
    ),
    AgentDefinition(
        id="announcement", character_id="guide-bot", name="Robo", title="Announcement agent",
        department="AI Support Center",
        description="Watches published university announcements, detects new or updated ones, sorts them by "
                    "category, extracts deadlines and prepares summaries or translations for review.",
        scope="Published announcements and configured official sources. Never publishes anything.",
        languages=LANGS,
        allowed_tools=READ_COMMON | {"deadline_extraction", "summarize_document", "translate_text",
                                     "official_page_fetch", "source_verification"},
        task_types=("announcement_digest", "summarize_announcement"),
        restricted_actions=NO_DECISIONS + ("publish_announcements",),
        actions=(AgentAction("latest_notices", "tool", "announcement_search", {"limit": 8}),
                 AgentAction("digest", "task", "announcement_digest", {})),
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
    ),
]}

CHARACTER_TO_AGENT = {a.character_id: a.id for a in AGENTS.values()}


def get_agent(agent_id: str) -> AgentDefinition | None:
    return AGENTS.get(agent_id)
