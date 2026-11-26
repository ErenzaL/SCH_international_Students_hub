"""Cost controls (migration 0018): budgets that survive restarts, cost estimates only from configured prices, the
background spending ceiling, the emergency stop, and the usage roll-up. The model is always a local fake: no paid
API is called by these tests."""
from __future__ import annotations

from typing import Any

import pytest

from app.core.errors import UpstreamError
from app.core.rate_limit import DailyBudget
from app.repositories.base import Query
from app.repositories.memory_store import MemoryStore
from app.services.llm.base import LLMError
from app.services.llm.controls import BackgroundControls, RuntimeFlags
from app.services.llm.usage import Prices, UsageRecorder, kst_day, usage
from tests.conftest import make_settings
from tests.test_auto_translation import KO_BODY, KO_TITLE, FakeTranslator, ann_row, jobs, publish, use_translator


# ------------------------------------------------------------------ persistent daily budgets
def test_a_restart_does_not_reopen_a_spent_budget():
    store = MemoryStore()
    first = DailyBudget().attach(store, {"background"})
    assert [first.take("background", 2) for _ in range(3)] == [True, True, False]
    restarted = DailyBudget().attach(store, {"background"})          # a new process, same database
    assert restarted.take("background", 2) is False and restarted.persistent is True
    assert restarted.used_persisted("background") == 2
    # keys that are not persisted stay in-process
    assert restarted.take("ip:1.2.3.4", 1) is True and restarted.take("ip:1.2.3.4", 1) is False


class _NoMigration:
    def rpc(self, name: str, params: dict[str, Any]) -> Any:
        raise UpstreamError("The database request failed.", details={"db_code": "PGRST202"})


class _Down:
    def __init__(self) -> None:
        self.inner, self.down = MemoryStore(), False

    def rpc(self, name: str, params: dict[str, Any]) -> Any:
        if self.down:
            raise UpstreamError("Could not reach the database.")
        return self.inner.rpc(name, params)


def test_without_the_migration_budgets_stay_in_process():
    b = DailyBudget().attach(_NoMigration(), {"background"}, fail_closed={"background"})
    assert [b.take("background", 2) for _ in range(3)] == [True, True, False]
    assert b.persistent is False and "0018" in (b.persist_error or "")


def test_background_fails_closed_when_the_counter_cannot_be_read_but_chat_does_not():
    store = _Down()
    b = DailyBudget().attach(store, {"background", "global"}, fail_closed={"background"})
    assert b.take("background", 5) is True and b.take("global", 5) is True and b.persistent is True
    store.down = True
    assert b.take("background", 5) is False                         # no background attempt without accounting
    assert b.take("global", 5) is True                               # students still get answers (local count)
    assert "unavailable" in (b.persist_error or "")


# ------------------------------------------------------------------ prices and estimates
def test_prices_are_estimates_only_for_configured_models():
    p = Prices("model-a=0.30/2.50, model-b=1/4, broken, model-c=x/1")
    assert p.table == {"model-a": (0.30, 2.50), "model-b": (1.0, 4.0)} and p.errors == ["broken", "model-c=x/1"]
    cost, priced = p.estimate("gemini", "model-a", 1_000_000, 100_000, 100_000)   # thinking billed as output
    assert priced and cost == pytest.approx(0.30 + 0.5)
    assert p.estimate("gemini", "unknown", 10, 10, 0) == (0.0, False)              # unknown, not zero
    assert p.estimate("ollama", "translategemma:12b", 10**6, 10**6, 0) == (0.0, True)   # local model


def test_usage_is_counted_by_lane_and_purpose_with_estimated_cost():
    rec = UsageRecorder()
    rec.configure(prices="m1=1/2")
    rec.attempt(lane="background", provider="gemini", model="m1", role="primary", purpose="translate", attempt=1,
                outcome="ok", latency_ms=5, input_tokens=1000, output_tokens=500)
    rec.attempt(lane="chat", provider="gemini", model="m2", role="primary", purpose="stream", attempt=1,
                outcome="error", latency_ms=5, error_code="llm_timeout")
    snap = rec.snapshot()
    assert snap["by_purpose"]["background:translate"]["ok"] == 1 and snap["by_purpose"]["chat:stream"]["failed"] == 1
    assert rec.spend_today("background") == (pytest.approx(0.002), 0)
    assert rec.spend_today("chat") == (0.0, 1)                       # m2 has no price: counted as unpriced


def test_usage_rows_reach_the_database_without_blocking():
    store = MemoryStore()
    rec = UsageRecorder()
    rec.configure(prices="m1=1/2", store=store)
    for _ in range(3):
        rec.attempt(lane="background", provider="gemini", model="m1", role="primary", purpose="translate",
                    attempt=1, outcome="ok", latency_ms=1, input_tokens=100, output_tokens=10, thinking_tokens=5)
    rec.sink.flush()  # type: ignore[union-attr]
    rows, _ = store.select("llm_usage_daily", Query(eq={"day": kst_day()}))
    assert len(rows) == 1 and rows[0]["attempts"] == 3 and rows[0]["input_tokens"] == 300
    assert rows[0]["thinking_tokens"] == 15 and rows[0]["est_cost_usd"] == pytest.approx(3 * (100 + 30) / 1e6)


