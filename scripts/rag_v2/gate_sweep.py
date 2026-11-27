#!/usr/bin/env python3
"""Evidence-gate threshold sweep on DEV + VALIDATION (answerable) and DEV-negatives (unanswerable).

Gate rule (deterministic, over the passages the answer model would read):
    sufficient  <=>  an exact identifier / code match
                     or  max similarity >= tau
                     or  (max lexical coverage >= lam  and  max similarity >= tau - 0.03)
    otherwise insufficient (no passage at all = none)
FRR = answerable questions the gate would refuse; TRR = negatives it would refuse. A refused answerable question whose
primary document IS in the context is the costly error ("frr_with_evidence").

    backend/.venv/bin/python scripts/rag_v2/gate_sweep.py E7   # reads E7_{dev,val,neg}_memory.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

R = Path(__file__).resolve().parents[2] / "scripts" / "benchmarks" / "results" / "rag_v2"


def sufficient(r: dict, tau: float, lam: float | None) -> bool:
    if not r.get("ctx_n"):
        return False
    sim = r.get("ctx_max_sim") or 0.0
    if r.get("ctx_exact") or sim >= tau:
        return True
    return lam is not None and (r.get("ctx_max_lex") or 0.0) >= lam and sim >= tau - 0.03


def sweep(tag: str, config: str) -> list[dict]:
    ans = [r for sp in ("dev", "val") for r in json.loads((R / f"{tag}_{sp}_memory.json").read_text())["results"][config]["rows"]]
    neg = json.loads((R / f"{tag}_neg_memory.json").read_text())["results"][config]["rows"]
    out = []
    for tau in [round(0.80 + 0.01 * i, 2) for i in range(11)]:
        for lam in (None, 0.5, 0.6, 0.7, 0.8, 1.0):
            refused = [r for r in ans if not sufficient(r, tau, lam)]
            out.append(dict(tau=tau, lam=lam, frr=round(len(refused) / len(ans), 3),
                            frr_with_evidence=round(sum(1 for r in refused if r.get("ctx_doc_hit")) / len(ans), 3),
                            trr=round(sum(1 for r in neg if not sufficient(r, tau, lam)) / len(neg), 3),
                            trr_hard=round(sum(1 for r in neg if "hard_negative" in r["id"] or r["need"] in
                                               ("NEG-05", "NEG-06", "NEG-07") and not sufficient(r, tau, lam))
                                           / max(1, sum(1 for r in neg if r["need"] in ("NEG-05", "NEG-06", "NEG-07"))), 3)))
    return out


def main() -> int:
    tag = sys.argv[1] if len(sys.argv) > 1 else "E7"
    res = {}
    for config in ("baseline", "hub0.1", "llm_rewrite", "hub0.1_llm_rewrite"):
        rows = sweep(tag, config)
        res[config] = rows
        print(f"== {config}: operating points with FRR <= 0.05 (best TRR first)")
        ok = sorted((r for r in rows if r["frr"] <= 0.05), key=lambda r: (-r["trr"], r["frr"]))[:5]
        for r in ok:
            print(f"   tau {r['tau']:.2f} lam {r['lam']}: FRR {r['frr']:.3f} (with evidence {r['frr_with_evidence']:.3f})  "
                  f"TRR {r['trr']:.3f} (hard {r['trr_hard']:.3f})")
        best = max(rows, key=lambda r: r["trr"] - r["frr"])
        print(f"   max(TRR-FRR): tau {best['tau']} lam {best['lam']}: FRR {best['frr']} TRR {best['trr']}")
    (R / f"{tag}_gate_sweep.json").write_text(json.dumps(res, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
