"""Research-grade retrieval evaluation: every metric, 95 % intervals, paired differences, per language and topic.

Reuses the production pipeline exactly as eval_retrieval_benchmark.py does (approved public corpus -> production chunker
-> production embedding model -> in-memory store -> RetrievalService.search). Read-only; no model is called.

    cd backend
    .venv/bin/python ../scripts/rag_research_eval.py --set dev      # retrieval_pilot_v0.1 (used during development)
    .venv/bin/python ../scripts/rag_research_eval.py --set heldout  # retrieval_heldout_v0.2 (never used for tuning)

Configurations (one index, the same queries):
  vector           dense retrieval only (multilingual-e5-small)
  hybrid_legacy    the hybrid ranking of `main` before Release A
  hybrid_nobridge  current hybrid ranking with the concept bridge switched off (RETRIEVAL_BRIDGE_WEIGHT=0)
  hybrid           current production configuration (hybrid + concept bridge 0.75)

Metrics (document level; a ranked list = the top-k chunks collapsed to distinct documents):
  Recall@k   share of questions with >= 1 relevant document in the first k documents
  MRR@10     mean 1/rank of the first relevant document (0 if not in the first 10)
  nDCG@k     graded: the most specific document (primary) gain 2, other relevant documents gain 1
  P@5        relevant documents among the first 5 / 5 (low by construction: most questions have 1-3 relevant docs)
  Top-1      the PRIMARY document is ranked first (stricter than Recall@1)
  coverage   share of the documents that are relevant to some question which are ranked first for at least one of them
Intervals: percentile bootstrap over questions (5,000 resamples, seed 7). Paired differences: the same resampled
questions for both configurations; "p_le_0" is the share of resamples in which the difference is <= 0.
The labels were drafted by an AI assistant and NOT reviewed by a person (see the dataset's provenance field).
"""
from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "backend"))
from eval_retrieval_benchmark import CACHE, DEFAULT_CORPUS, build_index  # noqa: E402

SETS = {"dev": ROOT / "scripts" / "benchmarks" / "retrieval_pilot_v0.1.json",
        "heldout": CACHE / "heldout_v0.2.json"}
LANGS = ("ko", "en", "id", "vi", "zh-CN")
KS = (1, 3, 5, 10)
RESULTS = ROOT / "scripts" / "benchmarks" / "results"
N_BOOT = 5000


def ranked_docs(svc, l2p, question: str, language: str, mode: str, top_k: int) -> tuple[list[str], float]:  # type: ignore[no-untyped-def]
    t0 = time.perf_counter()
    # one chunk per document for the weighted hybrid: the document order is the same (a document ranks by its best
    # chunk) and the list holds more distinct documents for Recall@10 / nDCG@10
    kw = {"max_per_document": 1} if mode == "hybrid" else {}
    res = svc.retrieval.search(question, language=language, top_k=top_k, mode=mode, **kw)
    ms = (time.perf_counter() - t0) * 1000
    return list(dict.fromkeys(l2p.get(h["document_id"]) for h in res["results"])), ms


def per_query(docs: list[str], expected: set[str], primary: str) -> dict:  # type: ignore[type-arg]
    rank = next((i + 1 for i, d in enumerate(docs) if d in expected), None)
    gain = lambda d: 2.0 if d == primary else (1.0 if d in expected else 0.0)  # noqa: E731
    ideal = sorted((gain(d) for d in expected), reverse=True)

    def ndcg(k: int) -> float:
        dcg = sum(gain(d) / math.log2(i + 2) for i, d in enumerate(docs[:k]))
        idcg = sum(g / math.log2(i + 2) for i, g in enumerate(ideal[:k]))
        return dcg / idcg if idcg else 0.0

    out = {f"recall@{k}": 1.0 if rank and rank <= k else 0.0 for k in KS}
    out.update({"mrr@10": 1.0 / rank if rank and rank <= 10 else 0.0, "ndcg@5": ndcg(5), "ndcg@10": ndcg(10),
                "p@5": sum(1 for d in docs[:5] if d in expected) / 5, "top1_primary": 1.0 if docs[:1] == [primary] else 0.0})
    return out | {"rank": rank}


METRICS = [f"recall@{k}" for k in KS] + ["mrr@10", "ndcg@5", "ndcg@10", "p@5", "top1_primary"]


def ci(values: list[float], rnd: random.Random) -> list[float]:
    if not values:
        return [0.0, 0.0]
    n = len(values)
    means = sorted(statistics.fmean(rnd.choices(values, k=n)) for _ in range(N_BOOT))
    return [round(means[int(0.025 * N_BOOT)], 3), round(means[int(0.975 * N_BOOT) - 1], 3)]


def summary(rows: list[dict], seed: int = 7) -> dict:  # type: ignore[type-arg]
    rnd = random.Random(seed)
    out: dict = {"n": len(rows)}  # type: ignore[type-arg]
    for m in METRICS:
        vals = [r[m] for r in rows]
        out[m] = round(statistics.fmean(vals), 3) if vals else None
        out[f"{m}_ci95"] = ci(vals, rnd)
    return out


def paired(a: list[dict], b: list[dict], metric: str, seed: int = 11) -> dict:  # type: ignore[type-arg]
    """b minus a over the same questions."""
    diffs = [y[metric] - x[metric] for x, y in zip(a, b, strict=True)]
    rnd = random.Random(seed)
    n = len(diffs)
    boots = sorted(statistics.fmean(rnd.choices(diffs, k=n)) for _ in range(N_BOOT))
    return dict(metric=metric, diff=round(statistics.fmean(diffs), 3),
                ci95=[round(boots[int(0.025 * N_BOOT)], 3), round(boots[int(0.975 * N_BOOT) - 1], 3)],
                p_le_0=round(sum(1 for x in boots if x <= 0) / N_BOOT, 4),
                better=sum(1 for d in diffs if d > 0), worse=sum(1 for d in diffs if d < 0), n=n)


