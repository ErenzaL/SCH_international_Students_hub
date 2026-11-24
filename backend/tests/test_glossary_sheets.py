"""The review sheets show exactly the terms the model is given, and keep what reviewers wrote."""
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import export_glossary as g  # noqa: E402


def read(p: Path) -> list[dict[str, str]]:
    with p.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def test_sheets_match_the_term_list():
    for lang in g.LANGS:
        assert [(r["korean"], r["proposed"]) for r in read(g.path(lang))] == [(r["korean"], r["proposed"]) for r in g.rows(lang)], \
            "run scripts/export_glossary.py"


def test_korean_column_is_readable_and_unique():
    ko = [r["korean"] for r in g.rows("en")]
    assert len(set(ko)) == len(ko) and not any(c in k for k in ko for c in "()\\*?|")


def test_reviewers_entries_survive_unless_the_term_changed(tmp_path):
    (tmp_path / "docs" / "review").mkdir(parents=True)
    g.write(tmp_path)
    p = g.path("vi", tmp_path)
    data = read(p)
    data[0][g.FIELDS[2]], data[0]["reviewer"] = "ok", "A"
    data[1][g.FIELDS[2]], data[1]["proposed"] = "ok", "an older term"
    with p.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, g.FIELDS)
        w.writeheader()
        w.writerows(data)
    g.write(tmp_path)
    after = read(p)
    assert (after[0][g.FIELDS[2]], after[0]["reviewer"]) == ("ok", "A") and after[1][g.FIELDS[2]] == ""
