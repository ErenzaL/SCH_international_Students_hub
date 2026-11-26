"""Tool Registry - the only things an agent can actually do.

Every tool is a thin, typed wrapper around an EXISTING Hub service (retrieval, public content, support tickets, the
guarded fetcher, the shared translation model). Tools never run model-generated code or SQL: their parameters are
validated by a Pydantic model (unknown fields rejected), and the handlers only call fixed service methods.

Permissions are enforced here, server-side, on every call (``ToolRegistry.run``):
  * the agent must list the tool in ``allowed_tools`` (registry.py);
  * the tool must be available (configured) - unavailable tools say why and never pretend to work;
  * tools that read private data or spend model budget need a signed-in user; results are scoped to that user;
  * ``background`` tools (network, model) only run inside a durable task, never in an HTTP request;
  * ``needs_approval`` tools (anything that writes) only run after the student approved that exact task.

Results are structured (items with links and reliability labels), so the UI never has to trust free text.
"""
from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from app.core.constants import LANGUAGES
from app.core.errors import AppError, Forbidden, NotAuthenticated, NotFound, ValidationFailed
from app.repositories.base import Query, get_one
from app.services.announcements import compute_status, today_kst

if TYPE_CHECKING:
    from app.security.auth import AuthUser
    from app.services.agents.registry import AgentDefinition
    from app.services.container import Services

Lang = Literal["ko", "en", "id", "vi", "zh-CN"]
Text = Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)]

# --------------------------------------------------------------------------- reliability labels
VERIFIED = "verified"                    # approved, published Hub content inside its freshness window
OUTDATED = "possibly_outdated"           # approved, but older than the category's review interval
EXPIRED = "expired"                      # its deadline has passed
EXTERNAL = "external_unverified"         # fetched from an allowlisted official site, not reviewed by staff
AI_GENERATED = "ai_generated"            # written by the shared model from the cited source; not reviewed
FROM_STUDENT = "student_input"           # the student's own text (translations of it)


class ToolUnavailable(AppError):
    status_code, code = 409, "tool_unavailable"


class ToolDenied(Forbidden):
    code = "tool_not_allowed"


@dataclass
class ToolContext:
    svc: Services
    agent: AgentDefinition
    user: AuthUser | None
    language: str
    in_task: bool = False
    approved: bool = False
    task: dict[str, Any] | None = None
    #: (agent_id, step, tool, message, data) - the task service stores these as agent_task_events
    log: Callable[..., None] = lambda *a, **k: None
    depth: int = 0
    #: called between steps of a task: heartbeat, cancellation and timeout checks
    checkpoint: Callable[[str], None] = lambda stage: None
    #: live progress of a running task (sources checked, current source ...), stored on the task row
    progress: Callable[[dict[str, Any]], None] = lambda p: None
    #: a scheduled (system) task: no user, started by an admin-enabled schedule
    system: bool = False


class P(BaseModel):
    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    params: type[P]
    handler: Callable[[ToolContext, Any], dict[str, Any]]
    requires_auth: bool = False
    background: bool = False        # network / model calls: only inside a durable task
    uses_llm: bool = False
    writes: bool = False
    needs_approval: bool = False
    availability: Callable[[Services], str | None] = field(default=lambda svc: None)  # None = available
    #: only these roles may use the tool (scheduled system tasks too); None = everyone
    roles: tuple[str, ...] | None = None

    def unavailable_reason(self, svc: Services) -> str | None:
        return self.availability(svc)


def result(tool: str, items: list[dict[str, Any]], *, notes: list[str] | None = None, **extra: Any) -> dict[str, Any]:
    """``notes`` are codes (the UI shows them in the student's language), e.g. ``no_match``, ``eligibility_office``."""
    return dict(tool=tool, items=items, count=len(items), notes=notes or [], **extra)


# =========================================================================== shared helpers
def _ann_item(a: dict[str, Any]) -> dict[str, Any]:
    status = a.get("status") or compute_status(a.get("valid_from"), a.get("deadline"), today_kst())
    return dict(kind="announcement", id=a["id"], title=a.get("display_title") or a["title"], category=a["category"],
                href=f"/announcements/{a['id']}", deadline=a.get("deadline"), event_date=a.get("event_date"),
                published_at=a.get("published_at"), status=status, excerpt=(a.get("excerpt") or "")[:300],
                source=(a.get("source") or {}).get("organization"),
                reliability=EXPIRED if status == "expired" else VERIFIED)


def _doc_item(d: dict[str, Any]) -> dict[str, Any]:
    return dict(kind="document", id=d["id"], title=d["title"], category=d["category"], href=f"/knowledge/{d['id']}",
                organization=d.get("organization"), verified_at=d.get("verified_at"),
                excerpt=(d.get("excerpt") or "")[:300],
                reliability=OUTDATED if d.get("is_stale") else VERIFIED)


def _passage_item(r: dict[str, Any], announcement_id: str | None = None) -> dict[str, Any]:
    from app.services.assistant.engine import citation_link

    link = citation_link(r, announcement_id) or {}
    return dict(kind="passage", document_id=r["document_id"], title=r["document_title"], heading=r.get("heading"),
                quote=(r.get("passage") or "")[:500], page=r.get("page"), category=r.get("category"),
                organization=r.get("organization"), verified_at=r.get("verified_at"), href=link.get("href"),
                link_kind=link.get("kind"), reliability=OUTDATED if r.get("is_stale") else VERIFIED)


