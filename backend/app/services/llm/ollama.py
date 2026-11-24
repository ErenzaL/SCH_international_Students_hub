"""Local models through Ollama's HTTP API (``LLM_PROVIDER=ollama`` and / or ``BACKGROUND_LLM_PROVIDER=ollama``).

Two interfaces over one implementation:

* async: ``await acomplete(...)`` / ``await astream(...)`` - usable from any event loop;
* sync: ``complete(...)`` / ``stream(...)`` - the ``LLMProvider`` interface every existing service uses (they run in
  worker threads). Never call the sync methods from a coroutine: they block.

All HTTP happens on one private event-loop thread per provider, so the concurrency limit covers every caller (chat,
translation jobs, agent tasks): there is only one GPU. The thread starts on first use.

Policy:

* loopback only: a base URL that is not this machine is refused at construction. Redirects and proxy environment
  variables are ignored, so a prompt cannot leave the host. There is no fallback to a cloud provider;
* Ollama silently drops the beginning of a prompt that does not fit ``num_ctx``. For grounded answers that would
  remove rules or sources without anyone noticing, so ``truncate`` is off and an oversized request is ``llm_context``;
* every attempt has a total time limit; waiting for a free slot is limited separately (``llm_rate_limited``);
* retried (bounded, with jitter): connection errors, timeouts, 429/5xx, empty or malformed responses. Never retried:
  400, unknown model, truncated output, oversized prompt, or anything after streamed text reached the caller;
* only metadata is logged (``usage.py``): never prompts, answers or Ollama's own error text.
"""
from __future__ import annotations

import asyncio
import inspect
import ipaddress
import json
import logging
import queue
import random
import threading
import time
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.services.llm.base import LLMError, LLMResult
from app.services.llm.usage import usage

log = logging.getLogger("app.llm.ollama")

INTERACTIVE_MAX_TOKENS = 4096   # calls at or below this size are interactive (short timeout); larger = jobs
_RETRYABLE = {"llm_unavailable", "llm_timeout", "llm_rate_limited", "llm_empty", "llm_malformed"}
_PROMPT_RESERVE = 4096          # tokens kept free for instructions and output when a source text is cut to fit


class _QueueTimeout(LLMError):
    """No free slot in time. Not retried: the caller already waited."""


def check_base_url(url: str) -> str:
    """The normalized base URL. Only plain loopback addresses are accepted."""
    url = (url or "").strip().rstrip("/")
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        _ = parts.port
    except ValueError:
        raise ValueError("OLLAMA_BASE_URL is not a valid URL.") from None
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = host == "localhost"
    if parts.scheme != "http" or not loopback or parts.username or parts.path or parts.query or parts.fragment:
        raise ValueError("OLLAMA_BASE_URL must be a loopback address such as http://127.0.0.1:11434 "
                         "(Ollama has no authentication and must not be used over the network).")
    return url


