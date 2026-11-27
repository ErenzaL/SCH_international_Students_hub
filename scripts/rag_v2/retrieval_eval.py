#!/usr/bin/env python3
"""RAG v2 retrieval evaluation: the production pipeline on DEV / VALIDATION / TEST, in memory or on real PostgreSQL.

    backend/.venv/bin/python scripts/rag_v2/retrieval_eval.py --split dev --configs baseline,vector --tag e1
    backend/.venv/bin/python scripts/rag_v2/retrieval_eval.py --split val --backend postgres --tag e2   # needs SCH_IT_*
    ... --split test --final   # TEST only in the final pre-registered run (logged in EXPERIMENT-LOG.md)

For every question and configuration two things are measured:
  1. document ranking: RetrievalService.search(question, top_k=10) (one passage per document for the weighted hybrid,
     as scripts/rag_research_eval.py does, so the list holds up to 10 distinct documents);
  2. what the answer model would read: AssistantEngine._retrieve([question]) + _select() with the production limits
     (4 sources x 3 passages, 9,000 characters). This is the path WITHOUT the LLM query rewrite (no Gemini key here):
     the same path production takes when the rewrite fails or no LLM is configured.
Passage-level metrics need gold quotes (TEST). Backends:
  memory    the in-memory store mirror (exact cosine; keyword leg = substring hits). Chunk ids come from a seeded
            generator (--seed) so equal scores break the same way in every run.
  postgres  SupabaseStore -> PostgREST -> PostgreSQL + pgvector (HNSW) with the real migrations: the SQL that
            production runs. Start a scratch stack with scripts/scratch_db.sh and `source DIR/env`.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import shlex
import statistics
import subprocess
import sys
import time
import types
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from configs import resolve  # noqa: E402
from lib import (CORPUS, DOC_METRICS, PASSAGE_METRICS, RESULTS, ROOT, breakdowns, doc_metrics, git_rev, load_split,  # noqa: E402
                 norm, paired, passage_metrics, pct, sha256_file, summarize)

sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "backend"))


# ------------------------------------------------------------------------------------------------ indexes
def seed_memory_ids(seed: int) -> None:
    import app.repositories.memory_store as ms
    rng = random.Random(seed)
    ms.uuid = types.SimpleNamespace(uuid4=lambda: uuid.UUID(int=rng.getrandbits(128), version=4))  # type: ignore[attr-defined]


def build_memory(corpus: list[dict[str, Any]], seed: int):  # type: ignore[no-untyped-def]
    seed_memory_ids(seed)
    from eval_retrieval_benchmark import build_index
    svc, l2p, info = build_index(corpus, 0.80)
    return svc, l2p, info | {"backend": "memory", "id_seed": seed}


PG_MAP = ROOT / "backend" / ".eval-cache" / "rag_v2_pg_index.json"   # id map of the index on the scratch stack


def build_postgres(corpus: list[dict[str, Any]], reuse: bool = False):  # type: ignore[no-untyped-def]
    import jwt

    from app.core.config import Settings
    from app.repositories.base import Query
    from app.repositories.memory_store import MemoryFileStorage
    from app.repositories.supabase_store import SupabaseStore
    from app.services.container import build_services
    from app.services.embeddings.factory import build_embedding_provider
    from app.services.llm.base import NullLLMProvider

    rest, psql, secret = (os.environ.get(k) for k in ("SCH_IT_REST_URL", "SCH_IT_PSQL", "SCH_IT_JWT_SECRET"))
    if not (rest and psql and secret):
        raise SystemExit("postgres backend: start scripts/scratch_db.sh with POSTGREST and `source DIR/env` first")

    def sql(stmt: str) -> str:
        out = subprocess.run(shlex.split(psql) + ["-v", "ON_ERROR_STOP=1", "-c", stmt], capture_output=True, text=True)
        if out.returncode:
            raise SystemExit(f"psql failed: {out.stderr.strip()[:300]}")
        return out.stdout.strip()

    indexed = int(sql("select count(*) from public.document_chunks where embedding is not null") or 0)
    if indexed:
        # an index built earlier by this script on this stack: reuse it when its id map is still valid
        saved = json.loads(PG_MAP.read_text()) if PG_MAP.exists() else {}
        if not reuse or saved.get("chunks") != indexed or saved.get("corpus_sha256") != sha256_file(CORPUS):
            raise SystemExit("the scratch database already holds indexed chunks: use a fresh scratch stack, or "
                             "--reuse-index for an index this script built from the same corpus")
        key = jwt.encode({"role": "service_role", "exp": int(time.time()) + 6 * 3600}, secret, algorithm="HS256")
        settings = Settings(_env_file=None, supabase_url=rest, supabase_service_role_key=key, supabase_jwt_secret=secret,
                            embedding_provider=os.environ.get("EMBEDDING_PROVIDER", "e5_onnx"), job_execution="inline",
                            environment="test", retrieval_min_similarity=0.80, min_extracted_chars=1)
        store = SupabaseStore(settings)
        svc = build_services(settings, store, MemoryFileStorage(), build_embedding_provider(settings), NullLLMProvider())
        return svc, saved["l2p"], saved["info"] | {"reused": True}
    # the migrations' sample rows ("[SAMPLE - TEST DATA]", no embedding) are not in production: keep them out of the
    # keyword leg
    seed_removed = int(sql("with d as (delete from public.document_chunks where embedding is null returning 1) "
                           "select count(*) from d") or 0)
    key = jwt.encode({"role": "service_role", "exp": int(time.time()) + 6 * 3600}, secret, algorithm="HS256")
    settings = Settings(_env_file=None, supabase_url=rest, supabase_service_role_key=key, supabase_jwt_secret=secret,
                        embedding_provider=os.environ.get("EMBEDDING_PROVIDER", "e5_onnx"), job_execution="inline",
                        environment="test", retrieval_min_similarity=0.80, min_extracted_chars=1,
                        rate_limit_ingest_per_minute=100000, rate_limit_search_per_minute=100000)
    store = SupabaseStore(settings)
    emb = build_embedding_provider(settings)
    svc = build_services(settings, store, MemoryFileStorage(), emb, NullLLMProvider())
    uid = str(uuid.uuid4())
    sql(f"insert into auth.users (id, email) values ('{uid}', 'rag-eval-{uid[:6]}@example.test')")
    sql(f"update public.profiles set role = 'admin' where id = '{uid}'")
    l2p: dict[str, str] = {}
    t0 = time.perf_counter()
    for d in corpus:
        src = store.insert("knowledge_sources", dict(
            title=d["title"][:200], organization=d.get("organization") or "SCH", source_type="manual_text",
            authority_type=d.get("authority_type") or "official_university", scope=d.get("scope") or "university",
            category=d.get("category") or "daily-living", language=d.get("language") or "en", original_url=None))
        job = svc.ingestion.ingest_text(src, title=d["title"], text=d["content"], requested_by=uid)
        v = store.select("document_versions", Query(eq={"id": job["version_id"]}))[0][0]
        if v["verification_status"] == "draft":
            store.update("document_versions", {"verification_status": "pending_review"}, {"id": v["id"]})
            v["verification_status"] = "pending_review"
        act = svc.ingestion.request_activation(v, uid, "evaluation")
        svc.ingestion.run_job(act["id"])
        l2p[job["document_id"]] = d["id"]
    n = int(sql("select count(*) from public.searchable_chunks"))
    info = dict(backend="postgres", index_seconds=round(time.perf_counter() - t0, 1), documents=len(corpus),
                chunks=int(sql("select count(*) from public.document_chunks")), searchable_chunks=n,
                embedding_model=emb.model_id, pg_version=sql("show server_version"),
                pgvector=sql("select extversion from pg_extension where extname = 'vector'"),
                hnsw_ef_search=sql("select coalesce(current_setting('hnsw.ef_search', true), '40 (pgvector default)')"), removed_sample_chunks=seed_removed)
    PG_MAP.write_text(json.dumps(dict(chunks=info["chunks"], corpus_sha256=sha256_file(CORPUS), l2p=l2p, info=info)))
    return svc, l2p, info


def quote_coverage(svc, l2p: dict[str, str], records: list[dict[str, Any]]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    """Can each gold quote be found inside ONE chunk at all (a quote across a chunk boundary can never be a hit)?"""
    from app.repositories.base import Query
    rows, _ = svc.store.select("document_chunks", Query(cols="document_id,heading,content", limit=100000))
    by_doc: dict[str, list[str]] = {}
    for c in rows:
        by_doc.setdefault(l2p.get(c["document_id"], c["document_id"]), []).append(norm(f"{c.get('heading') or ''}\n{c['content']}"))
    quotes = {(q["document_id"], q["quote"]) for r in records for q in r["quotes"]}
    split = sorted(f"{d[:8]}: {q[:70]}" for d, q in quotes if not any(q in t for t in by_doc.get(d, [])))
    return dict(quotes=len(quotes), within_one_chunk=len(quotes) - len(split), across_chunks=split)


# ---------------------------------------------------------------------------------------------- evaluation
def passage_text(h: dict[str, Any]) -> str:
    return f"{h.get('heading') or ''}\n{h.get('passage') or ''}"


REWRITE_CACHE = ROOT / "backend" / ".eval-cache" / "rag_v2_rewrites.json"
F_KEYS = ("hit@1", "hit@3", "hit@10", "mrr", "mrr_len", "ndcg@10", "rank")


class Rewriter:
    """The engine's own rewrite step (_queries) with a local model on loopback Ollama, cached per question."""

    def __init__(self, model: str) -> None:
        from app.services.llm.ollama import OllamaProvider
        self.model = model
        self.llm = OllamaProvider(model, temperature=0.0, seed=7, keep_alive="30m")
        self.cache: dict[str, Any] = json.loads(REWRITE_CACHE.read_text(encoding="utf-8")) if REWRITE_CACHE.exists() else {}
        self.calls = 0

    def queries(self, engine, question: str) -> tuple[list[str], dict[str, Any]]:  # type: ignore[no-untyped-def]
        key = f"{self.model}\u241f{question}"
        if key not in self.cache:
            saved, engine.llm = engine.llm, self.llm
            try:
                t0 = time.perf_counter()
                qs, info = engine._queries(question, [], use_llm=True)
                info = {k: v for k, v in info.items() if isinstance(v, (str, int, float, bool, type(None)))}
                self.cache[key] = dict(queries=qs, info=info, ms=round((time.perf_counter() - t0) * 1000))
                self.calls += 1
            finally:
                engine.llm = saved
            REWRITE_CACHE.write_text(json.dumps(self.cache, ensure_ascii=False, indent=0), encoding="utf-8")
        c = self.cache[key]
        return list(c["queries"]), dict(c["info"])


