"""Concept bridge: search in Korean and English for a question in any of the five languages, without a model call.

The sources are mostly Korean or English. The embedding model is multilingual, but a question in Vietnamese still prefers
text in scripts it has seen together with Vietnamese. The glossary concepts found in the question (query_analysis.CONCEPTS)
are written out in the official Korean and English terms, and both are searched as additional, weaker dense queries.

* Needs at least ``MIN_CONCEPTS`` concepts (or one concept and a visa code): one broad word alone would pull in its topic
  and lose the rest of the question.
* Adds nothing that was not in the question: only translations of terms that occur in it.
"""
from __future__ import annotations

import re

from app.services.retrieval.query_analysis import CONCEPTS, QueryAnalysis

MIN_CONCEPTS = 2
_HANGUL = re.compile(r"[가-힣]")
_ASCII = re.compile(r"^[A-Za-z0-9 \-]+$")
_FORMS = dict(CONCEPTS)


def canonical(concept: str, lang: str) -> str | None:
    """The first (official) form of a concept in Korean or English."""
    test = (lambda f: _HANGUL.search(f)) if lang == "ko" else (lambda f: _ASCII.match(f) and len(f) > 3)
    forms = _FORMS.get(concept, ())
    if lang == "en":      # forms are listed en, ko, id, vi, zh: English is what stands before the first Korean form
        cut = next((i for i, f in enumerate(forms) if _HANGUL.search(f)), len(forms))
        forms = forms[:cut]
    return next((f for f in forms if test(f)), None)


def bridge_queries(qa: QueryAnalysis) -> list[str]:
    if len(qa.concepts) + (1 if qa.codes else 0) < MIN_CONCEPTS:
        return []
    out = []
    for lang in ("ko", "en"):
        words = [w for c in qa.concepts if (w := canonical(c, lang))]
        if words:
            out.append(" ".join([*sorted(qa.codes), *words]))
    return out
