"""Chunk + embed a document version and persist chunks (reusing unchanged embeddings)."""
from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Any

from app.core.config import Settings
from app.core.errors import EmbeddingUnavailable
from app.repositories.base import Query, Store, get_one
from app.services.chunking import CHUNKER_VERSION, ChunkerConfig, chunk_text
from app.services.embeddings.base import EmbeddingError, EmbeddingProvider
from app.services.ingestion.normalize import text_fingerprint

log = logging.getLogger("app.indexing")


class IndexingService:
    def __init__(self, store: Store, embedder: EmbeddingProvider, settings: Settings):
        self.store = store
        self.embedder = embedder
        self.cfg = ChunkerConfig(settings.chunk_target_tokens, settings.chunk_max_tokens, settings.chunk_overlap_tokens)

    def index_version(self, version_id: str, *, raise_on_embedding_error: bool = False) -> dict[str, Any]:
        """(Re)build chunks for a version. Chunks are always stored; embeddings are generated when possible.

        Returns statistics incl. ``embedding_error`` when the model could not run (the version then stays
        un-approvable until a successful 'reprocess').
        """
        version = get_one(self.store, "document_versions", id=version_id)
        if version is None:
            raise ValueError("version not found")
        doc = get_one(self.store, "source_documents", id=version["document_id"]) or {}
        title = doc.get("title") or ""

        chunks = chunk_text(version["extracted_text"], self.cfg)
        inputs = [c.embedding_input(title) for c in chunks]
        hashes = [text_fingerprint(t) for t in inputs]

        existing, _ = self.store.select("document_chunks", Query(eq={"version_id": version_id}))
        reuse = {
            e["content_hash"]: e["embedding"]
            for e in existing
            if e.get("embedding") is not None and e.get("embedding_model") == self.embedder.model_id
        }
        vectors: dict[int, list[float]] = {}
        todo = [i for i, h in enumerate(hashes) if h not in reuse]
        error: str | None = None
        t0 = time.perf_counter()
        if todo:
            try:
                new_vecs = self.embedder.embed_passages([inputs[i] for i in todo])
                vectors.update(dict(zip(todo, new_vecs, strict=True)))
            except (EmbeddingError, MemoryError) as exc:
                error = f"{type(exc).__name__}: {exc}" if isinstance(exc, MemoryError) else str(exc)
                log.warning("embedding failed for version %s: %s", version_id, error)
                self._mark(version_id, "failed", error)
                if raise_on_embedding_error:
                    raise EmbeddingUnavailable(error) from exc
        embedding_ms = int((time.perf_counter() - t0) * 1000)

        rows = []
        for i, c in enumerate(chunks):
            emb = reuse.get(hashes[i]) if hashes[i] in reuse else vectors.get(i)
            rows.append(
                dict(
                    version_id=version_id, chunk_index=c.index, heading=c.heading, content=c.content,
                    content_hash=hashes[i], token_count=c.token_count, page_start=c.page_start, page_end=c.page_end,
                    chunk_strategy=CHUNKER_VERSION, embedding=emb,
                    embedding_model=self.embedder.model_id if emb is not None else None,
                )
            )
        # embeddings are computed *before* replacing rows so the window without chunks is tiny
        self.store.delete("document_chunks", {"version_id": version_id})
        self.store.insert_many("document_chunks", rows)
        embedded = sum(1 for r in rows if r["embedding"] is not None)
        if error is None:
            self._mark(version_id, "indexed" if rows and embedded == len(rows) else "failed",
                       None if rows else "No chunks were produced from this text.")
        return {
            "chunk_count": len(rows), "embedded_chunks": embedded, "failed_chunks": len(rows) - embedded,
            "reused_embeddings": len(rows) - len(todo), "embedding_model": self.embedder.model_id,
            "embedding_error": error, "embedding_ms": embedding_ms,
        }

    def _mark(self, version_id: str, status: str, error: str | None) -> None:
        patch: dict[str, Any] = {"indexing_status": status, "indexing_error": error}
        if status == "indexed":
            patch["indexed_at"] = datetime.now(UTC).isoformat()
        try:
            self.store.update("document_versions", patch, {"id": version_id})
        except Exception:  # noqa: BLE001 - status bookkeeping must not mask the real result
            log.warning("could not record indexing status for %s", version_id)

    def ensure_indexed(self, version_id: str) -> None:
        """Make sure every chunk of the version has an embedding (used right before approval)."""
        chunks, _ = self.store.select("document_chunks", Query(eq={"version_id": version_id}))
        if chunks and all(c.get("embedding") is not None and c.get("embedding_model") == self.embedder.model_id
                          for c in chunks):
            return
        self.index_version(version_id, raise_on_embedding_error=True)
