"""Deterministic evidence-sufficiency gate (RAG v2, Phase 6).

Decides from retrieval signals alone, before any generation, whether the passages selected for the answer model are
strong enough to answer from:

    none          no passage was selected
    sufficient    an exact identifier / visa-code match, or the best passage similarity >= tau, or
                  (best keyword coverage >= lam and best similarity >= tau - 0.03)
    insufficient  otherwise

Two threshold sets, because the similarity scale differs by path: after an LLM rewrite the passages were found by
up to four queries (standalone, original, English, Korean), which raises the similarity of real evidence much more
than that of unrelated text. Thresholds come from scripts/rag_v2/gate_sweep.py on DEV + VALIDATION + DEV-negatives
(docs/research/rag-v2/ANSWER-EVALUATION.md); the rewritten-path values were measured with a LOCAL rewrite model as a
proxy for Gemini and must be re-checked on real traffic before ``enforce`` is used.

Modes (ASSISTANT_EVIDENCE_GATE): ``off``; ``log`` (default: the decision is reported in the retrieval info and
logged, behaviour unchanged); ``enforce`` (an insufficient / none decision answers with the localized
"no approved information" reply WITHOUT calling the LLM, and shows no sources).
"""
from __future__ import annotations

from typing import Any

MODES = ("off", "log", "enforce")


def evaluate_gate(passages: list[dict[str, Any]], *, rewritten: bool, settings: Any) -> dict[str, Any]:
    if rewritten:
        tau, lam = settings.assistant_gate_similarity_rewritten, settings.assistant_gate_lexical_rewritten
    else:
        tau, lam = settings.assistant_gate_similarity, settings.assistant_gate_lexical
    sims = [float(p["similarity"]) for p in passages if p.get("similarity") is not None]
    lexs = [float(p.get("best_lexical") or p.get("lexical_coverage") or 0.0) for p in passages]
    best_sim = max(sims) if sims else 0.0
    best_lex = max(lexs) if lexs else 0.0
    exact = any(bool(p.get("exact_match")) for p in passages)
    if not passages:
        decision, reason = "none", "no_passages"
    elif exact:
        decision, reason = "sufficient", "exact_match"
    elif best_sim >= tau:
        decision, reason = "sufficient", "similarity"
    elif best_lex >= lam and best_sim >= tau - 0.03:
        decision, reason = "sufficient", "keywords_and_similarity"
    else:
        decision, reason = "insufficient", "weak_signals"
    return dict(decision=decision, reason=reason, path="rewritten" if rewritten else "original",
                best_similarity=round(best_sim, 4), best_keyword_coverage=round(best_lex, 3), exact_match=exact,
                thresholds=dict(similarity=tau, keywords=lam))
