"""Stage 1 of the reranking experiments: frozen first-stage candidate pools (local, read-only).

For each question: the top-20 chunks from B0 (dense, production threshold 0.80) and from E2 (weighted hybrid,
<= 5 chunks per document), with everything the later stages need (text, scores, metadata for evidence selection)
and the first-stage latency. Every reranker then scores exactly the same candidates.

    cd backend && .venv/bin/python ../research/scripts/make_candidates.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))
os.environ.setdefault("EMBEDDING_PROVIDER", "e5_onnx")
sys.path.insert(0, str(ROOT / "research/scripts"))
from snapshot_paths import CORPUS, RESULTS, SNAPSHOT  # noqa: E402
POOL = 20   # RetrievalService.search caps top_k at 20 (backend); effective pool = 20
KEEP = ("chunk_id", "document_id", "version_id", "heading", "passage", "similarity", "keyword_rank", "lexical_coverage",
        "exact_match", "code_mismatch", "valid_until", "document_title", "language", "source_url", "organization",
        "authority_type", "verified_at", "is_stale", "page", "score")


def main() -> None:
    import eval_retrieval_benchmark as ev

    corpus = json.loads(CORPUS.read_text())
    svc, l2p, info = ev.build_index(corpus, 0.80)
    for ds in ("pilot_v0.1", "heldout_v0.2"):
        bench = json.loads((ROOT / f"research/data/benchmarks/retrieval_{ds}.json").read_text())
        out = (RESULTS / f"candidates_{ds}.jsonl").open("w", encoding="utf-8")
        for r in bench["records"]:
            row = dict(question_id=r["question_id"], scenario_id=r["scenario_id"], language=r["language"],
                       question=r["question"], dataset_version=r["dataset_version"])
            for name, kwargs in (("B0", dict(mode="vector")), ("B0F", dict(mode="vector")),
                                 ("E2", dict(mode="hybrid", max_per_document=5))):
                # B0F = dense with NO similarity threshold: always exactly 30 candidates (equal-size control pool)
                svc.retrieval.settings.retrieval_min_similarity = 0.0 if name == "B0F" else 0.80
                t0 = time.perf_counter()
                hits = svc.retrieval.search(r["question"], top_k=POOL, **kwargs)["results"]
                ms = (time.perf_counter() - t0) * 1000
                row[name] = dict(first_stage_ms=round(ms, 1), candidates=[
                    {k: h.get(k) for k in KEEP} | {"public_document_id": l2p.get(h["document_id"])} for h in hits])
            out.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        out.close()
        print("wrote", out.name)
    (RESULTS / "candidates.manifest.json").write_text(json.dumps(dict(
        snapshot=SNAPSHOT, pool=POOL, b0="dense top-20, threshold 0.80", b0f="dense top-20, no threshold (equal-size control)", e2="weighted hybrid top-20, <= 5 chunks per document",
        corpus_chunks=info["chunks"], embedding_model=info["embedding_model"]), indent=1))


if __name__ == "__main__":
    main()
