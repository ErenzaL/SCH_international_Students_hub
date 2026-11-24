"""Gemini provider: primary/fallback policy, bounded retries, server retry delays, streaming without duplicates,
error classification, safe usage logging. Uses a fake client shaped like google-genai responses (no network)."""
from __future__ import annotations

import logging
from types import SimpleNamespace as NS
from typing import Any

import pytest
from google.genai import errors

from app.services.llm.base import LLMError, build_llm_provider
from app.services.llm.gemini import GeminiProvider
from app.services.llm.usage import usage
from tests.conftest import make_settings


def resp(text: str = "", *, finish: str = "STOP", thought: str | None = None, model: str | None = None,
         block: str | None = None, tokens: tuple[int, int, int] = (11, 7, 3)) -> NS:
    parts = ([NS(text=thought, thought=True)] if thought else []) + ([NS(text=text, thought=None)] if text else [])
    return NS(candidates=[NS(content=NS(parts=parts), finish_reason=NS(name=finish))],
              prompt_feedback=NS(block_reason=NS(name=block)) if block else None, model_version=model,
              usage_metadata=NS(prompt_token_count=tokens[0], candidates_token_count=tokens[1],
                                thoughts_token_count=tokens[2], total_token_count=sum(tokens)))


def api_error(code: int, status: str, message: str = "x", retry: str | None = None, quota: str | None = None):
    details: list[dict[str, Any]] = []
    if retry:
        details.append({"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": retry})
    if quota:
        details.append({"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [{"quotaId": quota}]})
    body = {"error": {"code": code, "status": status, "message": message, "details": details}}
    return (errors.ServerError if code >= 500 else errors.ClientError)(code, body)


class FakeModels:
    """Scripted per-model outcomes: each entry is a response, an exception, or (for streams) a list of chunks."""

    def __init__(self, script: dict[str, list[Any]]):
        self.script = {k: list(v) for k, v in script.items()}
        self.calls: list[tuple[str, str, Any]] = []

    def _next(self, model: str) -> Any:
        if not self.script.get(model):
            raise AssertionError(f"unexpected call to {model}")
        return self.script[model].pop(0)

    def generate_content(self, *, model: str, contents: str, config: Any) -> Any:
        self.calls.append(("generate", model, config))
        out = self._next(model)
        if isinstance(out, Exception):
            raise out
        return out

    def generate_content_stream(self, *, model: str, contents: str, config: Any):  # type: ignore[no-untyped-def]
        self.calls.append(("stream", model, config))
        out = self._next(model)
        if isinstance(out, Exception):
            raise out
        for chunk in out:
            if isinstance(chunk, Exception):
                raise chunk
            yield chunk


def provider(script: dict[str, list[Any]], **kw: Any) -> tuple[GeminiProvider, FakeModels, list[float]]:
    fake = FakeModels(script)
    sleeps: list[float] = []
    p = GeminiProvider("test-key-not-real", primary="primary-m", fallback="fallback-m",
                       client_factory=lambda: NS(models=fake), sleep=sleeps.append, **kw)
    return p, fake, sleeps


def models_called(fake: FakeModels) -> list[str]:
    return [m for _k, m, _c in fake.calls]


# ------------------------------------------------------------------------ success + config
def test_primary_success_reports_tokens_and_skips_thought_parts():
    p, fake, sleeps = provider({"primary-m": [resp("Hello [1]", thought="secret reasoning", model="gemini-x-001")]})
    r = p.complete("sys", "prompt", max_tokens=600)
    assert r.text == "Hello [1]" and "secret" not in r.text
    assert (r.provider, r.model, r.model_role, r.fallback_used, r.attempts) == ("gemini", "gemini-x-001", "primary", False, 1)
    assert (r.input_tokens, r.output_tokens, r.thinking_tokens, r.total_tokens) == (11, 7, 3, 21)
    assert sleeps == [] and models_called(fake) == ["primary-m"]


def test_generation_config_is_bounded_and_uses_thinking_level():
    p, fake, _ = provider({"primary-m": [resp("ok"), resp("ok")]}, request_timeout=25, job_timeout=150,
                          thinking_level="low", temperature=None)
    p.complete("system text", "q", max_tokens=2048)
    cfg = fake.calls[0][2]
    assert cfg.system_instruction == "system text" and cfg.thinking_config.thinking_level.value.lower() == "low"
    assert 2048 < cfg.max_output_tokens <= 2048 + 1024 and cfg.temperature is None
    assert cfg.http_options.timeout == 25_000                     # interactive call: short timeout
    p.complete("s", "q", max_tokens=16000)                         # translation job: long timeout
    assert fake.calls[1][2].http_options.timeout == 150_000
    p2, fake2, _ = provider({"primary-m": [resp("ok")]}, temperature=0.4)
    p2.complete("s", "q", max_tokens=100)
    assert fake2.calls[0][2].temperature == 0.4


# ------------------------------------------------------------------------ retries + fallback
def test_transient_error_is_retried_with_jittered_backoff_on_the_same_model():
    p, fake, sleeps = provider({"primary-m": [api_error(503, "UNAVAILABLE"), resp("ok")]}, retry_base=0.8)
    r = p.complete("s", "q", max_tokens=100)
    assert r.text == "ok" and r.attempts == 2 and models_called(fake) == ["primary-m", "primary-m"]
    assert len(sleeps) == 1 and 0.4 <= sleeps[0] <= 0.8


def test_server_retry_delay_is_respected_when_short():
    p, _, sleeps = provider({"primary-m": [api_error(429, "RESOURCE_EXHAUSTED", retry="2s"), resp("ok")]},
                            retry_max_delay=8)
    assert p.complete("s", "q", max_tokens=100).text == "ok"
    assert 2.0 <= sleeps[0] <= 2.3


def test_long_server_delay_fails_over_instead_of_waiting():
    p, fake, sleeps = provider({"primary-m": [api_error(429, "RESOURCE_EXHAUSTED", retry="45s")],
                                "fallback-m": [resp("from fallback")]}, retry_max_delay=8)
    r = p.complete("s", "q", max_tokens=100)
    assert r.text == "from fallback" and r.fallback_used and r.model_role == "fallback"
    assert sleeps == [] and models_called(fake) == ["primary-m", "fallback-m"]


def test_daily_quota_skips_retry_and_a_shared_quota_on_the_fallback_is_final():
    quota = api_error(429, "RESOURCE_EXHAUSTED", "Quota exceeded", quota="GenerateRequestsPerDayPerProjectPerModel")
    p, fake, sleeps = provider({"primary-m": [quota], "fallback-m": [quota, resp("never")]})
    with pytest.raises(LLMError) as ei:
        p.complete("s", "q", max_tokens=100)
    assert ei.value.code == "llm_quota" and sleeps == []
    assert models_called(fake) == ["primary-m", "fallback-m"]          # one try each, no loop


def test_attempts_are_bounded_when_everything_fails():
    down = api_error(503, "UNAVAILABLE")
    p, fake, sleeps = provider({"primary-m": [down, down], "fallback-m": [down, down]}, max_attempts=2)
    with pytest.raises(LLMError) as ei:
        p.complete("s", "q", max_tokens=100)
    assert ei.value.code == "llm_unavailable" and ei.value.transient
    assert models_called(fake) == ["primary-m", "primary-m", "fallback-m", "fallback-m"] and len(sleeps) == 2


@pytest.mark.parametrize("err,code", [
    (api_error(401, "UNAUTHENTICATED"), "llm_auth"),
    (api_error(403, "PERMISSION_DENIED"), "llm_permission"),
    (api_error(400, "INVALID_ARGUMENT", "API key not valid. Please pass a valid API key."), "llm_auth"),
    (api_error(400, "INVALID_ARGUMENT", "Invalid JSON payload"), "llm_bad_request"),
    (api_error(400, "FAILED_PRECONDITION", "User location is not supported"), "llm_precondition"),
])
def test_auth_and_invalid_requests_never_retry_or_fall_back(err, code):
    p, fake, sleeps = provider({"primary-m": [err], "fallback-m": [resp("must not be used")]})
    with pytest.raises(LLMError) as ei:
        p.complete("s", "q", max_tokens=100)
    assert ei.value.code == code and models_called(fake) == ["primary-m"] and sleeps == []


def test_unknown_model_falls_back_without_retrying():
    p, fake, _ = provider({"primary-m": [api_error(404, "NOT_FOUND")], "fallback-m": [resp("ok")]})
    r = p.complete("s", "q", max_tokens=100)
    assert r.fallback_used and models_called(fake) == ["primary-m", "fallback-m"]


def test_blocked_and_truncated_outputs_are_final():
    p, fake, _ = provider({"primary-m": [resp("", block="SAFETY")], "fallback-m": [resp("x")]})
    with pytest.raises(LLMError) as ei:
        p.complete("s", "q", max_tokens=100)
    assert ei.value.code == "llm_refused" and models_called(fake) == ["primary-m"]
    p, fake, _ = provider({"primary-m": [resp("cut", finish="MAX_TOKENS")], "fallback-m": [resp("x")]})
    with pytest.raises(LLMError) as ei:
        p.complete("s", "q", max_tokens=100)
    assert ei.value.code == "llm_truncated" and models_called(fake) == ["primary-m"]


def test_empty_or_malformed_responses_are_retried_then_fail_over():
    p, fake, _ = provider({"primary-m": [resp(""), resp("", finish="MALFORMED_RESPONSE")], "fallback-m": [resp("ok")]})
    assert p.complete("s", "q", max_tokens=100).text == "ok"
    assert models_called(fake) == ["primary-m", "primary-m", "fallback-m"]


def test_network_timeouts_are_retryable():
    import httpx

    p, fake, _ = provider({"primary-m": [httpx.ReadTimeout("slow"), resp("ok")]})
    assert p.complete("s", "q", max_tokens=100).text == "ok" and len(fake.calls) == 2


# ----------------------------------------------------------------------------- streaming
def test_stream_delivers_chunks_in_order():
    p, _, _ = provider({"primary-m": [[resp("Hel", finish="FINISH_REASON_UNSPECIFIED"), resp("lo [1]")]]})
    got: list[str] = []
    r = p.stream("s", "q", got.append, max_tokens=2048)
    assert "".join(got) == "Hello [1]" == r.text


def test_stream_failure_before_any_text_fails_over_without_duplicates():
    p, fake, _ = provider({"primary-m": [api_error(503, "UNAVAILABLE"), api_error(503, "UNAVAILABLE")],
                           "fallback-m": [[resp("Fallback "), resp("answer")]]})
    got: list[str] = []
    r = p.stream("s", "q", got.append, max_tokens=2048)
    assert "".join(got) == "Fallback answer" and r.fallback_used


def test_stream_failure_after_text_is_partial_and_never_retried():
    p, fake, _ = provider({"primary-m": [[resp("Partial ans", finish="FINISH_REASON_UNSPECIFIED"),
                                          api_error(503, "UNAVAILABLE")]],
                           "fallback-m": [[resp("second answer")]]})
    got: list[str] = []
    with pytest.raises(LLMError) as ei:
        p.stream("s", "q", got.append, max_tokens=2048)
    assert ei.value.partial and "".join(got) == "Partial ans" and models_called(fake) == ["primary-m"]


# --------------------------------------------------------------------------- logging + build
def test_usage_log_has_metadata_but_no_prompt_or_answer_text(caplog):
    usage.reset()
    p, _, _ = provider({"primary-m": [api_error(503, "UNAVAILABLE"), resp("ANSWER-TEXT-42")]})
    with caplog.at_level(logging.INFO, logger="app.llm.usage"):
        p.complete("SYSTEM-SECRET", "STUDENT-QUESTION-7", max_tokens=100)
    logs = "\n".join(r.getMessage() for r in caplog.records)
    assert "llm_attempt" in logs and "error=llm_unavailable" in logs and "outcome=ok" in logs
    for secret in ("SYSTEM-SECRET", "STUDENT-QUESTION-7", "ANSWER-TEXT-42", "test-key-not-real"):
        assert secret not in logs
    snap = usage.snapshot()
    assert snap["requests"] == 1 and snap["errors"] == {"llm_unavailable": 1} and snap["tokens"]["primary-m"]["total"] == 21


def test_build_gemini_provider_from_settings():
    s = make_settings(llm_provider="gemini", gemini_primary_model="gemini-3.6-flash",
                      gemini_fallback_model="gemini-3.5-flash-lite", llm_max_attempts_per_model=3)
    p = build_llm_provider(s.llm_provider, s.llm_api_key, s.llm_model, s.llm_effort, s.llm_timeout_seconds, settings=s)
    assert isinstance(p, GeminiProvider) and p.enabled and p.name == "gemini"
    assert (p.primary, p.fallback, p.max_attempts) == ("gemini-3.6-flash", "gemini-3.5-flash-lite", 3)
    same = GeminiProvider("k", primary="m", fallback="m")
    assert same.fallback == ""                                      # never "fall back" to the same model
    assert "test-key" not in repr(p.__dict__.get("_client"))


# ------------------------------------------------------------------------ background budget (chatbot reserve)
def test_background_gate_is_charged_for_every_attempt_and_stops_before_the_request():
    budget = {"left": 2}

    def gate() -> bool:
        if budget["left"] <= 0:
            return False
        budget["left"] -= 1
        return True

    down = api_error(503, "UNAVAILABLE")
    p, fake, _ = provider({"primary-m": [down, down], "fallback-m": [resp("never")]}, max_attempts=2,
                          attempt_gate=gate)
    with pytest.raises(LLMError) as ei:
        p.complete("s", "q", max_tokens=16000)
    # two attempts were charged (a retry counts); the third (the fallback) was refused before any request was sent
    assert ei.value.code == "llm_background_budget"
    assert models_called(fake) == ["primary-m", "primary-m"] and budget["left"] == 0
    with pytest.raises(LLMError):
        p.complete("s", "q", max_tokens=16000)
    assert models_called(fake) == ["primary-m", "primary-m"]          # nothing more reached the API


def test_background_provider_is_separate_from_the_chat_provider():
    from app.core.config import Settings
    from app.core.rate_limit import DailyBudget
    from app.services.llm.base import build_llm_from_settings
    from app.services.translation.auto import translation_llm

    s = Settings(_env_file=None, llm_provider="gemini", llm_api_key="test-key-not-real",
                 gemini_primary_model="chat-primary", gemini_fallback_model="chat-fallback",
                 llm_background_daily_attempts=3)
    chat = build_llm_from_settings(s)
    bg = translation_llm(s, chat, DailyBudget())
    assert bg is not chat and bg._circuit is not chat._circuit        # own circuit breaker
    assert (bg.primary, bg.fallback) == ("chat-primary", "chat-fallback") and chat.attempt_gate is None
    assert [bg.attempt_gate() for _ in range(4)] == [True, True, True, False]
    # a separate translation model never fails over onto the chatbot's fallback model
    s2 = s.model_copy(update={"translation_model": "bg-model"})
    bg2 = translation_llm(s2, build_llm_from_settings(s2), DailyBudget())
    assert (bg2.primary, bg2.fallback) == ("bg-model", "")
    # 0 = no background AI at all
    off = translation_llm(s.model_copy(update={"llm_background_daily_attempts": 0}), chat, DailyBudget())
    assert off.attempt_gate() is False
