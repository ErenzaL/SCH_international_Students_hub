"""Milestone 2.2: Gemini reliability (circuit breaker, error categories, probes, admin model check) and evidence
quality (quantity questions reach the passage with the figures; unrelated same-script documents no longer crowd out
the answer; glued mixed-script fragments are repaired without touching legitimate Korean terms)."""
from __future__ import annotations

import json
import logging
from types import SimpleNamespace as NS
from typing import Any

import pytest

from app.services.assistant.engine import _fix_script_mixing, _prioritize
from app.services.llm.base import LLMError
from app.services.llm.gemini import GeminiProvider
from tests.test_assistant import conv, say, use_llm
from tests.test_assistant_m2 import META, Bot, bot, setup_kb
from tests.test_gemini_provider import FakeModels, api_error, resp
from tests.test_retrieval import make_doc


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def provider(script: dict[str, list[Any]]) -> tuple[GeminiProvider, FakeModels, Clock]:
    fake = FakeModels(script)
    p = GeminiProvider("test-key", primary="primary-m", fallback="fallback-m", sleep=lambda _s: None,
                       client_factory=lambda: NS(models=fake))
    clock = Clock()
    p._clock = clock  # type: ignore[method-assign]
    return p, fake, clock


def called(fake: FakeModels) -> list[str]:
    return [m for _k, m, _c in fake.calls]


# ------------------------------------------------------------------------------ circuit breaker
def test_a_missing_primary_is_skipped_after_the_first_failure_then_retried_after_the_cooldown():
    p, fake, clock = provider({"primary-m": [api_error(404, "NOT_FOUND"), resp("primary back")],
                               "fallback-m": [resp("one"), resp("two")]})
    assert p.complete("s", "q", max_tokens=100).text == "one"
    assert p.complete("s", "q", max_tokens=100).text == "two"
    assert called(fake) == ["primary-m", "fallback-m", "fallback-m"]        # no second wasted primary call
    assert p.health()["primary-m"]["open"] is True and p.health()["primary-m"]["reason"] == "llm_model"
    clock.t += 901
    r = p.complete("s", "q", max_tokens=100)
    assert r.text == "primary back" and not r.fallback_used and p.health()["primary-m"]["open"] is False


def test_zero_quota_for_a_model_counts_as_exhausted_and_opens_the_circuit():
    zero = api_error(429, "RESOURCE_EXHAUSTED", "Quota exceeded for metric: generate_content_free_tier_requests, "
                                                "limit: 0, model: primary-m")
    p, fake, _ = provider({"primary-m": [zero], "fallback-m": [resp("ok"), resp("ok")]})
    p.complete("s", "q", max_tokens=100)
    p.complete("s", "q", max_tokens=100)
    assert called(fake) == ["primary-m", "fallback-m", "fallback-m"]
    assert p.health()["primary-m"]["reason"] == "llm_quota"


def test_repeated_temporary_errors_pause_a_model_briefly():
    down = api_error(503, "UNAVAILABLE")
    p, fake, clock = provider({"primary-m": [down] * 4, "fallback-m": [resp("a"), resp("b"), resp("c")]})
    p.complete("s", "q", max_tokens=100)      # primary 503 x2 -> fallback
    assert p.health()["primary-m"]["open"] is False
    p.complete("s", "q", max_tokens=100)      # 2 more -> 4 consecutive -> open for 60 s
    assert p.health()["primary-m"]["open"] is True and p.health()["primary-m"]["reason"] == "llm_unavailable"
    n = len(fake.calls)
    p.complete("s", "q", max_tokens=100)
    assert called(fake)[n:] == ["fallback-m"]
    clock.t += 61
    assert p._is_open("primary-m") is False


def test_when_every_model_is_paused_the_one_recovering_first_is_still_tried():
    p, fake, clock = provider({"primary-m": [api_error(404, "NOT_FOUND"), resp("primary")],
                               "fallback-m": [api_error(404, "NOT_FOUND")]})
    with pytest.raises(LLMError):
        p.complete("s", "q", max_tokens=100)
    assert p.health()["primary-m"]["open"] and p.health()["fallback-m"]["open"]
    assert p.complete("s", "q", max_tokens=100).text == "primary"   # half-open: never fail without trying


def test_error_details_are_logged_without_key_like_text(caplog):
    leak = api_error(400, "INVALID_ARGUMENT", "API key not valid. key=AIzaSyFAKEFAKEFAKEFAKEFAKE123 Bearer abc.def")
    p, _, _ = provider({"primary-m": [leak]})
    with caplog.at_level(logging.WARNING, logger="app.llm.usage"), pytest.raises(LLMError):
        p.complete("s", "q", max_tokens=100)
    logs = "\n".join(r.getMessage() for r in caplog.records)
    assert "http=400" in logs and "status=INVALID_ARGUMENT" in logs and "error=llm_auth" in logs
    assert "AIza" not in logs and "abc.def" not in logs and "[redacted]" in logs


def test_probe_tests_generate_and_stream_separately_without_retry_or_fallback():
    p, fake, _ = provider({"primary-m": [resp("OK", model="primary-m-001"), api_error(503, "UNAVAILABLE")]})
    rows = p.probe("primary-m")
    assert [r["call"] for r in rows] == ["generate", "stream"]
    assert rows[0]["ok"] and rows[0]["served_by"] == "primary-m-001" and rows[0]["total_tokens"] == 21
    assert rows[1]["ok"] is False and rows[1]["error"] == "llm_unavailable" and rows[1]["http"] == 503
    assert called(fake) == ["primary-m", "primary-m"]


