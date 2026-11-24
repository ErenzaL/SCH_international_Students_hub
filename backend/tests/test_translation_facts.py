"""Exact renderings for the local model and the checks of its drafts (cases from real drafts of the benchmark)."""
from __future__ import annotations

import threading

import pytest

from app.gpu_worker.generate import CheckedModel
from app.gpu_worker.glossary import TERMS, terms_in
from app.services.llm.base import LLMError, ScriptedLLMProvider
from app.services.translation.facts import ko_dates, ko_money, renderings, wrong_weekdays
from app.services.translation.quality import local_translation_warnings, validate_translation

SRC = "퇴사 안내\n\n- 1차 : 2026. 12. 11.(금) ~ 12. 12.(토) 9:30~17:00\n- 비용 : 10,000원\n- 범칙금 : 약 300만원\n- 문의 : 041-530-1234, 평점 2.5 이상"


def test_dates_and_amounts_are_found_and_nothing_else_is():
    assert [(d["year"], d["month"], d["day"], d["weekday"]) for d in ko_dates(SRC)] == [(2026, 12, 11, 4), (None, 12, 12, 5)]
    assert [v for _s, v in ko_money(SRC)] == [10_000, 3_000_000]
    assert [(d["month"], d["day"]) for d in ko_dates("11/27, 8월 14일(금), 11.09.(월), 2026-12-01, 13.45, 01:00, https://a.kr/12/11")] \
        == [(11, 27), (8, 14), (11, 9), (12, 1)]


@pytest.mark.parametrize("lang,date,money", [
    ("en", "December 11, 2026 (Friday)", "3,000,000 won"), ("id", "11 Desember 2026 (Jumat)", "3.000.000 won"),
    ("vi", "11/12/2026 (Thứ Sáu)", "3.000.000 won"), ("zh-CN", "2026年12月11日（周五）", "3,000,000韩元")])
def test_renderings(lang, date, money):
    r = dict(renderings(SRC, lang))
    assert r["2026. 12. 11.(금)"] == date and r["300만원"] == money


@pytest.mark.parametrize("draft,lang,wrong", [
    ("9/9/2026 (Sáu), 10:00", "vi", 1), ("9/9/2026 (Thứ Tư)", "vi", 0), ("ngày 9 tháng 9 năm 2026 (thứ 4)", "vi", 0),
    ("September 9, 2026 (Thursday)", "en", 1), ("Wednesday, September 9 (Wed)", "en", 0), ("9 September 2026 (Rabu)", "id", 0),
    ("9 September 2026 (Kamis)", "id", 1), ("2026年9月9日（周三）", "zh-CN", 0), ("2026年9月9日（星期五）", "zh-CN", 1), ("9/9/2026", "vi", 0)])
def test_wrong_weekdays(draft, lang, wrong):
    assert len(wrong_weekdays("기간 : 2026. 9. 9.(수) 10:00", draft, lang)) == wrong


def test_the_same_fact_in_another_form_is_not_flagged_but_a_lost_one_is():
    good = ("Move-out\n\n- 1st: December 11, 2026 (Friday) - December 12 (Saturday) 9:30-17:00\n- Cost: 10,000 won\n- Fine: about 3 million won\n"
            "- Contact: 041-530-1234, GPA of 2.5 or higher")
    assert validate_translation(SRC, good, "ko", "en") != []            # the shared checks flag "12" and "300"
    assert local_translation_warnings(SRC, good, "ko", "en") == []
    for lost, expected in (("about 3 million won", "300만원"), ("December 12 (Saturday)", "12. 12.(토)")):
        assert any(expected in w["value"] for w in local_translation_warnings(SRC, good.replace(lost, "soon"), "ko", "en"))
    assert any("not Sunday" in w["value"] for w in local_translation_warnings(SRC, good.replace("(Saturday)", "(Sunday)"), "ko", "en"))


@pytest.mark.parametrize("add,kind", [
    ("\nAll numbers are to be copied exactly as written.", "placeholder"), ("\n<sourcetext>", "placeholder"), ("\n更多信息请参阅附件", "language"),
    ("\nDeadline 23:59", "number_added"), ("\nhttps://evil.example", "url_added")])
