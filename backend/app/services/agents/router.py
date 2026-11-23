"""Request router: turns a student's free-text request to an agent into ONE of five decisions, deterministically
(keyword rules in the five site languages - no model call, so routing costs nothing and cannot be prompt-injected):

  answer       a question: send it to the grounded assistant (existing RAG chat, the shared model)
  tool         a structured, read-only lookup (runs now, returns items with links)
  task         background work (model or network): a durable task
  approval     an action with side effects (a request to a human supporter): a task that waits for confirmation
  clarify      too vague: ask the student to choose

When the matched work belongs to another desk, the plan names that agent; the caller delegates if the requesting
agent may (``can_delegate_to``), otherwise it points the student to the right desk.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.services.agents.registry import AgentDefinition


@dataclass
class Plan:
    route: str                           # answer | tool | task | approval | clarify
    agent_id: str                        # who does the work
    target: str | None = None            # tool name or task type
    params: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    options: list[str] = field(default_factory=list)


def _re(*words: str) -> re.Pattern[str]:
    return re.compile("|".join(words), re.IGNORECASE)


HUMAN = _re(r"사람|상담원|직원|서포터|담당자", r"human", r"real person", r"supporter", r"talk to (?:a|someone)",
            r"staff member", r"manusia|petugas|orang", r"người thật|nhân viên|tư vấn viên", r"人工|真人|工作人员")
MY_REQUESTS = _re(r"내 (?:요청|문의)", r"my (?:support )?(?:request|ticket)s?", r"status of my",
                  r"permintaan saya|tiket saya", r"yêu cầu của tôi", r"我的(?:请求|工单)")
SUMMARIZE = _re(r"요약", r"summar", r"ringkas", r"tóm tắt", r"总结|摘要")
TRANSLATE = _re(r"번역", r"translat", r"terjemah", r"dịch", r"翻译")
SCHOLARSHIP = _re(r"장학", r"scholarship", r"beasiswa", r"học bổng", r"奖学金")
CAREER = _re(r"채용|인턴|취업|일자리|아르바이트|알바", r"\bjob", r"intern", r"career", r"part[- ]time job",
             r"lowongan|magang|pekerjaan", r"việc làm|thực tập", r"招聘|实习|工作")
EVENT = _re(r"행사|이벤트|축제|설명회", r"\bevents?\b", r"festival", r"what'?s on", r"acara", r"sự kiện", r"活动")
TOPIK = _re(r"topik", r"한국어능력시험")
DEADLINE = _re(r"마감|기한|언제까지", r"deadline", r"due date", r"batas waktu|tenggat", r"hạn chót|hạn nộp", r"截止")
NOTICE = _re(r"공지", r"announcement|notice", r"pengumuman", r"thông báo", r"公告|通知")
CHANGES = _re(r"새로운|변경|바뀐", r"\bnew\b|changed|updated|what changed", r"baru|berubah", r"mới|thay đổi", r"新|变化|更新")
VISA_TOPICS: list[tuple[str, re.Pattern[str]]] = [
    ("part_time", _re(r"시간제\s*취업|아르바이트 허가", r"part[- ]time (?:work )?permi", r"work permit", r"izin kerja",
                      r"giấy phép làm thêm", r"打工许可")),
    ("extension", _re(r"연장", r"extend|extension", r"perpanjang", r"gia hạn", r"延期|延长")),
    ("residence_card", _re(r"외국인\s*등록|등록증|ARC\b", r"residence card|alien registration", r"kartu", r"thẻ cư trú",
                           r"登录证|外国人登记")),
    ("address", _re(r"주소|체류지", r"address", r"alamat", r"địa chỉ", r"地址")),
    ("d2", _re(r"D-?2")),
    ("d4", _re(r"D-?4")),
]
VISA = _re(r"비자|체류|출입국", r"visa", r"immigration", r"imigrasi", r"thị thực|xuất nhập cảnh", r"签证|出入境")
ACADEMIC_TOPICS: list[tuple[str, re.Pattern[str]]] = [
    ("registration", _re(r"수강\s*신청", r"course registration|register for (?:a )?course|enrol", r"pendaftaran mata kuliah|krs",
                         r"đăng ký (?:môn|học phần)", r"选课")),
    ("leave", _re(r"휴학|복학", r"leave of absence", r"cuti", r"bảo lưu", r"休学")),
    ("graduation", _re(r"졸업", r"graduat", r"kelulusan|lulus", r"tốt nghiệp", r"毕业")),
]
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)


def plan_request(agent: AgentDefinition, message: str, *, signed_in: bool) -> Plan:
    m = (message or "").strip()
    if len(m) < 2:
        return Plan("clarify", agent.id, reason="empty", options=_options(agent))
    ref = UUID.search(m)

    if MY_REQUESTS.search(m):
        return Plan("tool", "support-coordinator", "get_support_request_status", reason="my_requests")
    if HUMAN.search(m):
        return Plan("approval", "support-coordinator", "support_request",
                    dict(subject=m[:120], summary=m[:4000]), reason="human_support")
    if SUMMARIZE.search(m) and ref:
        return Plan("task", agent.id if "summarize_document" in agent.allowed_tools else "announcement",
                    "summarize_announcement", dict(ref=ref.group(0)), reason="summarize")
    if TRANSLATE.search(m) and not ref:
        return Plan("answer", agent.id, reason="translate_in_chat")     # the chat answers in the chosen language
    if SCHOLARSHIP.search(m):
        return Plan("tool", "scholarship", "scholarship_search", reason="scholarship")
    if TOPIK.search(m):
        return Plan("tool", "topik", "topik_dates", reason="topik")
    if CAREER.search(m) and not any(p.search(m) for _, p in VISA_TOPICS[:1]):
        return Plan("tool", "career", "career_opportunity_search", reason="career")
    for topic, pattern in VISA_TOPICS:
        if pattern.search(m):
            return Plan("tool", "immigration", "visa_checklist", dict(topic=topic), reason="visa")
    for topic, pattern in ACADEMIC_TOPICS:
        if pattern.search(m):
            return Plan("tool", "academic", "academic_checklist", dict(topic=topic), reason="academic")
    if EVENT.search(m):
        if CHANGES.search(m) and signed_in:
            return Plan("task", "events", "event_digest", reason="event_changes")
        return Plan("tool", "events", "event_search", reason="events")
    if NOTICE.search(m) or DEADLINE.search(m):
        if CHANGES.search(m) and signed_in:
            return Plan("task", "announcement", "announcement_digest", reason="announcement_changes")
        return Plan("tool", "announcement", "announcement_search", dict(status="active"), reason="notices")
    if VISA.search(m):
        return Plan("tool", "immigration", "visa_checklist", dict(topic="general"), reason="visa")
    # an actual question: the grounded assistant answers it (with citations), in the agent's language
    if len(m) >= 8 or "?" in m or "？" in m:
        return Plan("answer", agent.id, reason="question")
    return Plan("clarify", agent.id, reason="vague", options=_options(agent))


def _options(agent: AgentDefinition) -> list[str]:
    return [a.id for a in agent.actions][:4]
