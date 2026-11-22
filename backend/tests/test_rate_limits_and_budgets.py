"""Client identity behind proxies (no X-Forwarded-For spoofing), per-user and global assistant limits, daily AI
budgets, and the engine's behaviour when generation fails or the budget is used up."""
from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

from app.core.rate_limit import ai_budget, client_ip, limiter
from app.services.assistant.texts import t
from app.services.llm.base import LLMError, ScriptedLLMProvider
from tests.conftest import make_settings
from tests.test_assistant import Q, _events, answer_with, conv, use_llm
from tests.test_document_lifecycle import website_doc


@pytest.fixture
def kb(env):  # type: ignore[no-untyped-def]
    src, job = website_doc(env)          # approved, indexed "Visa and Stay" page
    return dict(env=env, doc=job["document_id"], src=src)


def req(headers: dict[str, str], peer: str = "10.0.0.9") -> NS:
    return NS(headers={k.lower(): v for k, v in headers.items()}, client=NS(host=peer))


def test_client_ip_ignores_the_client_controlled_left_of_x_forwarded_for():
    s = make_settings(client_ip_header="", trusted_proxy_hops=1)
    assert client_ip(req({"X-Forwarded-For": "6.6.6.6, 203.0.113.7"}), s) == "203.0.113.7"
    assert client_ip(req({"X-Forwarded-For": "203.0.113.7"}), s) == "203.0.113.7"
    two = make_settings(client_ip_header="", trusted_proxy_hops=2)
    assert client_ip(req({"X-Forwarded-For": "6.6.6.6, 203.0.113.7, 198.51.100.1"}), two) == "203.0.113.7"
    assert client_ip(req({"X-Forwarded-For": "not-an-ip"}), s) == "10.0.0.9"
    assert client_ip(req({}), s) == "10.0.0.9"


def test_client_ip_prefers_the_proxy_set_header_and_validates_it():
    s = make_settings(client_ip_header="true-client-ip", trusted_proxy_hops=1)
    assert client_ip(req({"True-Client-IP": "198.51.100.23", "X-Forwarded-For": "6.6.6.6, 1.1.1.1"}), s) == "198.51.100.23"
    assert client_ip(req({"True-Client-IP": "garbage", "X-Forwarded-For": "6.6.6.6, 1.1.1.1"}), s) == "1.1.1.1"
    assert client_ip(req({"True-Client-IP": "[2001:db8::1]:443"}), s) == "2001:db8::1"


def test_spoofed_forwarded_for_cannot_bypass_the_anonymous_limit(env):
    env.app.state.services.settings = make_settings(rate_limit_search_per_minute=3, client_ip_header="")
    from app.core.config import get_settings

    env.app.dependency_overrides[get_settings] = lambda: env.app.state.services.settings
    codes = [env.client.post("/api/v1/assistant/chat", json={"message": "visa"},
                             headers={"X-Forwarded-For": f"10.9.{i}.1, 203.0.113.50"}).status_code for i in range(5)]
    assert codes == [200, 200, 200, 429, 429]


def test_global_anonymous_cap_holds_even_with_distinct_ips(env):
    env.app.state.services.settings = make_settings(rate_limit_chat_anonymous_global_per_minute=2, client_ip_header="")
    codes = [env.client.post("/api/v1/assistant/chat", json={"message": "visa"},
                             headers={"X-Forwarded-For": f"203.0.113.{i}"}).status_code for i in range(4)]
    assert codes == [200, 200, 429, 429]


def test_signed_in_students_are_limited_per_account(kb):
    env = kb["env"]
    env.app.state.services.settings = make_settings(rate_limit_chat_user_per_minute=2)
    cid = conv(env)
    codes = [env.client.post(f"/api/v1/conversations/{cid}/messages", headers=env.auth("student"),
                             json={"content": Q}).status_code for _ in range(3)]
    assert codes == [201, 201, 429]
    other = conv(env, user="admin")      # another account is unaffected
    assert env.client.post(f"/api/v1/conversations/{other}/messages", headers=env.auth("admin"),
                           json={"content": Q}).status_code == 201


def test_daily_ai_limit_applies_only_when_answers_are_generated(kb):
    env = kb["env"]
    env.app.state.services.settings = make_settings(ai_daily_limit_per_client=1)
    body = {"message": Q}
    assert [env.client.post("/api/v1/assistant/chat", json=body).status_code for _ in range(3)] == [200] * 3  # no LLM
    use_llm(env, answer_with("Bring your passport [1]."))
    ai_budget.reset()
    first = env.client.post("/api/v1/assistant/chat", json=body)
    second = env.client.post("/api/v1/assistant/chat", json=body)
    assert first.status_code == 200 and second.status_code == 429
    assert second.json()["error"]["code"] == "daily_limit"


def test_global_budget_exhaustion_degrades_to_sources_instead_of_calling_the_model(kb):
    env = kb["env"]
    llm = answer_with("Bring your passport [1].")
    use_llm(env, llm)
    env.app.state.services.conversations.engine.budget = lambda: False
    r = env.client.post("/api/v1/assistant/chat", json={"message": Q, "language": "vi"}).json()
    assert r["answer"] == t("generation_failed", "vi") and r["citations"]
    assert r["metadata"]["fallback_reason"] == "daily_budget" and llm.calls == []


def test_partial_stream_failure_is_replaced_by_one_clean_message(kb):
    env = kb["env"]

    class Flaky(ScriptedLLMProvider):
        def stream(self, system, prompt, on_text, *, max_tokens=4096, effort=None):  # type: ignore[no-untyped-def]
            on_text("Register at the immig")
            raise LLMError("llm_unavailable", "stream cut", transient=True, partial=True)

    use_llm(env, Flaky(lambda s, p: "{}"))
    evs = _events(env.client.post("/api/v1/assistant/chat/stream", json={"message": Q, "language": "id"}).text)
    assert any(e == "delta" for e, _ in evs) and evs[-1][0] == "done"
    final = evs[-1][1]
    assert final["answer"] == t("generation_failed", "id")             # the client replaces the partial text
    assert final["metadata"]["partial_stream_discarded"] is True and "immig" not in final["answer"]


def test_admin_can_inspect_client_ip_resolution_and_llm_usage(env):
    r = env.client.get("/api/v1/admin/system/client-ip", headers={**env.auth("admin"),
                                                                  "X-Forwarded-For": "6.6.6.6, 203.0.113.9"})
    assert r.status_code == 200 and r.json()["resolved_client_ip"] == "203.0.113.9"
    assert env.client.get("/api/v1/admin/system/client-ip", headers=env.auth("student")).status_code == 403
    u = env.client.get("/api/v1/admin/system/llm-usage", headers=env.auth("admin"))
    assert u.status_code == 200 and u.json()["provider"] == "none"
    limiter.reset()
