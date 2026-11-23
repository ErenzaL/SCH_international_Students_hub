"""Re-score production retrieval runs with corrected document identities (erratum, 2026-11-23).

Labels use the PUBLIC announcement ids for the four announcements, production search returns their source_document
ids; the original files therefore scored every hit on an announcement as a miss. This writes *_rescored.csv next
to the untouched originals, mapping production ids back to the label ids (data/id_aliases.json)."""
import csv
import json
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
alias = json.loads((HERE / "data/id_aliases.json").read_text())["aliases"]
reverse = {v: k for k, v in alias.items()}
benches = {}
for name in ("retrieval_pilot_v0.1.json", "retrieval_heldout_v0.2.json"):
    b = json.loads((HERE / "data/benchmarks" / name).read_text())
    benches[b["dataset_version"]] = {r["question_id"]: r for r in b["records"]}
for src in sorted((HERE / "data/results").glob("retrieval_production_*[0-9].csv")):
    rows = list(csv.DictReader(src.open(encoding="utf-8")))
    changed = 0
    for row in rows:
        docs = [reverse.get(d, d) for d in json.loads(row["retrieved_documents"])]
        expected = set(benches[row["dataset_version"]][row["question_id"]]["expected_document_ids"])
        ranks = [i + 1 for i, d in enumerate(docs) if d in expected]
        new_first = str(ranks[0]) if ranks else ""
        changed += new_first != row["rank_first_relevant"]
        row.update(retrieved_documents=json.dumps(docs), relevant_ranks=json.dumps(ranks), rank_first_relevant=new_first)
    out = src.with_name(src.stem + "_rescored.csv")
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    m = json.loads(src.with_suffix(".manifest.json").read_text())
    m.update(rescored_from=src.name, rescoring="announcement ids mapped to label ids (data/id_aliases.json)",
             rows_with_changed_rank=changed)
    out.with_suffix(".manifest.json").write_text(json.dumps(m, indent=1))
    print(f"{out.name}: {changed} of {len(rows)} rows changed rank")
