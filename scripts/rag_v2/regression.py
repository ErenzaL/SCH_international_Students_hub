#!/usr/bin/env python3
"""RAG retrieval regression check (Phase 11): run before merging any change to chunking, embedding, retrieval,
evidence selection or the corpus snapshot.

    backend/.venv/bin/python scripts/rag_v2/regression.py                     # compare with the committed reference
    backend/.venv/bin/python scripts/rag_v2/regression.py --update-reference  # after an APPROVED change only

In-memory store, chunk-id seed 1, DEV + VALIDATION (never TEST), production chunker and the configuration named in
the reference. FAIL (exit 1) when, on either split, a metric falls by more than its tolerance:
    ctx_doc_hit 0.03 · mrr 0.03 · f_mrr 0.03 · hit@10 0.02      (tolerances ≥ the measured tie-break noise, E1s)
Exit 2 when the reference is not comparable (other corpus, dataset or configuration) or the test set is no longer
frozen. About one minute on the school server; no model or network call.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from configs import resolve  # noqa: E402
from lib import CORPUS, RESULTS, ROOT, git_rev, load_split, sha256_file, summarize  # noqa: E402

REFERENCE = RESULTS / "REGRESSION_REFERENCE.json"
TOLERANCE = {"ctx_doc_hit": 0.03, "mrr": 0.03, "f_mrr": 0.03, "hit@10": 0.02}


def measure(config: str) -> dict:
    from retrieval_eval import build_memory, run_config
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    svc, l2p, info = build_memory(corpus, 1)
    cfg = resolve(config)
    out = dict(config=config, config_hash=cfg["hash"], corpus_sha256=sha256_file(CORPUS), chunks=info["chunks"],
               git=git_rev(), splits={})
    for sp in ("dev", "val"):
        records, dinfo = load_split(sp, {d["id"] for d in corpus})
        rows = [r for r in run_config(svc, l2p, records, cfg) if r["answerability"] in ("answerable", "conflicting")]
        out["splits"][sp] = dict(dataset_sha256=dinfo["sha256"],
                                 metrics=summarize(rows, list(TOLERANCE) + ["hit@1"], ci=False))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None, help="default: the reference's configuration")
    ap.add_argument("--update-reference", action="store_true")
    a = ap.parse_args()
    frozen = subprocess.run([sys.executable, str(HERE / "build_testset.py"), "--check"], capture_output=True, text=True)
    if frozen.returncode:
        print("TEST SET NOT FROZEN:", frozen.stdout + frozen.stderr)
        return 2
    ref = json.loads(REFERENCE.read_text()) if REFERENCE.exists() else None
    config = a.config or (ref["config"] if ref else "baseline")
    now = measure(config)
    if a.update_reference or ref is None:
        REFERENCE.write_text(json.dumps(now, indent=1) + "\n")
        print(f"reference written for {config}: {json.dumps(now['splits'])}")
        return 0
    comparable = (ref["config_hash"] == now["config_hash"] and ref["corpus_sha256"] == now["corpus_sha256"]
                  and all(ref["splits"][s]["dataset_sha256"] == now["splits"][s]["dataset_sha256"] for s in ("dev", "val")))
    if not comparable:
        print("reference not comparable (configuration, corpus or dataset changed): re-run with --update-reference "
              "after the change has been reviewed")
        return 2
    failed = []
    for sp in ("dev", "val"):
        for m, tol in TOLERANCE.items():
            was, is_ = ref["splits"][sp]["metrics"].get(m), now["splits"][sp]["metrics"].get(m)
            if was is None or is_ is None:
                continue
            status = "FAIL" if is_ < was - tol else "ok"
            print(f"{status:4} {sp:3} {m:12} reference {was:.3f}  now {is_:.3f}  ({is_ - was:+.3f}, tolerance {tol})")
            if status == "FAIL":
                failed.append(f"{sp}:{m}")
    print("REGRESSION:" if failed else "no regression", ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