class OllamaProvider:
    name = "ollama"
    enabled = True

    def __init__(self, model: str, *, base_url: str = "http://127.0.0.1:11434", num_ctx: int = 16384,
                 max_output_tokens: int = 8192, temperature: float = 0.2, keep_alive: str = "10m",
                 connect_timeout: float = 3.0, request_timeout: float = 90.0, job_timeout: float = 180.0,
                 fast_timeout: float = 30.0, queue_timeout: float = 30.0, job_queue_timeout: float = 300.0,
                 max_concurrency: int = 1, max_attempts: int = 2, retry_base: float = 0.8,
                 retry_max_delay: float = 8.0, deadline: float = 120.0,
                 transport: httpx.AsyncBaseTransport | None = None,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep):
        self.base_url = check_base_url(base_url)
        self.model = self.primary = model.strip()
        self.fallback = ""
        #: the assistant repeats its answer format after the question (small models forget it otherwise)
        self.needs_format_reminder = True
        self.num_ctx = max(2048, int(num_ctx))
        self.max_output_tokens = max(256, min(int(max_output_tokens), self.num_ctx // 2))
        self.temperature = temperature
        self.keep_alive = keep_alive
        self.connect_timeout = connect_timeout
        self.request_timeout = request_timeout
        self.job_timeout = job_timeout
        self.fast_timeout = fast_timeout
        self.queue_timeout = queue_timeout
        self.job_queue_timeout = job_queue_timeout
        self.max_concurrency = max(1, int(max_concurrency))
        self.max_attempts = max(1, min(int(max_attempts), 4))
        self.retry_base = max(0.05, retry_base)
        self.retry_max_delay = max(0.0, retry_max_delay)
        self.deadline = max(1.0, deadline)
        #: long texts are cut to this many characters before they are summarized (about 1 token per Korean character)
        self.max_source_chars = max(1024, self.num_ctx - _PROMPT_RESERVE)
        self._transport = transport
        self._sleep = sleep
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._client: httpx.AsyncClient | None = None      # created and used on the private loop only
        self._slots: asyncio.Semaphore | None = None

    # ------------------------------------------------------------- private loop
    def _submit(self, coro: Coroutine[Any, Any, Any]) -> Any:
        with self._lock:
            if self._loop is None:
                self._loop = asyncio.new_event_loop()
                self._thread = threading.Thread(target=self._loop.run_forever, name="ollama-client", daemon=True)
                self._thread.start()
                self._slots = asyncio.Semaphore(self.max_concurrency)
            return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def close(self) -> None:
        """Cancel open requests and stop the loop thread. The provider starts again when it is used again."""
        with self._lock:
            loop, thread, client = self._loop, self._thread, self._client
            self._loop = self._thread = self._client = self._slots = None
        if loop is None or thread is None:
            return

        async def shutdown() -> None:
            tasks = [x for x in asyncio.all_tasks() if x is not asyncio.current_task()]
            for x in tasks:
                x.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if client is not None:
                await client.aclose()

        try:
            asyncio.run_coroutine_threadsafe(shutdown(), loop).result(timeout=5)
        except Exception:  # noqa: BLE001 - shutting down anyway
            log.warning("the Ollama client did not shut down cleanly")
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=5)

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url, transport=self._transport, trust_env=False, follow_redirects=False,
                # the total time of an attempt is bounded by asyncio.timeout in _attempt()
                timeout=httpx.Timeout(None, connect=self.connect_timeout))
        return self._client

    # ------------------------------------------------------------------- public: async
    async def acomplete(self, system: str, prompt: str, *, max_tokens: int = 16000, effort: str | None = None,
                        purpose: str = "complete", fast: bool = False, **_: Any) -> LLMResult:
        fut = self._submit(self._run(system, prompt, None, max_tokens=max_tokens, purpose=purpose, fast=fast))
        return await asyncio.wrap_future(fut)

    async def astream(self, system: str, prompt: str, on_text: Callable[[str], Any], *, max_tokens: int = 4096,
                      effort: str | None = None, purpose: str = "stream", **_: Any) -> LLMResult:
        """``on_text`` (a function or coroutine function) is called on the caller's event loop."""
        here = asyncio.get_running_loop()
        q: asyncio.Queue[str | None] = asyncio.Queue()
        fut = self._submit(self._run(system, prompt, lambda s: here.call_soon_threadsafe(q.put_nowait, s),
                                     max_tokens=max_tokens, purpose=purpose, stream=True))
        fut.add_done_callback(lambda _f: None if here.is_closed() else here.call_soon_threadsafe(q.put_nowait, None))
        try:
            while (piece := await q.get()) is not None:
                r = on_text(piece)
                if inspect.isawaitable(r):
                    await r
            return await asyncio.wrap_future(fut)
        finally:
            fut.cancel()          # no effect when finished; stops the generation when the caller went away

    # -------------------------------------------------------------------- public: sync
    def complete(self, system: str, prompt: str, *, max_tokens: int = 16000, effort: str | None = None,
                 purpose: str = "complete", fast: bool = False, **_: Any) -> LLMResult:
        return self._result(self._submit(
            self._run(system, prompt, None, max_tokens=max_tokens, purpose=purpose, fast=fast)))

    def stream(self, system: str, prompt: str, on_text: Any, *, max_tokens: int = 4096, effort: str | None = None,
               purpose: str = "stream", **_: Any) -> LLMResult:
        """``on_text`` runs in the calling thread (a slow consumer never blocks other requests)."""
        q: queue.Queue[str | None] = queue.Queue()
        fut = self._submit(self._run(system, prompt, q.put, max_tokens=max_tokens, purpose=purpose, stream=True))
        fut.add_done_callback(lambda _f: q.put(None))
        try:
            while (piece := q.get()) is not None:
                on_text(piece)
            return self._result(fut)
        finally:
            fut.cancel()

    @staticmethod
    def _result(fut: Any) -> LLMResult:
        from concurrent.futures import CancelledError

        try:
            return fut.result()
        except CancelledError as exc:
            raise LLMError("llm_unavailable", "The local model client was shut down.", transient=True) from exc

    # ----------------------------------------------------------------- admin
    def health(self) -> dict[str, Any]:
        return {}                  # no circuit breaker: a stopped Ollama refuses connections immediately

    def probe(self, model: str) -> list[dict[str, Any]]:
        """One tiny non-streaming and one tiny streaming call (synthetic prompt, no retries), as for Gemini."""
        out = []
        for kind in ("generate", "stream"):
            t0 = time.perf_counter()
            row: dict[str, Any] = {"model": model, "call": kind}
            try:
                r = self._result(self._submit(self._run(
                    "Reply with the single word OK.", "Health check.", (lambda _s: None) if kind == "stream" else None,
                    max_tokens=32, purpose="probe", stream=kind == "stream", model=model, attempts=1)))
                row.update(ok=True, served_by=r.model, input_tokens=r.input_tokens, output_tokens=r.output_tokens,
                           total_tokens=r.total_tokens)
            except LLMError as exc:
                row.update(ok=False, error=exc.code, detail=exc.message)
            row["latency_ms"] = int((time.perf_counter() - t0) * 1000)
            out.append(row)
        return out

    def installed_models(self) -> list[str]:
        """Names of the models installed on this machine (raises LLMError when Ollama is not reachable)."""
        async def get() -> list[str]:
            try:
                async with asyncio.timeout(self.connect_timeout + 5):
                    resp = await self._http().get("/api/tags")
                    resp.raise_for_status()
                    return [str(m["name"]) for m in resp.json()["models"]]
            except Exception as exc:  # noqa: BLE001 - classified, never raw
                raise _classify(exc, self.model) from exc

        return self._submit(get()).result()

    # ---------------------------------------------------------------- policy
    async def _run(self, system: str, prompt: str, sink: Callable[[str], Any] | None, *, max_tokens: int,
                   purpose: str, fast: bool = False, stream: bool = False, model: str | None = None,
                   attempts: int | None = None) -> LLMResult:
        model = model or self.model
        interactive = stream or max_tokens <= INTERACTIVE_MAX_TOKENS
        limit = self.request_timeout if interactive else self.job_timeout
        if fast:
            limit, attempts = min(limit, self.fast_timeout), 1
        attempts = attempts or self.max_attempts
        payload: dict[str, Any] = dict(
            model=model, stream=stream, keep_alive=self.keep_alive, truncate=False, shift=False,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            options=dict(num_ctx=self.num_ctx, num_predict=min(max_tokens, self.max_output_tokens),
                         temperature=self.temperature))
        if purpose == "rewrite":
            payload["format"] = "json"       # the query rewrite asks for one JSON object
        started = time.perf_counter()
        delivered = False

        def deliver(piece: str) -> None:
            nonlocal delivered
            delivered = True
            if sink is not None:
                sink(piece)

        for attempt in range(1, attempts + 1):
            t0 = time.perf_counter()
            timing: dict[str, float] = {}
            try:
                res = await self._attempt(payload, deliver, limit, interactive, timing)
            except LLMError as exc:
                exc.partial = delivered
                delay = None
                if exc.code in _RETRYABLE and not isinstance(exc, _QueueTimeout) and not delivered \
                        and attempt < attempts:
                    cap = min(self.retry_max_delay, self.retry_base * 2 ** (attempt - 1))
                    delay = random.uniform(cap / 2, cap)
                    if interactive and time.perf_counter() - started + delay >= self.deadline:
                        delay = None
                usage.attempt(provider=self.name, model=model, role="primary", purpose=purpose, attempt=attempt,
                              outcome="error", latency_ms=_ms(t0), error_code=exc.code, retry_in_s=delay,
                              http=getattr(exc, "http", None), detail=_detail(timing))
                if delay is None:
                    usage.request(fallback_used=False)
                    raise
                await self._sleep(delay)
                continue
            res.attempts = attempt
            res.latency_ms = _ms(started)
            usage.attempt(provider=self.name, model=res.model, role="primary", purpose=purpose, attempt=attempt,
                          outcome="ok", latency_ms=_ms(t0), input_tokens=res.input_tokens,
                          output_tokens=res.output_tokens, total_tokens=res.total_tokens, detail=_detail(timing))
            usage.request(fallback_used=False)
            return res
        raise AssertionError("unreachable")  # pragma: no cover

    async def _attempt(self, payload: dict[str, Any], deliver: Callable[[str], None], limit: float,
                       interactive: bool, timing: dict[str, float]) -> LLMResult:
        slots = self._slots
        assert slots is not None
        t0 = time.perf_counter()
        try:
            await asyncio.wait_for(slots.acquire(), self.queue_timeout if interactive else self.job_queue_timeout)
        except TimeoutError:
            raise _QueueTimeout("llm_rate_limited", "The local model is busy with other requests.",
                                transient=True) from None
        finally:
            timing["queue_ms"] = (time.perf_counter() - t0) * 1000
        try:
            async with asyncio.timeout(limit):
                return await self._call(payload, deliver, timing)
        except LLMError:
            raise
        except Exception as exc:  # noqa: BLE001 - classified, never leaked raw
            raise _classify(exc, payload["model"]) from exc
        finally:
            slots.release()

    async def _call(self, payload: dict[str, Any], deliver: Callable[[str], None],
                    timing: dict[str, float]) -> LLMResult:
        parts: list[str] = []
        final: dict[str, Any] | None = None
        async with self._http().stream("POST", "/api/chat", json=payload) as resp:
            if resp.status_code != 200:
                raise _status_error(resp.status_code, await resp.aread(), payload["model"])
            if payload["stream"]:
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    obj = json.loads(line)
                    if "error" in obj:      # Ollama reports failures during a stream as a line
                        raise _status_error(500, line.encode(), payload["model"])
                    piece = (obj.get("message") or {}).get("content") or ""
                    if piece:
                        parts.append(piece)
                        deliver(piece)
                    if obj.get("done"):
                        final = obj
                        break
            else:
                final = json.loads(await resp.aread())
                parts.append(final["message"]["content"])
        if final is None or not final.get("done", False):
            raise LLMError("llm_malformed", "The local model's response ended early.", transient=True)
        timing["load_ms"] = (final.get("load_duration") or 0) / 1e6
        if final.get("eval_duration"):
            timing["tokens_per_s"] = (final.get("eval_count") or 0) / (final["eval_duration"] / 1e9)
        if final.get("done_reason") == "length":
            raise LLMError("llm_truncated", "The generated text was cut off (output limit reached).")
        text = "".join(parts).strip()
        if not text:
            raise LLMError("llm_empty", "The model returned no text.", transient=True)
        tin, tout = int(final.get("prompt_eval_count") or 0), int(final.get("eval_count") or 0)
        return LLMResult(text=text, provider=self.name, model=str(final.get("model") or payload["model"]),
                         input_tokens=tin, output_tokens=tout, total_tokens=tin + tout)


