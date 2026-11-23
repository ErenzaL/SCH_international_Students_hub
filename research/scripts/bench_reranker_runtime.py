"""Phase 4: can the mMiniLM cross-encoder run on limited CPU and memory? (local measurement, no production access)

Each variant runs in a FRESH process (peak memory is per process) on the real benchmark workload: every question of
the frozen held-out v0.2 set with its 20 first-stage E2 candidates (corpus_v2), i.e. realistic query
and passage lengths. Variants:
  torch_fp32   sentence-transformers CrossEncoder on CPU (the model used in Milestone 5; research/.venv-rerank)
  onnx_fp32    torch.onnx export, onnxruntime CPU                      (backend venv: what the API would run)
  onnx_opt     + onnxruntime transformer fusions (fp32)
  onnx_int8    + dynamic INT8 weight quantization (118 MB file)
Measured: model load time, RSS before/after load, peak RSS, per-query latency (20 pairs) at 1 and 2 threads,
throughput, scores (for ranking agreement and retrieval quality, computed in analyse()).
`api_footprint` loads the backend API modules + the production e5 int8 embedder first, then the int8 reranker, to
show the combined memory of one API process. Apple M1 timings are NOT Render timings (Render shares a slower vCPU).

    research/scripts/bench_reranker_runtime.py run       # all variants (sequential, quiet machine)
    research/scripts/bench_reranker_runtime.py analyse   # agreement + quality tables -> reports/production_readiness/
"""
from __future__ import annotations

import json
import os
import resource
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODELS = ROOT / "research/models/mminilm"
OUT = ROOT / "research/data/experiments/reranker_runtime"
PY_BACKEND = ROOT / "backend/.venv/bin/python"
PY_TORCH = ROOT / "research/.venv-rerank/bin/python"
HELDOUT = 100            # the held-out v0.2 questions come first in workload(); quality is reported on them
FILES = {"onnx_fp32": "model_fp32.onnx", "onnx_opt": "model_opt.onnx", "onnx_int8": "model_int8.onnx"}


def rss_mb() -> float:
    import psutil

    return psutil.Process().memory_info().rss / 2**20


def peak_mb() -> float:
    r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return r / 2**20 if sys.platform == "darwin" else r / 1024      # macOS reports bytes, Linux KiB


def workload(limit: int | None = None) -> list[dict]:
    sys.path.insert(0, str(ROOT / "research/scripts"))
    from jsonl_io import open_jsonl

    rows = []
    for ds in ("heldout_v0.2", "pilot_v0.1"):
        for line in open_jsonl(ROOT / f"research/data/results/corpus_v2/candidates_{ds}.jsonl"):
            r = json.loads(line)
            rows.append(dict(question_id=r["question_id"], dataset=ds, question=r["question"],
                             candidates=r["E2"]["candidates"][:20]))
    return rows[:limit] if limit else rows


