"""Pydantic request/response models (see docs/api-contract.md)."""
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from app.core.constants import CATEGORY_SLUGS

Lang = Literal["ko", "en", "id", "vi", "zh-CN"]
SourceType = Literal["website", "pdf", "docx", "manual_text", "kakao_message"]
AuthorityType = Literal["official_university", "official_government", "supporter_submitted", "other"]
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

    _cat = field_validator("category")(_check_category)

    @model_validator(mode="after")
    def _rules(self) -> SourceCreate:
        if self.source_type == "website" and not self.original_url:
            raise ValueError("original_url is required for website sources")
        if self.source_type != "website" and self.sync_frequency != "manual":
            raise ValueError("only website sources can use daily/weekly sync")
        if self.source_type == "kakao_message" and self.authority_type != "supporter_submitted":
            raise ValueError("KakaoTalk sources must use authority_type 'supporter_submitted'")
        return self


class SourcePatch(BaseModel):
    title: Title | None = None
    organization: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)] | None = None
    category: str | None = None
    sync_frequency: SyncFrequency | None = None

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
    translation_status: Literal["machine_draft", "in_review"] = "in_review"


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