def _ms(since: float) -> int:
    return int((time.perf_counter() - since) * 1000)


def _detail(timing: dict[str, float]) -> str | None:
    """Numbers only (never text from a request or response)."""
    return " ".join(f"{k}={v:.0f}" for k, v in timing.items()) or None


def _status_error(status: int, body: bytes, model: str) -> LLMError:
    """Ollama's text is only used to recognize the kind of error; it is never repeated."""
    text = body[:2000].decode("utf-8", "replace").lower()
    if "exceed_context_size" in text or "exceeds the available context" in text or "context length" in text:
        err = LLMError("llm_context", "The text is too long for the local model's context window.")
    elif status == 404:
        err = LLMError("llm_model", f"The model '{model}' is not installed in Ollama.")
    elif status in (429, 503):
        err = LLMError("llm_rate_limited", "The local model is busy.", transient=True)
    elif status >= 500:
        err = LLMError("llm_unavailable", f"The local model failed ({status}).", transient=True)
    elif 400 <= status < 500:
        err = LLMError("llm_bad_request", f"Ollama rejected the request ({status}).")
    else:
        err = LLMError("llm_error", f"Unexpected response from Ollama ({status}).")
    err.http = status  # type: ignore[attr-defined]
    return err


def _classify(exc: Exception, model: str) -> LLMError:
    if isinstance(exc, httpx.HTTPStatusError):
        return _status_error(exc.response.status_code, b"", model)
    if isinstance(exc, (httpx.ConnectTimeout, httpx.ConnectError)):
        return LLMError("llm_unavailable", "Could not reach Ollama on this machine.", transient=True)
    if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
        return LLMError("llm_timeout", "The local model did not answer in time.", transient=True)
    if isinstance(exc, (httpx.TransportError, ConnectionError)):
        return LLMError("llm_unavailable", "The connection to Ollama was interrupted.", transient=True)
    if isinstance(exc, (ValueError, KeyError, AttributeError, TypeError)):
        return LLMError("llm_malformed", "Ollama returned an unexpected response.", transient=True)
    log.warning("unclassified Ollama failure: %s", type(exc).__name__)
    return LLMError("llm_error", "The local model request failed.", transient=True)
