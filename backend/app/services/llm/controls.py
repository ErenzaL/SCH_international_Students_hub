"""Cost controls for BACKGROUND AI work (translations, summaries, discovery), checked before every model attempt.

Order of the checks (the first that says no wins, nothing is sent to the provider):
  1. emergency stop: ``AI_BACKGROUND_STOP`` in the environment, or the admin switch (``app_runtime_flags``);
  2. today's attempt budget ``LLM_BACKGROUND_DAILY_ATTEMPTS`` (persistent with migration 0018);
  3. optional spend ceiling ``LLM_BACKGROUND_DAILY_USD_LIMIT``: today's ESTIMATED background cost (from
     ``LLM_PRICES``) must be below it. With a ceiling but no price for the model the attempt is refused: a cost that
     cannot be estimated is not assumed to be zero.
The chatbot is never stopped by these checks (it has its own per-user, per-client and global daily limits).
"""
from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Any

from app.services.llm.base import LLMError
from app.services.llm.usage import FREE_PROVIDERS, kst_day, usage

log = logging.getLogger("app.llm.controls")
STOP_FLAG = "ai_background_stop"


class RuntimeFlags:
    """Admin switches in ``app_runtime_flags`` (migration 0018), cached for a few seconds. Without the table every
    flag reads as unset and ``set`` raises (the environment variable still works)."""

    TTL = 15.0

    def __init__(self, store: Any):
        self.store = store
        self._cache: dict[str, tuple[float, Any]] = {}
        self.available: bool | None = None

    def get(self, key: str) -> Any:
        hit = self._cache.get(key)
        if hit and time.monotonic() - hit[0] < self.TTL:
            return hit[1]
        from app.repositories.base import Query

        value = None
        try:
            rows, _ = self.store.select("app_runtime_flags", Query(eq={"key": key}, cols="value", limit=1))
            value = rows[0]["value"] if rows else None
            self.available = True
        except Exception as exc:  # noqa: BLE001
            code = str((getattr(exc, "details", None) or {}).get("db_code") or "")
            if code in ("PGRST205", "42P01") or "unknown table" in str(exc).lower():
                self.available = False
            elif hit:                       # database briefly unreachable: keep the last known value
                return hit[1]
        self._cache[key] = (time.monotonic(), value)
        return value

    def set(self, key: str, value: Any, actor_id: str | None) -> None:
        from app.repositories.base import Query

        rows, _ = self.store.select("app_runtime_flags", Query(eq={"key": key}, cols="key", limit=1))
        row = dict(value=value, updated_by=actor_id, updated_at=datetime.now(UTC).isoformat())
        if rows:
            self.store.update("app_runtime_flags", row, {"key": key})
        else:
            self.store.insert("app_runtime_flags", dict(key=key) | row)
        self._cache[key] = (time.monotonic(), value)
        self.available = True


class BackgroundControls:
    def __init__(self, settings: Any, budget: Any, flags: RuntimeFlags | None, provider: str, model: str):
        self.settings, self.budget, self.flags = settings, budget, flags
        self.provider, self.model = provider, model

    def stopped(self) -> bool:
        if self.settings.ai_background_stop:
            return True
        return bool(self.flags.get(STOP_FLAG)) if self.flags is not None else False

    def spend_today(self) -> tuple[float, int]:
        """(estimated USD, unpriced attempts) of all background work today: from the database when available
        (all processes), else this process."""
        local = usage.spend_today("background")
        store = getattr(self.budget, "store", None)
        if store is None or getattr(usage.sink, "available", None) is not True:
            return local
        from app.repositories.base import Query

        try:
            rows, _ = store.select("llm_usage_daily", Query(eq={"day": kst_day(), "lane": "background"},
                                                            cols="est_cost_usd,priced,attempts,provider"))
        except Exception:  # noqa: BLE001
            return local
        cost = sum(float(r.get("est_cost_usd") or 0) for r in rows)
        unpriced = sum(int(r.get("attempts") or 0) for r in rows
                       if not r.get("priced") and r.get("provider") not in FREE_PROVIDERS)
        return max(round(cost, 6), local[0]), max(unpriced, local[1])

    def check(self) -> None:
        """Raises LLMError when the next background attempt must not be sent."""
        if self.stopped():
            raise LLMError("llm_background_stopped", "Background AI work is stopped by an administrator "
                                                     "(emergency stop); nothing was sent to the model.")
        limit = self.settings.llm_background_daily_attempts
        if limit <= 0 or not self.budget.take("background", limit):
            raise LLMError("llm_background_budget", "Today's AI budget for background work is used up; the "
                                                    "chatbot's share of the model quota is reserved.")
        ceiling = float(self.settings.llm_background_daily_usd_limit or 0)
        if ceiling > 0 and self.provider not in FREE_PROVIDERS:
            if self.model not in usage.prices.table:
                raise LLMError("llm_background_budget", f"A daily spending limit is set, but no price is configured "
                                                        f"for {self.model} (LLM_PRICES); background work waits.")
            spent, _unpriced = self.spend_today()
            if spent >= ceiling:
                raise LLMError("llm_background_budget", f"Today's estimated background AI cost ({spent:.4f} USD) "
                                                        f"reached the limit of {ceiling:.4f} USD.")

    def gate(self) -> bool:
        """For providers that take a boolean gate: False = stop (the provider raises its own budget error)."""
        try:
            self.check()
        except LLMError as exc:
            log.warning("background AI attempt refused: %s", exc.code)
            return False
        return True

    def state(self) -> dict[str, Any]:
        spent, unpriced = self.spend_today()
        return dict(stopped=self.stopped(), stop_from_env=bool(self.settings.ai_background_stop),
                    flags_available=None if self.flags is None else self.flags.available,
                    daily_usd_limit=float(self.settings.llm_background_daily_usd_limit or 0) or None,
                    estimated_spend_today_usd=spent, unpriced_attempts_today=unpriced,
                    model=self.model, provider=self.provider, model_priced=self.provider in FREE_PROVIDERS
                    or self.model in usage.prices.table)
