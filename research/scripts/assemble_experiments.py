"""Stage 3: assemble all Milestone 5 retrieval configurations from the frozen pools + reranker outputs (local).

Methods (document ranking = documents in order of first appearance):
  B0          dense pool (threshold 0.80; production behaviour, variable size, not reranked)
  B0F         dense pool, no threshold (equal-size)       B0FR_<m>  B0F pool reranked by model m
  E1          original SQL-RRF hybrid (Milestone 4 local run, top-10 documents)
  E2          weighted-hybrid pool                         E3_<m>    E2 pool reranked
  E2S         E2 pool -> the assistant's evidence selection (unchanged engine code), no reranking
  E4_<m>      E3 order -> the assistant's evidence selection (<= 4 source documents)
Also writes context-selection experiments (Phase 5): data/results/context_<ds>.csv.

    cd backend && .venv/bin/python ../research/scripts/assemble_experiments.py
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research/scripts"))
from snapshot_paths import RESULTS as RES  # noqa: E402
from jsonl_io import open_jsonl  # noqa: E402
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("EMBEDDING_PROVIDER", "e5_onnx")
FIELDS = ["method", "family", "reranker", "question_id", "scenario_id", "language", "category", "difficulty",
          "rank_first_relevant", "relevant_ranks", "n_relevant", "retrieved_documents", "first_stage_ms", "rerank_ms",
          "total_ms", "pool_size", "rerank_device"]
FIGURE = re.compile(r"\d+(?:[.,]\d+)?\s*(?:%|[A-Za-z가-힣]{1,8}|[一-鿿]{1,3})|\d{2,}")


def engine():
    from app.core.config import Settings
    from app.services.assistant.engine import AssistantEngine

    return AssistantEngine(retrieval=None, llm=None, settings=Settings(_env_file=None))   # type: ignore[arg-type]


def doc_order(cands: list[dict]) -> list[str]:
    return list(dict.fromkeys(c["public_document_id"] for c in cands if c.get("public_document_id")))


def as_hits(cands: list[dict]) -> list[dict]:
    """Candidate dicts in the shape the engine's evidence selection expects."""
    return [dict(c, best_lexical=c.get("lexical_coverage") or 0.0) for c in cands]


def selected_docs(eng, cands: list[dict], question: str, budget: int | None = None, per_source: int | None = None):
    from app.services.retrieval.query_analysis import find_codes, normalize_codes

    s = eng.settings
    saved = (s.assistant_context_chars, s.assistant_max_passages_per_source)
    if budget:
        s.assistant_context_chars = budget
    if per_source:
        s.assistant_max_passages_per_source = per_source
    try:
        sources = eng._select(as_hits(cands), find_codes(normalize_codes(question)), question)
    finally:
        s.assistant_context_chars, s.assistant_max_passages_per_source = saved
    pid = {c["document_id"]: c["public_document_id"] for c in cands}
    return sources, [pid.get(src["document_id"]) for src in sources]


def ranks(docs: list[str | None], expected: set[str]) -> list[int]:
    return [i + 1 for i, d in enumerate(docs) if d in expected]


