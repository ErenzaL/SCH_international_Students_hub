"""Google Gemini through the official ``google-genai`` SDK, with a primary and a fallback model.

Reliability policy (one request = at most ``max_attempts`` tries on the primary, then at most ``max_attempts`` on
the fallback; never a loop):

* retryable on the same model: 429 (unless the quota is exhausted for the day), 500/502/503/504, timeouts,
  connection errors, empty/malformed responses - with exponential backoff and full jitter, or the server-provided
  ``RetryInfo`` delay when there is one (a requested delay above ``retry_max_delay`` is not waited for; the request
  fails over instead of blocking a student for a minute);
* fail over to the fallback model: the retryable errors above, a daily-quota 429 and an unknown/unavailable model
  (404). The fallback may share the project's quota, so it is tried once and its failure is final;
* never retried and never failed over: invalid requests (400), authentication/permission errors (401/403), blocked
  or safety-stopped content and truncated output - another model would not fix them;
* streaming: once any text has reached the student, nothing is retried (``LLMError.partial``); the caller replaces
  the partial text with a clean message instead of appending a second answer.

The SDK's own retries are disabled so this is the only retry layer. Calls are synchronous: FastAPI runs the
assistant endpoints in its worker thread pool and the SSE stream in its own thread, so a blocking call never
stalls the event loop, and every existing caller (assistant, translation jobs, handoff summaries) keeps the same
interface. Only operational metadata is logged (see ``usage.py``).
"""
from __future__ import annotations

import logging
import random
import re
import threading
import time
from collections.abc import Callable
from typing import Any

from app.services.llm.base import LLMError, LLMResult
from app.services.llm.usage import usage

log = logging.getLogger("app.llm.gemini")

_BLOCKED_FINISH = {"SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "IMAGE_SAFETY",
                   "IMAGE_PROHIBITED_CONTENT", "LANGUAGE"}
_MALFORMED_FINISH = {"MALFORMED_RESPONSE", "MALFORMED_FUNCTION_CALL", "OTHER", "UNEXPECTED_TOOL_CALL"}
_EFFORT_TO_LEVEL = {"low": "low", "medium": "medium", "high": "high", "xhigh": "high", "max": "high",
                    "minimal": "minimal"}
# extra output budget for thinking on top of the visible-answer cap (thinking may count toward max_output_tokens)
_THINKING_HEADROOM = {"": 2048, "minimal": 256, "low": 1024, "medium": 4096, "high": 8192}
INTERACTIVE_MAX_TOKENS = 4096   # calls at or below this size are interactive (short timeout); larger = jobs


class _Failure(Exception):
    """Internal: a classified failure of one attempt."""

    def __init__(self, error: LLMError, *, retry_same: bool, fallback_ok: bool, retry_after: float | None = None,
                 status: str | None = None, http: int | None = None, detail: str | None = None,
                 quota_id: str | None = None):
        super().__init__(error.message)
        self.error = error
        self.retry_same = retry_same
        self.fallback_ok = fallback_ok
        self.retry_after = retry_after
        self.status, self.http, self.detail, self.quota_id = status, http, detail, quota_id


# Circuit breaker: a model that fails PERSISTENTLY (not found, no permission, quota exhausted or zero, project
# precondition) is skipped for a cooldown instead of costing every student request a failed call; three consecutive
# transient failures (5xx, timeouts, rate limits) pause it briefly. A success closes the circuit.
_COOLDOWN_S = {"llm_model": 900, "llm_permission": 900, "llm_precondition": 900, "llm_quota": 1800}
_TRANSIENT_TRIP, _TRANSIENT_COOLDOWN_S = 3, 60


