"""Evidence-sufficiency layer: requirement detection, passage checks, adjacent/second-search completion, conflicts."""
from __future__ import annotations

import pytest

from app.repositories.base import Query
from app.services.assistant.evidence import EvidenceChecker, EvidenceConfig, has_signal, required_information
from tests.test_document_lifecycle_indexing import activate, new_version, published_doc, svc


@pytest.mark.parametrize("q,need", [
    ("How much is the application fee?", "quantity"), ("신청 수수료는 얼마예요?", "quantity"),
    ("Berapa biaya pendaftaran?", "quantity"), ("Phí đăng ký là bao nhiêu?", "quantity"), ("申请费是多少？", "quantity"),
    ("When is the deadline to report?", "date"), ("신고 기한이 언제예요?", "date"), ("Kapan batas waktu lapor?", "date"),
    ("What documents do I need?", "requirement"), ("필요한 서류가 뭐예요?", "requirement"), ("需要什么材料？", "requirement"),
    ("Can I work part-time?", "eligibility"), ("아르바이트 가능해요?", "eligibility"), ("Tôi có được làm thêm không?", "eligibility"),
    ("How do I apply for a residence card?", "procedure"), ("외국인등록 신청 방법", "procedure"), ("如何办理外国人登录？", "procedure"),
])
def test_required_information_is_detected_in_five_languages(q, need):
    assert need in required_information(q)


def test_small_talk_and_open_questions_need_nothing_specific():
    assert required_information("Tell me about Korean culture") == []


def test_signals_are_generic_shapes_not_policy_values():
    assert has_signal("quantity", "The fee is 30,000 won.") and has_signal("quantity", "주당 20시간까지")
    assert not has_signal("quantity", "There is a fee for this service.")
    assert has_signal("date", "Report within 15 days of moving.") and has_signal("date", "2026. 12. 10.까지 신청")
    assert has_signal("requirement", "Bring your passport and a photo.")
    assert has_signal("eligibility", "Only students with TOPIK level 3 or higher.")
    assert has_signal("procedure", "Visit the immigration office and submit the form.")


def _chunk_sources(env, vid, index, similarity=-1.0):
    c = env.store.select("document_chunks", Query(eq={"version_id": vid, "chunk_index": index}))[0][0]
    v = env.store.select("document_versions", Query(eq={"id": vid}))[0][0]
    return [dict(document_id=v["document_id"], passages=[dict(
        chunk_id=c["id"], version_id=vid, document_id=v["document_id"], heading=c.get("heading"),
        passage=c["content"], page=c.get("page_start"), document_title="Guide", source_url="https://example.test/g",
        similarity=similarity)])]


def _guide(env):
    doc_id, _ = published_doc(env)
    filler = " ".join(f"Students apply for the certificate at the office, sentence {i}." for i in range(70))
    text = (f"## Application\n{filler}\n\n## Fee\nThe application fee is 30,000 won and is paid at the counter.\n\n"
            f"## Other\n{filler}")
    v = new_version(env, doc_id, text)
    activate(env, v)
    return v["id"]


def test_adjacent_chunk_completes_a_missing_figure_and_keeps_citations(env):
    vid = _guide(env)
    sources = _chunk_sources(env, vid, 2)
    checker = EvidenceChecker(env.store, svc(env).retrieval, EvidenceConfig(second_search=False))
    assert checker.check("How much is the application fee?", sources)["missing"] == ["quantity"]
    out, rep = checker.complete("How much is the application fee?", sources)
    assert rep["status"] == "sufficient" and rep["initially_missing"] == ["quantity"] and rep["still_missing"] == []
    added = [p for p in out[0]["passages"] if p.get("evidence_added") == "adjacent"]
    assert added and "30,000 won" in added[0]["passage"]
    assert added[0]["document_id"] == out[0]["document_id"] and added[0]["version_id"] == vid   # same citation
    assert rep["added_chunks"][0]["chunk_id"] == added[0]["chunk_id"]
    assert sources[0]["passages"][0].get("evidence_added") is None        # input not mutated


