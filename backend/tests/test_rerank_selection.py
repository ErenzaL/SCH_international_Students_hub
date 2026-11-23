"""Reranker integration (off by default) and evidence selection that preserves the reranker's order."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import Settings
from app.services.assistant.engine import AssistantEngine
from app.services.retrieval.rerank import (
    NoReranker,
    OnnxCrossEncoderReranker,
    build_reranker,
    encode_pair,
)
from tests.test_phase2 import paste
from tests.test_rag_sync import approve

MODEL_DIR = Path(__file__).resolve().parents[2] / "research/models/mminilm"


def hit(doc: str, n: int, text: str, *, score: float | None = None, lexical: float = 0.0, **kw):  # type: ignore[no-untyped-def]
    h = dict(chunk_id=f"{doc}-{n}", document_id=doc, version_id=f"v-{doc}", document_title=f"Doc {doc}",
             heading=None, passage=text, best_lexical=lexical, **kw)
    if score is not None:
        h["rerank_score"] = score
    return h


def engine(**overrides) -> AssistantEngine:  # type: ignore[no-untyped-def]
    s = Settings(_env_file=None, **overrides)  # type: ignore[call-arg]
    return AssistantEngine(retrieval=None, llm=None, settings=s)  # type: ignore[arg-type]


def words(i: int) -> str:
    return " ".join(f"w{i}x{j}" for j in range(40))      # distinct passages (no near-duplicates)


# ------------------------------------------------------------------------------------------- selection
def test_preserve_order_keeps_the_rerankers_ranking():
    # the reranker put document A (no keyword agreement) first; B agrees lexically but scored lower
    hits = [hit("A", 0, words(0), score=3.2), hit("B", 0, words(1), score=1.0, lexical=0.9),
            hit("A", 1, words(2), score=0.5), hit("C", 0, words(3), score=-2.0, lexical=0.8)]
    e = engine()
    assert [s["document_id"] for s in e._select(hits, set(), "q")] == ["B", "C", "A"]      # heuristic reorder
    kept = e._select(hits, set(), "q", preserve_order=True)
    assert [s["document_id"] for s in kept] == ["A", "B", "C"]
    assert [p["chunk_id"] for p in kept[0]["passages"]] == ["A-0", "A-1"]                 # passages by score


def test_preserve_order_sorts_by_score_and_keeps_ties_stable():
    hits = [hit("B", 0, words(1), score=1.0), hit("A", 0, words(0), score=2.0), hit("C", 0, words(2), score=1.0)]
    assert [s["document_id"] for s in engine()._select(hits, set(), "", preserve_order=True)] == ["A", "B", "C"]


def test_quantity_questions_do_not_reorder_reranked_passages():
    hits = [hit("A", 0, "The office explains the process in detail " + words(0), score=2.0),
            hit("A", 1, "The fee is 30,000 won " + words(1), score=1.0)]
    kept = engine()._select(hits, set(), "How much is the fee?", preserve_order=True)
    assert [p["chunk_id"] for p in kept[0]["passages"]] == ["A-0", "A-1"]


def test_deduplication_and_limits_hold_with_preserved_order():
    dup = words(9)
    hits = [hit("A", i, words(i), score=10 - i) for i in range(6)]                       # A dominates the ranking
    hits += [hit("B", 0, dup, score=3.0), hit("C", 0, dup + " extra", score=2.9)]         # near-duplicate of B
    hits += [hit(d, 0, words(20 + k), score=1.0 - k) for k, d in enumerate("DEFG")]
    e = engine(assistant_max_sources=4, assistant_max_passages_per_source=3, assistant_context_chars=9000)
    kept = e._select(hits, set(), "", preserve_order=True)
    assert [s["document_id"] for s in kept] == ["A", "B", "D", "E"]       # C dropped as a duplicate, max 4 sources
    assert len(kept[0]["passages"]) == 3                                   # one document cannot take the whole context
    assert sum(len(p["passage"]) for s in kept for p in s["passages"]) <= 9000


def test_character_budget_is_respected_with_preserved_order():
    long = "x " * 900                                                       # 1800 characters each
    hits = [hit("A", i, long + str(i), score=10 - i) for i in range(3)] + [hit("B", 0, long + "b", score=1.0)]
    kept = engine(assistant_context_chars=4000)._select(hits, set(), "", preserve_order=True)
    a = next(s for s in kept if s["document_id"] == "A")
    assert len(a["passages"]) == 2 and [s["document_id"] for s in kept] == ["A", "B"]


def test_validity_and_visa_code_filters_still_apply_after_reranking():
    hits = [hit("E7", 0, "E-7 work visa holders must " + words(0), score=5.0),
            hit("OLD", 0, words(1), score=4.0, valid_until="2020-01-01T00:00:00+00:00"),
            hit("D2", 0, "D-2 students must " + words(2), score=1.0)]
    kept = engine()._select(hits, {"D-2"}, "D-2 question", preserve_order=True)
    assert [s["document_id"] for s in kept] == ["D2"]


# ------------------------------------------------------------------------------------------- reranker module
class _FakeSP:
    def encode(self, text: str) -> list[int]:
        return [5 + (ord(c) % 50) for c in text]


def test_encode_pair_uses_xlmr_pair_format_and_longest_first_truncation():
    ids = encode_pair(_FakeSP(), "ab", "cde", 512)
    assert ids[0] == 0 and ids[-1] == 2 and ids[3:5] == [2, 2] and len(ids) == 2 + 3 + 4
    long = encode_pair(_FakeSP(), "q" * 10, "p" * 1000, 64)
    assert len(long) == 64 and long[1:11] == [6 + ord("q") % 50] * 10       # the query is kept whole


def test_onnx_reranker_orders_by_score_and_keeps_the_tail():
    class Session:
        def run(self, _out, feeds):  # type: ignore[no-untyped-def]
            # score = number of tokens: longer passages score higher in this stub
            return [feeds["attention_mask"].sum(axis=1, keepdims=True).astype("float32")]

    rr = OnnxCrossEncoderReranker("m.onnx", "sp.model", batch_size=2)
    rr._session, rr._sp = Session(), _FakeSP()
    hits = [hit("A", 0, "short"), hit("B", 0, "a much longer passage"), hit("C", 0, "mid size"),
            hit("D", 0, "not scored at all, beyond top_n")]
    out = rr.rerank("q", hits, top_n=3)
    assert [h["document_id"] for h in out] == ["B", "C", "A", "D"]
    assert out[0]["first_stage_rank"] == 2 and "rerank_score" in out[0] and "rerank_score" not in out[3]


def test_build_reranker_is_off_by_default():
    assert isinstance(build_reranker(Settings(_env_file=None)), NoReranker)  # type: ignore[call-arg]
    with pytest.raises(ValueError):
        build_reranker(Settings(_env_file=None, rerank_provider="onnx"))  # type: ignore[call-arg]


# ------------------------------------------------------------------------------------------- end to end
class KeywordReranker:
    """Deterministic stand-in for a cross-encoder: passages containing the keyword first."""
    enabled = True
    model_id = "keyword-test"

    def __init__(self, keyword: str, fail: bool = False):
        self.keyword, self.fail, self.calls = keyword, fail, 0

    def rerank(self, query, hits, top_n):  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.fail:
            raise RuntimeError("model crashed")
        head = sorted(hits[:top_n], key=lambda h: self.keyword not in (h.get("passage") or ""))
        return [dict(h, rerank_score=float(self.keyword in h["passage"])) for h in head] + hits[top_n:]


def published(env, title: str, text: str) -> str:
    vid = paste(env, role="admin", title=title, original_text=text, category="dormitory-housing").json()["version_id"]
    approve(env, vid)
    return vid


def test_end_to_end_reranked_retrieval_selection_and_citations(env):
    published(env, "Dormitory rules", "Dormitory residents must return by midnight. Dormitory guests are not allowed. " * 5)
    published(env, "Dormitory fees", "The dormitory fee is 1,200,000 won per semester, paid before move-in. " * 5)
    e = env.app.state.services.conversations.engine
    e.reranker = KeywordReranker("1,200,000")
    out = e.respond("How much does the dormitory cost?", language="en")
    info = out["retrieval"]["rerank"]
    assert info["applied"] and info["model"] == "keyword-test" and info["candidates"] >= 2 and e.reranker.calls == 1
    texts = {v["id"]: v["extracted_text"] for v in env.store.select("document_versions")[0]}
    assert any("1,200,000" in t for t in texts.values())           # the fee document really holds the figure
    cites = out["citations"]
    assert cites[0]["document_title"] == "Dormitory fees" and [c["n"] for c in cites] == list(range(1, len(cites) + 1))
    assert all(c["chunk_id"] in c["chunk_ids"] for c in cites)


def test_reranker_failure_keeps_the_first_stage_order(env):
    published(env, "Dormitory rules", "Dormitory residents must return by midnight. Dormitory guests are not allowed. " * 5)
    e = env.app.state.services.conversations.engine
    e.reranker = KeywordReranker("x", fail=True)
    out = e.respond("dormitory rules", language="en")
    assert out["retrieval"]["rerank"] == dict(applied=False, model="keyword-test", error="RuntimeError")
    assert out["citations"] and out["answer"]


def test_without_a_reranker_nothing_changes(env):
    published(env, "Dormitory rules", "Dormitory residents must return by midnight. Dormitory guests are not allowed. " * 5)
    out = env.app.state.services.conversations.engine.respond("dormitory rules", language="en")
    assert "rerank" not in out["retrieval"] and out["citations"]


@pytest.mark.skipif(not (MODEL_DIR / "model_int8.onnx").exists(), reason="local ONNX export not present (research only)")
def test_real_int8_model_ranks_the_answering_passage_first():
    rr = OnnxCrossEncoderReranker(str(MODEL_DIR / "model_int8.onnx"), str(MODEL_DIR / "sentencepiece.bpe.model"))
    hits = [hit("A", 0, "도서관은 평일 오전 9시부터 오후 10시까지 운영합니다."),
            hit("B", 0, "외국인등록증은 입국 후 90일 이내에 출입국·외국인청에서 신청해야 합니다."),
            hit("C", 0, "The cafeteria serves lunch from 11:30 to 13:30.")]
    out = rr.rerank("외국인등록은 언제까지 해야 하나요?", hits, top_n=20)
    assert out[0]["document_id"] == "B" and rr.loaded