def _passages(svc: Services, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Passages with the same link targets as chat citations (announcements open their announcement page)."""
    ids = list({r["document_id"] for r in results})
    anns = {a["document_id"]: a["id"] for a in svc.store.select("announcements", Query(
        in_={"document_id": ids}, eq={"publication_status": "published"}, cols="id,document_id"))[0]} if ids else {}
    return [_passage_item(r, anns.get(r["document_id"])) for r in results]


def _announcements(svc: Services, *, q: str | None = None, category: str | None = None, status: str | None = None,
                   size: int = 50, language: str | None = None) -> list[dict[str, Any]]:
    rows, _ = svc.public.list_announcements(q=q, category=category, language=None, status=status, page=1, size=size,
                                            display_language=language)
    return rows


def _documents(svc: Services, *, q: str | None = None, category: str | None = None, size: int = 50) -> list[dict[str, Any]]:
    rows, _ = svc.public.list_documents(q=q, category=category, scope=None, page=1, size=size)
    return rows


def _norm_title(t: str) -> str:
    return re.sub(r"[\W_]+", "", t.lower())


def _dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Same title (ignoring spacing / punctuation) = the same opportunity posted twice: keep the first one."""
    seen: set[str] = set()
    out = []
    for it in items:
        key = _norm_title(it["title"])
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def _matches(text: str, pattern: re.Pattern[str]) -> bool:
    return bool(pattern.search(text or ""))


# =========================================================================== deadline extraction (deterministic)
_FULL_DATE = re.compile(r"(20\d{2})\s*(?:[./-]|년)\s*(\d{1,2})\s*(?:[./-]|월)\s*(\d{1,2})\s*일?")
_MONTH_DAY = re.compile(r"(?<![\d.])(\d{1,2})\s*월\s*(\d{1,2})\s*일")
# "11/23" only counts as a date next to a range mark, "까지" or inside brackets (never "1/2 학기")
_SLASH = re.compile(r"(?<![\d/.])(\d{1,2})\s*/\s*(\d{1,2})(?![\d/])")
# the end of a range written short after its start: "2026. 11. 23.(월) ~ 11. 29.(일)", "11/23~29", "~ 2027. 1. 5."
_RANGE_END = re.compile(r"\.?(?:\s*\([^)]{1,6}\))?(?:\s*\d{1,2}:\d{2})?\s*[~∼～]\s*"
                        r"(?:(?P<y>20\d{2})\s*(?:[./-]|년)\s*)?(?:(?P<m>\d{1,2})\s*(?:[./]|월)\s*)?(?P<d>\d{1,2})(?![\d:])")
_DEADLINE_WORDS = re.compile(r"마감|까지|기한|접수\s*기간|신청\s*기간|제출|deadline|due|until|no later than|apply by|"
                             r"hạn|batas|截止", re.IGNORECASE)
_APPLY_WORDS = re.compile(r"신청|접수|모집|지원|apply|application|registration", re.IGNORECASE)
_EVENT_WORDS = re.compile(r"일시|행사|시험일|개최|event|exam date|date and time|ngày thi|tanggal|时间|日期", re.IGNORECASE)


def _line_dates(line: str, year: int) -> tuple[list[tuple[date, bool]], bool]:
    """(dates in reading order with year_assumed, the line contains a range) - see extract_dates."""
    toks: list[tuple[int, int, date, bool]] = []

    def free(a: int, b: int) -> bool:
        return all(b <= s or a >= e for s, e, _d, _x in toks)

    def add(a: int, b: int, y: int, mo: int, d: int, assumed: bool) -> None:
        try:
            if free(a, b):
                toks.append((a, b, date(y, mo, d), assumed))
        except ValueError:
            pass

    for m in _FULL_DATE.finditer(line):
        add(m.start(), m.end(), int(m[1]), int(m[2]), int(m[3]), False)
    for m in _MONTH_DAY.finditer(line):
        add(m.start(), m.end(), year, int(m[1]), int(m[2]), True)
    for m in _SLASH.finditer(line):
        around = line[max(0, m.start() - 2): m.end() + 3]
        if re.search(r"[~∼～(（)）]|까지", around):
            add(m.start(), m.end(), year, int(m[1]), int(m[2]), True)
    ranged = False
    for _a, b, start, assumed in sorted(toks):   # a copy: range ends are added to toks while iterating
        r = _RANGE_END.match(line, b)
        if not r or not free(r.start("d"), r.end()):
            continue
        ranged = True
        y = int(r["y"]) if r["y"] else start.year
        mo = int(r["m"]) if r["m"] else start.month
        d = int(r["d"])
        if not r["m"] and not r["y"] and d < start.day:      # "11/28~2" ends in the next month
            mo, y = (1, y + 1) if mo == 12 else (mo + 1, y)
        add(r.start("d"), r.end(), y, mo, d, assumed and not r["y"])
    toks.sort()
    return [(d, x) for _a, _b, d, x in toks], ranged or bool(re.search(r"[~∼～]", line))


def extract_dates(text: str, *, default_year: int | None = None, limit: int = 12) -> list[dict[str, Any]]:
    """Dates written in a text, each with the line it was quoted from and a kind (deadline / event / date).
    Purely pattern-based: nothing is inferred beyond what the text says; a date without a year uses
    ``default_year`` and is marked ``year_assumed``. In a range the last date is the deadline."""
    out: list[dict[str, Any]] = []
    year = default_year or today_kst().year
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        found, ranged = _line_dates(line, year)
        if not found:
            continue
        deadline = _DEADLINE_WORDS.search(line) or (ranged and _APPLY_WORDS.search(line))
        kind = "deadline" if deadline else "event" if _EVENT_WORDS.search(line) else "date"
        for i, (d, assumed) in enumerate(found):
            k = kind if (kind != "deadline" or i == len(found) - 1) else "period_start"
            out.append(dict(date=d.isoformat(), kind=k, quote=line[:240], year_assumed=assumed))
            if len(out) >= limit:
                return out
    return out


# =========================================================================== parameter models
class RagParams(P):
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=500)]
    category: Text | None = None
    top_k: int = Field(6, ge=1, le=10)


class DocLookupParams(P):
    document_id: Text | None = None
    q: Text | None = None
    category: Text | None = None
    limit: int = Field(8, ge=1, le=20)


class AnnSearchParams(P):
    q: Text | None = None
    category: Text | None = None
    status: Literal["active", "upcoming", "expired"] | None = None
    limit: int = Field(8, ge=1, le=20)


class AnnDetailParams(P):
    announcement_id: Text


class DeadlineParams(P):
    announcement_id: Text | None = None
    document_id: Text | None = None
    text: Annotated[str, StringConstraints(max_length=8000)] | None = None
    upcoming_only: bool = True


class SearchParams(P):
    q: Text | None = None
    include_expired: bool = False
    limit: int = Field(12, ge=1, le=30)


class EventParams(P):
    days: int = Field(60, ge=1, le=365)
    limit: int = Field(12, ge=1, le=30)


