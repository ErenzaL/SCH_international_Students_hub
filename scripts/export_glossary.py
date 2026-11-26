"""Write the term list of the local model as one review sheet per language (docs/review/glossary-<language>.csv).

    cd backend && .venv/bin/python ../scripts/export_glossary.py

Columns filled in by reviewers (decision, correction, reviewer, date, note) are kept when the sheet is written again; a
decision is cleared when the proposed term changed. Opens in any spreadsheet program (UTF-8 with BOM).
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.gpu_worker.glossary import TERMS  # noqa: E402

LANGS = {"en": 1, "id": 2, "vi": 3, "zh-CN": 4}
FIELDS = ["korean", "proposed", "decision (ok / change / remove)", "correction", "reviewer", "date", "note"]
NAMES = ("순천향", "글로벌빌리지", "학성사", "향설", "신창역", "국제교육교류처", "유학생지원센터", "국기원", "한국장학재단")


def readable(pattern: str) -> str:
    """The Korean words behind a pattern."""
    return " / ".join(re.sub(r"\(\?[!=<][^)]*\)|\\s\*", "", p) for p in pattern.split("|"))


def rows(lang: str) -> list[dict[str, str]]:
    out = [dict.fromkeys(FIELDS, "") | {"korean": readable(t[0]), "proposed": t[LANGS[lang]]} for t in TERMS]
    return sorted(out, key=lambda r: (not r["korean"].startswith(NAMES), r["korean"]))


def path(lang: str, root: Path = ROOT) -> Path:
    return root / "docs" / "review" / f"glossary-{lang}.csv"


def write(root: Path = ROOT) -> None:
    for lang in LANGS:
        p = path(lang, root)
        old = {}
        if p.exists():
            with p.open(encoding="utf-8-sig", newline="") as f:
                old = {r["korean"]: r for r in csv.DictReader(f)}
        with p.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, FIELDS)
            w.writeheader()
            for r in rows(lang):
                o = old.get(r["korean"])
                w.writerow({**r, **({k: o[k] for k in FIELDS[2:]} if o and o["proposed"] == r["proposed"] else {})})


if __name__ == "__main__":
    write()
