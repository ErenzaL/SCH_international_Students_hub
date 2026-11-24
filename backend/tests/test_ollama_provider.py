"""Ollama provider with mocked HTTP responses (no network, no model): requests, streaming, retries, concurrency,
error classification, privacy of the logs, and provider selection."""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from typing import Any

import httpx
import pytest

from app.core.config import Settings
from app.core.rate_limit import DailyBudget
from app.services.llm.base import LLMError, ScriptedLLMProvider, build_llm_from_settings
from app.services.llm.gemini import GeminiProvider
from app.services.llm.ollama import OllamaProvider
from app.services.llm.usage import usage
from app.services.translation.auto import BudgetedLLM, translation_llm
from tests.conftest import make_settings


def body(text: str = "ok", *, done: bool = True, reason: str | None = "stop", tin: int = 11, tout: int = 7) -> dict[str, Any]:
    out: dict[str, Any] = dict(model="qwen-test", message={"role": "assistant", "content": text}, done=done)
    if done:
        out |= dict(done_reason=reason, prompt_eval_count=tin, eval_count=tout, eval_duration=10**9, load_duration=0)
    return out


def ok(text: str = "ok", **kw: Any) -> httpx.Response:
    return httpx.Response(200, json=body(text, **kw))


def lines(*objs: Any) -> httpx.Response:
    return httpx.Response(200, content="".join(json.dumps(o, ensure_ascii=False) + "\n" for o in objs).encode())


class Fake:
    """Scripted outcomes; keeps every request."""

    def __init__(self, *script: Any):
        self.script = list(script)
        self.requests: list[dict[str, Any]] = []

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(json.loads(request.content) if request.content else {"path": request.url.path})
        out = self.script.pop(0)
        if isinstance(out, Exception):
            raise out
        if callable(out):
            return await out()
        return out


@pytest.fixture
def make():  # type: ignore[no-untyped-def]
    made: list[OllamaProvider] = []

    def build(*script: Any, **kw: Any) -> tuple[OllamaProvider, Fake, list[float]]:
        fake, sleeps = Fake(*script), []

        async def sleep(s: float) -> None:
            sleeps.append(s)

        p = OllamaProvider("qwen-test", transport=httpx.MockTransport(fake), sleep=sleep, **kw)
        made.append(p)
        return p, fake, sleeps

    yield build
    for p in made:
        p.close()


# ------------------------------------------------------------------ requests and results
def test_complete_sends_a_bounded_request_and_reports_tokens(make):
    p, fake, sleeps = make(ok("Hello [1]"), num_ctx=8192, max_output_tokens=9999)
    r = p.complete("sys", "prompt", max_tokens=16000)
    assert (r.text, r.provider, r.model, r.attempts, r.fallback_used) == ("Hello [1]", "ollama", "qwen-test", 1, False)
    assert (r.input_tokens, r.output_tokens, r.total_tokens) == (11, 7, 18) and r.latency_ms is not None
    sent = fake.requests[0]
    assert sent["truncate"] is False and sent["shift"] is False and sent["stream"] is False
    assert sent["options"]["num_ctx"] == 8192 and sent["options"]["num_predict"] == 4096
    assert [m["role"] for m in sent["messages"]] == ["system", "user"] and "format" not in sent and sleeps == []


def test_rewrites_ask_for_json_and_are_tried_once(make):
    p, fake, sleeps = make(httpx.Response(500, json={"error": "x"}))
    with pytest.raises(LLMError):
        p.complete("s", "q", max_tokens=500, fast=True, purpose="rewrite")
    assert fake.requests[0]["format"] == "json" and len(fake.requests) == 1 and sleeps == []


def test_async_interface_works_from_different_event_loops(make):
    p, _, _ = make(ok("one"), ok("two"))
    assert asyncio.run(p.acomplete("s", "q")).text == "one"
    assert asyncio.run(p.acomplete("s", "q")).text == "two"


