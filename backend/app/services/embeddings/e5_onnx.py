"""intfloat/multilingual-e5-small via ONNX Runtime (CPU, no PyTorch).

Why: the fp32 PyTorch model needs ~470 MB of weights plus ~150 MB of torch runtime, which does not fit a
512 MB Render free instance. The official int8 ONNX export (``onnx/model_qint8_avx512_vnni.onnx``, ~118 MB)
runs with onnxruntime. Tokenization uses the model's SentencePiece file with the XLM-R/fairseq id offset
(identical ids to the HF tokenizer, verified) because the ``tokenizers`` Unigram model alone needs ~300 MB.

Same E5 recipe as sentence-transformers: ``query:`` / ``passage:`` prefixes, attention-masked mean pooling,
L2 normalization, 512-token truncation. Vectors are tagged with their own model id
(``intfloat/multilingual-e5-small#qint8``) so they are never compared with fp32 vectors.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

import numpy as np

from app.services.embeddings.base import EmbeddingError, l2_normalize

log = logging.getLogger("app.embeddings")
VARIANTS = {"qint8": "onnx/model_qint8_avx512_vnni.onnx", "fp32": "onnx/model.onnx", "o4": "onnx/model_O4.onnx"}
MAX_LENGTH = 512
BOS_ID, PAD_ID, EOS_ID, UNK_ID = 0, 1, 2, 3


class E5OnnxEmbeddingProvider:
    def __init__(self, model_name: str = "intfloat/multilingual-e5-small", dimensions: int = 384, batch_size: int = 1,
                 variant: str = "qint8", cache_dir: str | None = None, threads: int | None = None):
        if variant not in VARIANTS:
            raise ValueError(f"unknown ONNX variant '{variant}' (use {', '.join(VARIANTS)})")
        self.repo = model_name
        self.variant = variant
        self.model_id = f"{model_name}#{variant}"
        self.dimensions = dimensions
        self.batch_size = batch_size
        self.cache_dir = cache_dir or None
        self.threads = threads
        self._session: Any | None = None
        self._tokenizer: Any | None = None
        self._lock = threading.Lock()
        self.load_seconds: float | None = None

    @property
    def loaded(self) -> bool:
        return self._session is not None

    def download(self) -> tuple[str, str]:
        """Fetch (or reuse cached) model + tokenizer files. Used at build time by `python -m app.cli prefetch-model`."""
        try:
            from huggingface_hub import hf_hub_download
        except ImportError as exc:
            raise EmbeddingError("huggingface-hub is not installed (pip install -r requirements.txt).") from exc
        try:
            model_path = hf_hub_download(self.repo, VARIANTS[self.variant], cache_dir=self.cache_dir)
            tok_path = hf_hub_download(self.repo, "onnx/sentencepiece.bpe.model", cache_dir=self.cache_dir)
        except Exception as exc:  # noqa: BLE001 - network / disk / hub errors
            raise EmbeddingError(f"Could not download embedding model '{self.model_id}': {exc}") from exc
        return model_path, tok_path

    def _load(self) -> tuple[Any, Any]:
        with self._lock:  # lazy: loaded on first use, never at API startup
            if self._session is None:
                try:
                    import onnxruntime as ort
                    import sentencepiece as spm
                except ImportError as exc:
                    raise EmbeddingError("onnxruntime / sentencepiece are not installed (pip install -r requirements.txt).") from exc
                t0 = time.perf_counter()
                model_path, tok_path = self.download()
                try:
                    opts = ort.SessionOptions()
                    # memory-lean defaults for 512 MB instances (measured: ~440 MB steady with the API loaded):
                    # no arena (freed after each run), batch 1, few threads. Raise for bigger instances.
                    opts.intra_op_num_threads = self.threads or min(2, os.cpu_count() or 1)
                    opts.enable_cpu_mem_arena = False
                    opts.enable_mem_pattern = False
                    opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
                    session = ort.InferenceSession(model_path, sess_options=opts, providers=["CPUExecutionProvider"])
                    tok = spm.SentencePieceProcessor(model_file=tok_path)
                except Exception as exc:  # noqa: BLE001
                    raise EmbeddingError(f"Could not load embedding model '{self.model_id}': {exc}") from exc
                self._inputs = {i.name for i in session.get_inputs()}
                self._session, self._tokenizer = session, tok
                self.load_seconds = round(time.perf_counter() - t0, 2)
                log.info("loaded %s in %.1fs", self.model_id, self.load_seconds)
            return self._session, self._tokenizer

    def _encode(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        session, tok = self._load()
        out: list[np.ndarray] = []
        try:
            for i in range(0, len(texts), self.batch_size):
                seqs = [self._ids(tok, t) for t in texts[i: i + self.batch_size]]
                width = max(len(x) for x in seqs)
                ids = np.full((len(seqs), width), PAD_ID, dtype=np.int64)
                mask = np.zeros((len(seqs), width), dtype=np.int64)
                for r, seq in enumerate(seqs):
                    ids[r, : len(seq)] = seq
                    mask[r, : len(seq)] = 1
                feeds = {"input_ids": ids, "attention_mask": mask}
                if "token_type_ids" in self._inputs:
                    feeds["token_type_ids"] = np.zeros_like(ids)
                hidden = session.run(None, feeds)[0]  # (batch, seq, 384)
                m = mask[..., None].astype(np.float32)
                pooled = (hidden * m).sum(axis=1) / np.clip(m.sum(axis=1), 1e-9, None)
                out.append(pooled.astype(np.float32))
        except MemoryError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise EmbeddingError(f"Embedding failed: {exc}") from exc
        vecs = np.concatenate(out, axis=0)
        if vecs.shape[1] != self.dimensions:
            raise EmbeddingError(f"Model produces {vecs.shape[1]}-d vectors but the database expects {self.dimensions}-d.")
        return l2_normalize(vecs).tolist()

    @staticmethod
    def _ids(tok: Any, text: str) -> list[int]:
        """XLM-R ids: <s>=0, <pad>=1, </s>=2, <unk>=3; SentencePiece ids shifted by the fairseq offset (+1)."""
        pieces = [i + 1 if i != 0 else UNK_ID for i in tok.encode(text)][: MAX_LENGTH - 2]
        return [BOS_ID, *pieces, EOS_ID]

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return self._encode([f"passage: {t}" for t in texts])

    def embed_query(self, text: str) -> list[float]:
        return self._encode([f"query: {text}"])[0]
