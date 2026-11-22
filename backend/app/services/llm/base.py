"""LLM provider abstraction for future RAG answer generation (Gemini or other).

Phase 1 ships only the null provider: the core site and retrieval work with no API key.
"""
from __future__ import annotations

from typing import Protocol


class LLMProvider(Protocol):
    name: str
    enabled: bool

    def generate_answer(self, question: str, passages: list[dict], language: str) -> str: ...


class NullLLMProvider:
    name = "none"
    enabled = False

    def generate_answer(self, question: str, passages: list[dict], language: str) -> str:
        raise NotImplementedError("Answer generation is not enabled (LLM_PROVIDER=none).")


def build_llm_provider(provider: str, api_key: str) -> LLMProvider:
    # A Gemini implementation will plug in here (provider == "gemini" and api_key) in Phase 2.
    return NullLLMProvider()