class TopicParams(P):
    topic: Literal["extension", "residence_card", "address", "part_time", "d2", "d4", "registration", "leave",
                   "graduation", "general"] = "general"
    q: Text | None = None


class EmptyParams(P):
    pass


class FetchParams(P):
    url: Annotated[str, StringConstraints(strip_whitespace=True, min_length=8, max_length=1000)]


class VerifyParams(P):
    document_id: Text | None = None
    announcement_id: Text | None = None
    url: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] | None = None


class SummarizeParams(P):
    document_id: Text | None = None
    announcement_id: Text | None = None
    language: Lang | None = None


class TranslateParams(P):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
    target_language: Lang
    source_language: Lang | None = None


class SupportRequestParams(P):
    subject: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=200)]
    summary: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
    language: Lang | None = None


class StatusParams(P):
    limit: int = Field(10, ge=1, le=30)


class UpcomingParams(P):
    days: int = Field(30, ge=1, le=180)
    category: Text | None = None
    limit: int = Field(12, ge=1, le=30)


class UpdatesParams(P):
    limit: int = Field(12, ge=1, le=30)
    include_closed: bool = True


class TermParams(P):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class QueueParams(P):
    status: Literal["todo", "machine_draft", "needs_review", "in_review", "changes_requested"] | None = None
    limit: int = Field(20, ge=1, le=50)


class DraftParams(P):
    announcement_id: Text | None = None
    document_id: Text | None = None
    summary: bool = False          # documents only: a labelled summary for review instead of a full translation


class SupportQueueParams(P):
    language: Lang | None = None
    limit: int = Field(20, ge=1, le=50)


class TaskStatusParams(P):
    task_id: Text


class CreateTaskParams(P):
    agent_id: Text
    task_type: Text
    params: dict[str, Any] = Field(default_factory=dict)


class WebSearchParams(P):
    query: Text


# =========================================================================== handlers
def rag_search(ctx: ToolContext, p: RagParams) -> dict[str, Any]:
    res = ctx.svc.retrieval.search(p.query, category=p.category, top_k=p.top_k, max_per_document=2)
    items = _passages(ctx.svc, res.get("results", []))
    notes = [] if items else ["no_match"]
    return result("rag_search", items, notes=notes, query=p.query)


def knowledge_document_lookup(ctx: ToolContext, p: DocLookupParams) -> dict[str, Any]:
    if p.document_id:
        d = ctx.svc.public.get_document(p.document_id)          # NotFound for anything not public
        return result("knowledge_document_lookup", [_doc_item(d)])
    return result("knowledge_document_lookup",
                  [_doc_item(d) for d in _documents(ctx.svc, q=p.q, category=p.category, size=p.limit)])


def announcement_search(ctx: ToolContext, p: AnnSearchParams) -> dict[str, Any]:
    rows = _announcements(ctx.svc, q=p.q, category=p.category, status=p.status, size=p.limit, language=ctx.language)
    return result("announcement_search", [_ann_item(a) for a in rows])


def announcement_detail(ctx: ToolContext, p: AnnDetailParams) -> dict[str, Any]:
    a = ctx.svc.public.get_announcement(p.announcement_id)
    item = _ann_item(a) | dict(dates=extract_dates(a["body"]), body_excerpt=a["body"][:1200])
    return result("announcement_detail", [item])


def deadline_extraction(ctx: ToolContext, p: DeadlineParams) -> dict[str, Any]:
    if sum(x is not None for x in (p.announcement_id, p.document_id, p.text)) != 1:
        raise ValidationFailed("Give exactly one of announcement_id, document_id or text.")
    today = today_kst()
    reviewed: list[dict[str, Any]] = []
    if p.announcement_id:
        a = ctx.svc.public.get_announcement(p.announcement_id)
        text, year, source = a["body"], int(str(a.get("published_at") or today)[:4]), _ann_item(a)
        # dates an admin entered and approved are the authoritative ones
        for k in ("deadline", "event_date"):
            if a.get(k):
                reviewed.append(dict(date=a[k], kind="deadline" if k == "deadline" else "event", quote=None,
                                     reviewed=True, year_assumed=False))
    elif p.document_id:
        d = ctx.svc.public.get_document(p.document_id)
        text, year, source = d["content"], int(str(d.get("verified_at") or today)[:4]), _doc_item(d)
    else:
        text, year, source = p.text or "", today.year, None
    found = reviewed + [x | {"reviewed": False} for x in extract_dates(text, default_year=year)]
    if p.upcoming_only:
        found = [x for x in found if x["date"] >= today.isoformat()]
    notes = ["dates_quoted"] if found else ["no_dates"]
    return result("deadline_extraction", found, notes=notes, source=source)


SCHOLARSHIP_RE = re.compile(r"장학|scholarship|beasiswa|học bổng|奖学金|tuition support|등록금\s*지원", re.IGNORECASE)
CAREER_RE = re.compile(r"채용|인턴|취업|일자리|구인|아르바이트|job|\bintern(?:ship)?s?\b|career|recruit|employment|part-time|"
                       r"lowongan|magang|việc làm|thực tập|招聘|实习", re.IGNORECASE)
TOPIK_RE = re.compile(r"topik|한국어능력시험|한국어\s*능력", re.IGNORECASE)


def _opportunities(ctx: ToolContext, p: SearchParams, *, categories: tuple[str, ...], pattern: re.Pattern[str],
                   tool: str, notes: list[str]) -> dict[str, Any]:
    anns = _announcements(ctx.svc, size=100, language=ctx.language)
    picked = [a for a in anns if a["category"] in categories or _matches(a["title"], pattern)]
    if p.q:
        ql = p.q.lower()
        picked = [a for a in picked if ql in (a["title"] + " " + (a.get("excerpt") or "")).lower()]
    items = [_ann_item(a) for a in picked]
    if not p.include_expired:
        items = [i for i in items if i["status"] != "expired"]
    # soonest deadline first; open-ended ones after
    items.sort(key=lambda i: (i["deadline"] is None, i["deadline"] or "", i["title"]))
    docs = [_doc_item(d) for c in categories for d in _documents(ctx.svc, q=p.q, category=c, size=20)]
    items = _dedupe(items + docs)[: p.limit]
    if not items:
        notes = ["nothing_published", *notes]
    return result(tool, items, notes=notes)


