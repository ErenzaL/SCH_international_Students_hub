"""Stage 2: rerank the frozen candidate pools with each model (local machine: Apple GPU via MPS if available, else CPU) -> data/results/reranked_<model>_<ds>.jsonl

    research/.venv-rerank/bin/python research/scripts/run_reranking.py --models mminilm,bge-m3 --datasets pilot_v0.1,heldout_v0.2

Records, per question and pool, the reranked candidate order and scores and the reranking latency; per model the
load time, peak resident memory and torch thread count. Development (pilot) runs first; held-out is scored with the
same, unchanged configuration.
"""
from __future__ import annotations

import argparse
import datetime as dt
import traceback
import json
import platform
import resource
import sys
import os
import time
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "scripts"))
from jsonl_io import open_jsonl  # noqa: E402
from reranking import MODELS, CrossEncoderReranker  # noqa: E402
from snapshot_paths import RESULTS, SNAPSHOT  # noqa: E402

POOLS = ("B0F", "E2")     # equal-size dense pool (control) and the improved-hybrid pool


def peak_rss_mb() -> float:
    r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return r / (1024 * 1024) if platform.system() == "Darwin" else r / 1024


def _completed(path: Path) -> set[str]:
    """Question IDs already reranked. A process killed mid-write leaves a partial last line: drop it so the
    question is redone (the file is rewritten with only the complete lines)."""
    if not path.exists():
        return set()
    good = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            good.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    path.write_text("".join(json.dumps(r) + "\n" for r in good), encoding="utf-8")
    return {r["question_id"] for r in good}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="mminilm,bge-m3")
    ap.add_argument("--datasets", default="pilot_v0.1,heldout_v0.2")
    a = ap.parse_args()
    import torch

    for key in a.models.split(","):
        spec = MODELS[key]
        device = os.environ.get("RERANK_DEVICE") or ("mps" if torch.backends.mps.is_available() else "cpu")
        rr = CrossEncoderReranker(spec["repo"], device=device)
        manifest = dict(model_key=key, snapshot=SNAPSHOT, process_attempt=int(os.environ.get("RERANK_ATTEMPT", "1")), pools=list(POOLS), **spec, load_seconds=round(rr.load_seconds, 1), device=device,
                        device_note="local Apple GPU (MPS) or CPU; spot check: MPS and CPU scores agree to 4-5 decimals with identical order",
                        torch=torch.__version__, torch_threads=torch.get_num_threads(), max_length=rr.max_length,
                        machine=f"{platform.machine()} {platform.platform()}", started_at=dt.datetime.now(dt.UTC).isoformat())
        for ds in a.datasets.split(","):
            rows = [json.loads(line) for line in open_jsonl(RESULTS / f"candidates_{ds}.jsonl")]
            path = RESULTS / f"reranked_{key}_{ds}.jsonl"
            done = _completed(path)
            log = (RESULTS / f"reranked_{key}.log").open("a", encoding="utf-8")
            with path.open("a", encoding="utf-8") as out:        # resumable: one flushed line per question
                for row in rows:
                    if row["question_id"] in done:
                        continue
                    try:
                        rec = dict(question_id=row["question_id"], model=key, snapshot=SNAPSHOT, device=device)
                        for pool in POOLS:
                            cands = row[pool]["candidates"]
                            t0 = time.perf_counter()
                            ranked = rr.rerank(row["question"], cands)
                            rec[pool] = dict(order=[i for i, _ in ranked], scores=[round(x, 5) for _, x in ranked],
                                             rerank_ms=round((time.perf_counter() - t0) * 1000, 1), n=len(cands))
                        out.write(json.dumps(rec) + "\n"); out.flush()
                    except Exception:  # noqa: BLE001 - logged, run continues; missing rows are visible in the output
                        log.write(f"{dt.datetime.now(dt.UTC).isoformat()} {row['question_id']}\n{traceback.format_exc()}\n")
                        log.flush()
            log.close()
            print(f"{key} {ds}: done", flush=True)
        manifest.update(peak_rss_mb=round(peak_rss_mb()), finished_at=dt.datetime.now(dt.UTC).isoformat())
        (RESULTS / f"reranked_{key}.manifest.json").write_text(json.dumps(manifest, indent=1))
        print(json.dumps(manifest))
        del rr


if __name__ == "__main__":
    main()
