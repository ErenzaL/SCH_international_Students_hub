"""Promote human-reviewed questions to a new, independent dataset version (retrieval-reviewed-1.0).

Input : data/review/label_review_worksheet.csv, filled in by human reviewers
        (reviewer, decision = accept | fix | reject, corrected_expected_document_ids = ';'-separated ids for "fix",
         reference_answer for high-stakes items).
Output: data/benchmarks/retrieval_reviewed_v1.0.json - only accepted/fixed, current (non-historical) questions.
Nothing is promoted without a reviewer name and a decision. AI-drafted labels are never marked reviewed.

    research/.venv/bin/python research/scripts/build_reviewed_dataset.py
"""
from __future__ import annotations

import csv
import datetime as dt
import json
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]


def main() -> None:
    src = {}
    for name in ("retrieval_pilot_v0.1.json", "retrieval_heldout_v0.2.json"):
        for r in json.loads((HERE / "data/benchmarks" / name).read_text())["records"]:
            src[(r["dataset_version"], r["question_id"])] = r
    out, skipped = [], {"no_review": 0, "rejected": 0, "historical": 0}
    with (HERE / "data/review/label_review_worksheet.csv").open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            # an adjudicated final decision wins; otherwise the (single) reviewer's decision
            decision = (row.get("final_decision") or row["decision"]).strip().lower()
            reviewer = row["reviewer"].strip()
            if not reviewer or decision not in ("accept", "fix", "reject"):
                skipped["no_review"] += 1
                continue
            if decision == "reject":
                skipped["rejected"] += 1
                continue
            if row["temporal_flag"] != "current":
                skipped["historical"] += 1
                continue
            r = dict(src[(row["dataset_version"], row["question_id"])])
            if decision == "fix":
                r["expected_document_ids"] = [x.strip() for x in row["corrected_expected_document_ids"].split(";") if x.strip()]
            r.update(review_status="human_reviewed", reviewer=reviewer, reviewed_decision=decision,
                     reviewers=2 if (row.get("reviewer_2") or "").strip() else 1,
                     reference_answer=row["reference_answer"].strip() or None, source_dataset_version=r["dataset_version"],
                     dataset_version="retrieval-reviewed-1.0", notes=row["notes"].strip() or None)
            out.append(r)
    target = HERE / "data/benchmarks/retrieval_reviewed_v1.0.json"
    if not out:
        print(f"no reviewed questions yet ({skipped}); {target.name} not written")
        return
    target.write_text(json.dumps(dict(dataset_version="retrieval-reviewed-1.0", created=dt.date.today().isoformat(),
                                      review_status="human_reviewed", records=out, skipped=skipped),
                                 ensure_ascii=False, indent=1))
    print(f"wrote {len(out)} reviewed questions -> {target} ({skipped})")


if __name__ == "__main__":
    main()
