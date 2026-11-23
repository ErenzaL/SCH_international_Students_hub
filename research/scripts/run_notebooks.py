"""Execute every research notebook top to bottom in a fresh kernel and record the outcome.

Executed copies (with outputs) go to research/notebooks/_executed/ (git-ignored); the committed notebooks stay
output-free. A summary is written to research/reports/notebook_validation.json.

    research/.venv/bin/python research/scripts/run_notebooks.py
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import time
from pathlib import Path

import nbformat
from nbclient import NotebookClient
from nbclient.exceptions import CellExecutionError

HERE = Path(__file__).resolve().parents[1]
import os
SNAPSHOT = os.environ.setdefault("RAG_SNAPSHOT", "corpus_v2")       # inherited by the notebook kernels
NB, OUT = HERE / "notebooks", HERE / "notebooks" / "_executed" / SNAPSHOT


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    only = set(sys.argv[1:])        # optional notebook number prefixes, e.g. "01 02"; others keep their last record
    for path in sorted(NB.glob("[0-9][0-9]_*.ipynb")):
        if only and path.name[:2] not in only:
            continue
        nb = nbformat.read(path, as_version=4)
        t0 = time.perf_counter()
        status, error = "ok", None
        try:
            NotebookClient(nb, timeout=600, kernel_name="sch-research",
                           resources={"metadata": {"path": str(NB)}}).execute()
        except CellExecutionError as exc:
            status, error = "failed", str(exc).splitlines()[-1][:300] if str(exc) else "cell error"
        nbformat.write(nb, OUT / path.name)
        outputs = [o for c in nb.cells if c.cell_type == "code" for o in c.get("outputs", [])]
        not_evaluated = sum("Not evaluated" in json.dumps(o) for o in outputs)
        images = sum(1 for o in outputs if "image/png" in (o.get("data") or {}))
        results.append(dict(notebook=path.name, status=status, seconds=round(time.perf_counter() - t0, 1),
                            code_cells=sum(c.cell_type == "code" for c in nb.cells), inline_figures=images,
                            not_evaluated_notices=not_evaluated, error=error))
        print(f"{path.name:40} {status:7} {results[-1]['seconds']:6}s  figures={images} not_evaluated={not_evaluated}"
              + (f"  ERROR: {error}" if error else ""))
    (HERE / "reports").mkdir(exist_ok=True)
    rep = HERE / "reports" / ("" if SNAPSHOT == "corpus_v1" else SNAPSHOT)
    rep.mkdir(parents=True, exist_ok=True)
    if only and (rep / "notebook_validation.json").exists():
        prev = json.loads((rep / "notebook_validation.json").read_text()).get("results", [])
        mine = {r["notebook"] for r in results}
        results = sorted([r for r in prev if r["notebook"] not in mine] + results, key=lambda r: r["notebook"])
    (rep / "notebook_validation.json").write_text(json.dumps(dict(
        executed_at=dt.datetime.now(dt.UTC).isoformat(), kernel="sch-research", snapshot=SNAPSHOT, results=results), indent=1))


if __name__ == "__main__":
    main()
