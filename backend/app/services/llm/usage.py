"""LLM usage accounting: one structured log line per model attempt plus aggregates for the admin view.

Only operational metadata is recorded (provider, model, lane, purpose, outcome, error code, token counts reported by
the API, latency). Prompts, answers, student messages and keys are never logged. Token counts are only what the
provider reports; nothing is estimated. A COST is estimated only for models whose prices the owner configured
(``LLM_PRICES``, USD per million tokens); it is an estimate, never an invoice.

Lanes: ``chat`` (student answers) and ``background`` (translations, summaries, discovery). In-process aggregates
reset on restart; with migration 0018 every attempt is also added to ``llm_usage_daily`` by a writer thread (the
request never waits for the database; a full queue drops rows and counts them as ``dropped``).
"""
from __future__ import annotations

import logging
import queue
import threading
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

log = logging.getLogger("app.llm.usage")
KST = timezone(timedelta(hours=9))
FREE_PROVIDERS = ("ollama",)          # local models: no per-token price


def kst_day() -> str:
    return datetime.now(KST).date().isoformat()


class Prices:
    """``model=input/output`` pairs in USD per million tokens, comma separated, e.g.
    ``gemini-x-flash=0.30/2.50,gemini-x-flash-lite=0.10/0.40``. Thinking tokens are priced as output (the way
    Gemini bills them). A model without a price is ``unpriced``: its cost is unknown, not zero."""

    def __init__(self, spec: str = ""):
        self.table: dict[str, tuple[float, float]] = {}
        self.errors: list[str] = []
        for part in (p.strip() for p in (spec or "").split(",")):
            if not part:
                continue
            try:
                model, rates = part.split("=", 1)
                pin, pout = (float(x) for x in rates.split("/", 1))
                if model.strip() and pin >= 0 and pout >= 0:
                    self.table[model.strip()] = (pin, pout)
                    continue
            except ValueError:
                pass
            self.errors.append(part[:60])

    def estimate(self, provider: str, model: str, input_tokens: int | None, output_tokens: int | None,
                 thinking_tokens: int | None) -> tuple[float, bool]:
        """(estimated USD, priced)."""
        if provider in FREE_PROVIDERS:
            return 0.0, True
        rates = self.table.get(model)
        if rates is None:
            return 0.0, False
        pin, pout = rates
        out = (output_tokens or 0) + (thinking_tokens or 0)
        return round(((input_tokens or 0) * pin + out * pout) / 1_000_000, 6), True


class UsageSink:
    """Adds attempts to ``llm_usage_daily`` from one daemon thread (bounded queue, never blocks a request)."""

    MAX_QUEUE = 2000

    def __init__(self, store: Any):
        self.store = store
        self.q: queue.Queue[dict[str, Any]] = queue.Queue(self.MAX_QUEUE)
        self.written = self.dropped = self.failed = 0
        self.available: bool | None = None
        self._thread = threading.Thread(target=self._run, name="llm-usage-sink", daemon=True)
        self._thread.start()

    def put(self, row: dict[str, Any]) -> None:
        if self.available is False:
            return
        try:
            self.q.put_nowait(row)
        except queue.Full:
            self.dropped += 1

    def _run(self) -> None:
        while True:
            row = self.q.get()
            if row is None:  # type: ignore[comparison-overlap]
                return
            self.write(row)

    def write(self, row: dict[str, Any]) -> None:
        try:
            self.store.rpc("llm_usage_add", row)
            self.written += 1
            self.available = True
        except Exception as exc:  # noqa: BLE001
            code = str((getattr(exc, "details", None) or {}).get("db_code") or "")
            if code in ("PGRST202", "PGRST205", "42883", "42P01") or "unknown rpc" in str(exc):
                self.available = False         # migration 0018 not applied: stop trying
            self.failed += 1

    def flush(self, timeout: float = 5.0) -> None:
        """Tests and shutdown: wait until the queue is written."""
        end = datetime.now(UTC) + timedelta(seconds=timeout)
        while not self.q.empty() and datetime.now(UTC) < end:
            threading.Event().wait(0.01)
        threading.Event().wait(0.02)


