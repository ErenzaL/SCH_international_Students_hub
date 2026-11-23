"""Benchmark v0.3-draft: document relevance vs passage sufficiency, multiple correct passages (review stage).

Never edits v0.1 / v0.2 (their SHA-256 is checked). Writes data/review/passage_labels_v0.3_draft.jsonl with, per
question:
  * relevant_documents_frozen    - the official v0.1/v0.2 labels, unchanged
  * proposed_additional_documents- AI-proposed from label_review_new_documents_corpus_v2.csv (pending human review)
  * passage_support              - chunking-independent criteria for a *supporting passage* (several can be correct):
                                   a passage of a relevant document that contains one of the evidence terms, or a
                                   guidebook passage on a reviewed evidence page
  * required_information         - information types the question asks for (evidence-sufficiency layer)
  * split                        - development (pilot, may be used for tuning) / test (held-out, never tuned)
Everything new carries status "pending_human_review"; nothing here is used as the official benchmark.

    research/.venv/bin/python research/scripts/benchmark_v03.py
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
B = ROOT / "research/data/benchmarks"
FROZEN_SHA16 = {"retrieval_pilot_v0.1.json": "910c442d12bb986e", "retrieval_heldout_v0.2.json": "a273350180dc1167"}
OUT = ROOT / "research/data/review/passage_labels_v0.3_draft.jsonl"
REVIEW = ROOT / "research/data/review/label_review_new_documents_corpus_v2.csv"
GUIDEBOOK = "d60bc363-0aae-44e5-b0c3-df8c61ad6f66"


def pages(s: str) -> list[int]:
    out: set[int] = set()
    for part in str(s or "").split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-")
            out |= set(range(int(a), int(b) + 1))
        elif part.isdigit():
            out.add(int(part))
    return sorted(out)


def verify_frozen() -> None:
    for name, sha in FROZEN_SHA16.items():
        got = hashlib.sha256((B / name).read_bytes()).hexdigest()[:16]
        assert got == sha, f"{name} changed ({got} != {sha}) - frozen benchmark files must not be edited"


def load(path: Path = OUT) -> list[dict]:
    return [json.loads(line) for line in path.open(encoding="utf-8")]


def main() -> None:
    from app.services.assistant.evidence import required_information

    verify_frozen()
    review = list(csv.DictReader(REVIEW.open(encoding="utf-8")))
    rows = []
    for name, split in (("retrieval_pilot_v0.1.json", "development"), ("retrieval_heldout_v0.2.json", "test")):
        bench = json.loads((B / name).read_text())
        for r in bench["records"]:
            prop = [x for x in review if x["scenario_id"] == r["scenario_id"] and x["ai_proposed_relevance"] == "relevant"]
            gb_pages = sorted({p for x in prop if x["document_id"] == GUIDEBOOK for p in pages(x["evidence_pages"])})
            rows.append(dict(
                question_id=r["question_id"], scenario_id=r["scenario_id"], language=r["language"], split=split,
                source_benchmark=f"{bench['dataset_version']} ({name})",
                relevant_documents_frozen=r["expected_document_ids"],
                proposed_additional_documents=[dict(document_id=x["document_id"], status=x["review_status"],
                                                    proposed_by=x["proposed_by"]) for x in prop],
                passage_support=dict(
                    evidence_terms=r.get("evidence_terms") or [],
                    guidebook_pages=gb_pages,
                    rule="supporting passage = passage of a relevant document containing >=1 evidence term "
                         "(case-insensitive), or a guidebook passage whose page is in guidebook_pages",
                    status="machine-derived criteria; pending_human_review" if (r.get("evidence_terms") or gb_pages)
                    else "no passage criteria (document-level only)"),
                required_information=required_information(r["question"]),
                status="pending_human_review"))
    OUT.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows), encoding="utf-8")
    n_test = sum(r["split"] == "test" for r in rows)
    print(f"wrote {OUT.relative_to(ROOT)}: {len(rows)} questions ({n_test} test), "
          f"{sum(bool(r['passage_support']['evidence_terms'] or r['passage_support']['guidebook_pages']) for r in rows)} "
          f"with passage criteria, {sum(bool(r['proposed_additional_documents']) for r in rows)} with AI-proposed documents")


if __name__ == "__main__":
    main()