def pct(xs: list[float], q: float) -> float:
    s = sorted(xs)
    return round(s[min(len(s) - 1, int(math.ceil(q * len(s))) - 1)], 1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", choices=list(SETS), required=True)
    ap.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    ap.add_argument("--min-sim", type=float, default=0.80)
    ap.add_argument("--top-k", type=int, default=10, help="passages retrieved; 10 = what the chatbot asks for (candidate pool 30)")
    a = ap.parse_args()
    bench = json.loads(SETS[a.set].read_text())
    records = bench["records"]
    corpus = json.loads(a.corpus.read_text())
    svc, l2p, info = build_index(corpus, a.min_sim)
    s = svc.retrieval.settings
    configs = {"vector": ("vector", {}), "hybrid_legacy": ("hybrid_legacy", {}),
               "hybrid_nobridge": ("hybrid", {"retrieval_bridge_weight": 0.0}), "hybrid": ("hybrid", {})}
    rows: dict[str, list[dict]] = {}  # type: ignore[type-arg]
    latency: dict[str, list[float]] = {}
    for name, (mode, over) in configs.items():
        saved = {k: getattr(s, k) for k in over}
        for k, v in over.items():
            setattr(s, k, v)
        for r in records[:3]:                                    # warm-up (model load, caches): not measured
            ranked_docs(svc, l2p, r["question"], r["language"], mode, a.top_k)
        rows[name], latency[name] = [], []
        for r in records:
            docs, ms = ranked_docs(svc, l2p, r["question"], r["language"], mode, a.top_k)
            q = per_query(docs, set(r["expected_document_ids"]), r["primary_document_id"])
            rows[name].append(q | dict(question_id=r["question_id"], language=r["language"], topic=r["category"],
                                       difficulty=r.get("difficulty"), top3=docs[:3], n_docs=len(docs)))
            latency[name].append(ms)
        for k, v in saved.items():
            setattr(s, k, v)
        print(f"{name:16} R@1 {statistics.fmean(x['recall@1'] for x in rows[name]):.3f}  "
              f"MRR {statistics.fmean(x['mrr@10'] for x in rows[name]):.3f}", flush=True)

    relevant_docs = {d for r in records for d in r["expected_document_ids"]}
    res: dict = {}  # type: ignore[type-arg]
    for name, rs in rows.items():
        first = {x["top3"][0] for x in rs if x["top3"]}
        res[name] = dict(
            overall=summary(rs),
            per_language={lg: summary([x for x in rs if x["language"] == lg]) for lg in LANGS},
            per_topic={t: summary([x for x in rs if x["topic"] == t]) for t in sorted({x["topic"] for x in rs})},
            per_difficulty={d: summary([x for x in rs if x["difficulty"] == d])
                            for d in sorted({str(x["difficulty"]) for x in rs})},
            coverage=dict(relevant_documents=len(relevant_docs),
                          ranked_first_somewhere=len(relevant_docs & first),
                          share=round(len(relevant_docs & first) / max(1, len(relevant_docs)), 3)),
            latency_ms=dict(p50=pct(latency[name], 0.50), p95=pct(latency[name], 0.95), max=round(max(latency[name]), 1)),
            distinct_documents_in_list=dict(median=statistics.median(x["n_docs"] for x in rs),
                                            min=min(x["n_docs"] for x in rs)),
            misses=[dict(question_id=x["question_id"], language=x["language"], topic=x["topic"], rank=x["rank"])
                    for x in rs if x["rank"] != 1])
    comparisons = [dict(a=x, b=y, **paired(rows[x], rows[y], m))
                   for x, y in (("vector", "hybrid"), ("hybrid_legacy", "hybrid"), ("hybrid_nobridge", "hybrid"))
                   for m in ("mrr@10", "recall@1", "ndcg@10")]
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    out = dict(set=a.set, dataset_version=bench["dataset_version"], provenance=bench.get("provenance"),
               questions=len(records), languages=dict(sorted({lg: sum(r["language"] == lg for r in records)
                                                              for lg in LANGS}.items())),
               at=datetime.now(UTC).isoformat(timespec="seconds"), git_commit=commit, index=info, top_k_chunks=a.top_k,
               settings=dict(retrieval_min_similarity=s.retrieval_min_similarity, vector_weight=s.retrieval_vector_weight,
                             keyword_weight=s.retrieval_keyword_weight, bridge_weight=s.retrieval_bridge_weight,
                             candidate_pool=s.retrieval_candidate_pool,
                             max_chunks_per_document=s.retrieval_max_chunks_per_document),
               bootstrap=dict(resamples=N_BOOT, seed=7, method="percentile, over questions"),
               latency_note="in-process (school server CPU, in-memory store): NOT the hosted latency",
               results=res, paired_differences=comparisons)
    path = RESULTS / f"rag_research_{a.set}.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n")
    print(f"\nwrote {path}")
    for c in comparisons:
        print(f"{c['b']} - {c['a']:16} {c['metric']:8} {c['diff']:+.3f} {c['ci95']} p<=0 {c['p_le_0']} "
              f"(better {c['better']}, worse {c['worse']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
