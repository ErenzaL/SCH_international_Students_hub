"""Deterministic hashing-trick embeddings for tests/offline development ONLY.

These vectors capture lexical overlap (character n-grams), not meaning. They are
stored with embedding_model='hash-dev-384' so they can never be mixed with real
E5 vectors at query time (retrieval filters on the model id).
"""
from __future__ import annotations

import hashlib
import re

import numpy as np

from app.services.embeddings.base import l2_normalize

_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)


class HashEmbeddingProvider:
    model_id = "hash-dev-384"

    def __init__(self, dimensions: int = 384):
        self.dimensions = dimensions

    def _vec(self, text: str) -> np.ndarray:
        v = np.zeros(self.dimensions, dtype=np.float32)
        for tok in _TOKEN.findall(text.lower()):
            grams = {tok} | {tok[i : i + 3] for i in range(max(len(tok) - 2, 0))}
            for g in grams:
                h = int.from_bytes(hashlib.blake2b(g.encode(), digest_size=8).digest(), "big")
                v[h % self.dimensions] += 1.0 if h & (1 << 40) else -1.0
        return v

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return l2_normalize(np.stack([self._vec(t) for t in texts])).tolist()

    def embed_query(self, text: str) -> list[float]:
        return self.embed_passages([text])[0]