def scholarship_search(ctx: ToolContext, p: SearchParams) -> dict[str, Any]:
    return _opportunities(ctx, p, categories=("scholarships",), pattern=SCHOLARSHIP_RE, tool="scholarship_search",
                          notes=["eligibility_office"])


def career_opportunity_search(ctx: ToolContext, p: SearchParams) -> dict[str, Any]:
    return _opportunities(ctx, p, categories=("employment-internships", "part-time-employment"), pattern=CAREER_RE,
                          tool="career_opportunity_search",
                          notes=["work_permission"])


def event_search(ctx: ToolContext, p: EventParams) -> dict[str, Any]:
    today = today_kst()
    horizon = date.fromordinal(today.toordinal() + p.days).isoformat()
    items = []
    for a in _announcements(ctx.svc, size=100, language=ctx.language):
        when = a.get("event_date")
        if when and today.isoformat() <= when <= horizon:
            items.append(_ann_item(a))
    items.sort(key=lambda i: i["event_date"])
    notes = [] if items else ["no_events"]
    return result("event_search", items[: p.limit], notes=notes)


# topic -> (retrieval category, query). Queries are bilingual because official guidance is mostly Korean.
TOPICS: dict[str, tuple[str, str]] = {
    "extension": ("visa-immigration", "체류기간 연장 허가 신청 서류 extension of stay period documents"),
    "residence_card": ("visa-immigration", "외국인등록증 발급 신청 alien registration residence card"),
    "address": ("visa-immigration", "체류지 변경 신고 기한 change of address report"),
    "part_time": ("visa-immigration", "시간제 취업 허가 유학생 part-time work permission D-2"),
    "d2": ("visa-immigration", "D-2 유학 비자 체류 student visa"),
    "d4": ("visa-immigration", "D-4 어학연수 비자 language training visa"),
    "registration": ("academic-life", "수강신청 기간 방법 course registration"),
    "leave": ("academic-life", "휴학 복학 신청 leave of absence return"),
    "graduation": ("academic-life", "졸업 요건 학점 graduation requirements"),
}


def _checklist(ctx: ToolContext, p: TopicParams, *, tool: str, default_category: str) -> dict[str, Any]:
    category, query = TOPICS.get(p.topic, (default_category, ""))
    if category != default_category:
        raise ValidationFailed(f"Topic '{p.topic}' belongs to another desk.")
    query = " ".join(x for x in (p.q, query) if x) or default_category.replace("-", " ")
    res = ctx.svc.retrieval.search(query, category=default_category, top_k=6, max_per_document=2)
    steps = _passages(ctx.svc, res.get("results", []))
    notes = ["checklist_quoted"]
    if any(s["reliability"] == OUTDATED for s in steps):
        notes.append("some_outdated")
    if not steps:
        notes = ["no_guide"]
    return result(tool, steps, notes=notes, topic=p.topic)


def visa_checklist(ctx: ToolContext, p: TopicParams) -> dict[str, Any]:
    out = _checklist(ctx, p, tool="visa_checklist", default_category="visa-immigration")
    out["notes"].append("visa_not_decision")
    return out


def academic_checklist(ctx: ToolContext, p: TopicParams) -> dict[str, Any]:
    return _checklist(ctx, p, tool="academic_checklist", default_category="academic-life")


def topik_dates(ctx: ToolContext, p: EmptyParams) -> dict[str, Any]:
    today = today_kst().isoformat()
    items: list[dict[str, Any]] = []
    for a in _announcements(ctx.svc, size=100, language=ctx.language):
        if a["category"] == "topik-korean" or _matches(a["title"], TOPIK_RE):
            detail = ctx.svc.public.get_announcement(a["id"])
            dates = [d for d in extract_dates(detail["body"], default_year=int(str(a.get("published_at"))[:4]))
                     if d["date"] >= today]
            items.append(_ann_item(a) | dict(dates=dates))
    guides = [_doc_item(d) for d in _documents(ctx.svc, category="topik-korean", size=10)]
    notes = [] if items else ["no_topik_notice"]
    return result("topik_dates", items + guides, notes=notes)


def official_page_fetch(ctx: ToolContext, p: FetchParams) -> dict[str, Any]:
    from app.services.ingestion.errors import FetchError
    from app.services.ingestion.extractors_html import extract_html

    try:
        fetched = ctx.svc.ingestion.fetcher.fetch(p.url)
    except FetchError as exc:
        raise AppError(exc.message, code="fetch_failed", status_code=502, details={"reason": exc.code}) from exc
    if not fetched.content_type.startswith(("text/html", "application/xhtml+xml", "text/plain")):
        raise ValidationFailed("Only web pages can be checked here; documents go through the review workflow.")
    doc = extract_html(fetched.content, fetched.url, fetched.encoding)
    item = dict(kind="external_page", title=doc.title[:200], href=fetched.url, excerpt=doc.text[:1500],
                dates=extract_dates(doc.text), reliability=EXTERNAL)
    return result("official_page_fetch", [item], notes=["external_unreviewed"])


def source_verification(ctx: ToolContext, p: VerifyParams) -> dict[str, Any]:
    from urllib.parse import urlsplit

    from app.services.retrieval.service import stale_info

    if sum(x is not None for x in (p.document_id, p.announcement_id, p.url)) != 1:
        raise ValidationFailed("Give exactly one of document_id, announcement_id or url.")
    svc = ctx.svc
    if p.announcement_id:
        try:
            a = svc.public.get_announcement(p.announcement_id)
        except NotFound:
            return result("source_verification", [dict(verdict="not_published", reliability=None)])
        item = _ann_item(a) | dict(verdict="hub_expired" if a["status"] == "expired" else "hub_verified",
                                   verified_at=a.get("verified_at"))
        return result("source_verification", [item])
    if p.document_id:
        try:
            d = svc.public.get_document(p.document_id)
        except NotFound:
            return result("source_verification", [dict(verdict="not_published", reliability=None)])
        item = _doc_item(d)
        return result("source_verification", [item | dict(verdict="hub_possibly_outdated" if item["reliability"] == OUTDATED
                                                            else "hub_verified")])
    url = p.url or ""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValidationFailed("Only http(s) URLs can be verified.")
    host = parts.hostname.lower()
    allowed = any(host == d or host.endswith("." + d) for d in svc.domains.domains())
    src = get_one(svc.store, "knowledge_sources", original_url=url)
    doc = get_one(svc.store, "source_documents", canonical_url=url)
    registered = bool((src and src.get("is_active") and src.get("authority_type") != "supporter_submitted") or doc)
    verdict = "hub_registered_source" if registered else "allowlisted_official_domain" if allowed else "unknown_source"
    item = dict(kind="url", href=url, host=host, verdict=verdict,
                reliability=VERIFIED if registered else EXTERNAL if allowed else None)
    if src:
        item |= stale_info(None, src.get("category"), src.get("stale_after_days")) | {"category": src.get("category")}
    return result("source_verification", [item])