def main() -> None:
    eng = engine()
    models = sorted(p.stem.split("_", 1)[1].rsplit("_", 2)[0] for p in RES.glob("reranked_*_pilot_v0.1.jsonl"))
    models = sorted({m for m in models})
    for ds in ("pilot_v0.1", "heldout_v0.2"):
        bench = {r["question_id"]: r for r in json.loads((ROOT / f"research/data/benchmarks/retrieval_{ds}.json").read_text())["records"]}
        cand = {json.loads(l)["question_id"]: json.loads(l) for l in open_jsonl(RES / f"candidates_{ds}.jsonl")}
        rer = {m: {json.loads(l)["question_id"]: json.loads(l) for l in (RES / f"reranked_{m}_{ds}.jsonl").open(encoding="utf-8")}
               for m in models if (RES / f"reranked_{m}_{ds}.jsonl").exists()}
        e1 = {r["question_id"]: r for r in csv.DictReader((RES / f"retrieval_local_{ds}.csv").open(encoding="utf-8"))
              if r["method"] == "E1"}
        rows, ctx_rows = [], []
        for qid, r in bench.items():
            c, exp = cand[qid], set(r["expected_document_ids"])
            base = dict(question_id=qid, scenario_id=r["scenario_id"], language=r["language"], category=r["category"],
                        difficulty=r["difficulty"], n_relevant=len(exp))

            def add(method, family, reranker, docs, first_ms, rer_ms, pool, device=""):
                rk = ranks(docs, exp)
                rows.append(dict(base, method=method, family=family, reranker=reranker or "", rerank_device=device,
                                 rank_first_relevant=rk[0] if rk else "", relevant_ranks=json.dumps(rk),
                                 retrieved_documents=json.dumps([d for d in docs if d][:10]),
                                 first_stage_ms=first_ms, rerank_ms=rer_ms if rer_ms is not None else "",
                                 total_ms=round(first_ms + (rer_ms or 0), 1), pool_size=pool))

            for p in ("B0", "B0F", "E2"):
                add(p, p, None, doc_order(c[p]["candidates"]), c[p]["first_stage_ms"], None, len(c[p]["candidates"]))
            e1docs = json.loads(e1[qid]["retrieved_documents"])
            add("E1", "E1", None, e1docs, float(e1[qid]["latency_ms"]), None, "")
            _src, docs = selected_docs(eng, c["E2"]["candidates"], r["question"])
            add("E2S", "E2S", None, docs, c["E2"]["first_stage_ms"], None, len(c["E2"]["candidates"]))
            for m, rr in rer.items():
                for pool, fam in (("B0F", "B0FR"), ("E2", "E3")):
                    if qid not in rr or pool not in rr[qid]:
                        continue                       # incomplete reranker run: question left out, visible in counts
                    order = [c[pool]["candidates"][i] for i in rr[qid][pool]["order"]]
                    dev = rr[qid].get("device", "cpu")    # rows written before the device field were CPU runs
                    add(f"{fam}_{m}", fam, m, doc_order(order), c[pool]["first_stage_ms"], rr[qid][pool]["rerank_ms"],
                        len(order), dev)
                    if pool == "E2":
                        _s, d4 = selected_docs(eng, order, r["question"])
                        add(f"E4_{m}", "E4", m, d4, c[pool]["first_stage_ms"], rr[qid][pool]["rerank_ms"], len(order), dev)
            # ---------------- Phase 5: context-selection strategies at several budgets (evidence the LLM would get)
            terms = [t.lower() for t in r.get("evidence_terms") or []]
            quantity = bool(re.search(r"how (many|much|long)|몇|얼마|berapa|bao nhiêu|多少|几", r["question"], re.I))
            strategies = {"top_k_no_rerank": c["E2"]["candidates"]}
            best = "bge-m3" if "bge-m3" in rer else (sorted(rer)[0] if rer else None)
            if best and qid in rer[best]:
                strategies["top_k_reranked"] = [c["E2"]["candidates"][i] for i in rer[best][qid]["E2"]["order"]]
            for budget in (3000, 6000, 9000):
                for name, order in strategies.items():
                    ctx, used = [], 0
                    for h in order:
                        size = min(len(h.get("passage") or ""), 1800)
                        if ctx and used + size > budget:
                            continue
                        ctx.append(h); used += size
                    ctx_rows.append(_ctx(base, name, budget, ctx, exp, terms, quantity))
                    if name == "top_k_reranked" or (name == "top_k_no_rerank" and "top_k_reranked" not in strategies):
                        balanced, per = [], {}
                        for h in order:                       # document-balanced: <= 2 passages per document
                            if per.get(h["document_id"], 0) >= 2:
                                continue
                            size = min(len(h.get("passage") or ""), 1800)
                            if balanced and sum(min(len(x.get("passage") or ""), 1800) for x in balanced) + size > budget:
                                continue
                            balanced.append(h); per[h["document_id"]] = per.get(h["document_id"], 0) + 1
                        ctx_rows.append(_ctx(base, "document_balanced", budget, balanced, exp, terms, quantity))
                        sources, _ = selected_docs(eng, order, r["question"], budget=budget)
                        ctx_rows.append(_ctx(base, "question_aware_selection", budget,
                                             [p for s in sources for p in s["passages"]], exp, terms, quantity))
        _write(RES / f"experiments_{ds}.csv", rows, FIELDS)
        _write(RES / f"context_{ds}.csv", ctx_rows, list(ctx_rows[0]))
        print(f"{ds}: {len(rows)} method rows, {len(ctx_rows)} context rows, rerankers: {list(rer)}")


def _ctx(base, strategy, budget, ctx, exp, terms, quantity):
    texts = [(h.get("passage") or "").lower() for h in ctx]
    toks = [set(re.findall(r"\w+", t)) for t in texts]
    pairs = [(i, j) for i in range(len(toks)) for j in range(i + 1, len(toks))]
    redundant = sum(1 for i, j in pairs if toks[i] and toks[j] and len(toks[i] & toks[j]) / len(toks[i] | toks[j]) >= 0.5)
    joined = " ".join(texts)
    return dict(base, strategy=strategy, budget_chars=budget, passages=len(ctx), chars=sum(len(t) for t in texts),
                documents=len({h["public_document_id"] for h in ctx}),
                expected_document_in_context=int(any(h["public_document_id"] in exp for h in ctx)),
                evidence_terms_found=(sum(t in joined for t in terms) / len(terms)) if terms else "",
                quantity_question=int(quantity), figure_in_expected_passage=int(any(
                    h["public_document_id"] in exp and FIGURE.search(h.get("passage") or "") for h in ctx)) if quantity else "",
                redundant_pair_share=round(redundant / len(pairs), 3) if pairs else 0.0)


def _write(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main()
