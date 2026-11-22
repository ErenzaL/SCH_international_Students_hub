"""LLM usage accounting: one structured log line per model attempt plus in-process aggregates for the admin view.

Only operational metadata is recorded (provider, model, role, outcome, error code, token counts reported by the
API, latency). Prompts, answers, student messages and keys are never logged. Token counts are only what the
provider reports; nothing is estimated and no cost is computed unless prices are configured explicitly.
Aggregates live in memory (one instance, reset on restart) and are kept separate from student conversations.
"""
from __future__ import annotations

import logging
import threading
from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import Any

log = logging.getLogger("app.llm.usage")


class UsageRecorder:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        with getattr(self, "_lock", threading.Lock()):
            self.started_at = datetime.now(UTC).isoformat()
            self.calls: Counter[str] = Counter()            # by "provider:model:role:outcome"
            self.errors: Counter[str] = Counter()           # by error code
            self.tokens: dict[str, Counter[str]] = defaultdict(Counter)   # model -> input/output/thinking/total
            self.fallback_activations = 0
            self.requests = 0
            self.latency_ms_total = 0
            self.last_error_at: str | None = None

    def attempt(self, *, provider: str, model: str, role: str, purpose: str, attempt: int, outcome: str,
                latency_ms: int, error_code: str | None = None, input_tokens: int | None = None,
                output_tokens: int | None = None, thinking_tokens: int | None = None,
                total_tokens: int | None = None, retry_in_s: float | None = None) -> None:
        log.info("llm_attempt provider=%s model=%s role=%s purpose=%s attempt=%d outcome=%s error=%s latency_ms=%d "
                 "input_tokens=%s output_tokens=%s thinking_tokens=%s total_tokens=%s retry_in_s=%s",
                 provider, model, role, purpose, attempt, outcome, error_code or "-", latency_ms,
                 _n(input_tokens), _n(output_tokens), _n(thinking_tokens), _n(total_tokens),
                 f"{retry_in_s:.2f}" if retry_in_s is not None else "-")
        with self._lock:
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

    def request(self, *, fallback_used: bool) -> None:
        with self._lock:
            self.requests += 1
            if fallback_used:
                self.fallback_activations += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(since=self.started_at, requests=self.requests, fallback_activations=self.fallback_activations,
                        fallback_rate=round(self.fallback_activations / self.requests, 4) if self.requests else None,
                        attempts=dict(self.calls), errors=dict(self.errors),
                        tokens={m: dict(c) for m, c in self.tokens.items()}, last_error_at=self.last_error_at,
                        note="In-process counters since the last restart; token counts are as reported by the API.")


def _n(v: int | None) -> str:
    return "-" if v is None else str(v)


usage = UsageRecorder()
