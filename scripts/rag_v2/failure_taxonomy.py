#!/usr/bin/env python3
"""Deterministic failure taxonomy for retrieval misses (DEV / VALIDATION result files of retrieval_eval.py).

A question is a MISS when its grade-2 (primary) document is not ranked first. Each miss gets exactly one cause, the
first rule that applies:

  label_gap          the primary document is not in the corpus snapshot (a dataset problem, not a system one)
  starved            fewer than 4 passages survived the similarity threshold and the primary is not among them
  same_language_pull question and primary document are in different languages and the top document is in the
                     QUESTION's language (a document is pulled up because it shares the question's language)
  hub_first          a hub guide (one of the two long guidebooks) is ranked first and the primary is not a hub
  korean_doc_first   a Korean document is ranked first for a non-Korean question whose primary is not Korean
  sibling_first      another labelled (grade-1) document is ranked first
  other              anything else
Flags (not exclusive): not_in_top10, not_in_context (the primary does not reach the answer model).

    backend/.venv/bin/python scripts/rag_v2/failure_taxonomy.py scripts/benchmarks/results/rag_v2/E2_val_postgres.json
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "backend" / ".eval-cache" / "public_corpus.json"
SOURCES = {"dev": ROOT / "scripts" / "benchmarks" / "retrieval_pilot_v0.1.json",
           "val": ROOT / "backend" / ".eval-cache" / "heldout_v0.2.json"}
HUBS = {"672ffe31", "d60bc363"}          # Guide for International Student in Korea; 한국 유학생 생활 가이드북


def classify(row: dict, primary: str | None, labelled: set[str], lang: dict[str, str]) -> str:
    top = row["top_docs"][0] if row["top_docs"] else None
    qlang = row["language"].split("-")[0]
    if primary is None or primary not in lang:
        return "label_gap"
    if row["n_results"] < 4 and not row.get("hit@10"):
        return "starved"
    if top and lang[primary] != qlang and lang.get(top) == qlang:
        return "same_language_pull"
    if top in HUBS and primary not in HUBS:
        return "hub_first"
    if top and lang.get(top) == "ko" and qlang != "ko" and lang[primary] != "ko":
        return "korean_doc_first"
    if top in labelled:
        return "sibling_first"
    return "other"


def analyse(path: Path, config: str = "baseline") -> dict:
    res = json.loads(path.read_text(encoding="utf-8"))
    split = res["split"]
    lang = {d["id"][:8]: d["language"] for d in json.loads(CORPUS.read_text(encoding="utf-8"))}
    recs = {r["question_id"]: r for r in json.loads(SOURCES[split].read_text(encoding="utf-8"))["records"]}
    rows = [r for r in res["results"][config]["rows"] if r.get("hit@1") is not None]
    misses = []
    for r in rows:
        if r["hit@1"] == 1:
            continue
        rec = recs[r["id"]]
        primary = (rec.get("primary_document_id") or "")[:8] or None
        labelled = {d[:8] for d in rec["expected_document_ids"]} - {primary}
        misses.append(dict(id=r["id"], need=r["need"], language=r["language"], topic=r["topic"],
                           cause=classify(r, primary, labelled, lang), primary=primary, top=r["top_docs"][:3],
                           rank=r.get("rank"), not_in_top10=not r.get("hit@10"),
                           not_in_context=r.get("ctx_doc_hit") == 0))
    return dict(file=str(path.relative_to(ROOT)), split=split, config=config, questions=len(rows), misses=len(misses),
                causes=dict(Counter(m["cause"] for m in misses).most_common()),
                causes_not_in_context=dict(Counter(m["cause"] for m in misses if m["not_in_context"]).most_common()),
                by_language=dict(Counter(m["language"] for m in misses)),
                rows=misses)


def main() -> int:
    out = [analyse(Path(p).resolve()) for p in sys.argv[1:]]
    for o in out:
        print(f"{o['file']}: {o['misses']} misses / {o['questions']}")
        print("  causes:", o["causes"])
        print("  of which the primary never reaches the model:", o["causes_not_in_context"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