def test_still_missing_information_is_recorded_not_invented(env):
    vid = _guide(env)
    sources = _chunk_sources(env, vid, 2)
    out, rep = EvidenceChecker(env.store, svc(env).retrieval, EvidenceConfig(adjacent=False, second_search=False)
                               ).complete("When is the deadline?", sources)
    assert rep["status"] == "insufficient" and rep["still_missing"] == ["date"] and out == sources


def test_second_search_is_bounded(env):
    vid = _guide(env)
    sources = _chunk_sources(env, vid, 2)
    cfg = EvidenceConfig(adjacent=False, second_search=True, max_added_passages=1)
    out, rep = EvidenceChecker(env.store, svc(env).retrieval, cfg).complete("How much is the application fee?", sources)
    assert len(rep["added_chunks"]) <= 1 and rep["actions"][-1]["action"] == "second_search"
    assert rep["status"] == "sufficient" and "30,000" in " ".join(p["passage"] for s in out for p in s["passages"])


def test_conflicting_figures_across_documents_are_reported():
    src = [dict(document_id="a", passages=[dict(passage="Students may work 20 hours per week.")]),
           dict(document_id="b", passages=[dict(passage="Students may work 30 hours per week.")]),
           dict(document_id="c", passages=[dict(passage="The table lists 20 hours and 25 hours.")])]
    c = EvidenceChecker.conflicts(src)
    assert len(c) == 1 and c[0]["unit"] == "hours" and c[0]["documents"] == ["a", "b", "c"]   # a/b and b/c disjoint
    assert EvidenceChecker.conflicts(src[:1] + src[2:]) == []        # overlapping values: no conflict


def test_engine_reports_evidence_check_only_when_enabled(env):
    vid = _guide(env)
    engine = svc(env).conversations.engine
    off = engine.respond("How much is the application fee?", language="en")
    assert "evidence_check" not in off["retrieval"]
    engine.settings.assistant_evidence_check = True
    try:
        on = engine.respond("How much is the application fee?", language="en")
    finally:
        engine.settings.assistant_evidence_check = False
    rep = on["retrieval"]["evidence_check"]
    assert rep["needs"] == ["quantity"] and rep["status"] in ("sufficient", "insufficient")
    assert [c["document_id"] for c in on["citations"]][:1] == [c["document_id"] for c in off["citations"]][:1]
    assert vid


def test_quantity_must_match_the_asked_unit_and_lists_need_two_markers():
    from app.services.assistant.evidence import quantity_kind

    assert quantity_kind("How much is the application fee?") == "money" and quantity_kind("주당 몇 시간 일할 수 있나요?") == "hours"
    assert not has_signal("quantity", "Students may work 20 hours per week.", "money")
    assert has_signal("quantity", "Students may work 20 hours per week.", "hours")
    assert not has_signal("requirement", "Bring your passport.") and not has_signal("procedure", "Apply early.")


def test_check_is_anchored_to_the_top_source():
    src = [dict(document_id="a", passages=[dict(passage="General overview of student life in Korea.")]),
           dict(document_id="b", passages=[dict(passage="The fee is 30,000 won.")])]
    assert EvidenceChecker.check("How much is the fee?", src, check_sources=1)["missing"] == ["quantity"]
    assert EvidenceChecker.check("How much is the fee?", src)["missing"] == []      # whole context: too lenient


def test_off_topic_additions_are_rejected_by_the_relevance_gate(env):
    vid = _guide(env)
    sources = _chunk_sources(env, vid, 2, similarity=1.01)     # nothing can be as similar as the top passage
    out, rep = EvidenceChecker(env.store, svc(env).retrieval).complete("How much is the application fee?", sources)
    assert rep["status"] == "insufficient" and rep["still_missing"] == ["quantity"] and rep["added_chunks"] == []
    assert rep["rejected_off_topic"] >= 1 and out == sources
