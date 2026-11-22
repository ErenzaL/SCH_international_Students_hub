"""Configurable LLM provider (answer generation and translation drafts).

* ``none`` (default): nothing is generated; the site, retrieval and the assistant's evidence-only replies keep working.
* ``anthropic``: Claude via the official ``anthropic`` SDK (``LLM_MODEL``, default ``claude-opus-5-5``).
Every provider exposes one primitive, ``complete(system, prompt)``; the prompts live in the services that use it
(``services/llm/answers.py``, ``services/translation_drafts.py``) so a provider never decides what is said.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

log = logging.getLogger(__name__)


class LLMError(Exception):
    """A generation failed. ``transient`` errors (rate limits, overload, network) may be retried by jobs."""

    def __init__(self, code: str, message: str, *, transient: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.transient = transient


@dataclass
class LLMResult:
    text: str
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0


class LLMProvider(Protocol):
    name: str
    model: str
    enabled: bool

    def complete(self, system: str, prompt: str, *, max_tokens: int = 16000, effort: str | None = None) -> LLMResult: ...


class NullLLMProvider:
    name = "none"
    model = ""
    enabled = False

    def complete(self, system: str, prompt: str, *, max_tokens: int = 16000, effort: str | None = None) -> LLMResult:
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

    def complete(self, system: str, prompt: str, *, max_tokens: int = 16000, effort: str | None = None) -> LLMResult:
        import anthropic

        try:
            response = self._get_client().beta.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                output_config={"effort": effort or self.effort},
                # on a policy decline the API re-runs the request on a fallback model inside the same call
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
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

    def complete(self, system: str, prompt: str, *, max_tokens: int = 16000, effort: str | None = None) -> LLMResult:
        self.calls.append((system, prompt))
        out = self.responder(system, prompt)
        if isinstance(out, Exception):
            raise out
        return LLMResult(text=str(out), provider=self.name, model=self.model)


def build_llm_provider(provider: str, api_key: str, model: str = "claude-opus-5-5", effort: str = "medium",
                       timeout: float = 120.0) -> LLMProvider:
    p = (provider or "none").strip().lower()
    if p in ("anthropic", "claude"):
        return AnthropicProvider(api_key, model or "claude-opus-5-5", effort or "medium", timeout)
    if p not in ("none", ""):
        log.warning("unknown LLM_PROVIDER %r; answer generation and translation drafts are disabled", provider)
    return NullLLMProvider()
