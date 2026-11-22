"""Configurable LLM provider (answer generation and translation drafts).

* ``none`` (default): nothing is generated; the site, retrieval and the assistant's evidence-only replies keep working.
* ``anthropic``: Claude via the official ``anthropic`` SDK (``LLM_MODEL``, default ``claude-opus-5-5``).
Every provider exposes one primitive, ``complete(system, prompt)``; the prompts live in the services that use it
(``services/assistant/engine.py``, ``services/translation_drafts.py``) so a provider never decides what is said.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

log = logging.getLogger(__name__)


class LLMError(Exception):
    """A generation failed. ``transient`` errors (rate limits, overload, network) may be retried by jobs.

    ``partial`` is set when a stream failed after text was already delivered to the caller (nothing may be retried
    then, or the student would see duplicated output)."""

    def __init__(self, code: str, message: str, *, transient: bool = False, partial: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.transient = transient
        self.partial = partial


@dataclass
class LLMResult:
    text: str
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    # optional operational metadata (filled by providers that report it; never estimated)
    thinking_tokens: int | None = None
    total_tokens: int | None = None
    latency_ms: int | None = None
    attempts: int = 1
    model_role: str = "primary"      # primary | fallback
    fallback_used: bool = False


class LLMProvider(Protocol):
    name: str
    model: str
    enabled: bool

    def complete(self, system: str, prompt: str, *, max_tokens: int = 16000, effort: str | None = None,
                 **_: Any) -> LLMResult: ...

    def stream(self, system: str, prompt: str, on_text: Any, *, max_tokens: int = 4096,
               effort: str | None = None, **_: Any) -> LLMResult: ...


class NullLLMProvider:
    name = "none"
    model = ""
    enabled = False

    def complete(self, system: str, prompt: str, *, max_tokens: int = 16000, effort: str | None = None,
                 **_: Any) -> LLMResult:
        raise LLMError("llm_disabled", "No LLM provider is configured (LLM_PROVIDER=none).")

    def stream(self, system: str, prompt: str, on_text: Any, *, max_tokens: int = 4096,
               effort: str | None = None, **_: Any) -> LLMResult:
        raise LLMError("llm_disabled", "No LLM provider is configured (LLM_PROVIDER=none).")


class AnthropicProvider:
    """Claude through the official SDK. The client is created lazily so importing the app stays cheap."""

    name = "anthropic"
    enabled = True

    def __init__(self, api_key: str, model: str, effort: str, timeout: float):
        self.model = model
        self.effort = effort
        self._api_key = api_key
        self._timeout = timeout
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            import anthropic

            kwargs: dict[str, Any] = {"timeout": self._timeout, "max_retries": 2}
            if self._api_key:   # otherwise the SDK resolves ANTHROPIC_API_KEY / profiles from the environment
                kwargs["api_key"] = self._api_key
            self._client = anthropic.Anthropic(**kwargs)
        return self._client

    def _kwargs(self, system: str, prompt: str, max_tokens: int, effort: str | None) -> dict[str, Any]:
        return dict(model=self.model, max_tokens=max_tokens, system=system,
                    messages=[{"role": "user", "content": prompt}], output_config={"effort": effort or self.effort},
                    # on a policy decline the API re-runs the request on a fallback model inside the same call
                    betas=["server-side-fallback-2026-07-01"], fallbacks="default")

    def complete(self, system: str, prompt: str, *, max_tokens: int = 16000, effort: str | None = None,
                 **_: Any) -> LLMResult:
        return self._call(lambda c: c.beta.messages.create(**self._kwargs(system, prompt, max_tokens, effort)))

    def stream(self, system: str, prompt: str, on_text: Any, *, max_tokens: int = 4096,
               effort: str | None = None, **_: Any) -> LLMResult:
        """Streams text deltas to ``on_text`` and returns the final message (same checks as ``complete``)."""
        def run(c: Any) -> Any:
            with c.beta.messages.stream(**self._kwargs(system, prompt, max_tokens, effort)) as s:
                for text in s.text_stream:
                    on_text(text)
                return s.get_final_message()

        return self._call(run)

    def _call(self, fn: Any) -> LLMResult:
        import anthropic

        try:
            response = fn(self._get_client())
        except anthropic.BadRequestError as exc:
            raise LLMError("llm_bad_request", f"The model rejected the request: {exc.message}") from exc
        except anthropic.AuthenticationError as exc:
            raise LLMError("llm_auth", "The LLM API key is missing or invalid.") from exc
        except anthropic.PermissionDeniedError as exc:
            raise LLMError("llm_permission", "The LLM API key lacks permission for this model.") from exc
        except anthropic.NotFoundError as exc:
            raise LLMError("llm_model", f"Unknown model '{self.model}'.") from exc
        except anthropic.RateLimitError as exc:
            raise LLMError("llm_rate_limited", "The LLM provider is rate limiting requests.", transient=True) from exc
        except anthropic.APIStatusError as exc:
            transient = exc.status_code >= 500
            raise LLMError("llm_unavailable" if transient else "llm_error",
                           f"LLM provider error ({exc.status_code}).", transient=transient) from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError("llm_unavailable", "Could not reach the LLM provider.", transient=True) from exc

        if response.stop_reason == "refusal":
            raise LLMError("llm_refused", "The model declined to generate this content.")
        if response.stop_reason == "max_tokens":
            raise LLMError("llm_truncated", "The generated text was cut off (output limit reached).")
        text = "".join(b.text for b in response.content if b.type == "text").strip()
        if not text:
            raise LLMError("llm_empty", "The model returned no text.")
        usage = response.usage
        return LLMResult(text=text, provider=self.name, model=response.model or self.model,
                         input_tokens=getattr(usage, "input_tokens", 0) or 0,
                         output_tokens=getattr(usage, "output_tokens", 0) or 0)


class ScriptedLLMProvider:
    """Deterministic provider for tests and local demos: ``responder(system, prompt) -> text``."""

    name = "scripted"
    enabled = True

    def __init__(self, responder: Any, model: str = "scripted-1"):
        self.responder = responder
        self.model = model
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, prompt: str, *, max_tokens: int = 16000, effort: str | None = None,
                 **_: Any) -> LLMResult:
        self.calls.append((system, prompt))
        out = self.responder(system, prompt)
        if isinstance(out, Exception):
            raise out
        return LLMResult(text=str(out), provider=self.name, model=self.model)

    def stream(self, system: str, prompt: str, on_text: Any, *, max_tokens: int = 4096,
               effort: str | None = None, **_: Any) -> LLMResult:
        res = self.complete(system, prompt, max_tokens=max_tokens, effort=effort)
        for i in range(0, len(res.text), 7):   # deliver in small pieces like a real stream
            on_text(res.text[i:i + 7])
        return res


def build_llm_provider(provider: str, api_key: str, model: str = "claude-opus-5-5", effort: str = "medium",
                       timeout: float = 120.0, settings: Any = None) -> LLMProvider:
    p = (provider or "none").strip().lower()
    if p in ("anthropic", "claude"):
        return AnthropicProvider(api_key, model or "claude-opus-5-5", effort or "medium", timeout)
    if p in ("gemini", "google"):
        from app.services.llm.gemini import GeminiProvider

        s = settings
        return GeminiProvider(
            api_key,
            primary=getattr(s, "gemini_primary_model", "") or "gemini-3.6-flash",
            fallback=getattr(s, "gemini_fallback_model", "gemini-3.5-flash-lite"),
            request_timeout=getattr(s, "llm_request_timeout_seconds", 30.0),
            job_timeout=timeout,
            thinking_level=getattr(s, "gemini_thinking_level", "low"),
            temperature=getattr(s, "llm_temperature", None),
            max_attempts=getattr(s, "llm_max_attempts_per_model", 2),
            retry_base=getattr(s, "llm_retry_base_seconds", 0.8),
            retry_max_delay=getattr(s, "llm_retry_max_delay_seconds", 8.0),
            deadline=getattr(s, "llm_request_deadline_seconds", 45.0),
            fast_timeout=getattr(s, "llm_fast_timeout_seconds", 12.0),
        )
    if p not in ("none", ""):
        log.warning("unknown LLM_PROVIDER %r; answer generation and translation drafts are disabled", provider)
    return NullLLMProvider()


def build_llm_from_settings(settings: Any) -> LLMProvider:
    """The configured provider (LLM_PROVIDER + its settings)."""
    return build_llm_provider(settings.llm_provider, settings.llm_api_key, settings.llm_model, settings.llm_effort,
                              settings.llm_timeout_seconds, settings=settings)