def test_sync_and_async_streaming_deliver_in_order(make):
    chunks = [body("안녕", done=False), body("하세요", done=False), body("")]
    p, fake, _ = make(lines(*chunks), lines(*chunks))
    got: list[str] = []
    caller = []
    r = p.stream("s", "q", lambda x: (got.append(x), caller.append(threading.current_thread())))
    assert got == ["안녕", "하세요"] and r.text == "안녕하세요" and set(caller) == {threading.current_thread()}
    agot: list[str] = []

    async def on_text(x: str) -> None:
        agot.append(x)

    assert asyncio.run(p.astream("s", "q", on_text)).text == "안녕하세요" and agot == got
    assert fake.requests[0]["stream"] is True


# ----------------------------------------------------------------- errors and retries
def test_transient_failures_are_retried_with_bounded_backoff(make):
    p, fake, sleeps = make(httpx.ConnectError("refused"), ok("ok"), retry_base=0.8)
    r = p.complete("s", "q", max_tokens=100)
    assert r.text == "ok" and r.attempts == 2 and len(sleeps) == 1 and 0.4 <= sleeps[0] <= 0.8
    p, fake, sleeps = make(*[httpx.Response(500, json={"error": "x"})] * 3, max_attempts=3)
    with pytest.raises(LLMError) as ei:
        p.complete("s", "q", max_tokens=100)
    assert ei.value.code == "llm_unavailable" and ei.value.transient and len(fake.requests) == 3 and len(sleeps) == 2


@pytest.mark.parametrize("response,code,transient", [
    (httpx.Response(404, json={"error": "model 'x' not found"}), "llm_model", False),
    (httpx.Response(400, json={"error": "bad"}), "llm_bad_request", False),
    (httpx.Response(400, json={"error": '{"type":"exceed_context_size_error","n_ctx":2048}'}), "llm_context", False),
    (httpx.Response(302, headers={"location": "http://example.test/"}), "llm_error", False),
    (ok("cut", reason="length"), "llm_truncated", False),
])
def test_permanent_failures_are_never_retried(make, response, code, transient):
    p, fake, sleeps = make(response)
    with pytest.raises(LLMError) as ei:
        p.complete("s", "q", max_tokens=100)
    assert (ei.value.code, ei.value.transient) == (code, transient) and len(fake.requests) == 1 and sleeps == []


@pytest.mark.parametrize("response,code", [
    (ok("   "), "llm_empty"), (httpx.Response(200, content=b"<html>"), "llm_malformed"),
    (httpx.Response(200, json={"unexpected": 1}), "llm_malformed"), (httpx.Response(503), "llm_rate_limited"),
    (httpx.Response(200, json=[]), "llm_malformed"),
])
def test_unusable_responses_are_retried(make, response, code):
    p, fake, _ = make(response, response)
    with pytest.raises(LLMError) as ei:
        p.complete("s", "q", max_tokens=100)
    assert ei.value.code == code and ei.value.transient and len(fake.requests) == 2


def test_the_whole_attempt_is_limited_in_time(make):
    async def slow() -> httpx.Response:
        await asyncio.sleep(30)
        return ok()

    p, fake, _ = make(slow, slow, request_timeout=0.05)
    t0 = time.perf_counter()
    with pytest.raises(LLMError) as ei:
        p.complete("s", "q", max_tokens=100)
    assert ei.value.code == "llm_timeout" and time.perf_counter() - t0 < 5 and len(fake.requests) == 2


def test_stream_failures_before_text_are_retried_and_after_text_are_partial(make):
    p, fake, _ = make(lines({"error": "boom"}), lines(body("fine", done=False), body("")))
    assert p.stream("s", "q", lambda _x: None).text == "fine" and len(fake.requests) == 2
    for broken in (lines(body("half", done=False), {"error": "boom"}), lines(body("half", done=False))):
        p, fake, _ = make(broken)
        got: list[str] = []
        with pytest.raises(LLMError) as ei:
            p.stream("s", "q", got.append)
        assert ei.value.partial and got == ["half"] and len(fake.requests) == 1


def test_a_failing_consumer_cancels_the_generation(make):
    cancelled = threading.Event()

    class Endless(httpx.AsyncByteStream):
        async def __aiter__(self):  # type: ignore[no-untyped-def]
            try:
                yield (json.dumps(body("x", done=False)) + "\n").encode()
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                cancelled.set()
                raise

    async def endless() -> httpx.Response:
        return httpx.Response(200, stream=Endless())

    p, _, _ = make(endless, ok("next"))

    def boom(_x: str) -> None:
        raise RuntimeError("client went away")

    with pytest.raises(RuntimeError):
        p.stream("s", "q", boom)
    assert cancelled.wait(3)
    assert p.complete("s", "q", max_tokens=100).text == "next"          # the slot was released