def test_admin_model_check_endpoint(env):
    fake = FakeModels({"primary-m": [resp("OK"), [resp("OK")]],
                       "fallback-m": [api_error(404, "NOT_FOUND", "models/fallback-m is not found"), resp("x")]})
    p = GeminiProvider("test-key", primary="primary-m", fallback="fallback-m", client_factory=lambda: NS(models=fake))
    use_llm(env, p)
    r = env.client.post("/api/v1/admin/system/llm-check", headers=env.auth("admin"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["primary"], body["fallback"]) == ("primary-m", "fallback-m")
    rows = {(x["role"], x["call"]): x for x in body["probes"]}
    assert rows[("primary", "generate")]["ok"] and rows[("primary", "stream")]["ok"]
    assert rows[("fallback", "generate")]["error"] == "llm_model" and "not found" in rows[("fallback", "generate")]["detail"]
    assert "test-key" not in json.dumps(body)
    assert env.client.post("/api/v1/admin/system/llm-check", headers=env.auth("student")).status_code == 403


# -------------------------------------------------------------------------------------- evidence
HOURS_DOC = ("# Part-Time Employment\n\n## 1. Who can apply?\n\nInternational students may apply for permission "
             "before starting a part-time job.\n\n## 2. Types of work\n\nRestaurants, cafés and tutoring are common. "
             "Some industries are excluded.\n\n## 3. How many hours can I work?\n\nAsk the student for their program "
             "and year before answering.\n\n## 4. Working hours per week\n\nBachelor students may work up to 20 "
             "hours per week during the semester (10 hours without the language requirement).")


def test_vietnamese_quantity_question_gets_the_passage_with_the_figures(env):
    setup_kb(env)
    make_doc(env, "Part-Time Employment for International Students", HOURS_DOC, category="part-time-employment")
    b = bot(env, Bot("Sinh viên đại học được làm tối đa 20 giờ mỗi tuần trong học kỳ [1].",
                     rewrite={"standalone": "Du học sinh được làm thêm bao nhiêu giờ mỗi tuần?",
                              "en": "How many hours per week can international students work part-time?",
                              "ko": "유학생 시간제 취업 주당 근무 시간"}))
    msg = say(env, conv(env, language="vi"), "Du học sinh được làm thêm bao nhiêu giờ mỗi tuần?")
    prompt = b.answers()[-1][1]
    assert "up to 20 hours per week" in prompt                       # the section that answers reaches the model
    assert msg["content"] == "Sinh viên đại học được làm tối đa 20 giờ mỗi tuần trong học kỳ."
    assert msg["metadata"]["offer_handoff"] is False


def test_prioritize_prefers_agreeing_documents_and_figures_for_quantity_questions():
    hit = lambda doc, chunk, text, lex=0.0: dict(document_id=doc, chunk_id=chunk, passage=text,  # noqa: E731
                                                 best_lexical=lex)
    pool = [hit("korean-guide", "k1", "입학 안내 일반 사항", 0.1), hit("pt", "p1", "Ask about your program first.", 0.6),
            hit("pt", "p2", "Up to 20 hours per week.", 0.4)]
    order = [h["chunk_id"] for h in _prioritize(pool, quantity=True)]
    assert order == ["p2", "p1", "k1"]          # agreeing document first; its figure passage first; others last
    assert [h["chunk_id"] for h in _prioritize(pool, quantity=False)] == ["p1", "p2", "k1"]


def test_glued_korean_fragments_are_repaired_but_korean_terms_are_kept():
    vi = "phải xin giấy phép thời gian làm제취업 (시간제취업 허가) từ cơ quan xuất nhập cảnh"
    assert _fix_script_mixing(vi, "vi") == ("phải xin giấy phép thời gian làm (시간제취업 허가) từ cơ quan xuất nhập cảnh", 1)
    for text, lang in (("Báo cáo qua HiKorea (체류지 변경신고) trong 15 ngày", "vi"),
                       ("请申请宿舍（생활관）", "zh-CN"), ("Bring your 외국인등록증", "en"),
                       ("외국인등록증을 HiKorea에서 신청하세요", "ko")):
        assert _fix_script_mixing(text, lang) == (text, 0)
    assert _fix_script_mixing("请在门户网站申请생활관入住", "zh-CN")[0] == "请在门户网站申请入住"


def test_mixed_script_repair_is_applied_to_generated_answers(env):
    setup_kb(env)
    bot(env, Bot("Bạn cần xin giấy phép làm제취업 (시간제취업 허가) trước khi đi làm [1].",
                 rewrite={"standalone": "Làm thêm cần giấy phép gì?", "en": "part-time work permit",
                          "ko": "시간제 취업 허가"}))
    msg = say(env, conv(env, language="vi"), "Làm thêm cần giấy phép gì?")
    assert msg["content"] == "Bạn cần xin giấy phép làm (시간제취업 허가) trước khi đi làm."
    assert msg["metadata"]["fixed_mixed_script"] == 1


_ = META
