"""Pydantic request/response models (see docs/api-contract.md)."""
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from app.core.constants import CATEGORY_SLUGS

Lang = Literal["ko", "en", "id", "vi", "zh-CN"]
SourceType = Literal["website", "sch_board", "pdf", "docx", "text_file", "screenshot", "manual_text", "kakao_message"]
AuthorityType = Literal["official_university", "official_government", "staff_communication", "supporter_submitted", "other"]
Scope = Literal["university", "national"]
SyncFrequency = Literal["manual", "daily", "weekly"]
Role = Literal["super_admin", "admin", "supporter", "student"]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=2000)]

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


class Loose(BaseModel):
    model_config = ConfigDict(extra="allow")


def _check_category(v: str) -> str:
    if v not in CATEGORY_SLUGS:
        raise ValueError(f"unknown category '{v}'")
    return v


# ------------------------------------------------------------------ requests
class BoardConfig(BaseModel):
    max_items: int = Field(default=5, ge=1, le=30)
    max_pages: int = Field(default=1, ge=1, le=5)


class SourceCreate(BaseModel):
    title: Title
    original_url: str | None = Field(default=None, max_length=2048)
    organization: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    source_type: SourceType
    authority_type: AuthorityType
    scope: Scope
    category: str
    language: Lang = "ko"
    sync_frequency: SyncFrequency = "manual"
    is_active: bool = True
    config: BoardConfig | None = None
    stale_after_days: int | None = Field(default=None, ge=1, le=3650)

    _cat = field_validator("category")(_check_category)

    @model_validator(mode="after")
    def _rules(self) -> SourceCreate:
        if self.source_type in ("website", "sch_board") and not self.original_url:
            raise ValueError("original_url is required for website and notice-board sources")
        if self.source_type not in ("website", "sch_board") and self.sync_frequency != "manual":
            raise ValueError("only website and notice-board sources can use daily/weekly sync")
        if self.source_type == "kakao_message" and self.authority_type not in ("supporter_submitted", "staff_communication"):
            raise ValueError("KakaoTalk sources must use authority_type 'staff_communication' or 'supporter_submitted'")
        return self


class SourcePatch(BaseModel):
    title: Title | None = None
    organization: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)] | None = None
    category: str | None = None
    sync_frequency: SyncFrequency | None = None
    language: Lang | None = None
    scope: Scope | None = None
    authority_type: AuthorityType | None = None
    config: BoardConfig | None = None
    stale_after_days: int | None = Field(default=None, ge=1, le=3650)

    @field_validator("category")
    @classmethod
    def _cat(cls, v: str | None) -> str | None:
        return _check_category(v) if v is not None else v


class SubmitText(BaseModel):
    title: Title
    text: Annotated[str, StringConstraints(min_length=10, max_length=200_000)]
    source_published_at: datetime | None = None
    external_id: Annotated[str, StringConstraints(max_length=200)] | None = None
    authorized_by_supporter: bool = False


class NoteBody(BaseModel):
    note: Annotated[str, StringConstraints(max_length=2000)] | None = None


class ReasonBody(BaseModel):
    reason: Reason


class RollbackBody(BaseModel):
    version_id: str
    note: Annotated[str, StringConstraints(max_length=2000)] | None = None


class SearchRequest(BaseModel):
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
    language: Lang | None = None
    category: str | None = None
    top_k: int = Field(default=5, ge=1, le=20)
    mode: Literal["hybrid", "vector", "keyword"] = "hybrid"
    scope: Scope | None = None
    authority: list[AuthorityType] | None = Field(default=None, max_length=5)

    @field_validator("category")
    @classmethod
    def _cat(cls, v: str | None) -> str | None:
        return _check_category(v) if v is not None else v


class AnnouncementCreate(BaseModel):
    title: Title
    body: Annotated[str, StringConstraints(min_length=10, max_length=100_000)]
    category: str
    target_audience: Annotated[str, StringConstraints(max_length=500)] | None = None
    event_date: date | None = None
    deadline: date | None = None
    valid_from: date | None = None
    source_type: Literal["manual_text", "kakao_message"] = "manual_text"
    source_published_at: datetime | None = None
    evidence_note: Annotated[str, StringConstraints(max_length=2000)] | None = None
    evidence_url: Annotated[str, StringConstraints(max_length=2048)] | None = None
    original_language: Lang = "ko"
    submit: bool = False
    authorized_by_supporter: bool = False

    _cat = field_validator("category")(_check_category)

    @field_validator("evidence_url")
    @classmethod
    def _url(cls, v: str | None) -> str | None:
        if v and not v.lower().startswith(("http://", "https://")):
            raise ValueError("evidence_url must start with http:// or https://")
        return v

    @model_validator(mode="after")
    def _dates(self) -> AnnouncementCreate:
        if self.deadline and self.valid_from and self.deadline < self.valid_from:
            raise ValueError("deadline cannot be before valid_from")
        return self


class AnnouncementPatch(BaseModel):
    title: Title | None = None
    body: Annotated[str, StringConstraints(min_length=10, max_length=100_000)] | None = None
    category: str | None = None
    target_audience: Annotated[str, StringConstraints(max_length=500)] | None = None
    event_date: date | None = None
    deadline: date | None = None
    valid_from: date | None = None
    evidence_note: Annotated[str, StringConstraints(max_length=2000)] | None = None
    evidence_url: Annotated[str, StringConstraints(max_length=2048)] | None = None

    @field_validator("category")
    @classmethod
    def _cat(cls, v: str | None) -> str | None:
        return _check_category(v) if v is not None else v

    @field_validator("evidence_url")
    @classmethod
    def _url(cls, v: str | None) -> str | None:
        if v and not v.lower().startswith(("http://", "https://")):
            raise ValueError("evidence_url must start with http:// or https://")
        return v


