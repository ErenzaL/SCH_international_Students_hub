"""Weighted hybrid retrieval: code normalization (D2 = D-2), demotion of passages about other visa codes, the
multilingual glossary (ARC = residence card = 외국인등록증), broad keywords not dominating, duplicates and
per-document caps, and that the legacy SQL fusion stays selectable for benchmarking."""
from __future__ import annotations

from app.services.retrieval.query_analysis import analyze, code_variants, find_codes, lexical_scores, normalize_codes
from tests.test_retrieval import make_doc, search


def test_code_normalization_and_spellings():
    assert normalize_codes("D2 visa, d 2, D-2-2, F2R, E 7, CEFR B2 and A2") == \
        "D-2 visa, D-2, D-2-2, F-2-R, E-7, CEFR B2 and A2"
    assert find_codes("Apply for the D2 extension or a D-2-2 change") == {"D-2", "D-2-2"}
    assert code_variants("D-2") == ["D-2", "D2"] and "F2R" in code_variants("F-2-R")
    qa = analyze("What documents do I need to extend my D2 visa?")
    assert qa.codes == {"D-2"} and "stay_extension" in qa.concepts and qa.exact_terms[:2] == ["D-2", "D2"]


def test_rare_terms_outweigh_broad_ones():
    qa = analyze("D-2 visa extension")
    texts = {"broad": "Visa information. Visa types. Visa visa visa.",
             "specific": "Extension of stay for D-2 students: apply before your visa expires.",
             "other": "E-7 visa holders and F-2-R visa rules.", "x1": "visa", "x2": "visa guide"}
    s = lexical_scores(qa, texts)
    assert s["specific"][0] > 0.9 and s["broad"][0] < 0.2 and s["other"][0] < 0.2


def test_d2_spelling_finds_the_d2_document_and_other_visa_codes_are_demoted(env):
    make_doc(env, "D2 visa extension", "How to apply for extension of stay as a D2 student: passport, residence card, "
                                       "certificate of enrollment.")
    make_doc(env, "E-7 employment visa", "The E-7 visa is for professional employment. Extension of stay for E-7 "
                                         "workers requires an employment contract. Visa visa extension.")
    make_doc(env, "F-2-R regional visa", "F-2-R regional residence visa extension procedures for regional talent.")
    res = search(env, "What documents do I need to extend my D-2 visa?")
    titles = [r["document_title"] for r in res["results"]]
    assert titles[0] == "D2 visa extension", titles
    assert res["retrieval"]["codes"] == ["D-2"] and res["retrieval"]["fusion"] == "weighted"
    others = [r for r in res["results"] if r["document_title"] != "D2 visa extension"]
    assert all(r["code_mismatch"] for r in others)
    top = res["results"][0]
    assert top["exact_match"] and not top["code_mismatch"]


def test_glossary_links_arc_and_residence_card_across_languages(env):
    make_doc(env, "외국인등록증 재발급 안내", "외국인등록증을 분실한 경우 출입국·외국인관서에서 재발급을 신청합니다.", language="ko")
    make_doc(env, "Dormitory guide", "Dormitory rooms and meal plans for new students.", category="dormitory-housing")
    for q in ("I lost my ARC, what should I do?", "How do I replace a lost residence card?"):
        res = search(env, q)                       # weighted hybrid (default) expands the glossary
        assert res["results"] and res["results"][0]["document_title"] == "외국인등록증 재발급 안내", (q, res)
        assert "residence_card" in res["retrieval"]["concepts"]
    legacy = search(env, "I lost my ARC, what should I do?", mode="keyword")   # baseline: no glossary
    assert all(r["document_title"] != "외국인등록증 재발급 안내" for r in legacy["results"])


def test_a_single_broad_keyword_is_not_evidence_on_its_own(env):
    env.app.state.services.retrieval.settings.retrieval_min_similarity = 0.99   # hash vectors: semantic leg is noise
    make_doc(env, "Visa overview", "General visa overview for all foreigners; visa categories explained.")
    res = search(env, "kimchi recipe visa")
    assert res["results"] == []                 # 'visa' alone matched; 'kimchi' / 'recipe' did not
    res = search(env, "visa categories overview")
    assert [r["document_title"] for r in res["results"]] == ["Visa overview"]


def test_duplicates_and_per_document_cap(env):
    text = "\n\n".join(f"## Section {i}\nTOPIK registration step {i}: sign up on the TOPIK website and pay the "
                       f"exam fee before the deadline. " * 6 for i in range(8))
    make_doc(env, "TOPIK guide", text, category="topik-korean")
    make_doc(env, "TOPIK schedule", "TOPIK exam schedule and registration periods.", category="topik-korean")
    res = search(env, "TOPIK registration", top_k=6)
    per_doc: dict[str, int] = {}
    for r in res["results"]:
        per_doc[r["document_title"]] = per_doc.get(r["document_title"], 0) + 1
    assert per_doc.get("TOPIK guide", 0) <= 3 and "TOPIK schedule" in per_doc


def test_legacy_and_single_leg_modes_remain_selectable(env):
    make_doc(env, "Doc", "Insurance enrollment information for students.", category="health-insurance")
    for mode in ("hybrid_legacy", "vector", "keyword", "hybrid"):
        res = search(env, "insurance enrollment", mode=mode)
        assert res["retrieval"]["mode"] == mode and res["results"], mode