class UsageRecorder:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.prices = Prices()
        self.sink: UsageSink | None = None
        self.reset()

    def reset(self) -> None:
        with getattr(self, "_lock", threading.Lock()):
            self.started_at = datetime.now(UTC).isoformat()
            self.calls: Counter[str] = Counter()            # by "provider:model:role:outcome"
            self.errors: Counter[str] = Counter()           # by error code
            self.tokens: dict[str, Counter[str]] = defaultdict(Counter)   # model -> input/output/thinking/total
            self.by_purpose: dict[str, Counter[str]] = defaultdict(Counter)  # "lane:purpose" -> attempts/tokens
            self.cost_day = kst_day()
            self.cost_today: dict[str, float] = defaultdict(float)        # lane -> estimated USD, this process
            self.unpriced_today: Counter[str] = Counter()                 # lane -> attempts without a price
            self.fallback_activations = 0
            self.requests = 0
            self.latency_ms_total = 0
            self.last_error_at: str | None = None
            self.last_errors: dict[str, dict[str, Any]] = {}

    def configure(self, *, prices: str = "", store: Any = None) -> None:
        self.prices = Prices(prices)
        if store is None:
            return
        if self.sink is None:
            self.sink = UsageSink(store)
        elif self.sink.store is not store:
            self.sink.store, self.sink.available = store, None

    def _roll(self) -> None:
        day = kst_day()
        if day != self.cost_day:
            self.cost_day, self.cost_today, self.unpriced_today = day, defaultdict(float), Counter()

    def attempt(self, *, provider: str, model: str, role: str, purpose: str, attempt: int, outcome: str,
                latency_ms: int, error_code: str | None = None, input_tokens: int | None = None,
                output_tokens: int | None = None, thinking_tokens: int | None = None,
                total_tokens: int | None = None, retry_in_s: float | None = None, http: int | None = None,
                status: str | None = None, detail: str | None = None, quota_id: str | None = None,
                lane: str = "chat") -> None:
        lane = lane if lane in ("chat", "background") else "chat"
        cost, priced = self.prices.estimate(provider, model, input_tokens, output_tokens, thinking_tokens)
        log.log(logging.INFO if outcome == "ok" else logging.WARNING,
                "llm_attempt provider=%s model=%s lane=%s role=%s purpose=%s attempt=%d outcome=%s error=%s http=%s "
                "status=%s quota=%s latency_ms=%d input_tokens=%s output_tokens=%s thinking_tokens=%s total_tokens=%s "
                "est_cost_usd=%s retry_in_s=%s detail=%s",
                provider, model, lane, role, purpose, attempt, outcome, error_code or "-", http or "-", status or "-",
                quota_id or "-", latency_ms, _n(input_tokens), _n(output_tokens), _n(thinking_tokens),
                _n(total_tokens), f"{cost:.6f}" if priced else "unpriced",
                f"{retry_in_s:.2f}" if retry_in_s is not None else "-", f'"{detail}"' if detail else "-")
        if error_code:
            with self._lock:
                self.last_errors[model] = dict(error=error_code, http=http, status=status, quota_id=quota_id,
                                               detail=detail, at=datetime.now(UTC).isoformat())
        with self._lock:
            self._roll()
            self.calls[f"{provider}:{model}:{role}:{outcome}"] += 1
            self.latency_ms_total += latency_ms
            if error_code:
                self.errors[error_code] += 1
                self.last_error_at = datetime.now(UTC).isoformat()
            t = self.tokens[model]
            for k, v in (("input", input_tokens), ("output", output_tokens), ("thinking", thinking_tokens),
                         ("total", total_tokens)):
                if v is not None:
                    t[k] += int(v)
            p = self.by_purpose[f"{lane}:{purpose}"]
            p["attempts"] += 1
            p["ok" if outcome == "ok" else "failed"] += 1
            p["input_tokens"] += int(input_tokens or 0)
            p["output_tokens"] += int(output_tokens or 0) + int(thinking_tokens or 0)
            self.cost_today[lane] += cost
            if not priced:
                self.unpriced_today[lane] += 1
        if self.sink is not None:
            self.sink.put(dict(p_day=kst_day(), p_lane=lane, p_provider=provider[:40], p_model=(model or "?")[:120],
                               p_purpose=(purpose or "?")[:60], p_ok=outcome == "ok", p_input=int(input_tokens or 0),
                               p_output=int(output_tokens or 0), p_thinking=int(thinking_tokens or 0),
                               p_cost=cost, p_priced=priced))

    def request(self, *, fallback_used: bool) -> None:
        with self._lock:
            self.requests += 1
            if fallback_used:
                self.fallback_activations += 1

    def spend_today(self, lane: str) -> tuple[float, int]:
        """(estimated USD, unpriced attempts) of this process today (KST)."""
        with self._lock:
            self._roll()
            return round(self.cost_today.get(lane, 0.0), 6), self.unpriced_today.get(lane, 0)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            self._roll()
            return dict(since=self.started_at, requests=self.requests, fallback_activations=self.fallback_activations,
                        fallback_rate=round(self.fallback_activations / self.requests, 4) if self.requests else None,
                        attempts=dict(self.calls), errors=dict(self.errors),
                        tokens={m: dict(c) for m, c in self.tokens.items()},
                        by_purpose={k: dict(c) for k, c in sorted(self.by_purpose.items())},
                        estimated_cost_today_usd={k: round(v, 6) for k, v in self.cost_today.items()},
                        unpriced_attempts_today=dict(self.unpriced_today),
                        prices_configured=sorted(self.prices.table), price_errors=self.prices.errors,
                        sink=None if self.sink is None else dict(available=self.sink.available,
                                                                 written=self.sink.written,
                                                                 dropped=self.sink.dropped, failed=self.sink.failed),
                        last_error_at=self.last_error_at, last_error_by_model=dict(self.last_errors),
                        note="In-process counters since the last restart; token counts are as reported by the API; "
                             "costs are estimates from LLM_PRICES, not an invoice.")


def _n(v: int | None) -> str:
    return "-" if v is None else str(v)


usage = UsageRecorder()