def make_queries(cfg: dict[str, Any], r: dict[str, Any], siblings: dict[str, dict[str, str]], engine,  # type: ignore[no-untyped-def]
                 rewriter: Rewriter | None) -> tuple[list[str], bool]:
    """Retrieval queries for the assistant stage. Returns (queries, rewritten): rewritten turns the bridge off, as
    production does after a successful rewrite."""
    v = cfg.get("variants")
    q = r["question"]
    if not v:
        return [q], False
    if v in ("oracle_en", "oracle_en_ko"):   # the same need asked in English / Korean = a perfect translation
        langs = ("en",) if v == "oracle_en" else ("en", "ko")
        return list(dict.fromkeys([q] + [siblings[r["need"]][lg] for lg in langs if lg in siblings[r["need"]]])), True
    if v == "llm_rewrite":
        assert rewriter is not None
        qs, info = rewriter.queries(engine, q)
        return qs, bool(info.get("rewritten"))
    raise SystemExit(f"unknown variants {v!r}")


def run_config(svc, l2p: dict[str, str], records: list[dict[str, Any]], cfg: dict[str, Any],  # type: ignore[no-untyped-def]
               rewriter: Rewriter | None = None) -> list[dict[str, Any]]:
    from app.services.retrieval.query_analysis import find_codes, normalize_codes
    s = svc.retrieval.settings
    engine = svc.conversations.engine
    siblings: dict[str, dict[str, str]] = {}
    for r in records:
        siblings.setdefault(r["need"], {})[r["language"].split("-")[0]] = r["question"]
    saved = {k: getattr(s, k) for k in cfg["settings"]}
    for k, v in cfg["settings"].items():
        setattr(s, k, v)
    mode = cfg["mode"]
    try:
        for r in records[:3]:          # warm-up (model load, caches): not measured
            svc.retrieval.search(r["question"], top_k=10, mode=mode)
        rows = []
        for r in records:
            q = r["question"]
            t0 = time.perf_counter()
            res = svc.retrieval.search(q, top_k=10, mode=mode, max_per_document=1 if mode == "hybrid" else None)
            ms = (time.perf_counter() - t0) * 1000
            docs = list(dict.fromkeys(l2p.get(h["document_id"], h["document_id"]) for h in res["results"]))
            sims = [h["similarity"] for h in res["results"] if h.get("similarity") is not None]
            row: dict[str, Any] = dict(id=r["id"], need=r["need"], language=r["language"], topic=r["topic"],
                                       difficulty=r["difficulty"], answerability=r["answerability"], overlap=r["overlap"],
                                       source_language=r["source_language"],
                                       cross_lingual=(r["source_language"] is not None and
                                                      r["language"].split("-")[0] != r["source_language"]),
                                       top_docs=[d[:8] for d in docs[:5]], n_results=len(res["results"]),
                                       top_similarity=round(max(sims), 4) if sims else None, ms=round(ms, 1))
            if 2 in r["relevant"].values():
                row |= doc_metrics(docs, r["relevant"])
            # what the answer model reads: the assistant's retrieve + evidence selection; hybrid configurations only
            if mode == "hybrid":
                queries, rewritten = make_queries(cfg, r, siblings, engine, rewriter)
                std = queries[0] if rewritten else q
                t1 = time.perf_counter()
                found = engine._retrieve(queries, top_k=10, bridge=not rewritten)
                sources = engine._select(found["hits"], find_codes(normalize_codes(std)), " ".join(dict.fromkeys([q, std])))
                row["assistant_ms"] = round((time.perf_counter() - t1) * 1000, 1)
                row["queries"] = len(queries)
                context = [p for src in sources for p in src["passages"]]
                row["context_docs"] = [l2p.get(src["document_id"], src["document_id"])[:8] for src in sources]
                row["context_chars"] = sum(len(p.get("passage") or "") for p in context)
                fused = list(dict.fromkeys(l2p.get(h["document_id"], h["document_id"]) for h in found["hits"]))
                row["fused_top_docs"] = [d[:8] for d in fused[:5]]
                if r["quotes"]:
                    row |= passage_metrics([passage_text(h) for h in found["hits"]], [passage_text(p) for p in context],
                                           r["quotes"])
                if 2 in r["relevant"].values():
                    strict = {d[:8] for d, g in r["relevant"].items() if g == 2}
                    row["ctx_doc_hit"] = float(bool(strict & set(row["context_docs"])))
                    row |= {f"f_{k}": v for k, v in doc_metrics(fused, r["relevant"]).items() if k in F_KEYS}
            rows.append(row)
        return rows
    finally:
        for k, v in saved.items():
            setattr(s, k, v)


