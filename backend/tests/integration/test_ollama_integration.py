"""Existing services (translation drafts, RAG answers, agent tasks) running on the Ollama provider with MOCKED Ollama
responses, through the real API and the in-memory store."""
from __future__ import annotations

import json
import re
from typing import Any

import httpx
import pytest

from app.core.rate_limit import DailyBudget
from app.services.assistant.prompts import META_MARKER
from app.services.llm.ollama import OllamaProvider
from app.services.llm.usage import usage
from app.services.translation.auto import BudgetedLLM
from app.services.translation.quality import local_model_warnings
from tests.test_agents import get_task, task
from tests.test_auto_translation import FakeTranslator, ann_row, public_ann, publish
from tests.test_retrieval import make_doc


class MockOllama:
    """Answers /api/chat like Ollama does, using ``responder(system, prompt)``."""

    def __init__(self, responder: Any):
        self.responder, self.requests = responder, []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.url.host == "127.0.0.1" and request.url.path == "/api/chat"
        req = json.loads(request.content)
        self.requests.append(req)
        out = self.responder(req["messages"][0]["content"], req["messages"][1]["content"])
        if isinstance(out, httpx.Response):
            return out
        end = dict(model=req["model"], message={"content": ""}, done=True, done_reason="stop", prompt_eval_count=100,
                   eval_count=20)
        if not req["stream"]:
            return httpx.Response(200, json=end | {"message": {"content": out}})
        rows = [dict(model=req["model"], message={"content": out[i:i + 9]}, done=False) for i in range(0, len(out), 9)]
        return httpx.Response(200, content="\n".join(json.dumps(r) for r in [*rows, end]).encode())


@pytest.fixture
def local(env):  # type: ignore[no-untyped-def]
    """``local(responder)``: background work and the assistant use one mocked Ollama."""
    made: list[OllamaProvider] = []

    def use(responder: Any) -> MockOllama:
        mock = MockOllama(responder)
        p = OllamaProvider("qwen2.5:7b-instruct", transport=httpx.MockTransport(mock), retry_base=0.05, retry_max_delay=0)
        made.append(p)
        svc, budget = env.app.state.services, DailyBudget()
        svc.llm = svc.conversations.llm = svc.conversations.engine.llm = p
        bg = BudgetedLLM(p, lambda: budget.take("background", 1000))
        svc.doc_translations.llm = svc.announcement_translator.llm = svc.discovery.llm = bg
        env.settings.translation_fallback_to_gemini = True    # announcements may use the server's model (here Ollama)
        return mock

    yield use
    for p in made:
        p.close()


def request_draft(env, aid: str, lang: str):  # type: ignore[no-untyped-def]
    return env.client.post(f"/api/v1/admin/announcements/{aid}/translations/{lang}/machine-translate",
                           headers=env.auth("admin"))


def test_announcement_draft_needs_review_and_is_not_published(env, local):
    mock = local(FakeTranslator())
    a = publish(env, title="장학금 신청 안내", body="신청 기간은 2026년 12월 1일부터입니다. https://sch.ac.kr/apply")
    assert mock.requests == []                                   # nothing is translated automatically
    assert request_draft(env, a["id"], "en").status_code == 202
    row = ann_row(env, a["id"], "en")
    assert (row["translation_status"], row["provider"], row["model"]) == \
        ("needs_review", "ollama", "qwen2.5:7b-instruct")
    assert public_ann(env, a["id"], "en")["translation"] is None  # students keep seeing the original
    assert all(r["truncate"] is False for r in mock.requests) and len(mock.requests) == 2


def test_a_draft_that_slips_into_chinese_needs_review(env, local):
    local(FakeTranslator(mutate=lambda t: t + " 请注意"))
    a = publish(env, title="장학금 신청 안내", body="신청 기간은 2026년 12월 1일부터입니다.")
    request_draft(env, a["id"], "en")
    row = ann_row(env, a["id"], "en")
    assert row["translation_status"] == "needs_review"
    assert any("Chinese" in w["value"] for w in row["warnings"])


def test_a_stopped_ollama_requeues_the_draft(env, local):
    mock = local(lambda s, p: httpx.Response(503))
    a = publish(env, title="장학금 신청 안내", body="신청 기간 안내입니다.")
    request_draft(env, a["id"], "en")
    job = env.store.t["ingestion_jobs"][-1]
    assert job["status"] == "queued" and job["error_code"] == "llm_rate_limited" and len(mock.requests) == 2
    assert ann_row(env, a["id"], "en")["translation_status"] == "todo"


def rag(answer: str) -> Any:
    def respond(system: str, prompt: str) -> str:
        if "search queries" in system:
            q = re.search(r"<latest_message>\n(.*)\n</latest_message>", prompt).group(1)  # type: ignore[union-attr]
            return json.dumps(dict(standalone=q, en="TOPIK registration", ko="TOPIK 접수", topic="new"))
        return answer + f'\n{META_MARKER}\n{{"evidence": "sufficient", "needs_human": "none", "in_scope": true}}'

    return respond


@pytest.mark.parametrize("lang,question", [("en", "How do I register for TOPIK?"), ("ko", "TOPIK 접수는 어떻게 하나요?"),
                                           ("id", "Bagaimana cara daftar TOPIK?"), ("vi", "Đăng ký TOPIK thế nào?"),
                                           ("zh-CN", "如何报名TOPIK？")])