# ----------------------------------------------------------------- concurrency
def test_concurrency_limit_is_shared_by_all_callers(make):
    state = {"now": 0, "max": 0}

    async def work() -> httpx.Response:
        state["now"] += 1
        state["max"] = max(state["max"], state["now"])
        await asyncio.sleep(0.03)
        state["now"] -= 1
        return ok()

    p, _, _ = make(*[work] * 6, max_concurrency=2)
    threads = [threading.Thread(target=p.complete, args=("s", "q")) for _ in range(3)]
    for th in threads:
        th.start()

    async def both() -> None:
        await asyncio.gather(*(p.acomplete("s", "q") for _ in range(3)))

    asyncio.run(both())
    for th in threads:
        th.join()
    assert state["max"] == 2


def test_waiting_for_a_slot_is_limited_and_not_retried(make):
    release = threading.Event()

    async def hold() -> httpx.Response:
        while not release.is_set():
            await asyncio.sleep(0.01)
        return ok("first")

    p, fake, sleeps = make(hold, queue_timeout=0.05)
    out: list[Any] = []
    th = threading.Thread(target=lambda: out.append(p.complete("s", "q", max_tokens=16000)))
    th.start()
    while not fake.requests:
        time.sleep(0.01)
    with pytest.raises(LLMError) as ei:
        p.complete("s", "q", max_tokens=100)
    release.set()
    th.join()
    assert ei.value.code == "llm_rate_limited" and ei.value.transient and sleeps == [] and len(fake.requests) == 1
    assert out[0].text == "first"


def test_close_stops_open_requests_and_the_provider_can_be_used_again(make):
    async def hang() -> httpx.Response:
        await asyncio.sleep(30)
        return ok()

    p, fake, _ = make(hang, ok("again"))
    errors: list[LLMError] = []

    def run() -> None:
        try:
            p.complete("s", "q")
        except LLMError as exc:
            errors.append(exc)

    th = threading.Thread(target=run)
    th.start()
    while not fake.requests:
        time.sleep(0.01)
    p.close()
    th.join(5)
    assert errors and errors[0].code == "llm_unavailable"
    assert p.complete("s", "q").text == "again"


# -------------------------------------------------------------- privacy and exposure
def test_logs_have_metadata_but_never_content(make, caplog):
    usage.reset()
    p, _, _ = make(httpx.Response(500, json={"error": "ECHO STUDENT-QUESTION-7"}), ok("ANSWER-TEXT-42"))
    with caplog.at_level(logging.DEBUG):
        p.complete("SYSTEM-SECRET", "STUDENT-QUESTION-7", max_tokens=100)
    logs = "\n".join(r.getMessage() for r in caplog.records)
    assert "provider=ollama" in logs and "input_tokens=11" in logs and "latency_ms=" in logs
    assert "error=llm_unavailable" in logs and "queue_ms=" in logs and "tokens_per_s=7" in logs
    for secret in ("SYSTEM-SECRET", "STUDENT-QUESTION-7", "ANSWER-TEXT-42", "ECHO"):
        assert secret not in logs
    snap = usage.snapshot()
    assert snap["tokens"]["qwen-test"]["total"] == 18 and "STUDENT" not in json.dumps(snap)
    p, _, _ = make(httpx.Response(400, json={"error": "ECHO STUDENT-QUESTION-7"}))
    with pytest.raises(LLMError) as ei:
        p.complete("s", "STUDENT-QUESTION-7", max_tokens=100)
    assert "STUDENT" not in ei.value.message


@pytest.mark.parametrize("url", ["http://0.0.0.0:11434", "http://192.168.0.5:11434", "http://ollama.example.test",
                                 "https://127.0.0.1:11434", "http://127.0.0.1.example.test", "http://u:p@127.0.0.1",
                                 "http://127.0.0.1:11434/api", "", "http://127.0.0.1:bad", "http://[::", "http://127.0.0.1@evil.test"])
def test_only_loopback_addresses_are_accepted(url):
    with pytest.raises(ValueError):
        OllamaProvider("m", base_url=url)


