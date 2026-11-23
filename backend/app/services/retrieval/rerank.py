"""Optional cross-encoder reranking of first-stage hybrid results (OFF by default: RERANK_PROVIDER=none).

Research (Milestone 5) found one change with a supported accuracy gain: reranking the top 20 hybrid passages with
the multilingual cross-encoder ``cross-encoder/mmarco-mMiniLMv2-L12-H384-v1``. This module runs an ONNX export of
it with onnxruntime on CPU - no PyTorch - using the model's SentencePiece file with the XLM-R/fairseq id offset
(the same tokenization as the e5 embedding provider; ids verified identical to the HF tokenizer on benchmark pairs).

    RERANK_PROVIDER=onnx
    RERANK_MODEL_PATH=/models/mminilm/model_int8.onnx
    RERANK_TOKENIZER_PATH=/models/mminilm/sentencepiece.bpe.model

The model is loaded lazily on first use. A failure never breaks an answer: the caller keeps the first-stage order.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Protocol

import numpy as np

log = logging.getLogger("app.rerank")
BOS_ID, PAD_ID, EOS_ID, UNK_ID = 0, 1, 2, 3


class RerankError(RuntimeError):
    pass


def passage_text(h: dict[str, Any]) -> str:
    """What the cross-encoder reads: section heading + passage (as in the research evaluation)."""
    head = (h.get("heading") or "").strip()
    return f"{head}\n{h.get('passage') or ''}" if head else (h.get("passage") or "")


def _sp_ids(sp: Any, text: str) -> list[int]:
    return [i + 1 if i != 0 else UNK_ID for i in sp.encode(text)]


def encode_pair(sp: Any, query: str, passage: str, max_length: int = 512) -> list[int]:
    """XLM-R pair ids ``<s> q </s></s> p </s>`` with longest-first truncation (as the HF fast tokenizer)."""
    q, p = _sp_ids(sp, query), _sp_ids(sp, passage)
    budget = max_length - 4
    if len(q) + len(p) > budget:
        if len(q) <= budget // 2:
            p = p[: budget - len(q)]
        elif len(p) <= budget // 2:
            q = q[: budget - len(p)]
        else:
            q, p = q[: budget - budget // 2], p[: budget // 2]
    return [BOS_ID, *q, EOS_ID, EOS_ID, *p, EOS_ID]


class Reranker(Protocol):
    enabled: bool
    model_id: str

    def rerank(self, query: str, hits: list[dict[str, Any]], top_n: int) -> list[dict[str, Any]]: ...


class NoReranker:
    enabled = False
    model_id = "none"

    def rerank(self, query: str, hits: list[dict[str, Any]], top_n: int) -> list[dict[str, Any]]:
        return hits


class OnnxCrossEncoderReranker:
    enabled = True

    def __init__(self, model_path: str, tokenizer_path: str, *, model_id: str = "mmarco-mMiniLMv2-L12-H384-v1#onnx",
                 max_length: int = 512, batch_size: int = 4, threads: int = 1):
        self.model_path, self.tokenizer_path = model_path, tokenizer_path
        self.model_id = model_id
        self.max_length, self.batch_size, self.threads = max_length, max(1, batch_size), max(1, threads)
        self._session: Any | None = None
        self._sp: Any | None = None
        self._lock = threading.Lock()
        self.load_seconds: float | None = None

    @property
    def loaded(self) -> bool:
        return self._session is not None

    def _load(self) -> tuple[Any, Any]:
        with self._lock:
            if self._session is None:
                try:
                    import onnxruntime as ort
                    import sentencepiece as spm
                except ImportError as exc:
                    raise RerankError("onnxruntime / sentencepiece are not installed.") from exc
                t0 = time.perf_counter()
                try:
                    opts = ort.SessionOptions()
                    opts.intra_op_num_threads = self.threads
                    opts.inter_op_num_threads = 1
                    opts.enable_cpu_mem_arena = False        # memory-lean, as the embedding provider
                    opts.enable_mem_pattern = False
                    opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
                    session = ort.InferenceSession(self.model_path, sess_options=opts,
                                                   providers=["CPUExecutionProvider"])
                    sp = spm.SentencePieceProcessor(model_file=self.tokenizer_path)
                except Exception as exc:  # noqa: BLE001
                    raise RerankError(f"Could not load reranker '{self.model_id}': {exc}") from exc
                self._session, self._sp = session, sp
                self.load_seconds = round(time.perf_counter() - t0, 2)
                log.info("loaded reranker %s in %.1fs", self.model_id, self.load_seconds)
            return self._session, self._sp

    def score(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        session, sp = self._load()
        seqs = [encode_pair(sp, query, p, self.max_length) for p in passages]
        scores = np.zeros(len(seqs), dtype=np.float32)
        order = sorted(range(len(seqs)), key=lambda i: len(seqs[i]))      # similar lengths share a batch: less padding
        try:
            for b in range(0, len(order), self.batch_size):
                idx = order[b: b + self.batch_size]
                width = max(len(seqs[i]) for i in idx)
                ids = np.full((len(idx), width), PAD_ID, dtype=np.int64)
                mask = np.zeros((len(idx), width), dtype=np.int64)
                for r, i in enumerate(idx):
                    ids[r, : len(seqs[i])] = seqs[i]
                    mask[r, : len(seqs[i])] = 1
                logits = session.run(None, {"input_ids": ids, "attention_mask": mask})[0]
                scores[idx] = np.asarray(logits, dtype=np.float32).reshape(len(idx), -1)[:, 0]
        except MemoryError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise RerankError(f"Reranking failed: {exc}") from exc
        return [float(x) for x in scores]

    def rerank(self, query: str, hits: list[dict[str, Any]], top_n: int) -> list[dict[str, Any]]:
        """The first ``top_n`` hits reordered by cross-encoder score (ties keep first-stage order); the rest follow
        unchanged. Each reranked hit carries ``rerank_score`` and its ``first_stage_rank``."""
        head, tail = hits[:top_n], hits[top_n:]
        scores = self.score(query, [passage_text(h) for h in head])
        order = sorted(range(len(head)), key=lambda i: (-scores[i], i))
        return [dict(head[i], rerank_score=round(scores[i], 5), first_stage_rank=i + 1) for i in order] + tail


def build_reranker(settings: Any) -> Reranker:
    provider = (getattr(settings, "rerank_provider", "none") or "none").lower()
    if provider == "none":
        return NoReranker()
    if provider == "onnx":
        if not settings.rerank_model_path or not settings.rerank_tokenizer_path:
            raise ValueError("RERANK_PROVIDER=onnx needs RERANK_MODEL_PATH and RERANK_TOKENIZER_PATH")
        return OnnxCrossEncoderReranker(settings.rerank_model_path, settings.rerank_tokenizer_path,
                                        max_length=settings.rerank_max_length, batch_size=settings.rerank_batch_size,
                                        threads=settings.rerank_threads)
    raise ValueError(f"unknown RERANK_PROVIDER '{provider}' (use none or onnx)")
