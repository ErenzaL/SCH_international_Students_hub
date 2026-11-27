#!/usr/bin/env python3
"""Paired comparison of two retrieval_eval.py result files (same split, same questions; different index or config).

    backend/.venv/bin/python scripts/rag_v2/compare.py A.json[:config] B.json[:config] [--metrics mrr,hit@1,...]

Prints B − A with need-level bootstrap intervals (lib.paired) for answerable questions.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import paired  # noqa: E402

DEFAULT = "hit@1,hit@1_len,mrr,mrr_len,ndcg@10,hit@10,ctx_doc_hit,ctx_hit,ctx_qrecall"


def load(spec: str) -> tuple[str, list[dict]]:
    path, _, cfg = spec.partition(":")
    res = json.loads(Path(path).read_text(encoding="utf-8"))
    cfg = cfg or "baseline"
    rows = [r for r in res["results"][cfg]["rows"] if r["answerability"] in ("answerable", "conflicting")]
    return f"{Path(path).name}:{cfg}", rows


def compare(a_spec: str, b_spec: str, metrics: list[str]) -> list[dict]:
    na, a = load(a_spec)
    nb, b = load(b_spec)
    out = []
    for m in metrics:
        if a and a[0].get(m) is not None and b[0].get(m) is not None:
            out.append(dict(a=na, b=nb, **paired(a, b, m)))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--metrics", default=DEFAULT)
    args = ap.parse_args()
    for c in compare(args.a, args.b, args.metrics.split(",")):
        print(f"{c['metric']:12} {c['diff']:+.3f} [{c['ci95'][0]:+.3f}, {c['ci95'][1]:+.3f}]  "
              f"needs +{c['needs_better']}/-{c['needs_worse']}  questions +{c['questions_better']}/-{c['questions_worse']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
