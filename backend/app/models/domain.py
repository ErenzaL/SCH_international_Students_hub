"""Internal domain objects shared by extractors, chunker and the ingestion pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Segment:
    """A contiguous piece of extracted text with its structural context."""

    text: str
    heading: str | None = None
    page: int | None = None


@dataclass
class ExtractedDocument:
    title: str
    text: str  # normalized, markdown-ish text that is stored as extracted_text
    language: str | None = None
    source_published_at: datetime | None = None
    links: list[dict[str, str]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Chunk:
    index: int
    heading: str | None
    content: str
    token_count: int
    page_start: int | None = None
    page_end: int | None = None

    def embedding_input(self, doc_title: str) -> str:
        """Text that gets embedded (adds title + heading context; content_hash is over this)."""
        head = " - ".join(p for p in (doc_title, self.heading) if p)
        return f"{head}\n{self.content}" if head else self.content


@dataclass
class FetchResult:
    url: str  # final URL after validated redirects
    requested_url: str
    status_code: int
    content_type: str
    content: bytes
    encoding: str | None
    redirects: list[str] = field(default_factory=list)