def test_loopback_addresses_and_client_isolation():
    for url in ("http://127.0.0.1:11434/", "http://localhost:11434", "http://[::1]:11434"):
        p = OllamaProvider("m", base_url=url)
        assert p.base_url == url.rstrip("/")

    async def check() -> None:
        c = p._http()
        assert c.trust_env is False and c.follow_redirects is False
        await c.aclose()

    asyncio.run(check())


# ------------------------------------------------------------------ probe / admin
def test_probe_and_installed_models(make):
    p, fake, _ = make(ok("OK"), httpx.Response(404, json={"error": "nope"}),
                      httpx.Response(200, json={"models": [{"name": "qwen-test"}]}))
    rows = p.probe("qwen-test")
    assert [(r["call"], r["ok"]) for r in rows] == [("generate", True), ("stream", False)]
    assert rows[1]["error"] == "llm_model" and p.installed_models() == ["qwen-test"]
    p, _, _ = make(httpx.ConnectError("down"))
    with pytest.raises(LLMError) as ei:
        p.installed_models()
    assert ei.value.code == "llm_unavailable"


# ------------------------------------------------------------------ selection
def test_defaults_are_unchanged():
    f = Settings.model_fields
    assert f["llm_provider"].default == "none" and f["background_llm_provider"].default == ""
    assert f["gemini_primary_model"].default == "gemini-3.6-flash" and f["agent_schedules_enabled"].default is False


def test_provider_is_selected_by_settings():
    p = build_llm_from_settings(make_settings(llm_provider="ollama", ollama_model="qwen2.5:7b-instruct",
                                              ollama_num_ctx=8192, ollama_max_concurrency=3))
    assert isinstance(p, OllamaProvider) and (p.model, p.num_ctx, p.max_concurrency) == ("qwen2.5:7b-instruct", 8192, 3)
    assert isinstance(build_llm_from_settings(make_settings(llm_provider="gemini", llm_api_key="not-real")), GeminiProvider)
    with pytest.raises(ValueError):
        build_llm_from_settings(make_settings(llm_provider="ollama", ollama_base_url="http://10.0.0.1:11434"))


def test_background_provider_is_selected_separately():
    s = make_settings(llm_provider="gemini", llm_api_key="not-real", background_llm_provider="ollama",
                      llm_background_daily_attempts=1)
    chat = build_llm_from_settings(s)
    bg = translation_llm(s, chat, DailyBudget())
    assert isinstance(chat, GeminiProvider) and isinstance(bg, BudgetedLLM) and bg.name == "ollama"
    # unset: exactly the existing behaviour (Gemini with its own circuit breaker and gate)
    same = make_settings(llm_provider="gemini", llm_api_key="not-real")
    assert isinstance(translation_llm(same, chat, DailyBudget()), GeminiProvider)
    # translation drafts only: no assistant provider
    off = make_settings(llm_provider="none", background_llm_provider="ollama")
    assert translation_llm(off, build_llm_from_settings(off), DailyBudget()).name == "ollama"
    # both local: one shared instance, so one concurrency limit for the GPU
    both = make_settings(llm_provider="ollama", background_llm_provider="ollama")
    shared = build_llm_from_settings(both)
    assert translation_llm(both, shared, DailyBudget())._inner is shared
    # local assistant, no background AI
    none = make_settings(llm_provider="ollama", background_llm_provider="none")
    assert translation_llm(none, build_llm_from_settings(none), DailyBudget()).enabled is False


def test_async_background_calls_are_budgeted_too(make):
    p, fake, _ = make(ok())
    b = BudgetedLLM(p, lambda: False)
    for call in (b.acomplete("s", "q"), b.astream("s", "q", print)):
        with pytest.raises(LLMError) as ei:
            asyncio.run(call)
        assert ei.value.code == "llm_background_budget"
    assert fake.requests == []


def test_scripted_provider_has_no_source_limit():
    from app.services.translation_drafts import summarize_document

    out = summarize_document(ScriptedLLMProvider(lambda s, p: "text"), title="t", body="x" * 30000, source_lang="ko",
                             target_lang="en", max_source_chars=40000)
    assert out["partial"] is False and out["source_chars"] == 30000