def _llm_source(ctx: ToolContext, document_id: str | None, announcement_id: str | None) -> tuple[str, str, str, dict[str, Any]]:
    if (document_id is None) == (announcement_id is None):
        raise ValidationFailed("Give exactly one of document_id or announcement_id.")
    if announcement_id:
        a = ctx.svc.public.get_announcement(announcement_id)
        return a["title"], a["body"], a["original_language"], _ann_item(a)
    d = ctx.svc.public.get_document(document_id or "")
    return d["title"], d["content"], d["language"] or "ko", _doc_item(d)


def summarize(ctx: ToolContext, p: SummarizeParams) -> dict[str, Any]:
    from app.services.translation_drafts import summarize_document

    title, body, src_lang, source = _llm_source(ctx, p.document_id, p.announcement_id)
    target = p.language or ctx.language
    out = summarize_document(ctx.svc.doc_translations.llm, title=title, body=body, source_lang=src_lang,
                             target_lang=target, max_source_chars=ctx.svc.settings.translation_summary_source_chars)
    item = dict(kind="summary", title=out["title"], body=out["body"], language=target, partial=out["partial"],
                href=source["href"], source=source, reliability=AI_GENERATED, model=out["model"])
    return result("summarize_document", [item], notes=["ai_summary"],
        usage=dict(input_tokens=out["input_tokens"], output_tokens=out["output_tokens"]))


def translate_text(ctx: ToolContext, p: TranslateParams) -> dict[str, Any]:
    from app.services.translation_drafts import CHUNK_PROMPT, LANGUAGE_NAMES, SYSTEM_PROMPT, _strip_wrappers

    src = p.source_language or ("ko" if re.search(r"[가-힣]", p.text) else "en")
    if src == p.target_language:
        raise ValidationFailed("The text is already in that language.")
    s, t = LANGUAGE_NAMES[src], LANGUAGE_NAMES[p.target_language]
    r = ctx.svc.doc_translations.llm.complete(
        SYSTEM_PROMPT.format(source=s, target=t),
        CHUNK_PROMPT.format(part=1, total=1, title="student text", source=s, target=t, text=p.text), max_tokens=4096)
    item = dict(kind="translation", body=_strip_wrappers(r.text), language=p.target_language, source_language=src,
                reliability=AI_GENERATED, model=r.model)
    return result("translate_text", [item], notes=["machine_translation"],
                  usage=dict(input_tokens=r.input_tokens, output_tokens=r.output_tokens))


def create_support_request(ctx: ToolContext, p: SupportRequestParams) -> dict[str, Any]:
    assert ctx.user is not None
    # consent = the student approved this exact request (subject, summary, language) in the task's approval step
    t = ctx.svc.support.create_ticket(ctx.user, dict(subject=p.subject, summary=p.summary,
                                                     language=p.language or ctx.user.preferred_language, consent=True))
    item = dict(kind="ticket", id=t["id"], ticket_number=t["ticket_number"], status=t["status"], subject=t["subject"],
                href=f"/support/requests/{t['id']}", reliability=VERIFIED)
    return result("create_support_request", [item])


def support_status(ctx: ToolContext, p: StatusParams) -> dict[str, Any]:
    assert ctx.user is not None
    rows, _ = ctx.svc.support.my_tickets(ctx.user, 1, p.limit)          # only the caller's own tickets
    items = [dict(kind="ticket", id=r["id"], ticket_number=r.get("ticket_number"), status=r["status"],
                  subject=r.get("subject"), updated_at=r.get("updated_at"), href=f"/support/requests/{r['id']}",
                  reliability=VERIFIED) for r in rows]
    return result("get_support_request_status", items,
                  notes=[] if items else ["no_tickets"])


def create_agent_task(ctx: ToolContext, p: CreateTaskParams) -> dict[str, Any]:
    task = ctx.svc.agents.delegate(ctx, p.agent_id, p.task_type, p.params)
    return result("create_agent_task", [task])


def agent_task_status(ctx: ToolContext, p: TaskStatusParams) -> dict[str, Any]:
    assert ctx.user is not None
    return result("get_agent_task_status", [ctx.svc.agents.get(ctx.user, p.task_id, with_events=False)])


def upcoming_deadlines(ctx: ToolContext, p: UpcomingParams) -> dict[str, Any]:
    """Deadlines and event dates that are still ahead: dates of published announcements, and deadlines quoted in reviewed
    official items. Soonest first."""
    today = today_kst()
    end = date.fromordinal(today.toordinal() + p.days).isoformat()
    items: list[dict[str, Any]] = []
    for a in _announcements(ctx.svc, category=p.category, size=100, language=ctx.language):
        when = [d for d in (a.get("deadline"), a.get("event_date")) if d and today.isoformat() <= d <= end]
        if when:
            items.append(_ann_item(a) | dict(next_date=min(when)))
    for i in ctx.svc.discovery.opportunities(kinds=None, limit=100, approved_documents=ctx.svc.public.approved_documents_for_sources):
        d = i.get("next_deadline")
        if d and today.isoformat() <= d <= end and (p.category is None or i.get("category") == p.category):
            items.append(i | dict(next_date=d))
    items = _dedupe(sorted(items, key=lambda i: (i["next_date"], i["title"])))[: p.limit]
    return result("upcoming_deadlines", items, notes=["dates_quoted"] if items else ["no_deadlines"])


