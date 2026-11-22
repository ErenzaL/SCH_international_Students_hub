"""Retrieval benchmark on the REAL approved corpus (public Knowledge Center documents + published announcements).

Reproducible, read-only: the corpus is fetched from the public API (no credentials), indexed locally with the
production chunker + embedding model in an in-memory store, and every retrieval mode is evaluated on the same index:

    cd backend
    .venv/bin/python ../scripts/eval_retrieval_benchmark.py --fetch-corpus https://sch-hub-api.onrender.com
    .venv/bin/python ../scripts/eval_retrieval_benchmark.py --json ../scripts/benchmarks/results/retrieval.json

Metrics (document level; a query's ranked list is its top-k chunks collapsed to distinct documents in order):
  * Recall@k  - share of queries with at least one expected document among the first k documents
  * MRR       - mean of 1/rank of the first expected document (0 when absent from the top-k chunks)
  * Primary@1 - share of queries whose most specific expected document is ranked first
  * Code contamination@5 - for questions naming a visa code: share of the top-5 chunks that mention another code
    but not the asked one (e.g. E-7 / F-2-R passages for a D-2 question); lower is better
95% intervals are percentile bootstrap intervals over queries (2,000 resamples, fixed seed).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import statistics
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
CACHE = ROOT / "backend" / ".eval-cache"
DEFAULT_CORPUS = CACHE / "public_corpus.json"
DEFAULT_BENCH = ROOT / "scripts" / "benchmarks" / "retrieval_pilot_v0.1.json"
LANGS = ("ko", "en", "id", "vi", "zh-CN")


def fetch_corpus(api: str, path: Path) -> None:
    base = api.rstrip("/") + "/api/v1"

    def get(p: str) -> dict:  # type: ignore[type-arg]
        req = urllib.request.Request(base + p, headers={"User-Agent": "sch-hub-eval"})
        return json.load(urllib.request.urlopen(req, timeout=120))

    out = []
    for d in get("/knowledge/documents?size=100")["items"]:
        full = get(f"/knowledge/documents/{d['id']}")
        out.append({k: full.get(k) for k in ("id", "title", "category", "organization", "scope", "authority_type",
                                             "language", "source_url", "version_number", "content")} | {"kind": "document"})
    for a in get("/announcements?size=100")["items"]:
        full = get(f"/announcements/{a['id']}")
        out.append(dict(id=full.get("document_id") or full["id"], title=full["title"], category="university-announcements",
                        organization="SCH", scope="university", authority_type="official_university",
                        language=full.get("original_language") or "ko", source_url=full.get("evidence_url"),
                        content=full.get("body") or "", kind="announcement"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False))
    print(f"fetched {len(out)} items -> {path}")


def build_index(corpus: list[dict], min_sim: float):  # type: ignore[no-untyped-def,type-arg]
    from app.core.config import Settings
    from app.repositories.base import Query
    from app.repositories.memory_store import MemoryFileStorage, MemoryStore, seed_categories
    from app.services.container import build_services
    from app.services.embeddings.factory import build_embedding_provider
    from app.services.llm.base import NullLLMProvider

    settings = Settings(_env_file=None, embedding_provider=os.environ.get("EMBEDDING_PROVIDER", "e5_onnx"),
                        job_execution="inline", environment="test", supabase_jwt_secret="x" * 32,
                        retrieval_min_similarity=min_sim, min_extracted_chars=1)
    store = MemoryStore()
    seed_categories(store)
    emb = build_embedding_provider(settings)
    svc = build_services(settings, store, MemoryFileStorage(), emb, NullLLMProvider())
    admin = store.insert("profiles", dict(id="00000000-0000-0000-0000-00000000ad01", email="eval@example.test",
                                          display_name="Eval", role="admin"))
    local_to_public: dict[str, str] = {}
    t0 = time.perf_counter()
    for d in corpus:
        src = store.insert("knowledge_sources", dict(
            title=d["title"][:200], organization=d.get("organization") or "SCH", source_type="manual_text",
            authority_type=d.get("authority_type") or "official_university", scope=d.get("scope") or "university",
            category=d.get("category") or "daily-living", language=d.get("language") or "en",
            original_url=None))
        job = svc.ingestion.ingest_text(src, title=d["title"], text=d["content"], requested_by=admin["id"])
        v = store.select("document_versions", Query(eq={"id": job["version_id"]}))[0][0]
        if v["verification_status"] == "draft":
            store.update("document_versions", {"verification_status": "pending_review"}, {"id": v["id"]})
            v["verification_status"] = "pending_review"
        act = svc.ingestion.request_activation(v, admin["id"], "evaluation")
        svc.ingestion.run_job(act["id"])
        local_to_public[job["document_id"]] = d["id"]
    chunks = store.select("document_chunks", Query())[0]
    info = dict(index_seconds=round(time.perf_counter() - t0, 1), documents=len(corpus), chunks=len(chunks),
                embedded_chunks=sum(1 for c in chunks if c.get("embedding") is not None), embedding_model=emb.model_id,
                chunk_target_tokens=settings.chunk_target_tokens, chunk_max_tokens=settings.chunk_max_tokens,
                chunk_overlap_tokens=settings.chunk_overlap_tokens)
    return svc, local_to_public, info


def bootstrap(values: list[float], n: int = 2000, seed: int = 7) -> tuple[float, float]:
    if not values:
        return (0.0, 0.0)
    rnd = random.Random(seed)
    means = sorted(statistics.fmean(rnd.choices(values, k=len(values))) for _ in range(n))
    return (round(means[int(0.025 * n)], 3), round(means[int(0.975 * n) - 1], 3))


def evaluate(svc, l2p: dict[str, str], records: list[dict], mode: str, top_k: int) -> dict:  # type: ignore[no-untyped-def,type-arg]
    from app.services.retrieval.query_analysis import code_matches, find_codes, normalize_codes

    rows = []
    for r in records:
        t0 = time.perf_counter()
        res = svc.retrieval.search(r["question"], language=r["language"], top_k=top_k, mode=mode)
        ms = (time.perf_counter() - t0) * 1000
        hits = res["results"]
        docs = list(dict.fromkeys(l2p.get(h["document_id"]) for h in hits))
        expected = set(r["expected_document_ids"])
        rank = next((i + 1 for i, d in enumerate(docs) if d in expected), None)
        contamination = None
        if r.get("asked_codes"):
            asked = set(r["asked_codes"])
            top5 = hits[:5]
            bad = [h for h in top5 if (cs := find_codes(normalize_codes(h["passage"] or ""))) and not code_matches(asked, cs)]
            contamination = len(bad) / len(top5) if top5 else 0.0
        rows.append(dict(question_id=r["question_id"], scenario_id=r["scenario_id"], language=r["language"],
                         rank=rank, primary_first=bool(docs) and docs[0] == r["primary_document_id"],
                         contamination=contamination, latency_ms=round(ms, 1),
                         top_titles=[h["document_title"] for h in hits[:3]]))

    def agg(rs: list[dict]) -> dict:  # type: ignore[type-arg]
        r1 = [1.0 if x["rank"] == 1 else 0.0 for x in rs]
        r5 = [1.0 if x["rank"] and x["rank"] <= 5 else 0.0 for x in rs]
        rr = [1.0 / x["rank"] if x["rank"] else 0.0 for x in rs]
        p1 = [1.0 if x["primary_first"] else 0.0 for x in rs]
        cont = [x["contamination"] for x in rs if x["contamination"] is not None]
        return dict(n=len(rs), recall_at_1=round(statistics.fmean(r1), 3), recall_at_5=round(statistics.fmean(r5), 3),
                    mrr=round(statistics.fmean(rr), 3), primary_at_1=round(statistics.fmean(p1), 3),
                    code_contamination_at_5=round(statistics.fmean(cont), 3) if cont else None,
                    ci95=dict(recall_at_1=bootstrap(r1), recall_at_5=bootstrap(r5), mrr=bootstrap(rr)))

    lat = sorted(x["latency_ms"] for x in rows)
    return dict(mode=mode, overall=agg(rows), per_language={lg: agg([x for x in rows if x["language"] == lg]) for lg in LANGS},
                latency_ms=dict(mean=round(statistics.fmean(lat), 1), p95=lat[int(0.95 * (len(lat) - 1))],
                                note="local in-memory store; excludes network/database time"),
                misses=[x for x in rows if x["rank"] != 1])


def threshold_study(svc, l2p: dict[str, str], records: list[dict]) -> list[dict]:  # type: ignore[no-untyped-def,type-arg]
    """Vector-only similarities of relevant vs irrelevant chunks (top 20, no threshold) -> effect of a cut-off."""
    saved = svc.retrieval.settings.retrieval_min_similarity
    svc.retrieval.settings.retrieval_min_similarity = 0.0
    best_rel, irrelevant = [], []
    for r in records:
        hits = svc.retrieval.search(r["question"], top_k=20, mode="vector")["results"]
        exp = set(r["expected_document_ids"])
        rel = [h["similarity"] for h in hits if l2p.get(h["document_id"]) in exp]
        best_rel.append(max(rel) if rel else None)
        irrelevant += [h["similarity"] for h in hits if l2p.get(h["document_id"]) not in exp]
    svc.retrieval.settings.retrieval_min_similarity = saved
    out = []
    for t in (0.76, 0.78, 0.80, 0.82, 0.84):
        kept = sum(1 for s in best_rel if s is not None and s >= t)
        out.append(dict(threshold=t, queries_keeping_a_relevant_chunk=round(kept / len(records), 3),
                        irrelevant_chunks_removed=round(sum(1 for s in irrelevant if s < t) / max(1, len(irrelevant)), 3)))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch-corpus", metavar="API_BASE")
    ap.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    ap.add_argument("--benchmark", type=Path, default=DEFAULT_BENCH)
    ap.add_argument("--modes", default="vector,hybrid_legacy,hybrid")
    ap.add_argument("--top-k", type=int, default=5)
    ap.add_argument("--min-sim", type=float, default=0.80, help="RETRIEVAL_MIN_SIMILARITY (production: 0.80)")
    ap.add_argument("--json", type=Path)
    a = ap.parse_args()
    if a.fetch_corpus:
        fetch_corpus(a.fetch_corpus, a.corpus)
        return
    corpus = json.loads(a.corpus.read_text())
    bench = json.loads(a.benchmark.read_text())
    svc, l2p, info = build_index(corpus, a.min_sim)
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    except OSError:
        commit = None
    s = svc.retrieval.settings
    out = dict(benchmark=bench["dataset_version"], review_status="draft_unreviewed (AI-drafted labels)",
               queries=len(bench["records"]), corpus_sha256=hashlib.sha256(a.corpus.read_bytes()).hexdigest()[:16],
               git_commit=commit, index=info, top_k=a.top_k,
               settings=dict(retrieval_min_similarity=s.retrieval_min_similarity, fusion=s.retrieval_fusion,
                             vector_weight=s.retrieval_vector_weight, keyword_weight=s.retrieval_keyword_weight,
                             candidate_pool=s.retrieval_candidate_pool,
                             max_chunks_per_document=s.retrieval_max_chunks_per_document,
                             code_mismatch_penalty=s.retrieval_code_mismatch_penalty),
               results=[evaluate(svc, l2p, bench["records"], m, a.top_k) for m in a.modes.split(",")],
               threshold_study=threshold_study(svc, l2p, bench["records"]))
    print(f"index: {info['documents']} docs, {info['chunks']} chunks ({info['embedded_chunks']} embedded) with "
          f"{info['embedding_model']} in {info['index_seconds']} s; {out['queries']} queries; min_sim={a.min_sim}")
    for res in out["results"]:
        o = res["overall"]
        print(f"\n== {res['mode']}: R@1 {o['recall_at_1']:.3f} {o['ci95']['recall_at_1']}  R@5 {o['recall_at_5']:.3f}  "
              f"MRR {o['mrr']:.3f} {o['ci95']['mrr']}  Primary@1 {o['primary_at_1']:.3f}  "
              f"code-contamination@5 {o['code_contamination_at_5']}  latency {res['latency_ms']['mean']} ms")
        print(f"   {'lang':6} {'n':>3} {'R@1':>6} {'R@5':>6} {'MRR':>6} {'P@1':>6}")
        for lg in LANGS:
            p = res["per_language"][lg]
            print(f"   {lg:6} {p['n']:>3} {p['recall_at_1']:>6.3f} {p['recall_at_5']:>6.3f} {p['mrr']:>6.3f} "
                  f"{p['primary_at_1']:>6.3f}")
    print("\nthreshold study (vector leg, top-20 without threshold):")
    for t in out["threshold_study"]:
        print(f"   >= {t['threshold']:.2f}: queries keeping a relevant chunk {t['queries_keeping_a_relevant_chunk']:.3f}, "
              f"irrelevant chunks removed {t['irrelevant_chunks_removed']:.3f}")
    if a.json:
        a.json.parent.mkdir(parents=True, exist_ok=True)
        a.json.write_text(json.dumps(out, ensure_ascii=False, indent=1))
        print(f"\nwrote {a.json}")


if __name__ == "__main__":
    main()