def child(variant: str, threads: int, batch: int, limit: int | None) -> dict:
    os.environ["OMP_NUM_THREADS"] = str(threads)
    sys.path.insert(0, str(ROOT / "backend"))
    import numpy  # noqa: F401  (baseline includes numpy)

    work = workload(limit)
    base = rss_mb()
    t0 = time.perf_counter()
    if variant == "torch_fp32":
        import torch

        torch.set_num_threads(threads)
        sys.path.insert(0, str(ROOT / "research/scripts"))
        from reranking import CrossEncoderReranker, passage_text

        rr = CrossEncoderReranker("cross-encoder/mmarco-mMiniLMv2-L12-H384-v1", max_length=512, batch_size=batch)

        def score(q: str, cands: list[dict]) -> list[float]:
            return [float(x) for x in rr.model.predict([(q, passage_text(c)) for c in cands], batch_size=batch,
                                                       show_progress_bar=False)]
        rr.model.predict([("warm", "up")])
    else:
        from app.services.retrieval.rerank import OnnxCrossEncoderReranker, passage_text

        rr = OnnxCrossEncoderReranker(str(MODELS / FILES[variant]), str(MODELS / "sentencepiece.bpe.model"),
                                      batch_size=batch, threads=threads)
        rr.score("warm", ["up"])

        def score(q: str, cands: list[dict]) -> list[float]:
            return rr.score(q, [passage_text(c) for c in cands])
    load_s = time.perf_counter() - t0
    after_load = rss_mb()
    lat, scores = [], {}
    t_all = time.perf_counter()
    for w in work:
        t = time.perf_counter()
        scores[w["question_id"]] = score(w["question"], w["candidates"])
        lat.append((time.perf_counter() - t) * 1000)
    total_s = time.perf_counter() - t_all
    pairs = sum(len(w["candidates"]) for w in work)
    lat_sorted = sorted(lat)
    return dict(variant=variant, threads=threads, batch=batch, questions=len(work), pairs=pairs,
                load_seconds=round(load_s, 2), rss_before_mb=round(base), rss_after_load_mb=round(after_load),
                peak_rss_mb=round(peak_mb()), model_file_mb=round((MODELS / FILES[variant]).stat().st_size / 2**20)
                if variant in FILES else None,
                latency_ms=dict(median=round(lat_sorted[len(lat) // 2], 1), p90=round(lat_sorted[int(len(lat) * .9)], 1),
                                max=round(lat_sorted[-1], 1), mean=round(sum(lat) / len(lat), 1)),
                throughput=dict(queries_per_s=round(len(work) / total_s, 2), pairs_per_s=round(pairs / total_s, 1)),
                scores=scores)


def api_footprint(threads: int, batch: int) -> dict:
    """One API process: backend modules + production e5 int8 embedder (loaded), then + the int8 reranker."""
    sys.path.insert(0, str(ROOT / "backend"))
    os.environ.setdefault("EMBEDDING_PROVIDER", "e5_onnx")
    base = rss_mb()
    import app.main  # noqa: F401  (routes, services, pydantic models: what uvicorn imports)
    from app.services.embeddings.e5_onnx import E5OnnxEmbeddingProvider
    from app.services.retrieval.rerank import OnnxCrossEncoderReranker, passage_text

    modules = rss_mb()
    emb = E5OnnxEmbeddingProvider(threads=threads)
    emb.embed_query("외국인등록 기한")
    with_embedder = rss_mb()
    rr = OnnxCrossEncoderReranker(str(MODELS / FILES["onnx_int8"]), str(MODELS / "sentencepiece.bpe.model"),
                                  batch_size=batch, threads=threads)
    work = workload(40)
    t0 = time.perf_counter()
    rr.score("warm", ["up"])
    load_s = time.perf_counter() - t0
    after_load = rss_mb()
    lat = []
    for w in work:
        emb.embed_query(w["question"])
        t = time.perf_counter()
        rr.score(w["question"], [passage_text(c) for c in w["candidates"]])
        lat.append((time.perf_counter() - t) * 1000)
    return dict(variant="api_footprint", threads=threads, batch=batch, rss_python_mb=round(base),
                rss_api_modules_mb=round(modules), rss_with_e5_int8_mb=round(with_embedder),
                rss_with_e5_and_reranker_mb=round(after_load), peak_rss_mb=round(peak_mb()),
                reranker_load_seconds=round(load_s, 2), median_rerank_ms=round(sorted(lat)[len(lat) // 2], 1))


def run() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = [("onnx_int8", 1, 4), ("onnx_int8", 2, 4), ("onnx_int8", 1, 1), ("onnx_int8", 1, 20),
            ("onnx_opt", 1, 4), ("torch_fp32", 1, 4), ("torch_fp32", 2, 4)]
    for variant, threads, batch in jobs:
        name = f"{variant}_t{threads}_b{batch}"
        py = PY_TORCH if variant == "torch_fp32" else PY_BACKEND
        t0 = time.perf_counter()
        subprocess.run([str(py), __file__, "child", variant, str(threads), str(batch), str(OUT / f"{name}.json")],
                       check=True, env=dict(os.environ, TOKENIZERS_PARALLELISM="false"))
        r = json.loads((OUT / f"{name}.json").read_text())
        print(f"{name:22s} load {r['load_seconds']:5.1f}s  rss {r['rss_before_mb']}->{r['rss_after_load_mb']} MB "
              f"peak {r['peak_rss_mb']} MB  median {r['latency_ms']['median']} ms  p90 {r['latency_ms']['p90']} ms  "
              f"{r['throughput']['pairs_per_s']} pairs/s  ({time.perf_counter() - t0:.0f}s)", flush=True)
    for threads in (1, 2):
        subprocess.run([str(PY_BACKEND), __file__, "api", str(threads), "4", str(OUT / f"api_footprint_t{threads}.json")],
                       check=True)
        print(json.loads((OUT / f"api_footprint_t{threads}.json").read_text()), flush=True)


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "child":
        _, _, variant, threads, batch, out = sys.argv
        Path(out).write_text(json.dumps(child(variant, int(threads), int(batch), HELDOUT)))
    elif cmd == "api":
        _, _, threads, batch, out = sys.argv
        Path(out).write_text(json.dumps(api_footprint(int(threads), int(batch))))
    elif cmd == "run":
        run()