def evaluate_split(split: str, svc, l2p: dict[str, str], iinfo: dict[str, Any], corpus: list[dict[str, Any]],  # type: ignore[no-untyped-def]
                   cfgs: list[dict[str, Any]], a: argparse.Namespace) -> None:
    records, dinfo = load_split(split, {d["id"] for d in corpus})
    qcov = quote_coverage(svc, l2p, records) if split == "test" else None
    results: dict[str, Any] = {}
    rows_by: dict[str, list[dict[str, Any]]] = {}
    metrics = DOC_METRICS + PASSAGE_METRICS + ["ctx_doc_hit"] + [f"f_{k}" for k in F_KEYS if k != "rank"]
    rewriter = Rewriter(a.rewrite_model) if any(c.get("variants") == "llm_rewrite" for c in cfgs) else None
    print(f"== {split}: {dinfo['questions']} questions, {dinfo['needs']} needs", flush=True)
    for cfg in cfgs:
        t0 = time.perf_counter()
        rows = run_config(svc, l2p, records, cfg, rewriter)
        rows_by[cfg["name"]] = rows
        ans = [r for r in rows if r["answerability"] in ("answerable", "conflicting")]
        noans = [r for r in rows if r["answerability"] not in ("answerable", "conflicting")]
        results[cfg["name"]] = dict(
            config=cfg, seconds=round(time.perf_counter() - t0, 1),
            overall=summarize(ans, metrics),
            breakdowns=breakdowns(ans, metrics),
            no_answer_questions=dict(n=len(noans), with_results=sum(1 for r in noans if r["n_results"] > 0),
                                     with_context=sum(1 for r in noans if r.get("context_docs")),
                                     top_similarity=[r["top_similarity"] for r in noans]),
            top_similarity_answerable=dict(p05=pct([r["top_similarity"] for r in ans if r["top_similarity"]], 0.05),
                                           p50=pct([r["top_similarity"] for r in ans if r["top_similarity"]], 0.5)),
            latency_ms=dict(p50=pct([r["ms"] for r in rows], 0.5), p95=pct([r["ms"] for r in rows], 0.95),
                            max=round(max(r["ms"] for r in rows), 1)),
            rows=rows)
        o = results[cfg["name"]]["overall"]
        print(f"{cfg['name']:14} hit@1 {o.get('hit@1')}  hit@10 {o.get('hit@10')}  mrr {o.get('mrr')}  "
              f"ndcg@10 {o.get('ndcg@10')}  ctx_doc_hit {o.get('ctx_doc_hit')}  ctx_hit {o.get('ctx_hit')}  "
              f"f_hit@1 {o.get('f_hit@1')}  f_mrr {o.get('f_mrr')}", flush=True)
    comparisons = []
    if "baseline" in rows_by:
        base = [r for r in rows_by["baseline"] if r["answerability"] in ("answerable", "conflicting")]
        for name, rows in rows_by.items():
            if name == "baseline":
                continue
            other = [r for r in rows if r["answerability"] in ("answerable", "conflicting")]
            for m in ("mrr", "hit@1", "ndcg@10", "ctx_hit", "ctx_doc_hit", "f_hit@1", "f_mrr", "ctx_qrecall"):
                if base and base[0].get(m) is not None and other[0].get(m) is not None:
                    comparisons.append(dict(a="baseline", b=name, **paired(base, other, m)))
    out = dict(tag=a.tag, split=split, final_test_run=a.final, at=datetime.now(UTC).isoformat(timespec="seconds"),
               git=git_rev(), dataset=dinfo, corpus=dict(file=str(CORPUS.relative_to(ROOT)), sha256=sha256_file(CORPUS)),
               index=iinfo, quote_coverage=qcov, path_note="no LLM query rewrite (production path when the rewrite "
               "is unavailable); latency is in-process on the school server, not the hosted latency",
               bootstrap="percentile, resampling information needs, 5000 resamples", results=results,
               paired_vs_baseline=comparisons)
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / f"{a.tag}_{split}_{a.backend}{'' if a.chunker == 'v1' else '_' + a.chunker}.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {path.relative_to(ROOT)}")
    for c in comparisons:
        print(f"  {c['b']:>12} - baseline {c['metric']:12} {c['diff']:+.3f} {c['ci95']}  needs +{c['needs_better']}/-{c['needs_worse']}")
    if qcov:
        print(f"quote coverage: {qcov['within_one_chunk']}/{qcov['quotes']} quotes fit in one chunk")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--split", required=True, help="dev, val, test or a comma list (one index for all)")
    ap.add_argument("--configs", default="baseline")
    ap.add_argument("--backend", choices=["memory", "postgres"], default="memory")
    ap.add_argument("--seed", type=int, default=1, help="memory backend: seed of the chunk ids (tie-breaks)")
    ap.add_argument("--tag", required=True, help="experiment id, used in the result file name (see EXPERIMENT-LOG.md)")
    ap.add_argument("--final", action="store_true", help="required for TEST: the final, pre-registered run")
    ap.add_argument("--reuse-index", action="store_true", help="postgres: reuse the index this script built on the stack")
    ap.add_argument("--chunker", choices=["v1", "v2", "v2b"], default="v1", help="chunker version of the index")
    ap.add_argument("--rewrite-model", default="qwen2.5:7b-instruct", help="local model (loopback Ollama) for llm_rewrite")
    a = ap.parse_args()
    os.environ["CHUNKER_VERSION"] = a.chunker      # read by Settings when the index is built
    splits = a.split.split(",")
    if any(sp not in ("dev", "val", "test") for sp in splits):
        raise SystemExit("--split: dev, val, test")
    if "test" in splits and not a.final:
        raise SystemExit("TEST is used only in the final pre-registered run: add --final and log it in EXPERIMENT-LOG.md")
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    cfgs = [resolve(c) for c in a.configs.split(",")]
    svc, l2p, iinfo = build_memory(corpus, a.seed) if a.backend == "memory" else build_postgres(corpus, a.reuse_index)
    iinfo = dict(iinfo, chunker=a.chunker)
    print(f"index: {iinfo}", flush=True)
    for sp in splits:
        evaluate_split(sp, svc, l2p, iinfo, corpus, cfgs, a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
