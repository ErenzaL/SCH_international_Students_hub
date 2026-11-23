"""Retrieval evaluation runner -> one CSV row per (target, method, question).  READ-ONLY.

Targets
  local       the repository's retrieval code (working tree) on an in-memory index built with the production chunker
              and embedding model from the public corpus snapshot (backend/.eval-cache/public_corpus.json)
  production  the deployed public search API (real Supabase/pgvector index); nothing is written anywhere

Methods (see research/configs/experiments.json)
  B0   vector-only          mode=vector
  E1   original hybrid      mode=hybrid_legacy  (equal-weight RRF inside search_knowledge_v2)
  E2   improved hybrid      mode=hybrid         (weighted application-side fusion)
  E2S  E2 + the assistant's evidence selection (local only; original question only - no LLM query rewriting)

Run from backend/ with the backend virtualenv:
  .venv/bin/python ../research/scripts/run_retrieval_eval.py --target local \
      --dataset ../research/data/benchmarks/retrieval_heldout_v0.2.json --out ../research/data/results/retrieval_local_heldout.csv
"""
from __future__ import annotations

import argparse
import http.client
import csv
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))
FIELDS = ["run_id", "target", "code_version", "dataset_version", "method", "question_id", "scenario_id", "language",
          "category", "difficulty", "rank_first_relevant", "relevant_ranks", "n_relevant", "retrieved_documents",
          "latency_ms", "error"]
MODES = {"B0": "vector", "E1": "hybrid_legacy", "E2": "hybrid"}


def git_version() -> str:
    try:
        head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "backend/app"], cwd=ROOT, capture_output=True,
                               text=True).stdout.strip()
        return head + ("+working-tree" if dirty else "")
    except OSError:
        return "unknown"


def doc_ranks(doc_ids: list[str], expected: set[str]) -> list[int]:
    return [i + 1 for i, d in enumerate(doc_ids) if d in expected]


def run_local(records: list[dict], methods: list[str], top_k: int, corpus_path: Path) -> list[dict]:
    import eval_retrieval_benchmark as ev  # noqa: E402  (repository script)

    corpus = json.loads(corpus_path.read_text())
    svc, l2p, _info = ev.build_index(corpus, 0.80)
    eng = svc.conversations.engine
    rows = []
    for m in methods:
        for r in records:
            t0 = time.perf_counter()
            if m == "E2S":
                found = eng._retrieve([r["question"]])
                sources = eng._select(found["hits"], set(), r["question"])
                docs = [l2p.get(s["document_id"]) for s in sources]
            else:
                res = svc.retrieval.search(r["question"], top_k=top_k, mode=MODES[m])
                docs = list(dict.fromkeys(l2p.get(h["document_id"]) for h in res["results"]))
            rows.append(_row(r, m, docs, (time.perf_counter() - t0) * 1000, None))
    return rows


def warm_up(api: str, tries: int = 12) -> None:
    """Free Render instances sleep: wait until the API answers before timing anything."""
    for _ in range(tries):
        try:
            urllib.request.urlopen(api.rstrip("/") + "/health", timeout=60).read()
            return
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException):
            time.sleep(10)
    raise SystemExit("production API did not become healthy")


def run_production(records: list[dict], methods: list[str], top_k: int, api: str, pause: float) -> list[dict]:
    warm_up(api)
    rows = []
    for m in methods:
        if m not in MODES:
            continue
        for r in records:
            body = json.dumps({"query": r["question"], "top_k": top_k, "mode": MODES[m]}).encode()
            err, docs = None, []
            t0 = time.perf_counter()
            for attempt in range(3):
                try:
                    req = urllib.request.Request(api.rstrip("/") + "/api/v1/knowledge/search", data=body,
                                                 headers={"Content-Type": "application/json",
                                                          "User-Agent": "sch-hub-research-eval"})
                    res = json.load(urllib.request.urlopen(req, timeout=120))
                    docs = list(dict.fromkeys(h["document_id"] for h in res["results"]))
                    err = None
                    break
                except urllib.error.HTTPError as exc:
                    err = f"http_{exc.code}"
                    time.sleep(20 if exc.code == 429 else 3)
                    t0 = time.perf_counter()
                except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as exc:
                    err = type(exc).__name__
                    time.sleep(5)
                    t0 = time.perf_counter()
            rows.append(_row(r, m, docs, (time.perf_counter() - t0) * 1000, err))
            time.sleep(pause)
    return rows


def _row(r: dict, method: str, docs: list[str | None], ms: float, err: str | None) -> dict:
    expected = set(r["expected_document_ids"])
    ranks = doc_ranks([d for d in docs if d], expected)
    return dict(question_id=r["question_id"], scenario_id=r["scenario_id"], language=r["language"],
                category=r["category"], difficulty=r["difficulty"], method=method,
                rank_first_relevant=ranks[0] if ranks else "", relevant_ranks=json.dumps(ranks),
                n_relevant=len(expected), retrieved_documents=json.dumps([d for d in docs if d][:10]),
                latency_ms=round(ms, 1), error=err or "")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", choices=["local", "production"], required=True)
    ap.add_argument("--dataset", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--methods", default="B0,E1,E2,E2S")
    ap.add_argument("--top-k", type=int, default=10)
    ap.add_argument("--api", default="https://sch-hub-api.onrender.com")
    ap.add_argument("--pause", type=float, default=2.2, help="seconds between production requests (rate limit)")
    ap.add_argument("--corpus", type=Path, default=ROOT / "backend/.eval-cache/public_corpus.json",
                    help="local target: public corpus snapshot file (corpus_v1 = public_corpus.json)")
    ap.add_argument("--snapshot", default="corpus_v1", help="corpus snapshot label recorded in the manifest")
    a = ap.parse_args()
    os.environ.setdefault("EMBEDDING_PROVIDER", "e5_onnx")
    bench = json.loads(a.dataset.read_text())
    methods = a.methods.split(",")
    run_id = f"{a.target}-{bench['dataset_version']}-{dt.datetime.now(dt.UTC).strftime('%Y%m%dT%H%M%SZ')}"
    code = git_version() if a.target == "local" else os.environ.get("PRODUCTION_CODE_VERSION", "deployed (unknown commit)")
    rows = run_local(bench["records"], methods, a.top_k, a.corpus) if a.target == "local" else \
        run_production(bench["records"], methods, a.top_k, a.api, a.pause)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with a.out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for row in rows:
            w.writerow(dict(row, run_id=run_id, target=a.target, code_version=code,
                            dataset_version=bench["dataset_version"]))
    manifest = dict(run_id=run_id, target=a.target, code_version=code, dataset=str(a.dataset.name),
                    dataset_version=bench["dataset_version"],
                    dataset_sha256_16=hashlib.sha256(a.dataset.read_bytes()).hexdigest()[:16],
                    methods=methods, top_k=a.top_k, questions=len(bench["records"]), rows=len(rows),
                    errors=sum(1 for r in rows if r["error"]), finished_at=dt.datetime.now(dt.UTC).isoformat())
    manifest["snapshot"] = a.snapshot
    if a.target == "local":
        manifest["corpus_sha256_16"] = hashlib.sha256(a.corpus.read_bytes()).hexdigest()[:16]
    a.out.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=1))
    print(json.dumps(manifest))


if __name__ == "__main__":
    main()
