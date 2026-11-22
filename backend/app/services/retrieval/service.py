"""Retrieval: query embedding + pgvector cosine + keyword leg fused with RRF (in the DB function).

Only approved, current, in-window content can be returned (enforced by the SQL view the
search function reads from). No evidence => empty result list; nothing is fabricated.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from app.core.config import Settings
from app.core.errors import EmbeddingUnavailable
from app.repositories.base import Store
from app.services.embeddings.base import EmbeddingError, EmbeddingProvider

log = logging.getLogger("app.retrieval")
_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
_HANGUL = re.compile(r"^[가-힣]+$")
_KO_PARTICLES = ("에서는", "으로는", "에서", "으로", "에는", "에게", "까지", "부터", "은", "는", "이", "가", "을", "를", "의", "에", "로", "와", "과", "도", "만")
_STOP = {"the", "a", "an", "of", "to", "for", "and", "or", "in", "on", "is", "are", "how", "do", "i", "my", "what", "can",
         "yang", "dan", "di", "ke", "untuk", "dengan", "apa", "bagaimana", "saya"}
MAX_TOKENS = 12


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

    def search(self, query: str, *, language: str | None = None, category: str | None = None, top_k: int = 5,
               mode: str = "hybrid") -> dict[str, Any]:
        top_k = min(max(top_k, 1), 20)
        tokens = query_tokens(query)
        warning: str | None = None
        embedding: list[float] | None = None
        effective = mode

        if mode in ("hybrid", "vector"):
            try:
                embedding = self.embedder.embed_query(query)
            except EmbeddingError as exc:
                if mode == "vector":
                    raise EmbeddingUnavailable(f"Vector search is unavailable: {exc}") from exc
                log.warning("embedding unavailable, falling back to keyword search: %s", exc)
                effective = "keyword"
                warning = f"Semantic search is unavailable ({exc}); showing keyword matches only."
        if effective == "keyword" and not tokens:
            return self._response(query, [], effective, warning)

        rows = self.store.rpc("search_knowledge", dict(
            p_query_embedding=embedding, p_query_tokens=tokens or None, p_model=self.embedder.model_id,
            p_category=category, p_match_count=top_k, p_mode=effective,
        ))
        min_sim = self.settings.retrieval_min_similarity
        results = []
        for r in rows or []:
            if min_sim and r.get("keyword_rank") is None and (r.get("similarity") or 0) < min_sim:
                continue  # semantic-only match below the evidence threshold
            results.append(dict(
                chunk_id=r["chunk_id"], document_id=r["document_id"], version_id=r["version_id"],
                document_title=r["document_title"], passage=r["passage"], heading=r.get("heading"), page=r.get("page"),
                similarity=r.get("similarity"), keyword_rank=r.get("keyword_rank"), score=r["score"],
                source_url=r.get("source_url"), organization=r["organization"], authority_type=r["authority_type"],
                scope=r["scope"], category=r["category"], source_published_at=r.get("source_published_at"),
                verified_at=r.get("verified_at"), language=r["language"],
            ))
        return self._response(query, results, effective, warning)

    def _response(self, query: str, results: list[dict[str, Any]], mode: str, warning: str | None) -> dict[str, Any]:
        return dict(query=query, results=results, retrieval=dict(
            mode=mode, embedding_model=self.embedder.model_id, total=len(results), warning=warning))
