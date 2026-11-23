"""Benchmark impact of a corpus snapshot change (frozen questions and labels, no tuning) -> CSV + JSON summary.

Compares the local retrieval runs of two snapshots question by question: rank changes, questions where a newly added
document now ranks first, and whether a new document contains the scenario's evidence terms (a *candidate* label
revision - to be confirmed by a human reviewer, never applied automatically).

    research/.venv/bin/python research/scripts/snapshot_impact.py corpus_v1 corpus_v2
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

R = Path(__file__).resolve().parents[1]
DATA = R / "data"


def results_dir(snap: str) -> Path:
    return DATA / "results" if snap == "corpus_v1" else DATA / "results" / snap


def main(old: str, new: str) -> None:
    items_old = {i["id"] for i in json.loads((DATA / "snapshots" / old / "corpus_manifest.json").read_text())["items"]}
    items_new = {i["id"]: i for i in json.loads((DATA / "snapshots" / new / "corpus_manifest.json").read_text())["items"]}
    added = {k: v for k, v in items_new.items() if k not in items_old}
    removed = sorted(items_old - set(items_new))
    corpus = {d["id"]: d for d in json.loads((R.parent / "backend/.eval-cache/public_corpus_v2.json").read_text())} \
        if new == "corpus_v2" else {}
    rows, summary = [], dict(old=old, new=new, added_documents=[dict(id=k, title=v["title"], language=v["language"],
                                                                          category=v["category"]) for k, v in added.items()],
                             removed_documents=removed, datasets={})
    for ds in ("pilot_v0.1", "heldout_v0.2"):
        bench = {r["question_id"]: r for r in json.loads((DATA / f"benchmarks/retrieval_{ds}.json").read_text())["records"]}
        load = lambda s: {(r["method"], r["question_id"]): r for r in csv.DictReader(  # noqa: E731
            (results_dir(s) / f"retrieval_local_{ds}.csv").open(encoding="utf-8"))}
        a, b = load(old), load(new)
        evidence_in_new = {}
        for qid, rec in bench.items():
            terms = [t.lower() for t in rec.get("evidence_terms") or []]
            evidence_in_new[qid] = sorted(d for d in added if terms and corpus.get(d)
                                          and sum(t in corpus[d]["content"].lower() for t in terms) >= max(1, len(terms) // 2))
        s = dict(questions=len(bench), by_method={})
        for (method, qid), rb in b.items():
            ra = a.get((method, qid))
            if ra is None:
                continue
            rk = lambda r: int(r["rank_first_relevant"]) if r["rank_first_relevant"] else None  # noqa: E731
            top_b = (json.loads(rb["retrieved_documents"]) or [None])[0]
            rows.append(dict(dataset=ds, method=method, question_id=qid, scenario_id=rb["scenario_id"], language=rb["language"],
                             rank_old=rk(ra) or "", rank_new=rk(rb) or "", top1_new=top_b or "",
                             top1_is_added_document=int(top_b in added),
                             added_documents_with_evidence_terms=json.dumps(evidence_in_new[qid])))
            m = s["by_method"].setdefault(method, dict(improved=0, worse=0, unchanged=0, lost_top1=0,
                                                         added_document_ranked_first=0, candidate_label_revisions=0))
            o, n = rk(ra) or 99, rk(rb) or 99
            m["improved" if n < o else "worse" if n > o else "unchanged"] += 1
            m["lost_top1"] += int(o == 1 and n != 1)
            m["added_document_ranked_first"] += int(top_b in added)
            m["candidate_label_revisions"] += int(top_b in added and top_b in evidence_in_new[qid])
        s["scenarios_with_evidence_in_added_documents"] = sorted({bench[q]["scenario_id"] for q, v in evidence_in_new.items() if v})
        summary["datasets"][ds] = s
    out = results_dir(new)
    with (out / f"snapshot_impact_{old}_to_{new}.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)
    (out / f"snapshot_impact_{old}_to_{new}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(*(sys.argv[1:3] or ("corpus_v1", "corpus_v2")))
