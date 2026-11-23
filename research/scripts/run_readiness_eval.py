"""Production readiness, Phase 3/5 (retrieval + context level, local, no LLM, no production access).

Same questions (frozen pilot v0.1 + held-out v0.2), same corpus snapshot (corpus_v2 = production text), same context
budget, one query per question (no LLM rewriting), in-memory index built with the production embedder:

  A        DEPLOYED code (git main, run from a worktree): _retrieve(top_k=8) + the deployed _select,
           with the shared context budget (4 sources x 3 passages, 9000 chars)
  A_dep    A with its deployed budget (2 passages per source, 7000 chars) - sensitivity only
  B        working tree: improved hybrid _retrieve(top_k=10, 5 per document) + evidence selection (no reranker)
  C        working tree: _retrieve(top_k=20) + mMiniLM INT8 ONNX reranker (backend module, 1 thread) over the top 20
           + order-preserving selection
  C_noprs  C but with the old (order-destroying) selection - isolates the Phase 3 fix on the production pool
  E4fix    Milestone 5 frozen E2 pool + frozen torch mMiniLM order + order-preserving selection (compare E3 / E4)

    cd backend && .venv/bin/python ../research/scripts/run_readiness_eval.py B C C_noprs E4fix
    <worktree>/backend/.venv... : .venv/bin/python ../research/scripts/run_readiness_eval.py A A_dep --backend <worktree>/backend
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "research/data/experiments/readiness/corpus_v2"
CORPUS = ROOT / "research/data/experiments/chunking/C0_existing/corpus.json"     # corpus_v2 production text
MODELS = ROOT / "research/models/mminilm"
BUDGET = dict(assistant_max_sources=4, assistant_max_passages_per_source=3, assistant_context_chars=9000)


def records() -> list[dict]:
    out = []
    for ds in ("pilot_v0.1", "heldout_v0.2"):
        out += [dict(r, dataset=ds) for r in json.loads((ROOT / f"research/data/benchmarks/retrieval_{ds}.json").read_text())["records"]]
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pipelines", nargs="+")
    ap.add_argument("--backend", default=str(ROOT / "backend"), help="backend tree to import (A: the deployed code)")
    args = ap.parse_args()
    sys.path.insert(0, args.backend)
    sys.path.insert(1, str(ROOT / "scripts"))
    sys.path.insert(2, str(ROOT / "research/scripts"))
    os.environ.setdefault("EMBEDDING_PROVIDER", "e5_onnx")
    import eval_retrieval_benchmark as ev   # note: it puts the repository backend first on sys.path

    backend = str(Path(args.backend).resolve())
    sys.path[:] = [backend] + [x for x in sys.path if Path(x).resolve() != (ROOT / "backend").resolve() or backend == str((ROOT / "backend").resolve())]
    import app

    from app.services.retrieval.query_analysis import find_codes, normalize_codes

    print("backend:", Path(app.__file__).parent, flush=True)
    assert Path(app.__file__).resolve().is_relative_to(Path(args.backend).resolve()), "wrong backend imported"
    svc, l2p, info = ev.build_index(json.loads(CORPUS.read_text()), 0.80)
    eng = svc.conversations.engine
    s = eng.settings
    deployed_budget = dict(assistant_max_sources=s.assistant_max_sources,
                           assistant_max_passages_per_source=s.assistant_max_passages_per_source,
                           assistant_context_chars=s.assistant_context_chars)
    reranker = None
    if {"C", "C_noprs"} & set(args.pipelines):
        from app.services.retrieval.rerank import OnnxCrossEncoderReranker

        reranker = OnnxCrossEncoderReranker(str(MODELS / "model_int8.onnx"), str(MODELS / "sentencepiece.bpe.model"),
                                            batch_size=4, threads=1)
        reranker.score("warm", ["up"])
    frozen = {}
    if "E4fix" in args.pipelines:
        from jsonl_io import open_jsonl

        res = ROOT / "research/data/results/corpus_v2"
        for ds in ("pilot_v0.1", "heldout_v0.2"):
            cand = {json.loads(x)["question_id"]: json.loads(x) for x in open_jsonl(res / f"candidates_{ds}.jsonl")}
            for x in (res / f"reranked_mminilm_{ds}.jsonl").open(encoding="utf-8"):
                r = json.loads(x)
                frozen[r["question_id"]] = (cand[r["question_id"]]["E2"], r["E2"])
    OUT.mkdir(parents=True, exist_ok=True)

    def set_budget(b: dict) -> None:
        for k, v in b.items():
            setattr(s, k, v)

    def pub(sources: list[dict]) -> list[dict]:
        return [dict(document_id=l2p.get(src["document_id"], src["document_id"]), passages=[dict(
            page=p.get("page"), chars=len(p.get("passage") or ""), heading=(p.get("heading") or "")[:80],
            rerank_score=p.get("rerank_score"), first_stage_rank=p.get("first_stage_rank"),
            text=(p.get("passage") or "")[:1800]) for p in src["passages"]]) for src in sources]

    for name in args.pipelines:
        set_budget(deployed_budget if name == "A_dep" else BUDGET)
        rows = []
        for r in records():
            q = r["question"]
            codes = find_codes(normalize_codes(q))
            t0 = time.perf_counter()
            rerank_ms = None
            if name in ("A", "A_dep"):
                found = eng._retrieve([q], top_k=8)
                t1 = time.perf_counter()
                sources = eng._select(found["hits"], codes)          # the deployed signature
            elif name == "B":
                found = eng._retrieve([q], top_k=10)
                t1 = time.perf_counter()
                sources = eng._select(found["hits"], codes, q)
            elif name in ("C", "C_noprs"):
                found = eng._retrieve([q], top_k=20)
                t1 = time.perf_counter()
                hits = reranker.rerank(q, found["hits"], 20)
                rerank_ms = (time.perf_counter() - t1) * 1000
                sources = eng._select(hits, codes, q, preserve_order=(name == "C"))
            elif name == "E4fix":
                pool, rr = frozen[r["question_id"]]
                cands = pool["candidates"]
                hits = [dict(cands[i], document_id=cands[i]["public_document_id"], chunk_id=f"{r['question_id']}-{i}",
                             best_lexical=cands[i].get("lexical_coverage") or 0.0, rerank_score=rr["scores"][k])
                        for k, i in enumerate(rr["order"])]
                found = dict(hits=hits)
                t1 = time.perf_counter()
                sources = eng._select(hits, codes, q, preserve_order=True)     # hits carry public ids already
            else:
                raise SystemExit(f"unknown pipeline {name}")
            t2 = time.perf_counter()
            rows.append(dict(pipeline=name, dataset=r["dataset"], question_id=r["question_id"], scenario_id=r["scenario_id"],
                             language=r["language"], first_stage_ms=round((t1 - t0) * 1000, 1),
                             rerank_ms=round(rerank_ms, 1) if rerank_ms is not None else None,
                             select_ms=round((t2 - t1) * 1000 - (rerank_ms or 0), 2), pool=len(found["hits"]),
                             sources=pub(sources)))
        with (OUT / f"{name}.jsonl").open("w", encoding="utf-8") as f:
            f.writelines(json.dumps(x, ensure_ascii=False) + "\n" for x in rows)
        print(name, len(rows), "questions", flush=True)
    (OUT / f"run_{'_'.join(args.pipelines)}.json").write_text(json.dumps(dict(
        backend="working tree backend" if Path(args.backend).resolve() == (ROOT / "backend").resolve() else "other backend tree (e.g. a git worktree of main)", pipelines=args.pipelines, index=info, budget=BUDGET, deployed_budget=deployed_budget,
        corpus=str(CORPUS.relative_to(ROOT)), reranker="model_int8.onnx batch 4, 1 thread" if reranker else None), indent=1))


if __name__ == "__main__":
    main()
