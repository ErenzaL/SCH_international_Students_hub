"""Replaceable embedding provider interface."""
from __future__ import annotations

from typing import Protocol

import numpy as np


class EmbeddingError(Exception):
    """Model could not be loaded or run (network, missing dependency, ...)."""


class EmbeddingProvider(Protocol):
    model_id: str
    dimensions: int

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        """Embed document chunks (applies the provider's passage prefix). L2-normalized."""
        ...

    def embed_query(self, text: str) -> list[float]:
        """Embed a user query (applies the provider's query prefix). L2-normalized."""
        ...


def l2_normalize(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vectors / norms