class GeminiProvider:
    name = "gemini"
    enabled = True

    def __init__(self, api_key: str, *, primary: str, fallback: str = "", request_timeout: float = 30.0,
                 job_timeout: float = 120.0, thinking_level: str = "low", temperature: float | None = None,
                 max_attempts: int = 2, retry_base: float = 0.8, retry_max_delay: float = 8.0,
                 deadline: float = 45.0, fast_timeout: float = 12.0,
                 client_factory: Callable[[], Any] | None = None, sleep: Callable[[float], None] = time.sleep,
                 attempt_gate: Callable[[], bool] | None = None):
        self.primary = primary.strip()
        self.fallback = (fallback or "").strip()
        if self.fallback == self.primary:
            self.fallback = ""
        self.model = self.primary
        self.request_timeout = request_timeout
        self.job_timeout = job_timeout
        level = (thinking_level or "").strip().lower()
        if level and level not in ("minimal", "low", "medium", "high"):
            log.warning("ignoring unsupported GEMINI_THINKING_LEVEL %r (using the model default)", thinking_level)
            level = ""
        self.thinking_level = level
        self.temperature = temperature
        self.max_attempts = max(1, min(int(max_attempts), 4))
        self.retry_base = max(0.05, retry_base)
        self.retry_max_delay = max(0.0, retry_max_delay)
        self.deadline = max(1.0, deadline)
        self.fast_timeout = max(1.0, fast_timeout)
        self._api_key = api_key
        self._client: Any = None
        self._client_factory = client_factory
        self._sleep = sleep
        self._circuit: dict[str, dict[str, Any]] = {}
        #: background providers: consulted before EVERY attempt (retries and fallback included); False = stop now
        self.attempt_gate = attempt_gate
        self.lane = "chat"           # chat | background (usage accounting)
        self._circuit_lock = threading.Lock()
        self._clock = time.monotonic

    # ------------------------------------------------------------- circuit breaker
    def _is_open(self, model: str) -> bool:
        with self._circuit_lock:
            c = self._circuit.get(model)
            return bool(c and c.get("until", 0) > self._clock())

    def _record(self, model: str, failure: _Failure | None) -> None:
        with self._circuit_lock:
            c = self._circuit.setdefault(model, {"fails": 0, "until": 0.0, "reason": None})
            if failure is None:
                if c.get("until") or c.get("fails"):
                    log.info("llm_circuit model=%s state=closed", model)
                c.update(fails=0, until=0.0, reason=None)
                return
            code = failure.error.code
            c["fails"] += 1
            cooldown = _COOLDOWN_S.get(code)
            if cooldown is None and c["fails"] >= _TRANSIENT_TRIP and code in ("llm_unavailable", "llm_timeout",
                                                                              "llm_rate_limited"):
                cooldown = _TRANSIENT_COOLDOWN_S
            if cooldown:
                c.update(until=self._clock() + cooldown, reason=code)
                log.warning("llm_circuit model=%s state=open reason=%s status=%s for_s=%d", model, code,
                            failure.status or "-", cooldown)

    def health(self) -> dict[str, Any]:
        """Per-model circuit state for the admin view (no secrets)."""
        now = self._clock()
        with self._circuit_lock:
            return {m: {"open": c.get("until", 0) > now, "reason": c.get("reason"),
                        "retry_in_s": max(0, int(c.get("until", 0) - now)), "consecutive_failures": c.get("fails", 0)}
                    for m, c in self._circuit.items()}

    def probe(self, model: str) -> list[dict[str, Any]]:
        """One tiny non-streaming and one tiny streaming call to ``model`` - no retries, no fallback, no circuit -
        to see exactly how this API key and model behave with the configuration production uses."""
        out = []
        for kind in ("generate", "stream"):
            t0 = time.perf_counter()
            row: dict[str, Any] = {"model": model, "call": kind}
            try:
                cfg = self._config("Reply with the single word OK.", 32, "low")
                client = self._get_client()
                if kind == "generate":
                    resp = client.models.generate_content(model=model, contents="Health check.", config=cfg)
                    text, _f, _b = _read(resp)
                else:
                    text, resp = "", None
                    for chunk in client.models.generate_content_stream(model=model, contents="Health check.",
                                                                       config=cfg):
                        resp = chunk
                        text += _read(chunk)[0]
                um = getattr(resp, "usage_metadata", None)
                row.update(ok=bool(text.strip()), served_by=getattr(resp, "model_version", None) or model,
                           input_tokens=_int(getattr(um, "prompt_token_count", None)),
                           output_tokens=_int(getattr(um, "candidates_token_count", None)),
                           total_tokens=_int(getattr(um, "total_token_count", None)))
                if not text.strip():
                    row.update(error="llm_empty")
            except LLMError as exc:
                row.update(ok=False, error=exc.code, detail=exc.message)
            except Exception as exc:  # noqa: BLE001 - classified, never raw
                f = _classify(exc, model)
                row.update(ok=False, error=f.error.code, http=f.http, status=f.status, detail=f.detail,
                           quota_id=f.quota_id, retry_after_s=f.retry_after)
            row["latency_ms"] = int((time.perf_counter() - t0) * 1000)
            out.append(row)
        return out

    # ------------------------------------------------------------------ client
    def _get_client(self) -> Any:
        if self._client is None:
            if self._client_factory is not None:
                self._client = self._client_factory()
            else:
                from google import genai
                from google.genai import types

                opts = types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1))  # we retry ourselves
                try:   # without a key the SDK reads GEMINI_API_KEY / GOOGLE_API_KEY from the environment
                    self._client = genai.Client(api_key=self._api_key or None, http_options=opts)
                except ValueError as exc:
                    raise LLMError("llm_auth", "The Gemini API key is not configured.") from exc
        return self._client

    def _config(self, system: str, max_tokens: int, effort: str | None, fast: bool = False) -> Any:
        from google.genai import types

        level = _EFFORT_TO_LEVEL.get((effort or "").lower(), self.thinking_level) if effort else self.thinking_level
        timeout = self.request_timeout if max_tokens <= INTERACTIVE_MAX_TOKENS else self.job_timeout
        if fast:
            timeout = min(timeout, self.fast_timeout)
        kwargs: dict[str, Any] = dict(
            system_instruction=system,
            max_output_tokens=max_tokens + _THINKING_HEADROOM.get(level, 2048),
            http_options=types.HttpOptions(timeout=int(timeout * 1000)),
        )
        if level:
            kwargs["thinking_config"] = types.ThinkingConfig(thinking_level=level)
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        return types.GenerateContentConfig(**kwargs)

    # ------------------------------------------------------------------ public
    def complete(self, system: str, prompt: str, *, max_tokens: int = 16000, effort: str | None = None,
                 purpose: str = "complete", fast: bool = False, **_: Any) -> LLMResult:
        """``fast``: a quick auxiliary call (query rewriting) - one attempt on the fast (fallback, Flash-Lite) model,
        then one on the other model only if the first is unavailable; short timeout."""
        def one(model: str, state: dict[str, Any]) -> LLMResult:
            resp = self._get_client().models.generate_content(model=model, contents=prompt,
                                                              config=self._config(system, max_tokens, effort, fast))
            text, finish, blocked = _read(resp)
            _check(text, finish, blocked, partial=False)
            return self._result(text, model, resp, state)

        return self._run(one, purpose=purpose, fast=fast, interactive=max_tokens <= INTERACTIVE_MAX_TOKENS)

    def stream(self, system: str, prompt: str, on_text: Any, *, max_tokens: int = 4096,
               effort: str | None = None, purpose: str = "stream", **_: Any) -> LLMResult:
        def one(model: str, state: dict[str, Any]) -> LLMResult:
            parts: list[str] = []
            last: Any = None
            finish = blocked = None
            for chunk in self._get_client().models.generate_content_stream(
                    model=model, contents=prompt, config=self._config(system, max_tokens, effort)):
                last = chunk
                piece, f, b = _read(chunk)
                finish, blocked = f or finish, b or blocked
                if piece:
                    parts.append(piece)
                    state["delivered"] = True
                    on_text(piece)
            text = "".join(parts).strip()
            _check(text, finish, blocked, partial=bool(state.get("delivered")))
            return self._result(text, model, last, state)

        return self._run(one, purpose=purpose, interactive=True)

    # ------------------------------------------------------------------ policy
    def _run(self, one: Callable[[str, dict[str, Any]], LLMResult], *, purpose: str, fast: bool = False,
             interactive: bool = True) -> LLMResult:
        if fast:
            chain = ([("fallback", self.fallback)] if self.fallback else []) + [("primary", self.primary)]
            attempts_per_model = 1
        else:
            chain = [("primary", self.primary)] + ([("fallback", self.fallback)] if self.fallback else [])
            attempts_per_model = self.max_attempts
        live = [(r, m) for r, m in chain if not self._is_open(m)]
        if len(live) < len(chain):
            skipped = [m for _r, m in chain if (_r, m) not in live]
            if not live:       # everything is paused: still try the model that recovers first (half-open probe)
                with self._circuit_lock:
                    live = [min(chain, key=lambda rm: self._circuit.get(rm[1], {}).get("until", 0))]
            log.info("llm_circuit skip=%s using=%s purpose=%s", ",".join(skipped), ",".join(m for _r, m in live), purpose)
        chain = live
        state: dict[str, Any] = {"delivered": False, "attempts": 0}
        started = time.perf_counter()
        last: _Failure | None = None
        for role, model in chain:
            for attempt in range(1, attempts_per_model + 1):
                if interactive and state["attempts"] and time.perf_counter() - started >= self.deadline:
                    break         # the request already took too long: stop here instead of holding the worker
                if self.attempt_gate is not None and not self.attempt_gate():
                    raise LLMError("llm_background_budget", "Today's AI budget for background work is used up; the "
                                   "chatbot's share of the model quota is reserved.")
                state["attempts"] += 1
                state["role"] = role
                t0 = time.perf_counter()
                try:
                    res = one(model, state)
                except LLMError as exc:          # raised by _check / client creation
                    failure = _Failure(exc, retry_same=exc.code in ("llm_empty", "llm_malformed"),
                                       fallback_ok=exc.code in ("llm_empty", "llm_malformed"))
                except Exception as exc:  # noqa: BLE001 - classified below, never leaked raw
                    failure = _classify(exc, model)
                else:
                    res.latency_ms = int((time.perf_counter() - started) * 1000)
                    res.fallback_used = res.model_role == "fallback" and not fast
                    usage.attempt(lane=self.lane, provider=self.name, model=res.model, role=role, purpose=purpose, attempt=attempt,
                                  outcome="ok", latency_ms=int((time.perf_counter() - t0) * 1000),
                                  input_tokens=res.input_tokens, output_tokens=res.output_tokens,
                                  thinking_tokens=res.thinking_tokens, total_tokens=res.total_tokens)
                    usage.request(fallback_used=res.fallback_used)
                    self._record(model, None)
                    return res
                if state["delivered"]:          # text already reached the student: never retry or fail over
                    failure.error.partial = True
                    failure.retry_same = failure.fallback_ok = False
                delay = self._delay(attempt, failure) if failure.retry_same and attempt < attempts_per_model else None
                if delay is not None and interactive:
                    remaining = self.deadline - (time.perf_counter() - started)
                    delay = delay if delay < remaining else None
                usage.attempt(lane=self.lane, provider=self.name, model=model, role=role, purpose=purpose, attempt=attempt,
                              outcome="error", latency_ms=int((time.perf_counter() - t0) * 1000),
                              error_code=failure.error.code, retry_in_s=delay, http=failure.http,
                              status=failure.status, detail=failure.detail, quota_id=failure.quota_id)
                if not failure.error.partial:
                    self._record(model, failure)
                last = failure
                if delay is None:
                    break
                self._sleep(delay)
            if last is None or not last.fallback_ok:
                break
        usage.request(fallback_used=state.get("role") == "fallback" and not fast)
        assert last is not None
        raise last.error

    def _delay(self, attempt: int, failure: _Failure) -> float | None:
        if failure.retry_after is not None:
            if failure.retry_after > self.retry_max_delay:
                return None          # the server wants us to wait longer than a student should: fail over
            return failure.retry_after + random.uniform(0, self.retry_base / 4)
        cap = min(self.retry_max_delay, self.retry_base * (2 ** (attempt - 1)))
        return random.uniform(cap / 2, cap)   # "equal jitter": never zero, never above the cap

    def _result(self, text: str, model: str, resp: Any, state: dict[str, Any]) -> LLMResult:
        um = getattr(resp, "usage_metadata", None)
        role = state.get("role", "primary")
        return LLMResult(
            text=text, provider=self.name, model=getattr(resp, "model_version", None) or model,
            input_tokens=_int(getattr(um, "prompt_token_count", None)) or 0,
            output_tokens=_int(getattr(um, "candidates_token_count", None)) or 0,
            thinking_tokens=_int(getattr(um, "thoughts_token_count", None)),
            total_tokens=_int(getattr(um, "total_token_count", None)),
            attempts=state["attempts"], model_role=role, fallback_used=role == "fallback")


