"""Retrieval over approved, current, in-window content only (enforced by the ``searchable_chunks`` view that
``search_knowledge_v2`` reads; nothing here can widen it). No evidence => empty result list; nothing is fabricated.

Modes (``mode=`` per request; ``hybrid`` is the default):
  * ``hybrid`` (RETRIEVAL_FUSION=weighted): the dense leg (pgvector cosine) and the keyword leg are fetched
    separately from the same SQL function, then fused here: weighted reciprocal-rank fusion where semantic rank
    counts fully and keyword rank counts in proportion to the rarity-weighted share of query terms a passage
    covers (``query_analysis.lexical_scores``). Visa codes are normalized (D2 = D-2), a passage about a different
    code (E-7, F-2-R) than the one asked about is demoted, near-duplicate chunks are dropped and each document
    contributes at most ``retrieval_max_chunks_per_document`` passages.
  * ``hybrid_legacy``: the original equal-weight RRF inside the SQL function (benchmark baseline).
  * ``vector`` / ``keyword``: one leg only (``vector`` is the B0 baseline of the evaluation).
"""
from __future__ import annotations

import logging
import re
import threading
from collections import OrderedDict
from typing import Any

from app.core.config import Settings
from app.core.errors import EmbeddingUnavailable
from app.repositories.base import Store
from app.services.embeddings.base import EmbeddingError, EmbeddingProvider
from app.services.retrieval import families
from app.services.retrieval.bridge import bridge_queries
from app.services.retrieval.query_analysis import (
    analyze,
    code_matches,
    find_codes,
    lexical_scores,
    normalize_codes,
    token_set,
)

log = logging.getLogger("app.retrieval")
_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
_HANGUL = re.compile(r"^[가-힣]+$")
_KO_PARTICLES = ("에서는", "으로는", "에서", "으로", "에는", "에게", "까지", "부터", "은", "는", "이", "가", "을", "를", "의", "에", "로", "와", "과", "도", "만")
_STOP = {"the", "a", "an", "of", "to", "for", "and", "or", "in", "on", "is", "are", "how", "do", "i", "my", "what", "can",
         "yang", "dan", "di", "ke", "untuk", "dengan", "apa", "bagaimana", "saya"}
MAX_TOKENS = 12
QUERY_CACHE = 256
# exact identifiers students search for: visa types (D-2, D-2-2, E-7, F-2-7), TOPIK levels, acronyms (ARC, NHIS)
# ASCII-only boundaries so "D-2签证" / "D-2비자" (identifier glued to CJK text) still match
_IDENT = re.compile(r"(?<![A-Za-z0-9-])([A-Za-z]-\d{1,2}(?:-\d{1,2})?|TOPIK\s?(?:I{1,3}|[1-6])(?:\s?급)?|[A-Z]{2,6})(?![A-Za-z0-9-])")
_ACRONYM_STOP = {"I", "A", "OK", "AM", "PM", "SCH", "THE"}


def exact_terms(query: str) -> list[str]:
    """Identifier-like terms that must match on word boundaries (sent separately from fuzzy tokens)."""
    out = []
    for m in _IDENT.finditer(query):
        t = re.sub(r"\s+", " ", m.group(1)).strip()
        if t.upper() in _ACRONYM_STOP:
            continue
        t = re.sub(r"급$", "", t).strip()
        if re.fullmatch(r"[A-Za-z0-9]+([ -][A-Za-z0-9]+)*", t):
            out.append(t.upper() if re.fullmatch(r"[a-z]-\d.*", t) else t)
    return list(dict.fromkeys(out))[:6]


def stale_info(verified_at: str | None, category: str | None, override: int | None) -> dict[str, Any]:
    from datetime import UTC, datetime

    from app.core.constants import STALE_AFTER_DAYS, STALE_AFTER_DAYS_DEFAULT

    limit = override or STALE_AFTER_DAYS.get(category or "", STALE_AFTER_DAYS_DEFAULT)
    if not verified_at:
        return dict(is_stale=False, verification_age_days=None, stale_after_days=limit)
    age = (datetime.now(UTC) - datetime.fromisoformat(str(verified_at).replace("Z", "+00:00"))).days
    return dict(is_stale=age > limit, verification_age_days=age, stale_after_days=limit)


