"""Chunk + embed a document version and replace its chunks atomically (reusing unchanged embeddings).

Lifecycle (see docs/ingestion.md, "Automatic RAG synchronization"):
  ingestion  -> chunks only (``embed=False``) so reviewers can inspect them; nothing is embedded or searchable
  approval   -> durable ``index_version`` job -> chunk -> embed (bounded batches) -> validate -> atomic activation
Chunks of a version are always replaced in ONE database transaction (``replace_version_chunks``), so a failed
or retried run never leaves a partial or duplicated chunk set, and other versions are never touched.
"""
from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from app.core.config import Settings
from app.core.errors import EmbeddingUnavailable
from app.repositories.base import Query, Store, get_one
from app.services.chunking import ChunkerConfig, chunk_text, chunker_version
from app.services.document_titles import version_title
from app.services.embeddings.base import EmbeddingError, EmbeddingProvider
from app.services.ingestion.normalize import text_fingerprint

log = logging.getLogger("app.indexing")
EMBED_BATCH = 8  # texts per embedding call: bounds memory and gives progress/heartbeat points


class IndexingService:
    def __init__(self, store: Store, embedder: EmbeddingProvider, settings: Settings):
        self.store = store
        self.embedder = embedder
        self.settings = settings
        self.dimensions = settings.embedding_dimensions
        self.cfg = ChunkerConfig(settings.chunk_target_tokens, settings.chunk_max_tokens, settings.chunk_overlap_tokens,
                                 settings.chunker_version)

    def index_version(self, version_id: str, *, raise_on_embedding_error: bool = False, embed: bool | None = None,
                      progress: Callable[[int, int], None] | None = None) -> dict[str, Any]:
        """(Re)build chunks for a version. ``embed=None`` uses EMBED_ON_INGEST (pre-review content).

        Returns statistics incl. ``embedding_error`` when the model could not run.
        """
        embed = self.settings.embed_on_ingest if embed is None else embed
        version = get_one(self.store, "document_versions", id=version_id)
        if version is None:
            raise ValueError("version not found")
        doc = get_one(self.store, "source_documents", id=version["document_id"]) or {}
        title = version_title(version, doc)      # the title this version is published with, not the live one

        chunks = chunk_text(version["extracted_text"], self.cfg)
        inputs = [c.embedding_input(title) for c in chunks]
        hashes = [text_fingerprint(t) for t in inputs]

        # other versions' vectors are only reused when this run embeds (approval/activation); a pending version that is
        # only chunked for review keeps no vectors, exactly as before
        reuse, reused_from_other = self._reusable(version_id, version["document_id"], other_versions=bool(embed))
        vectors: dict[int, list[float]] = {}
        todo = [i for i, h in enumerate(hashes) if h not in reuse]
        error: str | None = None
        t0 = time.perf_counter()
        if embed and todo:
            try:
                for start in range(0, len(todo), EMBED_BATCH):
                    batch = todo[start: start + EMBED_BATCH]
                    vecs = self.embedder.embed_passages([inputs[i] for i in batch])
                    if len(vecs) != len(batch):
                        raise EmbeddingError(f"model returned {len(vecs)} vectors for {len(batch)} chunks")
                    for i, v in zip(batch, vecs, strict=True):
                        if len(v) != self.dimensions or not all(math.isfinite(x) for x in v):
                            raise EmbeddingError(f"invalid embedding for chunk {i} (dims {len(v)})")
                        vectors[i] = v
                    if progress:
                        progress(min(start + EMBED_BATCH, len(todo)), len(todo))
            except (EmbeddingError, MemoryError) as exc:
                error = f"{type(exc).__name__}: {exc}" if isinstance(exc, MemoryError) else str(exc)
                log.warning("embedding failed for version %s: %s", version_id, error)
                vectors.clear()  # never store a partially embedded set
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
                    chunk_strategy=chunker_version(self.cfg), embedding=emb,
                    embedding_model=self.embedder.model_id if emb is not None else None,
                )
            )
        # one transaction: the old chunk set stays until the new one is fully written
        self.store.rpc("replace_version_chunks", {"p_version_id": version_id,
                                                  "p_chunks": [{k: v for k, v in r.items() if k != "version_id"}
                                                               for r in rows]})
        embedded = sum(1 for r in rows if r["embedding"] is not None)
        if error is None:
            if rows and embedded == len(rows):
                self._mark(version_id, "indexed", None)
            elif not rows:
                self._mark(version_id, "failed", "No chunks were produced from this text.")
            else:
                self._mark(version_id, "not_indexed", None)
        return {
            "chunk_count": len(rows), "embedded_chunks": embedded, "failed_chunks": len(rows) - embedded,
            "reused_embeddings": len(rows) - len(todo),
            "reused_from_other_versions": sum(1 for h in hashes if h in reused_from_other),
            "embedding_model": self.embedder.model_id,
            "embedding_error": error, "embedding_ms": embedding_ms,
        }

    def _reusable(self, version_id: str, document_id: str, *, other_versions: bool = True
                  ) -> tuple[dict[str, list[float]], set[str]]:
        """Embeddings that can be reused, keyed by the hash of the exact embedding input (title + heading + text).

        Sources: this version's own chunks (re-index / retry) and the chunks of the document's other versions, so an
        updated document only embeds the chunks whose text actually changed. A vector is reused only when it was
        produced by the current embedding model and has the configured dimensions; other versions' chunks are read,
        never modified. Returns (hash -> embedding, hashes found only in other versions)."""
        model = self.embedder.model_id
        own, _ = self.store.select("document_chunks", Query(eq={"version_id": version_id}))
        reuse: dict[str, list[float]] = {}
        for e in own:
            vec = self._vector(e) if e.get("embedding_model") == model else None
            if vec is not None and e.get("content_hash"):
                reuse[e["content_hash"]] = vec
        others: set[str] = set()
        if not other_versions:
            return reuse, others
        try:
            versions, _ = self.store.select("document_versions", Query(eq={"document_id": document_id}, cols="id"))
            ids = [v["id"] for v in versions if v["id"] != version_id]
            if ids:
                rows, _ = self.store.select("document_chunks", Query(
                    in_={"version_id": ids}, eq={"embedding_model": model}, cols="content_hash,embedding,embedding_model"))
                for e in rows:
                    h, vec = e.get("content_hash"), self._vector(e)
                    if h and h not in reuse and vec is not None:
                        reuse[h] = vec
                        others.add(h)
        except Exception:  # noqa: BLE001 - reuse is an optimisation; on any error the chunks are embedded instead
            log.warning("could not load reusable embeddings from other versions of %s", document_id)
        return reuse, others

    def _vector(self, chunk: dict[str, Any]) -> list[float] | None:
        """A stored embedding as a list of floats, or None if absent/invalid. PostgREST returns pgvector columns as
        text ("[0.1,0.2,...]"); passing that string on to replace_version_chunks would store NULL, so parse it."""
        emb = chunk.get("embedding")
        if emb is None:
            return None
        try:
            if isinstance(emb, str):
                emb = [float(x) for x in emb.strip().strip("[]").split(",") if x.strip()]
            vec = [float(x) for x in emb]
        except (TypeError, ValueError):
            return None
        return vec if len(vec) == self.dimensions and all(math.isfinite(x) for x in vec) else None

    def _mark(self, version_id: str, status: str, error: str | None) -> None:
        patch: dict[str, Any] = {"indexing_status": status, "indexing_error": error}
        if status == "indexed":
            patch["indexed_at"] = datetime.now(UTC).isoformat()
        try:
            self.store.update("document_versions", patch, {"id": version_id})
        except Exception:  # noqa: BLE001 - status bookkeeping must not mask the real result
            log.warning("could not record indexing status for %s", version_id)

    def chunk_counts(self, version_id: str) -> tuple[int, int]:
        """(total chunks, chunks embedded by the current model) as stored in the database."""
        rows, _ = self.store.select("document_chunks", Query(eq={"version_id": version_id}, cols="id,embedding_model"))
        return len(rows), sum(1 for r in rows if r.get("embedding_model") == self.embedder.model_id)

    def ensure_indexed(self, version_id: str) -> None:
        """Make sure every chunk of the version has an embedding from the current model."""
        total, ok = self.chunk_counts(version_id)
        if total and total == ok:
            return
        self.index_version(version_id, raise_on_embedding_error=True, embed=True)