# --------------------------------------------------------------------- helpers
def _int(v: Any) -> int | None:
    return int(v) if isinstance(v, (int, float)) else None


def _read(resp: Any) -> tuple[str, str | None, str | None]:
    """(visible text without thought parts, finish reason, prompt block reason) of a response or stream chunk."""
    blocked = None
    pf = getattr(resp, "prompt_feedback", None)
    if pf is not None and getattr(pf, "block_reason", None):
        blocked = _enum_name(pf.block_reason)
    cands = getattr(resp, "candidates", None) or []
    if not cands:
        return "", None, blocked
    c = cands[0]
    finish = _enum_name(getattr(c, "finish_reason", None))
    parts = getattr(getattr(c, "content", None), "parts", None) or []
    text = "".join(p.text for p in parts if getattr(p, "text", None) and not getattr(p, "thought", False))
    return text, finish, blocked


def _enum_name(v: Any) -> str | None:
    if v is None:
        return None
    name = getattr(v, "name", None) or str(v)
    name = name.split(".")[-1]
    return None if name in ("FINISH_REASON_UNSPECIFIED", "BLOCKED_REASON_UNSPECIFIED", "STOP") else name


def _check(text: str, finish: str | None, blocked: str | None, *, partial: bool) -> None:
    if blocked:
        raise LLMError("llm_refused", "The request was blocked by the model's safety filters.", partial=partial)
    if finish in _BLOCKED_FINISH:
        raise LLMError("llm_refused", f"Generation stopped by the model ({finish}).", partial=partial)
    if finish == "MAX_TOKENS":
        raise LLMError("llm_truncated", "The generated text was cut off (output limit reached).", partial=partial)
    if finish in _MALFORMED_FINISH and not text:
        raise LLMError("llm_malformed", f"The model returned a malformed response ({finish}).", transient=True,
                       partial=partial)
    if not text:
        raise LLMError("llm_empty", "The model returned no text.", transient=True, partial=partial)