def test_additions_are_flagged(add, kind):
    good = "Guide\n\nApply by December 1, 2026 (Tuesday) at https://example.ac.kr/apply for more details about the program."
    src = "안내\n\n2026. 12. 1.(화)까지 https://example.ac.kr/apply에서 신청하세요."
    assert local_translation_warnings(src, good, "ko", "en") == []
    assert kind in {w["type"] for w in local_translation_warnings(src, good + add, "ko", "en")}


def test_a_url_followed_by_chinese_text_is_not_a_new_url():
    src = "신청서는 https://example.ac.kr/apply에서 제출하세요."
    assert local_translation_warnings(src, "请在https://example.ac.kr/apply提交申请表。", "ko", "zh-CN") == []


def test_dropped_list_items_are_flagged():
    src = "안내\n" + "\n".join(f"- 항목 {x}" for x in "가나다라마바")
    out = "Notice\n- item a\n- item b\n- item c"
    assert "missing_sections" in {w["type"] for w in local_translation_warnings(src, out, "ko", "en")}


def test_other_providers_keep_their_checks():
    src, out = "기간 2026-12-01", "Period December 1, 2026"
    assert [w["value"] for w in validate_translation(src, out, "ko", "en")] == ["12", "01"]


# ------------------------------------------------------------------------------- generation
def model(*answers, target="en", source="ko"):  # type: ignore[no-untyped-def]
    it = iter(answers)
    llm = ScriptedLLMProvider(lambda s, p: next(it))
    llm.max_source_chars = 12000  # type: ignore[attr-defined]
    return CheckedModel(llm, source, target, threading.Event(), repair=True), llm


def ask(m, text):  # type: ignore[no-untyped-def]
    return m.complete("Copy codes (for example D-2, D-4-1, F-2-7) exactly.", f"Translate from Korean into English.\n\n<source_text>\n{text}\n</source_text>")


def test_prompt_has_exact_forms_and_terms_but_no_examples_to_repeat():
    m, llm = model("December 11, 2026 (Friday): dormitory move-out")
    ask(m, "<공지>\n2026. 12. 11.(금) 생활관 퇴사")
    system, prompt = llm.calls[0]
    assert "D-4-1" not in system and "[공지]" in prompt and "<공지>" not in prompt
    assert "- 2026. 12. 11.(금) → December 11, 2026 (Friday)" in prompt and "- 생활관 → dormitory" in prompt
    assert len(llm.calls) == 1


def test_the_best_of_at_most_three_versions_is_kept():
    m, llm = model("soon", "December 11, 2026 (Sunday)", "December 11, 2026 (Friday)")
    assert ask(m, "2026. 12. 11.(금)까지").text == "December 11, 2026 (Friday)" and m.repairs == 2
    assert "Friday, not Sunday" in llm.calls[2][1]
    m, llm = model("soon", "later")
    assert ask(m, "2026. 12. 11.(금)까지").text == "soon" and len(llm.calls) == 2      # no improvement: stop


def test_a_draft_in_the_wrong_language_is_refused():
    zh = "公告：请各位同学注意，宿舍将于下周关闭。"
    m, _ = model(zh, zh, zh)
    with pytest.raises(LLMError) as e:
        ask(m, "생활관이 다음 주에 닫힙니다. 모든 학생은 확인하세요.")
    assert e.value.code == "llm_malformed" and e.value.transient
    m, _ = model("이것은 번역되지 않은 한국어 제목입니다", "이것은 번역되지 않은 한국어 제목입니다")
    with pytest.raises(LLMError):
        ask(m, "이것은 번역되지 않은 한국어 제목입니다")


def test_glossary_has_every_language_once_and_only_terms_of_the_text_are_used():
    assert len({t[0] for t in TERMS}) == len(TERMS) and all(len(t) == 5 and all(t) for t in TERMS)
    assert dict(terms_in("생활관 벌점 안내", "vi")) == {"생활관": "ký túc xá", "벌점": "điểm phạt"}
    assert terms_in("생활관", "ko") == []