# ------------------------------------------------------------------ background controls
def controls(**kw: Any) -> tuple[BackgroundControls, MemoryStore]:
    store = MemoryStore()
    s = make_settings(**({"llm_background_daily_attempts": 10} | kw))
    budget = DailyBudget().attach(store, {"background"}, fail_closed={"background"})
    return BackgroundControls(s, budget, RuntimeFlags(store), "gemini", "m1"), store


def test_the_emergency_stop_refuses_before_anything_is_sent():
    ctl, store = controls(ai_background_stop=True)
    with pytest.raises(LLMError) as ei:
        ctl.check()
    assert ei.value.code == "llm_background_stopped"
    assert not store.t["llm_daily_counters"]                         # the budget was not even charged
    ctl2, store2 = controls()
    ctl2.flags.set("ai_background_stop", True, None)  # type: ignore[union-attr]
    with pytest.raises(LLMError, match="emergency stop"):
        ctl2.check()
    ctl2.flags.set("ai_background_stop", False, None)  # type: ignore[union-attr]
    ctl2.check()


def test_a_spending_ceiling_needs_a_price_and_stops_at_the_limit(monkeypatch):
    ctl, _ = controls(llm_background_daily_usd_limit=0.01)
    monkeypatch.setattr(usage, "prices", Prices(""))
    with pytest.raises(LLMError, match="no price is configured"):
        ctl.check()
    monkeypatch.setattr(usage, "prices", Prices("m1=1/1"))
    monkeypatch.setattr(usage, "spend_today", lambda lane: (0.0, 0))
    ctl.check()
    monkeypatch.setattr(usage, "spend_today", lambda lane: (0.0101, 0))
    with pytest.raises(LLMError, match="reached the limit"):
        ctl.check()
    local, _ = controls(llm_background_daily_usd_limit=0.01)
    local.provider = "ollama"                                         # the local GPU model costs nothing per token
    local.check()


# ------------------------------------------------------------------ the whole path: a translation job (Journey J)
def test_an_exhausted_budget_defers_translation_jobs_without_a_retry_loop(env):
    s = env.settings
    s.auto_translate_announcements = True
    s.llm_background_daily_attempts = 1
    fake = FakeTranslator()
    p = use_translator(env, fake)
    svc = env.app.state.services
    from app.services.translation.auto import BudgetedLLM

    gate = BackgroundControls(s, svc.background_budget, svc.runtime_flags, "scripted", "translate-1")
    svc.announcement_translator.llm = BudgetedLLM(p, lambda: (gate.check(), True)[1])
    a = publish(env, title=KO_TITLE, body=KO_BODY)                   # en + id: two jobs, but one attempt allowed
    statuses = sorted((j["payload"]["language"], j["status"], j.get("error_code")) for j in jobs(env))
    assert ("id", "queued", "llm_background_budget") in statuses or ("en", "queued", "llm_background_budget") in statuses
    deferred = next(j for j in jobs(env) if j["status"] == "queued")
    assert deferred["statistics"]["deferrals"] == 1 and deferred["run_after"] > deferred["created_at"]
    calls = fake.calls
    for _ in range(3):                                               # running again today sends nothing new
        svc.ingestion.run_job(deferred["id"])
    assert fake.calls == calls
    assert ann_row(env, a["id"], deferred["payload"]["language"])["translation_status"] == "todo"   # nothing corrupted


def test_admins_flip_the_stop_switch_and_it_is_audited(env):
    url = "/api/v1/admin/system/ai-background-stop"
    assert env.client.post(url, headers=env.auth("supporter"), json=dict(stop=True)).status_code == 403
    assert env.client.post(url, headers=env.auth("student"), json=dict(stop=True)).status_code == 403
    r = env.client.post(url, headers=env.auth("admin"), json=dict(stop=True, note="test"))
    assert r.status_code == 200 and r.json()["stopped"] is True
    audit = [a for a in env.store.t["audit_log"] if a["action"] == "ai.background_stop"]
    assert audit and audit[0]["actor_id"] == env.users["admin"]
    svc = env.app.state.services
    assert svc.runtime_flags.get("ai_background_stop") is True
    info = env.client.get("/api/v1/admin/system/llm-usage", headers=env.auth("admin")).json()
    assert info["daily"]["available"] is True and info["daily_budget"]["persisted_keys"] == ["global"]
    assert env.client.post(url, headers=env.auth("admin"), json=dict(stop=False)).json()["stopped"] is False