def _retry_after(exc: Any) -> float | None:
    """Server-provided retry delay: google.rpc.RetryInfo in the error details, else a Retry-After header."""
    details = getattr(exc, "details", None)
    items: list[Any] = []
    if isinstance(details, dict):
        err = details.get("error", details)
        items = err.get("details") or [] if isinstance(err, dict) else []
    for it in items:
        if isinstance(it, dict) and str(it.get("@type", "")).endswith("RetryInfo"):
            m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)s\s*", str(it.get("retryDelay", "")))
            if m:
                return float(m.group(1))
    headers = getattr(getattr(exc, "response", None), "headers", None)
    try:
        ra = headers.get("retry-after") if headers is not None else None
        return float(ra) if ra else None
    except (TypeError, ValueError):
        return None


def _daily_quota(exc: Any) -> bool:
    """A 429 for an exhausted per-day quota - or a quota of 0 (the model is not included in this project's tier):
    retrying the same model now is pointless."""
    text = f"{getattr(exc, 'details', '')} {getattr(exc, 'message', '')}"
    return bool(re.search(r"per ?day|PerDay|daily|limit:\s*0\b", text))


_SECRETISH = re.compile(r"AIza[0-9A-Za-z_\-]{10,}|(key|token)=[^&\s]+|Bearer\s+\S+", re.I)