def test_rag_answers_are_grounded_in_existing_documents(env, local, lang, question):
    make_doc(env, "TOPIK guide", "TOPIK registration opens online each exam cycle. Register on the official site.",
             category="topik-korean")
    mock = local(rag("TOPIK: official site [1]."))
    r = env.client.post("/api/v1/assistant/chat", json=dict(message=question, language=lang)).json()
    assert r["answer"] == "TOPIK: official site." and r["metadata"]["provider"] == "ollama", r
    assert r["language"] == lang and r["citations"][0]["document_title"] == "TOPIK guide"
    assert mock.requests[0]["format"] == "json" and mock.requests[1]["stream"] is True


def test_rag_answer_is_streamed_without_markers(env, local):
    make_doc(env, "TOPIK guide", "TOPIK registration opens online each exam cycle.", category="topik-korean")
    local(rag("TOPIK registration opens online [1]."))
    r = env.client.post("/api/v1/assistant/chat/stream", json=dict(message="TOPIK registration?", language="en"))
    assert "event: delta" in r.text and "event: done" in r.text
    deltas = "".join(json.loads(x)["text"] for x in re.findall(r"event: delta\ndata: (.*)", r.text))
    assert "[1]" not in deltas and "META" not in deltas and "opens online" in deltas


def test_rag_without_citations_or_without_a_model_falls_back_to_sources(env, local):
    make_doc(env, "TOPIK guide", "TOPIK registration opens online each exam cycle.", category="topik-korean")
    local(rag("Just register somewhere."))
    r = env.client.post("/api/v1/assistant/chat", json=dict(message="TOPIK registration?", language="en")).json()
    assert r["metadata"]["fallback_reason"] == "no_citations" and "somewhere" not in r["answer"] and r["citations"]
    local(lambda s, p: httpx.Response(500))
    r = env.client.post("/api/v1/assistant/chat", json=dict(message="TOPIK registration?", language="en")).json()
    assert r["metadata"]["fallback_reason"] == "llm_unavailable" and r["citations"]


def test_agent_tasks_use_the_local_model(env, local):
    from tests.test_agents import publish as publish_ann

    a = publish_ann(env)
    mock = local(lambda s, p: "Scholarship notice" if "document title" in p else "- Apply before the deadline.")
    t = task(env, "announcement", "summarize_announcement", {"ref": a["id"], "language": "en"})
    assert t.status_code == 201, t.text
    full = get_task(env, t.json()["id"]).json()
    assert full["status"] == "completed", full
    assert full["output"]["items"][0]["reliability"] == "ai_generated"
    assert full["output"]["provenance"]["generated_by"] == "qwen2.5:7b-instruct" and mock.requests


def test_long_sources_are_cut_to_the_context_window_and_marked_partial(local, env):
    from app.services.translation_drafts import summarize_document

    local(lambda s, p: "Summary of the document in English.")
    llm = env.app.state.services.doc_translations.llm
    out = summarize_document(llm, title="t", body="가" * 30000, source_lang="ko", target_lang="en", max_source_chars=40000)
    assert out["partial"] is True and out["source_chars"] == llm.max_source_chars == 16384 - 4096


def test_usage_is_visible_to_admins_without_content(env, local):
    usage.reset()
    make_doc(env, "TOPIK guide", "TOPIK registration opens online each exam cycle.", category="topik-korean")
    local(rag("TOPIK registration opens online [1]."))
    env.client.post("/api/v1/assistant/chat", json=dict(message="TOPIK registration PRIVATE-77?", language="en"))
    r = env.client.get("/api/v1/admin/system/llm-usage", headers=env.auth("admin"))
    assert r.json()["provider"] == "ollama" and r.json()["usage"]["tokens"]["qwen2.5:7b-instruct"]["input"] == 200
    assert "PRIVATE-77" not in r.text


@pytest.mark.parametrize("source,target,original,translated,flagged", [
    ("ko", "en", "안내", "Notice", False), ("ko", "en", "안내", "Notice 通知", True),
    ("ko", "en", "大學 안내", "大學 (university) notice", False),
    ("ko", "vi", "안내 " * 30, "안내 " * 30, True),
    ("zh-CN", "en", "国际处通知。" * 10, "International Office (国际处) notice for all students. " * 3, False),
    ("zh-CN", "en", "国际处通知。" * 10, "国际处通知。" * 10, True),
    ("en", "id", "x", "The students must submit the form and the passport to the office for the visa. " * 3, True),
    ("en", "id", "x", "Mahasiswa harus menyerahkan formulir dan paspor untuk visa yang akan diproses dalam dua hari. " * 3, False),
])
def test_local_model_checks(source, target, original, translated, flagged):
    assert bool(local_model_warnings(original, translated, source, target)) is flagged


def test_format_reminder_is_only_sent_to_local_models(env, local):
    from app.services.assistant.engine import FORMAT_REMINDER
    from app.services.llm.base import ScriptedLLMProvider

    head = FORMAT_REMINDER.strip().splitlines()[0]
    make_doc(env, "TOPIK guide", "TOPIK registration opens online each exam cycle.", category="topik-korean")
    mock = local(rag("TOPIK registration opens online [1]."))
    env.client.post("/api/v1/assistant/chat", json=dict(message="TOPIK registration?", language="vi"))
    assert head in mock.requests[-1]["messages"][1]["content"] and "Tiếng Việt" in mock.requests[-1]["messages"][1]["content"]
    other = ScriptedLLMProvider(rag("TOPIK registration opens online [1]."))
    env.app.state.services.conversations.engine.llm = other
    env.client.post("/api/v1/assistant/chat", json=dict(message="TOPIK registration?", language="vi"))
    assert other.calls and all(head not in prompt for _s, prompt in other.calls)
