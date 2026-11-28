"""Deterministic evidence-sufficiency gate (assistant/gate.py, RAG v2 Phase 6)."""
from __future__ import annotations

from types import SimpleNamespace as NS

from app.services.assistant.gate import evaluate_gate
from app.services.assistant.texts import t
from app.services.llm.base import ScriptedLLMProvider
from tests.test_assistant import conv, say, use_llm
from tests.test_assistant_m2 import Bot, setup_kb

S = NS(assistant_gate_similarity=0.82, assistant_gate_lexical=0.6,
       assistant_gate_similarity_rewritten=0.86, assistant_gate_lexical_rewritten=0.7)


def p(sim=None, lex=0.0, exact=False):  # type: ignore[no-untyped-def]
    return {"similarity": sim, "best_lexical": lex, "exact_match": exact}


def test_no_passage_is_none() -> None:
    assert evaluate_gate([], rewritten=False, settings=S)["decision"] == "none"


def test_exact_identifier_match_is_sufficient_even_with_low_similarity() -> None:
    g = evaluate_gate([p(0.5, exact=True)], rewritten=True, settings=S)
    assert (g["decision"], g["reason"]) == ("sufficient", "exact_match")


def test_similarity_threshold_depends_on_the_path() -> None:
    assert evaluate_gate([p(0.84)], rewritten=False, settings=S)["decision"] == "sufficient"
    assert evaluate_gate([p(0.84)], rewritten=True, settings=S)["decision"] == "insufficient"
    assert evaluate_gate([p(0.87)], rewritten=True, settings=S)["decision"] == "sufficient"


def test_keywords_count_only_together_with_a_nearly_sufficient_similarity() -> None:
    assert evaluate_gate([p(0.80, lex=0.65)], rewritten=False, settings=S)["reason"] == "keywords_and_similarity"
    assert evaluate_gate([p(0.78, lex=1.0)], rewritten=False, settings=S)["decision"] == "insufficient"
    assert evaluate_gate([p(None, lex=1.0)], rewritten=False, settings=S)["decision"] == "insufficient"


def test_best_signal_of_any_passage_counts() -> None:
    g = evaluate_gate([p(0.70), p(0.83, lex=0.1)], rewritten=False, settings=S)
    assert g["decision"] == "sufficient" and g["best_similarity"] == 0.83


def _ask(env, question, *, mode, sim=0.82):  # type: ignore[no-untyped-def]
    setup_kb(env)
    env.settings.assistant_evidence_gate = mode
    env.settings.assistant_gate_similarity = env.settings.assistant_gate_similarity_rewritten = sim
    b = Bot("Apply at HiKorea before your stay expires [1].")
    use_llm(env, ScriptedLLMProvider(b))
    return b, say(env, conv(env), question)


def test_enforce_answers_weak_evidence_without_calling_the_model(env) -> None:  # type: ignore[no-untyped-def]
    # hash test vectors never reach 0.99 and the question names no code: "insufficient" or "none"
    b, msg = _ask(env, "When can I apply for the winter dormitory?", mode="enforce", sim=0.99)
    assert b.answers() == []                                  # no answer generation was requested
    assert msg["content"] == t("none", "en")
    assert msg["citations"] == []
    assert msg["metadata"]["answer_generation"] == "gated"
    assert msg["metadata"]["evidence_gate"] in ("insufficient", "none")


def test_a_named_visa_code_that_the_evidence_contains_passes_the_gate(env) -> None:  # type: ignore[no-untyped-def]
    b, msg = _ask(env, "How do I extend my D-2 visa?", mode="enforce", sim=0.99)
    assert len(b.answers()) == 1 and msg["metadata"]["evidence_gate"] == "sufficient"


def test_enforce_lets_sufficient_evidence_through(env) -> None:  # type: ignore[no-untyped-def]
    b, msg = _ask(env, "How do I extend my D-2 visa?", mode="enforce", sim=-1.0)
    assert len(b.answers()) == 1
    assert msg["metadata"]["evidence_gate"] == "sufficient"
    assert msg["metadata"]["answer_generation"] == "llm"


def test_log_mode_reports_the_decision_but_changes_nothing(env) -> None:  # type: ignore[no-untyped-def]
    b, msg = _ask(env, "When can I apply for the winter dormitory?", mode="log", sim=0.99)
    assert len(b.answers()) == 1                              # generation still happens
    assert msg["metadata"]["evidence_gate"] in ("insufficient", "none")
    assert msg["metadata"]["answer_generation"] == "llm"


def test_off_mode_has_no_gate(env) -> None:  # type: ignore[no-untyped-def]
    _b, msg = _ask(env, "How do I extend my D-2 visa?", mode="off")
    assert msg["metadata"]["evidence_gate"] is None


def test_default_mode_is_log(env) -> None:  # type: ignore[no-untyped-def]
    assert env.settings.assistant_evidence_gate == "log"