def official_updates(ctx: ToolContext, p: UpdatesParams) -> dict[str, Any]:
    """What this desk's official sources published: students see only items an admin reviewed and the Knowledge Center
    approved; admins also see waiting candidates (labelled)."""
    staff = ctx.user is not None and ctx.user.is_admin
    items = ctx.svc.discovery.opportunities(kinds=None, include_closed=p.include_closed, limit=p.limit, agent_id=ctx.agent.id,
                                            approved_documents=ctx.svc.public.approved_documents_for_sources,
                                            reviewed_only=not staff)
    sources = [s for s in ctx.svc.discovery.list_sources(ctx.agent.id) if s["enabled"]]
    notes = ["no_sources"] if not sources else ["no_reviewed_updates"] if not items else \
        ["official_unreviewed" if any(i["reliability"] != VERIFIED for i in items) else "official_reviewed"]
    return result("official_updates", items, notes=notes,
                  sources=[dict(name=s["name"], url=s["url"], last_checked_at=s.get("last_checked_at"),
                                status=s.get("last_status")) for s in sources])


def terminology_lookup(ctx: ToolContext, p: TermParams) -> dict[str, Any]:
    """Administrative terms found in a text (any of the five languages), in all five languages. A draft term list."""
    from app.gpu_worker.glossary import TERMS

    items = []
    low = p.text.lower()
    for row in TERMS:
        hit = re.search(row[0], p.text)
        if not hit:
            hit = next((x for x in row[1:] if len(x) > 2 and re.split(r" \(|（", x)[0].lower() in low), None)
        if hit:
            ko = re.sub(r"\(\?[!=<].*?\)|\\\\s\*|\\\\", "", row[0]).split("|")[0]
            items.append(dict(kind="term", title=ko, terms={"ko": ko, "en": row[1], "id": row[2], "vi": row[3], "zh-CN": row[4]},
                              reliability=None))
        if len(items) >= 15:
            break
    return result("terminology_lookup", items, notes=["terms_draft"] if items else ["no_terms"])


def translation_review_queue(ctx: ToolContext, p: QueueParams) -> dict[str, Any]:
    """Translations of this supporter's language that wait for a person. Only the caller's own language permissions count."""
    from app.security.permissions import languages_with

    assert ctx.user is not None
    lang = ctx.agent.fixed_language or ctx.language
    mine = set(languages_with(ctx.user, "support")) | set(languages_with(ctx.user, "review"))
    if lang not in mine:
        return result("translation_review_queue", [], notes=["not_your_language"], counts={}, language=lang)
    svc = ctx.svc
    open_states = {"todo", "machine_draft", "draft", "in_review", "changes_requested", "needs_review"}
    anns, _ = svc.translations.tasks(ctx.user, p.status, lang, None, 1, 100)
    docs, _ = svc.doc_translations.tasks(ctx.user, status=p.status, language=lang, outdated=None, page=1, size=100)
    items: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for t, kind in [*((a, "announcement") for a in anns), *((d, "document") for d in docs)]:
        st = t["translation_status"]
        if st not in open_states and not t.get("is_outdated"):
            continue
        if kind == "document" and not t.get("document_live", True):
            continue
        counts["outdated" if t.get("is_outdated") else st] = counts.get("outdated" if t.get("is_outdated") else st, 0) + 1
        ref = t["announcement_id"] if kind == "announcement" else t["document_id"]
        items.append(dict(kind="translation_task", id=t["id"], title=t.get("announcement_title") or t.get("document_title") or "",
                          content_kind=kind, ref=ref, status=st, outdated=bool(t.get("is_outdated")), updated_at=t.get("updated_at"),
                          can_review=bool(t.get("can_can_review") or t.get("can_review")),
                          href=f"/admin/translations/{ref}/{lang}" if kind == "announcement" else f"/admin/translations/documents/{ref}/{lang}",
                          reliability=None))
    rank = {"in_review": 0, "needs_review": 1, "machine_draft": 2, "draft": 3, "changes_requested": 4, "todo": 5}
    items.sort(key=lambda i: (rank.get(i["status"], 9), str(i["updated_at"] or "")))
    return result("translation_review_queue", items[: p.limit], notes=[] if items else ["queue_empty"], counts=counts, language=lang)


def request_translation_draft(ctx: ToolContext, p: DraftParams) -> dict[str, Any]:
    """Queue one machine DRAFT in this supporter's language (the durable translation queue: GPU worker when one is connected,
    else the server's model). Every rule of the admin page applies; a draft never becomes public without a reviewer."""
    if (p.announcement_id is None) == (p.document_id is None):
        raise ValidationFailed("Give exactly one of announcement_id or document_id.")
    assert ctx.user is not None
    lang = ctx.agent.fixed_language or ctx.language
    if p.document_id:
        out = ctx.svc.doc_translations.request_drafts(p.document_id, [lang], ctx.user, summary=p.summary)[0]
        job_id, status = out["job_id"], out["status"]
    else:
        if p.summary:
            raise ValidationFailed("Announcements are translated in full.")
        perms = ctx.svc.translations.permissions(ctx.user, lang)
        if not (perms["can_edit"] or perms["can_review"]):
            raise Forbidden("You are not assigned to translations in this language.")
        job = ctx.svc.announcement_translator.queue(p.announcement_id or "", lang, ctx.user.id)
        job_id, status = job["id"], job["status"]
    job = get_one(ctx.svc.store, "ingestion_jobs", id=job_id) or {}
    item = dict(kind="translation_job", id=job_id, title=lang, status=status, executor=job.get("executor") or "local", reliability=None,
                href="/admin/translations")
    return result("request_translation_draft", [item], notes=["draft_needs_review"])


def support_queue(ctx: ToolContext, p: SupportQueueParams) -> dict[str, Any]:
    """Waiting requests in the caller's languages: number, language, age, priority. Never the student's text."""
    from app.security.permissions import languages_with

    assert ctx.user is not None
    if p.language and p.language not in languages_with(ctx.user, "support"):
        raise ToolDenied("You are not assigned to support in this language.")
    rows, total = ctx.svc.support.inbox(ctx.user, "queue", p.language, 1, p.limit)
    items = [dict(kind="ticket", id=r["id"], ticket_number=r["ticket_number"], status=r["status"], title=f"#{r['ticket_number']}",
                  language=r["language"], priority=r["priority"], created_at=r["created_at"], escalated=r["escalated"],
                  href=f"/admin/support/{r['id']}" if r["can_open"] else "/admin/support", reliability=None) for r in rows]
    return result("support_queue", items, notes=[] if items else ["queue_empty"], counts=ctx.svc.support.counts(ctx.user), total=total)


