"""Chunk-quality experiment: one separate local in-memory index per guidebook variant (research only).

For every variant from pdf_chunk_variants.py: corpus_v2 with ONLY the guidebook text replaced -> production ingestion,
chunker (same settings) and embedding model (multilingual-e5-small ONNX int8) in an in-memory store -> the frozen
pilot v0.1 and held-out v0.2 questions with methods B0 / E1 / E2 / E2S (same code path as the corpus_v2 benchmark).
Production Supabase is never contacted. Outputs (research/data/experiments/chunking/results/):

  retrieval_<variant>.csv   one row per question x method (document ranking, top-10 documents, latency)
  passages_<variant>.jsonl  E2 top-5 passages per question (evidence completeness, error analysis)
  chunks_<variant>.csv      the guidebook's chunks (length, heading, pages, text)
  index_<variant>.json      index build statistics

    EMBEDDING_PROVIDER=e5_onnx backend/.venv/bin/python research/scripts/run_chunking_experiment.py
    ... --latency-only --reps 3     # re-time B0/E2 retrieval (no ranking change) on a quiet machine
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "research/scripts"))
os.environ.setdefault("EMBEDDING_PROVIDER", "e5_onnx")
EXP = ROOT / "research/data/experiments/chunking"
RES = EXP / "results"
DOC_ID = "d60bc363-0aae-44e5-b0c3-df8c61ad6f66"
VARIANTS = ["C0_existing", "C1_merge_short", "C2_paragraph", "C3_heading", "C4_table", "P1_prod_fixed_body"]
MODES = {"B0": "vector", "E1": "hybrid_legacy", "E2": "hybrid"}


def records() -> list[dict]:
    out = []
    for ds in ("pilot_v0.1", "heldout_v0.2"):
        out += json.loads((ROOT / f"research/data/benchmarks/retrieval_{ds}.json").read_text())["records"]
    return out


def main() -> None:
    import eval_retrieval_benchmark as ev
    from app.repositories.base import Query
    from run_retrieval_eval import FIELDS, _row

    ap = argparse.ArgumentParser()
    ap.add_argument("--variants", default=",".join(VARIANTS))
    ap.add_argument("--latency-only", action="store_true")
    ap.add_argument("--reps", type=int, default=3)
    a = ap.parse_args()
    RES.mkdir(parents=True, exist_ok=True)
    recs = records()
    for name in a.variants.split(","):
        corpus = json.loads((EXP / name / "corpus.json").read_text())
        t0 = time.perf_counter()
        svc, l2p, info = ev.build_index(corpus, 0.80)
        info["build_seconds"] = round(time.perf_counter() - t0, 1)
        p2l = {v: k for k, v in l2p.items()}
        if a.latency_only:
            lat: dict[str, list[float]] = {"B0": [], "E2": []}
            for m in lat:
                for r in recs:
                    for _ in range(a.reps):
                        t1 = time.perf_counter()
                        svc.retrieval.search(r["question"], top_k=10, mode=MODES[m])
                        lat[m].append((time.perf_counter() - t1) * 1000)
            out = {m: dict(n=len(v), median_ms=round(statistics.median(v), 2), p90_ms=round(sorted(v)[int(0.9 * len(v))], 2))
                   for m, v in lat.items()}
            (RES / f"latency_{name}.json").write_text(json.dumps(dict(variant=name, reps=a.reps, **out), indent=1))
            print(name, out, flush=True)
            continue
        # ---- the guidebook's chunks in this index
        doc = next(d for d in svc.store.select("source_documents")[0] if d["id"] == p2l[DOC_ID])
        chunks = svc.store.select("document_chunks", Query(eq={"version_id": doc["current_version_id"]},
                                                          order=[("chunk_index", False)]))[0]
        with (RES / f"chunks_{name}.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["chunk_index", "chars", "token_count", "heading", "page_start", "page_end",
                                              "embedded", "content"])
            w.writeheader()
            for c in chunks:
                w.writerow(dict(chunk_index=c["chunk_index"], chars=len(c["content"]), token_count=c.get("token_count"),
                                heading=c.get("heading") or "", page_start=c.get("page_start"), page_end=c.get("page_end"),
                                embedded=c.get("embedding") is not None, content=c["content"]))
        info.update(variant=name, guidebook_chunks=len(chunks))
        (RES / f"index_{name}.json").write_text(json.dumps(info, indent=1))
        # ---- retrieval
        eng = svc.conversations.engine
        rows, passages = [], []
        for m in ("B0", "E1", "E2", "E2S"):
            for r in recs:
                t1 = time.perf_counter()
                if m == "E2S":
                    found = eng._retrieve([r["question"]])
                    sources = eng._select(found["hits"], set(), r["question"])
                    docs = [l2p.get(s["document_id"]) for s in sources]
                else:
                    res = svc.retrieval.search(r["question"], top_k=10, mode=MODES[m])["results"]
                    docs = list(dict.fromkeys(l2p.get(h["document_id"]) for h in res))
                    if m == "E2":
                        passages.append(dict(question_id=r["question_id"], passages=[dict(
                            document_id=l2p.get(h["document_id"]), heading=h.get("heading"), page=h.get("page"),
                            similarity=h.get("similarity"), text=h.get("passage")) for h in res[:5]]))
                row = _row(r, m, docs, (time.perf_counter() - t1) * 1000, None)
                rows.append(dict(row, run_id=f"chunking-{name}", target="local", code_version="experiment",
                                 dataset_version=r["dataset_version"]))
        with (RES / f"retrieval_{name}.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(rows)
        with (RES / f"passages_{name}.jsonl").open("w", encoding="utf-8") as f:
            for p in passages:
                f.write(json.dumps(p, ensure_ascii=False, default=str) + "\n")
        print(name, json.dumps(info), flush=True)


if __name__ == "__main__":
    main()
