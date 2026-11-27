#!/usr/bin/env python3
"""A/B performance and memory check of the RAG v2 changes (Phase 10). Run each mode in its OWN process:

    backend/.venv/bin/python scripts/rag_v2/perf_check.py --mode rc     # release-candidate settings
    backend/.venv/bin/python scripts/rag_v2/perf_check.py --mode v2     # hub scaling 0.1 (+ gate / screens, always on)

Workload: index the corpus (production chunker + int8 e5), then 200 DEV + VALIDATION questions through
AssistantEngine.respond() without an LLM (rewrite and generation are network calls in production and unchanged).
Reported: peak RSS (getrusage), RSS after the workload, respond() latency p50 / p95, the size of the chunk-count cache
that hub scaling adds, and microbenchmarks of the new deterministic checks. The in-memory store keeps the vectors in
this process (production keeps them in PostgreSQL), so only the DIFFERENCE between the two modes carries over to the
API; absolute values are not Render's.
"""
from __future__ import annotations

import argparse
import json
import resource
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from lib import CORPUS, RESULTS, ROOT, git_rev, load_split  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "backend"))


def rss_mb() -> float:
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) / 1024
    return 0.0


def deep_size(obj, seen=None) -> int:  # type: ignore[no-untyped-def]
    seen = seen or set()
    if id(obj) in seen:
        return 0
    seen.add(id(obj))
    size = sys.getsizeof(obj)
    if isinstance(obj, dict):
        size += sum(deep_size(k, seen) + deep_size(v, seen) for k, v in obj.items())
    elif isinstance(obj, (list, tuple, set)):
        size += sum(deep_size(x, seen) for x in obj)
    return size


def bench(fn, n: int = 2000) -> float:  # type: ignore[no-untyped-def]
    t0 = time.perf_counter()
    for _ in range(n):
        fn()
    return round((time.perf_counter() - t0) / n * 1e6, 1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["rc", "v2"], required=True)
    a = ap.parse_args()
    from retrieval_eval import build_memory
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    rss0 = rss_mb()
    svc, _l2p, info = build_memory(corpus, 1)
    s = svc.retrieval.settings
    s.retrieval_hub_beta = 0.1 if a.mode == "v2" else 0.0
    s.assistant_evidence_gate = "log" if a.mode == "v2" else "off"
    engine = svc.conversations.engine
    records = [r for sp in ("dev", "val") for r in load_split(sp, {d["id"] for d in corpus})[0]]
    rss_index = rss_mb()
    for r in records[:5]:
        engine.respond(r["question"], language=r["language"])
    ms = []
    for r in records:
        t0 = time.perf_counter()
        engine.respond(r["question"], language=r["language"])
        ms.append((time.perf_counter() - t0) * 1000)
    out = dict(mode=a.mode, git=git_rev(), questions=len(records), index=info,
               rss_mb=dict(start=round(rss0), after_index=round(rss_index), after_workload=round(rss_mb()),
                           peak=round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)),
               respond_ms=dict(p50=round(statistics.median(ms), 1), p95=round(sorted(ms)[int(0.95 * len(ms)) - 1], 1),
                               mean=round(statistics.fmean(ms), 1)),
               chunk_count_cache_bytes=deep_size(svc.retrieval._sizes) if svc.retrieval._sizes else 0)
    if a.mode == "v2":
        from app.services.assistant.citation_check import check_citations
        from app.services.assistant.gate import evaluate_gate
        from app.services.assistant.injection import screen_passage
        found = engine._retrieve([records[0]["question"]], top_k=10)
        srcs = engine._select(found["hits"], set(), records[0]["question"])
        passages = [p for x in srcs for p in x["passages"]]
        answer = "Apply before your stay expires [1]. The fee is KRW 35,000 [2]. Report within 15 days [1]."
        out["microbench_us_per_call"] = dict(
            evaluate_gate=bench(lambda: evaluate_gate(passages, rewritten=True, settings=s)),
            check_citations=bench(lambda: check_citations(answer, srcs), 500),
            screen_passage_all_context=bench(lambda: [screen_passage(p["passage"]) for p in passages], 500))
    path = RESULTS / f"P1_perf_{a.mode}.json"
    path.write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
