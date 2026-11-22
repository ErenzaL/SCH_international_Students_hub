from __future__ import annotations

from app.core.config import Settings
from app.services.embeddings.base import EmbeddingProvider
from app.services.embeddings.e5 import E5EmbeddingProvider
from app.services.embeddings.hash_provider import HashEmbeddingProvider


def build_embedding_provider(settings: Settings) -> EmbeddingProvider:
    kind = settings.embedding_provider.lower()
    if kind == "e5":
        return E5EmbeddingProvider(settings.embedding_model, settings.embedding_dimensions, settings.embedding_batch_size)
    if kind == "hash":
        return HashEmbeddingProvider(settings.embedding_dimensions)
    raise ValueError(f"Unknown EMBEDDING_PROVIDER '{settings.embedding_provider}' (use 'e5' or 'hash')")
