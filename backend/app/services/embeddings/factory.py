from __future__ import annotations

import importlib.util
import logging

from app.core.config import Settings
from app.services.embeddings.base import EmbeddingProvider
from app.services.embeddings.e5 import E5EmbeddingProvider
from app.services.embeddings.e5_onnx import E5OnnxEmbeddingProvider
from app.services.embeddings.hash_provider import HashEmbeddingProvider

log = logging.getLogger("app.embeddings")


def build_embedding_provider(settings: Settings) -> EmbeddingProvider:
    """``e5_onnx`` (int8 ONNX, fits 512 MB instances), ``e5`` (PyTorch fp32 via sentence-transformers),
    ``hash`` (lexical, development only). ``e5`` falls back to ``e5_onnx`` when sentence-transformers is not
    installed, so a deployment without requirements-ml.txt still gets real multilingual embeddings."""
    kind = settings.embedding_provider.lower()
    onnx = lambda: E5OnnxEmbeddingProvider(settings.embedding_model, settings.embedding_dimensions,  # noqa: E731
                                           settings.embedding_onnx_batch_size, settings.embedding_onnx_variant,
                                           settings.embedding_cache_dir or None, settings.embedding_threads or None)
    if kind == "e5_onnx":
        return onnx()
    if kind == "e5":
        if importlib.util.find_spec("sentence_transformers") is None:
            log.warning("sentence-transformers is not installed; using the ONNX E5 provider instead")
            return onnx()
        return E5EmbeddingProvider(settings.embedding_model, settings.embedding_dimensions, settings.embedding_batch_size)
    if kind == "hash":
        return HashEmbeddingProvider(settings.embedding_dimensions)
    raise ValueError(f"Unknown EMBEDDING_PROVIDER '{settings.embedding_provider}' (use 'e5_onnx', 'e5' or 'hash')")