def query_tokens(query: str) -> list[str]:
    """Split a user query into search tokens (adds particle-stripped variants for Korean words)."""
    out: list[str] = []
    for raw in _TOKEN.findall(query.lower()):
        if raw in _STOP:
            continue
        cjk = bool(re.search(r"[぀-ヿ㐀-鿿가-힯]", raw))
        if len(raw) < 2 and not cjk:
            continue
        out.append(raw)
        if _HANGUL.match(raw) and len(raw) >= 3:
            for p in _KO_PARTICLES:
                if raw.endswith(p) and len(raw) - len(p) >= 2:
                    out.append(raw[: -len(p)])
                    break
    return list(dict.fromkeys(out))[:MAX_TOKENS]


class RetrievalService:
    def __init__(self, store: Store, embedder: EmbeddingProvider, settings: Settings):
        self.store = store
        self.embedder = embedder
        self.settings = settings
        self._cache: OrderedDict[tuple[str, str], list[float]] = OrderedDict()
        self._cache_lock = threading.Lock()

    def search(self, query: str, *, language: str | None = None, category: str | None = None, top_k: int = 5,
               mode: str = "hybrid", scope: str | None = None, authority: list[str] | None = None,
               max_per_document: int | None = None, bridge: bool = True) -> dict[str, Any]:
        top_k = min(max(top_k, 1), 20)
        if mode == "hybrid" and self.settings.retrieval_fusion != "weighted":
            mode = "hybrid_legacy"
        if mode == "hybrid":
            return self._search_weighted(query, category=category, top_k=top_k, scope=scope, authority=authority,
                                         max_per_document=max_per_document, bridge=bridge)
        return self._search_sql(query, category=category, top_k=top_k, mode="hybrid" if mode == "hybrid_legacy" else mode,
                                scope=scope, authority=authority, label=mode)

    # ----------------------------------------------------------- shared helpers
    def _embed(self, query: str, *, required: bool) -> tuple[list[float] | None, str | None]:
        key = (self.embedder.model_id, query)
        with self._cache_lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key], None
        try:
            vec = self.embedder.embed_query(query)
            with self._cache_lock:        # question vectors only (about 12 KB each), never results: those must stay current
                self._cache[key] = vec
                while len(self._cache) > QUERY_CACHE:
                    self._cache.popitem(last=False)
            return vec, None
        except EmbeddingError as exc:
            if required:
                raise EmbeddingUnavailable(f"Vector search is unavailable: {exc}") from exc
            log.warning("embedding unavailable, falling back to keyword search: %s", exc)
            return None, f"Semantic search is unavailable ({exc}); showing keyword matches only."

    def _rpc(self, *, embedding: list[float] | None, tokens: list[str] | None, exact: list[str] | None, mode: str,
             category: str | None, scope: str | None, authority: list[str] | None, count: int) -> list[dict[str, Any]]:
        return self.store.rpc("search_knowledge_v2", dict(
            p_query_embedding=embedding, p_query_tokens=tokens or None, p_exact_terms=exact or None,
            p_model=self.embedder.model_id, p_category=category, p_scope=scope, p_authority=authority or None,
            p_match_count=count, p_mode=mode,
        )) or []

    @staticmethod
    def _result(r: dict[str, Any], **extra: Any) -> dict[str, Any]:
        return dict(
            chunk_id=r["chunk_id"], document_id=r["document_id"], version_id=r["version_id"],
            document_title=r["document_title"], passage=r["passage"], heading=r.get("heading"), page=r.get("page"),
            similarity=r.get("similarity"), keyword_rank=r.get("keyword_rank"), score=r["score"],
            source_url=r.get("source_url"), organization=r["organization"], authority_type=r["authority_type"],
            scope=r["scope"], category=r["category"], source_published_at=r.get("source_published_at"),
            verified_at=r.get("verified_at"), language=r["language"], source_id=r.get("source_id"),
            source_type=r.get("source_type"), valid_until=r.get("valid_until"),
            exact_match=bool(r.get("exact_match")),
            **{k: r[k] for k in ("superseded_by", "superseded_by_title", "copy_of") if r.get(k)},
            **stale_info(r.get("verified_at"), r.get("category"), r.get("stale_after_days")), **extra,
        )

    # ------------------------------------------------------- legacy / single leg
    def _search_sql(self, query: str, *, category: str | None, top_k: int, mode: str, scope: str | None,
                    authority: list[str] | None, label: str) -> dict[str, Any]:
        tokens = query_tokens(query)
        exact = exact_terms(query)
        warning: str | None = None
        embedding: list[float] | None = None
        effective = mode
        if mode in ("hybrid", "vector"):
            embedding, warning = self._embed(query, required=mode == "vector")
            if embedding is None:
                effective = "keyword"
        if effective == "keyword" and not tokens and not exact:
            return self._response(query, [], effective, warning)
        rows = self._rpc(embedding=embedding, tokens=tokens, exact=exact, mode=effective, category=category,
                         scope=scope, authority=authority, count=top_k)
        min_sim = self.settings.retrieval_min_similarity
        results = []
        for r in rows:
            if min_sim and r.get("keyword_rank") is None and (r.get("similarity") or 0) < min_sim:
                continue  # semantic-only match below the evidence threshold
            if exact and not r.get("exact_match") and r.get("keyword_rank") is None \
                    and (r.get("similarity") or 0) < max(min_sim, 0.0) + 0.02:
                continue  # the query names an identifier this passage does not contain and similarity is marginal
            results.append(self._result(r))
        shown = "hybrid_legacy" if label == "hybrid_legacy" and effective == "hybrid" else effective
        return self._response(query, results, shown, warning)

    # ---------------------------------------------------------- weighted fusion
    def _search_weighted(self, query: str, *, category: str | None, top_k: int, scope: str | None,
                         authority: list[str] | None, max_per_document: int | None = None,
                         bridge: bool = True) -> dict[str, Any]:
        s = self.settings
        qa = analyze(query)
        pool = max(top_k * 3, min(max(s.retrieval_candidate_pool, top_k), 50))
        embedding, warning = self._embed(query, required=False)
        common = dict(category=category, scope=scope, authority=authority, count=pool)
        vec_rows = self._rpc(embedding=embedding, tokens=None, exact=None, mode="vector", **common) \
            if embedding is not None else []
        kw_rows = self._rpc(embedding=None, tokens=qa.keyword_tokens, exact=qa.exact_terms, mode="keyword", **common) \
            if (qa.keyword_tokens or qa.exact_terms) else []
        mode = "hybrid" if embedding is not None else "keyword"
        # the question's glossary concepts in official Korean and English (bridge.py): extra, weaker dense queries
        bridges = bridge_queries(qa) if bridge and embedding is not None and s.retrieval_bridge_weight > 0 else []
        bridge_rows = []
        for b in bridges:
            vec, _w = self._embed(b, required=False)
            if vec is not None:
                bridge_rows.append(self._rpc(embedding=vec, tokens=None, exact=None, mode="vector", **common))

        cands: dict[str, dict[str, Any]] = {}
        for r in vec_rows:
            cands[r["chunk_id"]] = dict(r, keyword_rank=None, exact_match=False)
        for r in kw_rows:
            c = cands.setdefault(r["chunk_id"], dict(r, similarity=None))
            c["keyword_rank"], c["exact_match"] = r.get("keyword_rank"), bool(r.get("exact_match"))
        bridge_rank: dict[str, float] = {}       # best reciprocal rank in any bridge query
        for rows in bridge_rows:
            for i, r in enumerate(rows, 1):
                cid = r["chunk_id"]
                cands.setdefault(cid, dict(r, similarity=None, keyword_rank=None, exact_match=False, bridged=r.get("similarity")))
                bridge_rank[cid] = max(bridge_rank.get(cid, 0.0), 1.0 / (60.0 + i))
        if not cands:
            return self._response(query, [], mode, warning, qa.exact_terms)

        texts = {cid: f"{c.get('document_title') or ''}\n{c.get('heading') or ''}\n{c.get('passage') or ''}"
                 for cid, c in cands.items()}
        lex = lexical_scores(qa, texts)
        k = 60.0
        def stable(cid: str) -> tuple[str, str]:   # content-based tie-break: reproducible across re-indexing
            c = cands[cid]
            return (str(c.get("document_title") or ""), str(c.get("passage") or "")[:80])

        vec_rank = {cid: i for i, cid in enumerate(
            sorted((cid for cid, c in cands.items() if c.get("similarity") is not None),
                   key=lambda cid: (-float(cands[cid]["similarity"]), stable(cid))), 1)}
        lex_rank = {cid: i for i, cid in enumerate(
            sorted((cid for cid in cands if lex[cid][0] > 0),
                   key=lambda cid: (-lex[cid][0], -float(cands[cid].get("similarity") or 0.0), stable(cid))), 1)}
        min_sim = s.retrieval_min_similarity
        scored: list[tuple[float, dict[str, Any], dict[str, Any]]] = []
        for cid, c in cands.items():
            sim = c.get("similarity")
            coverage, matched = lex[cid]
            codes_here = find_codes(normalize_codes(texts[cid]))
            exact = bool(qa.codes) and code_matches(qa.codes, codes_here) or bool(c.get("exact_match")) and not qa.codes
            # the code itself is one of the weighted terms, so a passage that merely mentions "D-2" does not reach
            # 0.5 coverage on its own when the question asks about something else as well
            strong_lex = coverage >= 0.5
            if sim is None and not strong_lex and not (cid in bridge_rank and coverage > 0):
                continue          # keyword-only overlap on weak/broad words is not evidence
            if sim is not None and min_sim and sim < min_sim and not strong_lex:
                continue          # semantic-only match below the evidence threshold
            score = s.retrieval_vector_weight / (k + vec_rank[cid]) if cid in vec_rank else 0.0
            if cid in lex_rank:
                score += s.retrieval_keyword_weight * coverage / (k + lex_rank[cid])
            score += s.retrieval_bridge_weight * bridge_rank.get(cid, 0.0)
            if exact and qa.codes:
                score += s.retrieval_keyword_weight / (k + 1)
            mismatch = bool(qa.codes) and bool(codes_here) and not code_matches(qa.codes, codes_here)
            if mismatch:
                score *= s.retrieval_code_mismatch_penalty
            if c.get("authority_type") in ("official_government", "official_university"):
                score += 1e-6     # tie-break toward official sources (as the SQL function does)
            row = dict(c, score=score, exact_match=exact,
                       keyword_rank=c.get("keyword_rank") if strong_lex else None)
            scored.append((score, row, dict(lexical_coverage=round(coverage, 3), matched_terms=matched,
                                            code_mismatch=mismatch)))
        scored.sort(key=lambda x: (-x[0], str(x[1].get("document_title") or ""), str(x[1].get("passage") or "")[:80]))

        # an older edition or a copy of a notice never ranks above its newer edition / original (families.py)
        marked = {id(r): m for (_s, r, _x), m in zip(scored, families.annotate([r for _s, r, _x in scored], query), strict=True)}
        scored = [(sc, marked[id(r)], x) for sc, r, x in scored]
        scored = [t for t in scored if not (t[1].get("superseded_by") or t[1].get("copy_of"))] + \
            [t for t in scored if t[1].get("superseded_by") or t[1].get("copy_of")]

        results: list[dict[str, Any]] = []
        per_doc: dict[str, int] = {}
        kept_tokens: dict[str, list[set[str]]] = {}
        for _score, row, extra in scored:
            doc = row["document_id"]
            if per_doc.get(doc, 0) >= (max_per_document or s.retrieval_max_chunks_per_document):
                continue
            toks = token_set(row.get("passage") or "")
            if any(_jaccard(toks, t) >= 0.8 for t in kept_tokens.get(doc, [])):
                continue          # overlapping chunk of the same document (chunk overlap / repeated sections)
            per_doc[doc] = per_doc.get(doc, 0) + 1
            kept_tokens.setdefault(doc, []).append(toks)
            results.append(self._result(row, **extra))
            if len(results) >= top_k:
                break
        resp = self._response(query, results, mode, warning, qa.exact_terms)
        resp["retrieval"].update(fusion="weighted", normalized_query=qa.normalized if qa.normalized != query else None,
                                 codes=sorted(qa.codes), concepts=qa.concepts, candidates=len(cands))
        return resp

    def _response(self, query: str, results: list[dict[str, Any]], mode: str, warning: str | None,
                  exact: list[str] | None = None) -> dict[str, Any]:
        return dict(query=query, results=results, retrieval=dict(
            mode=mode, embedding_model=self.embedder.model_id, total=len(results), warning=warning,
            exact_terms=exact_terms(query) if exact is None else exact))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)
