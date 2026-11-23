"""Human-review progress (labels and answers) - reports only what has actually been filled in."""
import pandas as pd
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
w = pd.read_csv(HERE / "data/review/label_review_worksheet.csv", dtype=str).fillna("")
a = pd.read_csv(HERE / "data/review/answer_annotation_template.csv", dtype=str).fillna("")
w["reviewed_once"] = w["reviewer"].str.strip().ne("") & w["decision"].str.strip().ne("")
w["reviewed_twice"] = w["reviewed_once"] & w["reviewer_2"].str.strip().ne("") & w["decision_2"].str.strip().ne("")
w["disagreement"] = w["reviewed_twice"] & (w["decision"].str.lower() != w["decision_2"].str.lower())
w["adjudicated"] = w["final_decision"].str.strip().ne("")
print("LABELS"); print(w.groupby(["split", "priority"])[["reviewed_once", "reviewed_twice", "disagreement", "adjudicated"]]
                       .sum().astype(int).assign(total=w.groupby(["split", "priority"]).size()))
scored = a[["correctness", "relevance", "faithfulness"]].apply(lambda c: c.str.strip().ne("")).all(axis=1)
print(f"\nANSWERS: {int(scored.sum())}/{len(a)} scored (human: {int((scored & a['judge_type'].str.lower().eq('human')).sum())})")
print("\nHuman review complete:", bool(w["reviewed_once"].all() and scored.all()))
