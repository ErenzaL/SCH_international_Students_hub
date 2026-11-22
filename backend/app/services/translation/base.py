"""Translation provider abstraction (Phase 2).

Phase 1 deliberately does NOT auto-translate anything. Planned flow:
original notice -> AI draft translation (machine_draft) -> assigned language supporter
-> human review (human_approved) -> publication -> RAG indexing.
Machine output must always be stored as `machine_draft` and never labelled reviewed.
"""
from __future__ import annotations

from typing import Protocol


class TranslationProvider(Protocol):
    name: str

    def translate(self, text: str, source_language: str, target_language: str) -> str: ...


class NullTranslationProvider:
    name = "none"

    def translate(self, text: str, source_language: str, target_language: str) -> str:
        raise NotImplementedError("No translation provider is configured (Phase 1: human translation only).")
