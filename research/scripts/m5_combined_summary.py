"""Milestone 5 combined summary across corpus snapshots -> reports/milestone5_combined_summary.{csv,md}

Reads experiments_<dataset>.csv of corpus_v1, corpus_v2 and the experimental corpus_v2_p1 (guidebook re-extracted
with the body-size fix) and reports, per snapshot and label set, the key methods with 95 % cluster-bootstrap CIs and
the pre-specified paired comparisons. Label sets: frozen v0.1/v0.2 (official) and, for corpus_v2*, the AI-proposed
credits for the two new documents (sensitivity only, not human-reviewed).

    research/.venv/bin/python research/scripts/m5_combined_summary.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import analysis as A  # noqa: E402

SNAPS = {"corpus_v1": A.DATA / "results", "corpus_v2": A.DATA / "results/corpus_v2",
         "corpus_v2_p1": A.DATA / "results/corpus_v2_p1"}
METHODS = ["B0", "E1", "E2", "E2S", "B0FR_mminilm", "B0FR_bge-m3", "E3_mminilm", "E3_bge-m3", "E4_mminilm", "E4_bge-m3"]
PAIRS = [("E3_mminilm", "E2"), ("E3_bge-m3", "E2"), ("E3_bge-m3", "E3_mminilm"), ("E2", "B0"), ("E2", "E1"),
         ("B0FR_bge-m3", "B0"), ("E4_bge-m3", "E3_bge-m3"), ("E4_mminilm", "E3_mminilm")]


def labels() -> dict[str, dict[str, set[str]]]:
    rec = {}
    for ds in ("pilot_v0.1", "heldout_v0.2"):
        rec.update({r["question_id"]: r for r in json.loads((A.DATA / f"benchmarks/retrieval_{ds}.json").read_text())["records"]})
    frozen = {q: set(r["expected_document_ids"]) for q, r in rec.items()}
    sens = json.loads((A.DATA / "experiments/chunking/label_sensitivity_ai_proposed.json").read_text())["add"]
    ai = {q: frozen[q] | set(sens.get(r["scenario_id"], [])) for q, r in rec.items()}
    return {"frozen": frozen, "ai_sensitivity": ai}


def main() -> None:
    L = labels()
    rows, pairs, lat = [], [], []
    for snap, res in SNAPS.items():
        files = [res / f"experiments_{ds}.csv" for ds in ("pilot_v0.1", "heldout_v0.2")]
        if not all(f.exists() for f in files):
            print(snap, "not evaluated (no experiments files)")
            continue
        raw = pd.concat([pd.read_csv(f).assign(dataset=f.stem.split("_", 1)[1]) for f in files], ignore_index=True)
        models = set(raw.reranker.dropna())
        for lab, exp in L.items():
            if lab == "ai_sensitivity" and snap == "corpus_v1":
                continue                       # the new documents are not in corpus_v1
            df = A.score_rankings(raw, exp)
            for ds in ("heldout_v0.2", "pilot_v0.1"):
                d = df[(df.dataset == ds) & df.method.isin(METHODS)]
                s = A.summarize(d, ["method"], ("r1", "r5", "rr", "ndcg5")).assign(snapshot=snap, labels=lab, dataset=ds)
                rows.append(s)
                for a, b in PAIRS:
                    if {a, b} <= set(d.method):
                        for col in ("rr", "r1"):
                            r = A.paired_difference(d, a, b, col)
                            pairs.append(dict(r, snapshot=snap, labels=lab, dataset=ds))
        d = raw[raw.method.isin(["E2", "E3_mminilm", "E3_bge-m3"])]
        for (m, dev), g in d.groupby([d.method, d.rerank_device.fillna("-")]):
            lat.append(dict(snapshot=snap, method=m, rerank_device=dev, n=len(g), first_stage_ms=g.first_stage_ms.median(),
                            rerank_ms=g.rerank_ms.median(), total_ms=g.total_ms.median(), total_p90_ms=g.total_ms.quantile(.9)))
        print(snap, "rerankers:", sorted(models))
    S, P, T = pd.concat(rows), pd.DataFrame(pairs), pd.DataFrame(lat)
    out = A.RESEARCH / "reports"
    S.to_csv(out / "milestone5_combined_summary.csv", index=False)
    P.to_csv(out / "milestone5_combined_paired.csv", index=False)
    T.to_csv(out / "milestone5_combined_latency.csv", index=False)
    fmt = lambda r, k="rr": f"{r[k]:.3f} [{r[k + '_lo']:.3f}, {r[k + '_hi']:.3f}]"  # noqa: E731
    md = ["# Milestone 5 combined summary (generated)\n"]
    for (snap, lab, ds), g in S.groupby(["snapshot", "labels", "dataset"], sort=False):
        md.append(f"\n## {snap} - {lab} labels - {ds}\n")
        g = g.set_index("method").reindex([m for m in METHODS if m in set(g.method)])
        md.append(pd.DataFrame({"R@1": g.r1.round(2), "R@5": g.r5.round(2), "nDCG@5": g.ndcg5.round(3),
                                "MRR [95% CI]": [fmt(r) for _, r in g.iterrows()]}).to_markdown())
        p = P[(P.snapshot == snap) & (P.labels == lab) & (P.dataset == ds) & (P.metric == "rr")]
        md.append("\n\nPaired MRR differences: " + "; ".join(
            f"{r.a} vs {r.b} {100*r['diff']:+.1f} pp [{100*r.lo:+.1f}, {100*r.hi:+.1f}]" + (" *" if r.ci_excludes_zero else "")
            for _, r in p.iterrows()) + "  (* = 95% CI excludes 0)\n")
    md.append("\n## Latency (median per question, local Apple M1)\n\n" + T.round(1).to_markdown(index=False) + "\n")
    (out / "milestone5_combined_summary.md").write_text("\n".join(md))
    print("wrote", out / "milestone5_combined_summary.md")


if __name__ == "__main__":
    main()