def web_search(ctx: ToolContext, p: WebSearchParams) -> dict[str, Any]:  # pragma: no cover - never available
    raise ToolUnavailable("No web search provider is configured.")


# =========================================================================== official-source discovery (Phase 3)
ADMIN = ("super_admin", "admin")
STAFF = ("supporter", "admin", "super_admin")
#: what each discovery desk shows as opportunities
DESK_KINDS = {"career": ["job"], "events": ["event", "program"], "scholarship": ["scholarship", "competition", "program"]}


class SourceCheckParams(P):
    source_ids: list[Annotated[str, StringConstraints(max_length=64)]] | None = Field(default=None, max_length=10)
    max_items: int | None = Field(default=None, ge=1, le=30)
    max_sources: int = Field(5, ge=1, le=10)
    summarize: bool = False


class OpportunityParams(P):
    q: Text | None = None
    kind: Literal["scholarship", "competition", "program", "job", "event"] | None = None
    include_closed: bool = False
    limit: int = Field(12, ge=1, le=30)


class CandidateParams(P):
    status: Literal["candidate", "dismissed", "imported", "all"] = "candidate"
    changed_only: bool = False
    limit: int = Field(20, ge=1, le=50)


def official_source_check(ctx: ToolContext, p: SourceCheckParams) -> dict[str, Any]:
    """Check this agent's configured official sources now (admin or an enabled schedule). New and changed items
    become review candidates; nothing is published."""
    disc = ctx.svc.discovery
    sched = (ctx.task or {}).get("schedule_id")
    run = disc.check_sources(ctx.agent.id, source_ids=p.source_ids, max_sources=p.max_sources, max_items=p.max_items,
                             scheduled=bool(sched), summarize=p.summarize, progress=ctx.progress,
                             checkpoint=ctx.checkpoint, log_step=ctx.log)
    changed = [i for r in run["sources"] for i in r["item_ids"]]
    items = disc.items_by_id(list(dict.fromkeys(changed)), admin=True)
    items.sort(key=lambda i: {"new": 0, "updated": 1, "unchanged": 2}[i["change"]])
    notes = ["candidates_need_review"] if items else ["no_sources" if not run["sources_total"] else "nothing_found"]
    if any(r["status"] in ("failed", "blocked") for r in run["sources"]):
        notes.append("some_sources_failed")
    if any(r["status"] == "recently_checked" for r in run["sources"]):
        notes.append("recently_checked")
    return result("official_source_check", items, notes=notes, sources=run["sources"], new_count=run["new"],
                  updated_count=run["updated"])


def opportunity_search(ctx: ToolContext, p: OpportunityParams) -> dict[str, Any]:
    kinds = [p.kind] if p.kind else DESK_KINDS.get(ctx.agent.id, DESK_KINDS["scholarship"])
    staff = ctx.user is not None and ctx.user.is_admin
    # students and visitors: only discoveries an admin reviewed and the Knowledge Center approved
    items = ctx.svc.discovery.opportunities(q=p.q, kinds=kinds, include_closed=p.include_closed, limit=p.limit,
                                            approved_documents=ctx.svc.public.approved_documents_for_sources,
                                            reviewed_only=not staff)
    if staff:
        unreviewed = any(i["reliability"] != "verified" for i in items)
        notes = [("official_unreviewed" if unreviewed else "official_reviewed"), "open_only_when_stated"] if items \
            else ["no_discoveries"]
    elif items:
        notes = ["official_reviewed", "open_only_when_stated"]
    elif not p.include_closed and ctx.svc.discovery.opportunities(
            q=p.q, kinds=kinds, include_closed=True, limit=1,
            approved_documents=ctx.svc.public.approved_documents_for_sources):
        notes = ["reviewed_closed_hidden"]           # approved ones exist, all closed: say so precisely
    else:
        notes = ["no_reviewed_discoveries"]
    if any("missing_deadline" in i["flags"] or "missing_eligibility" in i["flags"] for i in items):
        notes.append("some_missing_info")
    return result("opportunity_search", items, notes=notes)


def review_candidates(ctx: ToolContext, p: CandidateParams) -> dict[str, Any]:
    items = ctx.svc.discovery.candidates(agent_id=ctx.agent.id, status=p.status, changed_only=p.changed_only,
                                         limit=p.limit)
    return result("review_candidates", items, notes=[] if items else ["no_candidates"])


def _drafts_available(svc: Services) -> str | None:
    if svc.doc_translations.can_generate or svc.announcement_translator.can_generate:
        return None
    return "No translation model is configured and no GPU worker is connected."


def _llm_available(svc: Services) -> str | None:
    llm = svc.doc_translations.llm
    return None if getattr(llm, "enabled", False) else "No AI model is configured on this server."


