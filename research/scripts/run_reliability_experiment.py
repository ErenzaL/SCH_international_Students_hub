"""Retrieval reliability experiment (local, isolated): evidence-sufficiency layer on top of the assistant pipelines.

For corpus_v2 (production text) and the experimental corpus_v2_p1 (guidebook re-extracted with the body-size fix),
each question of the frozen pilot v0.1 / held-out v0.2 sets goes through:

  E2S      engine._retrieve + engine._select (the assistant's current evidence path, unchanged)
  E2S+EV   E2S + EvidenceChecker.complete (adjacent chunks, one bounded second search)
  E4       mMiniLM-reranked E2 candidate pool (frozen, data/results/<snapshot>/reranked_mminilm_*) + engine._select
  E4+EV    E4 + EvidenceChecker.complete
  (E4 with bge-m3 is added when its reranking output exists)

and the full trace (sources, passages, pages, required information, what was added, what is still missing,
potential conflicts, latency) is written to research/data/experiments/reliability/<snapshot>/traces.jsonl.
In-memory store only; production is never contacted. No LLM is called.

    EMBEDDING_PROVIDER=e5_onnx backend/.venv/bin/python research/scripts/run_reliability_experiment.py
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
sys.path.insert(0, str(ROOT / "research/scripts"))
os.environ.setdefault("EMBEDDING_PROVIDER", "e5_onnx")
EXP = ROOT / "research/data/experiments"
SNAPS = {"corpus_v2": (EXP / "chunking/C0_existing/corpus.json", ROOT / "research/data/results/corpus_v2"),
         "corpus_v2_p1": (EXP / "chunking/P1_prod_fixed_body/corpus.json", ROOT / "research/data/results/corpus_v2_p1")}


def records() -> list[dict]:
    out = []
    for ds in ("pilot_v0.1", "heldout_v0.2"):
        out += [dict(r, dataset=ds) for r in json.loads((ROOT / f"research/data/benchmarks/retrieval_{ds}.json").read_text())["records"]]
    return out


def main() -> None:
    import eval_retrieval_benchmark as ev
    from jsonl_io import open_jsonl
    from app.repositories.base import Query
    from app.services.assistant.evidence import EvidenceChecker, EvidenceConfig
    from app.services.retrieval.query_analysis import find_codes, normalize_codes

    only = set(sys.argv[1:])
    recs = records()
    for snap, (corpus_path, res_dir) in SNAPS.items():
        if only and snap not in only:
            continue
        svc, l2p, info = ev.build_index(json.loads(corpus_path.read_text()), 0.80)
        eng = svc.conversations.engine
        checker = EvidenceChecker(svc.store, svc.retrieval, EvidenceConfig())
        ver_doc = {v["id"]: v["document_id"] for v in svc.store.select("document_versions")[0]}
        live = {}
        for c in svc.store.select("document_chunks", Query(cols="id,version_id,content"))[0]:
            live[(l2p.get(ver_doc.get(c["version_id"])), c["content"])] = c
        rer = {}
        for m in ("mminilm", "bge-m3"):
            rows = {}
            for ds in ("pilot_v0.1", "heldout_v0.2"):
                f = res_dir / f"reranked_{m}_{ds}.jsonl"
                if f.exists():
                    rows.update({json.loads(x)["question_id"]: json.loads(x) for x in f.open(encoding="utf-8")})
            if len(rows) == len(recs):
                rer[m] = rows
        cand = {}
        for ds in ("pilot_v0.1", "heldout_v0.2"):
            cand.update({json.loads(x)["question_id"]: json.loads(x) for x in open_jsonl(res_dir / f"candidates_{ds}.jsonl")})
        out_dir = EXP / "reliability" / snap
        out_dir.mkdir(parents=True, exist_ok=True)
        unmatched = 0

        def to_live(c: dict) -> dict | None:
            nonlocal unmatched
            row = live.get((c.get("public_document_id"), c.get("passage")))
            if row is None:
                unmatched += 1
                return None
            return dict(c, chunk_id=row["id"], version_id=row["version_id"], document_id=ver_doc[row["version_id"]],
                        best_lexical=c.get("lexical_coverage") or 0.0)

        def trace(r, pipeline, sources, select_ms, report=None):
            return dict(snapshot=snap, dataset=r["dataset"], question_id=r["question_id"], scenario_id=r["scenario_id"],
                        language=r["language"], pipeline=pipeline, select_ms=round(select_ms, 1),
                        evidence_ms=(report or {}).get("latency_ms"),
                        documents=[l2p.get(s["document_id"]) for s in sources],
                        sources=[dict(document_id=l2p.get(s["document_id"]), passages=[dict(
                            page=p.get("page"), chars=len(p.get("passage") or ""), added=p.get("evidence_added"),
                            heading=(p.get("heading") or "")[:80], text=(p.get("passage") or "")[:1800])
                            for p in s["passages"]]) for s in sources],
                        evidence=report and {k: report[k] for k in ("needs", "quantity_kind", "initially_missing", "still_missing", "status",
                                                                    "actions", "conflicts")} | dict(
                            conflicts=[dict(c, documents=[l2p.get(d) for d in c["documents"]],
                                           values={l2p.get(k, k): v for k, v in c.get("values", {}).items()})
                                      for c in report["conflicts"]],
                            added=[dict(a, document_id=l2p.get(a["document_id"])) for a in report["added_chunks"]]))

        with (out_dir / "traces.jsonl").open("w", encoding="utf-8") as f:
            for r in recs:
                q = r["question"]
                codes = find_codes(normalize_codes(q))
                t0 = time.perf_counter()
                found = eng._retrieve([q])
                base = eng._select(found["hits"], codes, q)
                sel_ms = (time.perf_counter() - t0) * 1000
                f.write(json.dumps(trace(r, "E2S", base, sel_ms), ensure_ascii=False) + "\n")
                ext, rep = checker.complete(q, base, max_sources=svc.settings.assistant_max_sources)
                f.write(json.dumps(trace(r, "E2S+EV", ext, sel_ms, rep), ensure_ascii=False) + "\n")
                for m, rows in rer.items():
                    c = cand[r["question_id"]]["E2"]["candidates"]
                    hits = [h for h in (to_live(c[i]) for i in rows[r["question_id"]]["E2"]["order"]) if h]
                    t1 = time.perf_counter()
                    src = eng._select(hits, codes, q)
                    ms = (time.perf_counter() - t1) * 1000 + rows[r["question_id"]]["E2"]["rerank_ms"] \
                        + cand[r["question_id"]]["E2"]["first_stage_ms"]
                    tag = "E4" if m == "mminilm" else "E4bge"
                    f.write(json.dumps(trace(r, tag, src, ms), ensure_ascii=False) + "\n")
                    ext, rep = checker.complete(q, src, max_sources=svc.settings.assistant_max_sources)
                    f.write(json.dumps(trace(r, f"{tag}+EV", ext, ms, rep), ensure_ascii=False) + "\n")
        meta = dict(snapshot=snap, corpus=str(corpus_path.relative_to(ROOT)), rerankers=sorted(rer), index=info,
                    unmatched_candidate_passages=unmatched, evidence_config=EvidenceConfig().__dict__)
        (out_dir / "run.json").write_text(json.dumps(meta, indent=1))
        print(snap, json.dumps(meta), flush=True)


if __name__ == "__main__":
    main()
