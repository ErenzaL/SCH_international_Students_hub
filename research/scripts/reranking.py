"""Optional multilingual cross-encoder reranking interface (research only - not used by the backend or Render).

    rr = CrossEncoderReranker("BAAI/bge-reranker-v2-m3")
    ranked = rr.rerank("question", [{"heading": ..., "passage": ...}, ...])   # -> [(index, score), ...] best first

The interface takes the first-stage passages unchanged and returns their indices reordered by the cross-encoder score,
so any first stage (dense, hybrid) can be reranked and compared on identical candidates.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

MODELS = {
    # verified on the official model cards (see reports/milestone5 report): licence, size
    "bge-m3": dict(repo="BAAI/bge-reranker-v2-m3", license="apache-2.0", params="568M (0.6B)", base="bge-m3 / XLM-RoBERTa"),
    "mminilm": dict(repo="cross-encoder/mmarco-mMiniLMv2-L12-H384-v1", license="apache-2.0", params="118M (0.1B)",
                    base="multilingual MiniLMv2 (distilled from XLM-R Large)"),
}


def passage_text(c: dict) -> str:
    head = (c.get("heading") or "").strip()
    return f"{head}\n{c.get('passage') or ''}" if head else (c.get("passage") or "")


@dataclass
class CrossEncoderReranker:
    model_id: str
    max_length: int = 512
    batch_size: int = 16
    device: str = "cpu"
    load_seconds: float = field(init=False, default=0.0)

    def __post_init__(self) -> None:
        from sentence_transformers import CrossEncoder

        import torch

        t0 = time.perf_counter()
        self.model = CrossEncoder(self.model_id, max_length=self.max_length, device=self.device)
        # transformers memory-maps safetensors weights; on this Apple-silicon machine reading the mapped classifier
        # weights crashed the process natively (SIGBUS). Copying every tensor into ordinary memory avoids it and
        # leaves the values (and therefore the scores) unchanged.
        with torch.no_grad():
            for p in self.model.model.parameters():
                p.data = p.data.clone().contiguous()
            for b in self.model.model.buffers():
                b.data = b.data.clone()
        self.load_seconds = time.perf_counter() - t0

    def rerank(self, query: str, candidates: list[dict]) -> list[tuple[int, float]]:
        if not candidates:
            return []
        scores = self.model.predict([(query, passage_text(c)) for c in candidates], batch_size=self.batch_size,
                                    show_progress_bar=False)
        order = sorted(range(len(candidates)), key=lambda i: (-float(scores[i]), i))
        return [(i, float(scores[i])) for i in order]