TOOLS: dict[str, Tool] = {t.name: t for t in [
    Tool("rag_search", "Search approved Hub guides and notices (quoted passages with links).", RagParams, rag_search),
    Tool("knowledge_document_lookup", "Open or list approved Knowledge Center guides.", DocLookupParams,
         knowledge_document_lookup),
    Tool("announcement_search", "List published university announcements.", AnnSearchParams, announcement_search),
    Tool("announcement_detail", "Read one published announcement with the dates it mentions.", AnnDetailParams,
         announcement_detail),
    Tool("deadline_extraction", "Find deadlines and dates written in an announcement, guide or text.", DeadlineParams,
         deadline_extraction),
    Tool("scholarship_search", "Published scholarship notices and guides, deduplicated, expired ones flagged.",
         SearchParams, scholarship_search),
    Tool("event_search", "Upcoming published events, soonest first.", EventParams, event_search),
    Tool("career_opportunity_search", "Published job, internship and career notices and guides.", SearchParams,
         career_opportunity_search),
    Tool("visa_checklist", "Procedure steps quoted from approved immigration guides.", TopicParams, visa_checklist),
    Tool("academic_checklist", "Procedure steps quoted from approved academic guides.", TopicParams, academic_checklist),
    Tool("topik_dates", "TOPIK notices with the dates they announce, and TOPIK guides.", EmptyParams, topik_dates),
    Tool("official_page_fetch", "Read a page on an allowlisted official website (not reviewed).", FetchParams,
         official_page_fetch, requires_auth=True, background=True),
    Tool("source_verification", "Check whether a source is approved Hub content or an allowlisted official site.",
         VerifyParams, source_verification),
    Tool("summarize_document", "AI summary of an approved guide or announcement in a chosen language.",
         SummarizeParams, summarize, requires_auth=True, background=True, uses_llm=True, availability=_llm_available),
    Tool("translate_text", "AI translation of a short text.", TranslateParams, translate_text, requires_auth=True,
         background=True, uses_llm=True, availability=_llm_available),
    Tool("create_support_request", "Send a request to a human Global Supporter (after you confirm).",
         SupportRequestParams, create_support_request, requires_auth=True, writes=True, needs_approval=True),
    Tool("get_support_request_status", "Status of your own support requests.", StatusParams, support_status,
         requires_auth=True),
    Tool("create_agent_task", "Hand a task to another agent.", CreateTaskParams, create_agent_task, requires_auth=True),
    Tool("get_agent_task_status", "Status of one of your tasks.", TaskStatusParams, agent_task_status,
         requires_auth=True),
    Tool("official_source_check", "Check the configured official websites now; new or changed notices become "
         "review candidates.", SourceCheckParams, official_source_check, background=True, roles=ADMIN),
    Tool("opportunity_search", "Opportunities found on configured official websites (students: only reviewed and approved ones).",
         OpportunityParams, opportunity_search),
    Tool("review_candidates", "Discovered official notices waiting for an admin's review.", CandidateParams,
         review_candidates, roles=ADMIN),
    Tool("upcoming_deadlines", "Deadlines and event dates that are still ahead, from published and reviewed content.", UpcomingParams,
         upcoming_deadlines),
    Tool("official_updates", "Reviewed items found on this desk's official websites.", UpdatesParams, official_updates),
    Tool("terminology_lookup", "Administrative terms in five languages (draft term list).", TermParams, terminology_lookup),
    Tool("translation_review_queue", "Translations in this language that wait for a person.", QueueParams,
         translation_review_queue, requires_auth=True, roles=STAFF),
    Tool("request_translation_draft", "Queue a machine draft for review in this language.", DraftParams,
         request_translation_draft, requires_auth=True, writes=True, roles=STAFF, availability=lambda svc: _drafts_available(svc)),
    Tool("support_queue", "Waiting support requests in your languages (no private text).", SupportQueueParams, support_queue,
         requires_auth=True, roles=STAFF),
    Tool("official_web_search", "Search the open web for official pages.", WebSearchParams, web_search,
         availability=lambda svc: "No web search provider is configured. Agents use the Hub's approved content and "
                                  "allowlisted official pages only."),
]}


class ToolRegistry:
    """Validates and runs one tool call for one agent. All permission checks happen here."""

    def __init__(self, tools: dict[str, Tool] | None = None):
        self.tools = tools or TOOLS

    def describe(self, svc: Services, agent: AgentDefinition, known: dict[str, str | None] | None = None) -> list[dict[str, Any]]:
        """``known``: availability already looked up for other agents (some checks read the database)."""
        known = {} if known is None else known
        out = []
        for name in sorted(agent.allowed_tools):
            t = self.tools.get(name)
            if t is None:
                continue
            if name not in known:
                known[name] = t.unavailable_reason(svc)
            reason = known[name]
            out.append(dict(name=name, description=t.description, available=reason is None, unavailable_reason=reason,
                            requires_sign_in=t.requires_auth, background=t.background, uses_ai=t.uses_llm,
                            needs_approval=t.needs_approval,
                            admin_only=t.roles is not None and "supporter" not in t.roles, roles=list(t.roles) if t.roles else None))
        return out

    def check(self, ctx: ToolContext, name: str) -> Tool:
        t = self.tools.get(name)
        if t is None or name not in ctx.agent.allowed_tools:
            raise ToolDenied(f"{ctx.agent.name} is not allowed to use '{name}'.")
        reason = t.unavailable_reason(ctx.svc)
        if reason:
            raise ToolUnavailable(reason)
        if t.roles is not None and not ctx.system:
            if ctx.user is None:
                raise NotAuthenticated("Sign in to use this.")
            if ctx.user.role not in t.roles:
                if "supporter" in t.roles:
                    raise ToolDenied(f"'{name}' is only available to Global Supporters and administrators.", code="staff_only")
                raise ToolDenied(f"'{name}' is only available to administrators.", code="admin_only")
        if t.requires_auth and ctx.user is None and not ctx.system:
            raise NotAuthenticated("Sign in to use this.")
        if t.background and not ctx.in_task:
            raise ToolDenied(f"'{name}' runs only as a background task.", code="background_only")
        if t.needs_approval and not ctx.approved:
            raise ToolDenied(f"'{name}' needs your confirmation first.", code="approval_required")
        return t

    def validate(self, name: str, params: dict[str, Any]) -> P:
        t = self.tools.get(name)
        if t is None:
            raise ToolDenied(f"Unknown tool '{name}'.")
        try:
            return t.params.model_validate(params or {})
        except ValidationError as exc:
            raise ValidationFailed("Invalid tool parameters.",
                                   details={"errors": [dict(loc=list(e["loc"]), msg=e["msg"]) for e in exc.errors()]}) from exc

    def run(self, ctx: ToolContext, name: str, params: dict[str, Any]) -> dict[str, Any]:
        tool = self.check(ctx, name)
        p = self.validate(name, params)
        started = time.monotonic()
        ctx.log(ctx.agent.id, "tool", name, f"{ctx.agent.name} used {name}", dict(params=p.model_dump(exclude_none=True)))
        out = tool.handler(ctx, p)
        out["duration_ms"] = int((time.monotonic() - started) * 1000)
        out["agent_id"] = ctx.agent.id
        ctx.log(ctx.agent.id, "result", name, f"{name}: {out['count']} result(s)", dict(count=out["count"]))
        return out


_ = LANGUAGES
