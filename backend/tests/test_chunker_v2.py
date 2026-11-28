"""Chunker v2: no text is dropped (RAG v2 audit: v1 lost 57.7 % of a PDF-extracted guidebook)."""
from __future__ import annotations

import re

import pytest

from app.core.config import Settings
from app.services.chunking import ChunkerConfig, chunk_text, chunker_version, parse_segments


def _indexed(text: str, version: str) -> str:
    return " ".join(f"{c.heading or ''} {c.content}" for c in chunk_text(text, ChunkerConfig(version=version)))


PDF_LIKE = "\n".join([
    "## 외국인 유학생 가이드북",
    "## (5) 시간제 취업허가의 특례(허가제외 대상)",
    "## •일시적 사례금, 상금 기타 일상 생활에 수반되는 보수를 받고 행하는 활동은 허가대상에서 제외",
    "## (6) 허가를 받지 않고 취업한 자의 위반자 처리기준",
    "•불법취업(불법고용)에 해당하므로 당사자 및 그 고용주를 처벌",
    "## (2) 신고기한: 변경일로부터 15일 이내",
])


def test_v1_loses_heading_lines_that_follow_each_other() -> None:
    # documents the release behaviour that v2 fixes
    assert "사례금" not in _indexed(PDF_LIKE, "v1")


@pytest.mark.parametrize("version", ["v2", "v2b"])
def test_no_line_of_text_is_lost(version: str) -> None:
    indexed = re.sub(r"\s+", " ", _indexed(PDF_LIKE, version))
    for line in PDF_LIKE.split("\n"):
        assert re.sub(r"\s+", " ", line.lstrip("# ").strip()) in indexed


def test_final_heading_without_body_is_kept() -> None:
    assert "15일 이내" in _indexed(PDF_LIKE, "v2")
    assert "15일 이내" not in _indexed(PDF_LIKE, "v1")


STRUCTURED = """# Part-Time Employment

Intro paragraph about the rules.

## Who can apply?

Students holding D-2 or D-4 status after six months.

## Documents

- Passport
- Residence card

[Page 2]

## Hours

Up to 25 hours on weekdays.
"""


@pytest.mark.parametrize("version", ["v2", "v2b"])
def test_structured_markdown_chunks_exactly_as_v1(version: str) -> None:
    v1 = chunk_text(STRUCTURED, ChunkerConfig(version="v1"))
    other = chunk_text(STRUCTURED, ChunkerConfig(version=version))
    assert [(c.heading, c.content, c.page_start) for c in v1] == [(c.heading, c.content, c.page_start) for c in other]


def test_heading_directly_followed_by_heading_becomes_text_of_the_outer_section() -> None:
    segs = parse_segments("# Title\n## Section\nBody text.", "v2")
    assert [(s.heading, s.text) for s in segs] == [(None, "Title"), ("Section", "Body text.")]


def test_v2b_reads_pdf_line_marks_as_text_but_v2_keeps_them_as_sections() -> None:
    v2b = parse_segments(PDF_LIKE, "v2b")
    assert {s.heading for s in v2b} == {None}           # one section: the marks were PDF line starts
    assert any("사례금" in s.text for s in v2b)
    assert len({s.heading for s in parse_segments(PDF_LIKE, "v2")}) > 1


def test_v2b_keeps_real_structure() -> None:
    assert parse_segments(STRUCTURED, "v2b") == parse_segments(STRUCTURED, "v1")


def test_unknown_version_is_rejected() -> None:
    with pytest.raises(ValueError):
        chunker_version(ChunkerConfig(version="v9"))


def test_setting_selects_the_version_stored_with_the_chunks() -> None:
    from app.repositories.base import Query
    from app.repositories.memory_store import MemoryStore
    from app.services.embeddings.hash_provider import HashEmbeddingProvider
    from app.services.indexing import IndexingService

    store = MemoryStore()
    settings = Settings(_env_file=None, chunker_version="v2", environment="test", supabase_jwt_secret="x" * 32)
    doc = store.insert("source_documents", dict(title="Guide", source_id=None))
    version = store.insert("document_versions", dict(document_id=doc["id"], version_number=1, extracted_text=PDF_LIKE,
                                                     verification_status="approved"))
    IndexingService(store, HashEmbeddingProvider(), settings).index_version(version["id"])
    rows, _ = store.select("document_chunks", Query(eq={"version_id": version["id"]}))
    assert rows and {r["chunk_strategy"] for r in rows} == {"v2"}
    assert any("사례금" in r["content"] for r in rows)