def _safe_detail(exc: Any) -> str | None:
    """Google's error message, shortened, with anything key-like removed (safe for logs and the admin view)."""
    msg = str(getattr(exc, "message", "") or "")
    return _SECRETISH.sub("[redacted]", re.sub(r"\s+", " ", msg))[:240] or None


def _quota_id(exc: Any) -> str | None:
    m = re.search(r"'quotaId':\s*'([^']+)'|\"quotaId\":\s*\"([^\"]+)\"", str(getattr(exc, "details", "")))
    return (m.group(1) or m.group(2)) if m else None


def _classify(exc: Exception, model: str) -> _Failure:
    try:
        from google.genai import errors as gerr
    except ImportError:  # pragma: no cover - the SDK is a hard dependency of this provider
        gerr = None  # type: ignore[assignment]

    if gerr is not None and isinstance(exc, gerr.APIError):
        f = _classify_api(exc, model)
        f.http, f.status = int(getattr(exc, "code", 0) or 0) or None, str(getattr(exc, "status", "") or "") or None
        f.detail, f.quota_id = _safe_detail(exc), _quota_id(exc)
        return f
    return _classify_other(exc)


def _classify_api(exc: Any, model: str) -> _Failure:
    code = int(getattr(exc, "code", 0) or 0)
    status = str(getattr(exc, "status", "") or "")
    if code == 429:
        daily = _daily_quota(exc)
        return _Failure(LLMError("llm_quota" if daily else "llm_rate_limited",
                                 "The Gemini API quota is exhausted." if daily
                                 else "Gemini is rate limiting requests.", transient=True),
                        retry_same=not daily, fallback_ok=True, retry_after=None if daily else _retry_after(exc))
    if code in (401, 403) or status in ("UNAUTHENTICATED", "PERMISSION_DENIED") \
            or re.search(r"API_KEY_INVALID|API key not valid", str(getattr(exc, "details", ""))):
        return _Failure(LLMError("llm_permission" if code == 403 else "llm_auth",
                                 "The Gemini API key is missing, invalid or not permitted."),
                        retry_same=False, fallback_ok=False)
    if code == 404 or status == "NOT_FOUND":
        return _Failure(LLMError("llm_model", f"Gemini model '{model}' is not available to this project."),
                        retry_same=False, fallback_ok=True)
    if code in (500, 502, 503, 504, 499) or status in ("INTERNAL", "UNAVAILABLE", "DEADLINE_EXCEEDED"):
        return _Failure(LLMError("llm_unavailable", f"Gemini is temporarily unavailable ({code}).", transient=True),
                        retry_same=True, fallback_ok=True, retry_after=_retry_after(exc))
    if code == 400 and status == "FAILED_PRECONDITION":
        return _Failure(LLMError("llm_precondition", "Gemini cannot serve this project right now "
                                                     "(billing, region or project setup)."),
                        retry_same=False, fallback_ok=False)
    if 400 <= code < 500:
        return _Failure(LLMError("llm_bad_request", f"Gemini rejected the request ({code} {status})."),
                        retry_same=False, fallback_ok=False)
    return _Failure(LLMError("llm_error", f"Gemini error ({code}).", transient=True),
                    retry_same=False, fallback_ok=True)


def _classify_other(exc: Exception) -> _Failure:
    import httpx

    if isinstance(exc, (httpx.TimeoutException, TimeoutError)):
        return _Failure(LLMError("llm_timeout", "Gemini did not answer in time.", transient=True),
                        retry_same=True, fallback_ok=True)
    if isinstance(exc, (httpx.TransportError, ConnectionError)):
        return _Failure(LLMError("llm_unavailable", "Could not reach Gemini.", transient=True),
                        retry_same=True, fallback_ok=True)
    if isinstance(exc, (ValueError, KeyError, AttributeError, TypeError)):   # unexpected response shape
        log.warning("unexpected Gemini response shape: %s", type(exc).__name__)
        return _Failure(LLMError("llm_malformed", "Gemini returned an unexpected response.", transient=True),
                        retry_same=False, fallback_ok=True)
    log.warning("unclassified Gemini failure: %s", type(exc).__name__)
    return _Failure(LLMError("llm_error", "Gemini request failed.", transient=True), retry_same=False, fallback_ok=True)
