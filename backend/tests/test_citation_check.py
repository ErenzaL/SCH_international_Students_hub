"""Per-citation support check (assistant/citation_check.py)."""
from __future__ import annotations

from app.services.assistant.citation_check import check_citations


def src(text: str) -> dict:  # type: ignore[type-arg]
    return {"document_id": text[:5], "passages": [{"passage": text, "document_title": "", "heading": ""}]}


S = [src("The residence card fee is KRW 35,000."), src("Report a new address within 15 days.")]


def test_supported_sentence_is_unchanged() -> None:
    text, rep = check_citations("The card costs KRW 35,000 [1].", S)
    assert text == "The card costs KRW 35,000 [1]." and rep["supported"] == 1 and rep["reattributed"] == 0


def test_figure_cited_to_the_wrong_source_is_reattributed() -> None:
    text, rep = check_citations("You must report within 15 days [1].", S)
    assert text == "You must report within 15 days [2]."
    assert rep["reattributed"] == 1 and rep["details"][0]["to"] == 2


def test_figures_from_two_sources_in_one_sentence_are_reported_not_changed() -> None:
    text, rep = check_citations("Pay KRW 35,000 and report within 15 days [1].", S)
    assert text == "Pay KRW 35,000 and report within 15 days [1]." and rep["ambiguous"] == 1


def test_sentences_without_figures_are_not_checked() -> None:
    _t, rep = check_citations("Apply at the immigration office [2].", S)
    assert rep["checked"] == 0


def test_uncited_figure_is_reported_when_the_answer_cites_elsewhere() -> None:
    _t, rep = check_citations("Report the move [2]. It costs 35,000 won.", S)
    assert rep["uncited"] == 1


def test_list_items_and_korean_dates() -> None:
    k = [src("신청 기간: 2026. 12. 1. ~ 12. 11."), src("생활관비 1일 10,000원")]
    text, rep = check_citations("- 생활관비는 하루 10,000원입니다 [1].\n- 신청은 12월 11일까지 [1].", k)
    assert "10,000원입니다 [2]." in text and rep["reattributed"] == 1 and rep["supported"] == 1