class TranslationUpsert(BaseModel):
    title: Title
    body: Annotated[str, StringConstraints(min_length=1, max_length=100_000)]
    translation_status: Literal["machine_draft", "in_review"] = "in_review"  # machine_draft = save draft


class TranslationApprove(BaseModel):
    original_verified: bool = False
    note: Annotated[str, StringConstraints(max_length=2000)] | None = None


class RoleUpdate(BaseModel):
    role: Role


class LanguagesUpdate(BaseModel):
    languages: list[Lang]


# ----------------------------------------------------------------- responses
class JobAccepted(BaseModel):
    job_id: str
    status: str


class SourceRef(BaseModel):
    title: str | None = None
    organization: str | None = None
    url: str | None = None
    authority_type: str | None = None
    scope: str | None = None


# --------------------------------------------------------------- Phase 2
class UrlCheck(BaseModel):
    url: Annotated[str, StringConstraints(strip_whitespace=True, min_length=8, max_length=2048)]
    source_type: Literal["website", "sch_board"] = "website"
    language: Lang | None = None


class SourceMeta(BaseModel):
    """Metadata for a source created through an intake form."""
    title: Title
    organization: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    category: str
    scope: Scope = "university"
    authority_type: AuthorityType = "official_university"
    language: Lang = "ko"
    original_url: Annotated[str, StringConstraints(max_length=2048)] | None = None

    _cat = field_validator("category")(_check_category)


class ScreenshotSubmit(BaseModel):
    title: Title
    text: Annotated[str, StringConstraints(min_length=10, max_length=100_000)]
    submit: bool = False
    redact_personal_info: bool = True
    source_published_at: datetime | None = None
    fields: dict[str, str | None] = Field(default_factory=dict)

    @field_validator("fields")
    @classmethod
    def _fields(cls, v: dict[str, str | None]) -> dict[str, str | None]:
        allowed = {"deadline", "event_date", "time", "location", "fee", "contact", "eligibility", "required_documents",
                   "application_method", "target_audience", "notes"}
        bad = set(v) - allowed
        if bad:
            raise ValueError(f"unknown field(s): {', '.join(sorted(bad))}")
        return {k: (x[:1000] if isinstance(x, str) else x) for k, x in v.items()}


class AnnouncementPaste(BaseModel):
    original_text: Annotated[str, StringConstraints(min_length=10, max_length=100_000)]
    normalized_text: Annotated[str, StringConstraints(min_length=10, max_length=100_000)] | None = None
    title: Title
    organization: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    category: str
    language: Lang = "ko"
    scope: Scope = "university"
    authority_type: Literal["staff_communication", "official_university", "supporter_submitted"] = "staff_communication"
    received_via: Literal["kakaotalk", "email", "other"] = "kakaotalk"
    target_audience: Annotated[str, StringConstraints(max_length=500)] | None = None
    event_date: date | None = None
    deadline: date | None = None
    location: Annotated[str, StringConstraints(max_length=500)] | None = None
    application_method: Annotated[str, StringConstraints(max_length=2000)] | None = None
    notes: Annotated[str, StringConstraints(max_length=2000)] | None = None
    original_url: Annotated[str, StringConstraints(max_length=2048)] | None = None
    source_published_at: datetime | None = None
    source_id: str | None = None
    redact_personal_info: bool = True
    authorized_by_supporter: bool = False
    submit: bool = False

    _cat = field_validator("category")(_check_category)


class VersionPatch(BaseModel):
    extracted_text: Annotated[str, StringConstraints(min_length=10, max_length=500_000)] | None = None
    title: Title | None = None
    fields: dict[str, str | None] | None = None
    fields_confirmed: bool | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    source_published_at: datetime | None = None


class NoteRequired(BaseModel):
    note: Reason


class DomainAdd(BaseModel):
    domain: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=253)]
    note: Annotated[str, StringConstraints(max_length=500)] | None = None


# ------------------------------------------------- support, conversations, profile
class ProfilePatch(BaseModel):
    preferred_language: Lang | None = None
    display_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)] | None = None


class ConversationCreate(BaseModel):
    language: Lang | None = None   # default: the profile's preferred language
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)] | None = None


class ConversationPatch(BaseModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)] | None = None
    is_private: bool | None = None
    language: Lang | None = None


class ConversationMessage(BaseModel):
    content: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
    language: Lang | None = None   # use another language for this message (the profile is not changed)


class TicketCreate(BaseModel):
    language: Lang | None = None   # default: the profile's preferred language
    subject: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=200)]
    summary: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
    conversation_id: str | None = None
    message_ids: list[str] = Field(default_factory=list, max_length=50)
    additional_message: Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)] | None = None
    consent: bool = False


class TicketReply(BaseModel):
    body: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=8000)]


class TicketFeedback(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] | None = None


class TicketTransfer(BaseModel):
    to_supporter_id: str | None = None   # null = back to the language queue
    reason: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None


class TicketPriority(BaseModel):
    priority: Literal["low", "normal", "high", "urgent"]


class Availability(BaseModel):
    is_available: bool
    max_active_tickets: int | None = Field(default=None, ge=1, le=100)


class TeamAssignment(BaseModel):
    language: Lang
    can_support: bool = True
    can_review_translations: bool = False
    is_team_lead: bool = False


class TeamUpdate(BaseModel):
    assignments: list[TeamAssignment] = Field(max_length=5)
    is_available: bool | None = None
    max_active_tickets: int | None = Field(default=None, ge=1, le=100)


class NotificationsRead(BaseModel):
    ids: list[int] | None = Field(default=None, max_length=200)


class DocumentDelete(BaseModel):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=2000)]
    confirm_title: Annotated[str, StringConstraints(max_length=500)]   # must equal the document title
