"""Answer-annotation template for human reviewers (rubric v1) from the recorded production answers."""
import csv
import json
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
src = HERE / "data/results/answers_production_heldout_v0.2.jsonl"
rows = [json.loads(line) for line in src.read_text(encoding="utf-8").splitlines() if line.strip()]
out = HERE / "data/review/answer_annotation_template.csv"
fields = ["question_id", "language", "question", "answer_generation", "model", "answer", "cited_titles",
          "correctness", "relevance", "faithfulness", "citation_accuracy", "unsupported_claims", "language_ok",
          "appropriate_abstention", "reviewer", "judge_type", "judge_model", "rubric_version", "notes"]
with out.open("w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()
    for r in rows:
        w.writerow({k: r.get(k, "") for k in fields[:6]} | {"cited_titles": " | ".join(r.get("cited_titles") or []),
                                                          "rubric_version": "answer_rubric_v1"})
print(f"{len(rows)} answers -> {out}")
