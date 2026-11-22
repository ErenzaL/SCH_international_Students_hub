"""intfloat/multilingual-e5-small via sentence-transformers (CPU, lazy-loaded).

E5 convention: prefix passages with ``passage: `` and questions with ``query: ``;
embeddings are L2-normalized so cosine similarity == dot product.
"""
from __future__ import annotations

import logging
import threading
from typing import Any

import numpy as np

from app.services.embeddings.base import EmbeddingError, l2_normalize

log = logging.getLogger("app.embeddings")


class E5EmbeddingProvider:
    def __init__(self, model_name: str = "intfloat/multilingual-e5-small", dimensions: int = 384, batch_size: int = 16):
        self.model_id = model_name
        self.dimensions = dimensions
        self.batch_size = batch_size
        self._model: Any | None = None
        self._lock = threading.Lock()

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def _load(self) -> Any:
        with self._lock:  # lazy: the model is only loaded on first use, never at API startup
            if self._model is None:
                try:
                    from sentence_transformers import SentenceTransformer
                except ImportError as exc:
                    raise EmbeddingError(
                        "sentence-transformers is not installed. Run `pip install -r requirements-ml.txt` "
                        "or set EMBEDDING_PROVIDER=hash for development only."
                    ) from exc
                try:
                    log.info("loading embedding model %s (first use)", self.model_id)
                    model = SentenceTransformer(self.model_id, device="cpu")
                except Exception as exc:  # noqa: BLE001 - network / disk / hub errors
                    raise EmbeddingError(f"Could not load embedding model '{self.model_id}': {exc}") from exc
                dim = model.get_sentence_embedding_dimension()
                if dim != self.dimensions:
                    raise EmbeddingError(
                        f"Model produces {dim}-d vectors but the database expects {self.dimensions}-d."
                    )
                self._model = model
            return self._model

    def _encode(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._load()
        try:
            vecs = model.encode(texts, batch_size=self.batch_size, convert_to_numpy=True, show_progress_bar=False)
        except Exception as exc:  # noqa: BLE001
            raise EmbeddingError(f"Embedding failed: {exc}") from exc
        return l2_normalize(np.asarray(vecs, dtype=np.float32)).tolist()

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return self._encode([f"passage: {t}" for t in texts])

    def embed_query(self, text: str) -> list[float]:
        return self._encode([f"query: {text}"])[0]
