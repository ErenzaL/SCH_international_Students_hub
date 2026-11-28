"""Targeted evaluation: English questions about Korean official notices (scripts/benchmarks/crosslang_en_ko_v1.json).

    cd backend
    .venv/bin/python ../scripts/eval_crosslang.py --split dev                                   # baseline, full detail
    .venv/bin/python ../scripts/eval_crosslang.py --split dev --setting cross=retrieval_cross_script_weight:1.0
    .venv/bin/python ../scripts/eval_crosslang.py --split heldout --setting cross=retrieval_cross_script_weight:1.0 --ledger-note "why"

Corpus = the public Knowledge Center documents (backend/.eval-cache/public_corpus.json) + the 36 cached public notices
(announcement_corpus.json, announcement_corpus_heldout.json; --notices DIR), indexed with the production chunker and embedding model in
memory. Public announcements that duplicate a notice (same title) are left out, so every target exists once.

Reported per setting: MRR, Recall@1, Recall@5 for English and Korean, the paired English-Korean gap on the SAME notices, English topic vs
detail questions, and with "strict" (the notice only) and "lenient" (also a closely related document named in the set) labels.
Candidate vs baseline: paired bootstrap 95 % interval of the English MRR difference.

Held-out discipline: for --split heldout only aggregates are printed and written, never a question or a ranking, and every run is
appended to scripts/benchmarks/results/crosslang_heldout_ledger.json (time, commit, settings, numbers), so the number of looks is
visible. Adoption rule (docs/development/CROSSLANG-EVAL.md): a ranking default changes only when, on held-out with reviewed labels,
English MRR improves by >= 0.05 with the interval above 0, Korean MRR drops by <= 0.02, and the general benchmarks do not get worse.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import statistics
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))
from eval_retrieval_benchmark import build_index  # noqa: E402

DATA = ROOT / "scripts/benchmarks/crosslang_en_ko_v1.json"
LEDGER = ROOT / "scripts/benchmarks/results/crosslang_heldout_ledger.json"
CACHE = ROOT / "backend/.eval-cache"


def norm(t: str) -> str:
    return re.sub(r"\W+", "", t or "").lower()


def corpus(notice_dir: Path) -> list[dict]:  # type: ignore[type-arg]
    notices = []
    for f in ("announcement_corpus.json", "announcement_corpus_heldout.json"):
        p = notice_dir / f
        if not p.exists():
            raise SystemExit(f"missing {p}: build it with scripts/build_announcement_corpus.py (public notices, cached locally only)")
        notices += json.loads(p.read_text())
    titles = {norm(n["title"]) for n in notices}
    public = [d for d in json.loads((CACHE / "public_corpus.json").read_text()) if norm(d["title"]) not in titles]
    return public + [dict(id=n["id"], title=n["title"], content=n["text"], language="ko", category="university-announcements",
                          organization="SCH", scope="university", authority_type="official_university", kind="announcement") for n in notices]


def bootstrap_diff(a: list[float], b: list[float], n: int = 2000, seed: int = 7) -> tuple[float, float]:
    rnd = random.Random(seed)
    idx = range(len(a))
    diffs = sorted(statistics.fmean(a[i] - b[i] for i in rnd.choices(idx, k=len(a))) for _ in range(n))
    return round(diffs[int(0.025 * n)], 3), round(diffs[int(0.975 * n) - 1], 3)


def ranks(svc, l2p: dict[str, str], records: list[dict], top_k: int) -> list[dict]:  # type: ignore[no-untyped-def,type-arg]
    out = []
    for r in records:
        hits = svc.retrieval.search(r["question"], language=r["language"], top_k=top_k)["results"]
        docs = list(dict.fromkeys(l2p.get(h["document_id"]) for h in hits))
        strict = next((i + 1 for i, d in enumerate(docs) if d in set(r["expected_document_ids"])), None)
        ok = set(r["expected_document_ids"]) | set(r.get("acceptable_document_ids") or [])
        lenient = next((i + 1 for i, d in enumerate(docs) if d in ok), None)
        out.append(dict(question_id=r["question_id"], notice_id=r["notice_id"], language=r["language"], kind=r["kind"], strict=strict,
                        lenient=lenient, top=docs[:3]))
    return out


def rr(x: int | None) -> float:
    return 1.0 / x if x else 0.0


def agg(rows: list[dict], key: str) -> dict:  # type: ignore[type-arg]
    if not rows:
        return dict(n=0)
    return dict(n=len(rows), mrr=round(statistics.fmean(rr(x[key]) for x in rows), 3),
                recall_at_1=round(statistics.fmean(1.0 if x[key] == 1 else 0.0 for x in rows), 3),
                recall_at_5=round(statistics.fmean(1.0 if x[key] and x[key] <= 5 else 0.0 for x in rows), 3))


def summary(rows: list[dict]) -> dict:  # type: ignore[type-arg]
    out = {}
    for key in ("strict", "lenient"):
        en = [x for x in rows if x["language"] == "en"]
        ko = {x["notice_id"]: x for x in rows if x["language"] == "ko"}
        en_topic = [x for x in en if x["kind"] == "topic"]
        gap = [rr(x[key]) - rr(ko[x["notice_id"]][key]) for x in en_topic if x["notice_id"] in ko]
        out[key] = dict(english=agg(en, key), english_topic=agg(en_topic, key), english_detail=agg([x for x in en if x["kind"] == "detail"], key),
                        korean=agg(list(ko.values()), key),
                        paired_gap_en_topic_minus_ko=round(statistics.fmean(gap), 3) if gap else None)
    return out


def apply(svc, setting: str) -> dict[str, float]:  # type: ignore[no-untyped-def]
    """'name=field:value,field:value' -> sets the retrieval settings in place; returns the changes."""
    changes: dict[str, float] = {}
    for part in setting.split("=", 1)[1].split(","):
        field, value = part.split(":")
        if not hasattr(svc.retrieval.settings, field):
            raise SystemExit(f"unknown setting {field}")
        changes[field] = float(value)
        setattr(svc.retrieval.settings, field, float(value))
    return changes


def commit() -> str:
    r = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], capture_output=True, text=True)
    dirty = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--", "backend/app"], capture_output=True, text=True).stdout.strip()
    return r.stdout.strip() + ("+dirty" if dirty else "")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--split", choices=["dev", "heldout"], required=True)
    ap.add_argument("--setting", action="append", default=[], help="candidate as name=field:value[,field:value]; repeatable")
    ap.add_argument("--notices", type=Path, default=CACHE)
    ap.add_argument("--top-k", type=int, default=8)
    ap.add_argument("--json", type=Path, help="write the results (dev: per question; heldout: aggregates only)")
    ap.add_argument("--ledger-note", default="", help="held-out: why this look is needed")
    a = ap.parse_args()
    data = json.loads(DATA.read_text())
    records = [r for r in data["records"] if r["split"] == a.split]
    if a.split == "heldout" and not a.ledger_note:
        raise SystemExit("held-out runs need --ledger-note (why this look is needed); they are recorded in the ledger")
    t0 = time.time()
    svc, l2p, info = build_index(corpus(a.notices), 0.80)
    baseline_settings = {f: getattr(svc.retrieval.settings, f) for f in ("retrieval_cross_script_weight", "retrieval_hub_beta", "retrieval_bridge_weight")}
    results = {}
    base_rows = ranks(svc, l2p, records, a.top_k)
    results["baseline"] = dict(settings=baseline_settings, summary=summary(base_rows))
    for s in a.setting:
        saved = dict(baseline_settings)
        changes = apply(svc, s)
        rows = ranks(svc, l2p, records, a.top_k)
        for f, v in saved.items():
            setattr(svc.retrieval.settings, f, v)
        en_b = [rr(x["strict"]) for x in base_rows if x["language"] == "en"]
        en_c = [rr(x["strict"]) for x in rows if x["language"] == "en"]
        ko_b = [rr(x["strict"]) for x in base_rows if x["language"] == "ko"]
        ko_c = [rr(x["strict"]) for x in rows if x["language"] == "ko"]
        results[s.split("=", 1)[0]] = dict(
            settings=changes, summary=summary(rows),
            versus_baseline=dict(english_mrr_diff=round(statistics.fmean(en_c) - statistics.fmean(en_b), 3), english_mrr_diff_ci95=bootstrap_diff(en_c, en_b),
                                 korean_mrr_diff=round(statistics.fmean(ko_c) - statistics.fmean(ko_b), 3), korean_mrr_diff_ci95=bootstrap_diff(ko_c, ko_b)),
            **({"rows": rows} if a.split == "dev" else {}))
    if a.split == "dev":
        results["baseline"]["rows"] = base_rows
    out = dict(dataset=data["dataset"], version=data["version"], split=a.split, questions=len(records), index=info, commit=commit(),
               seconds=round(time.time() - t0, 1), results=results)
    for name, r in results.items():
        s = r["summary"]["strict"]
        line = (f"{name:<12} EN MRR {s['english']['mrr']:.3f} (topic {s['english_topic']['mrr']:.3f}, detail {s['english_detail']['mrr']:.3f})  "
                f"KO MRR {s['korean']['mrr']:.3f}  gap {s['paired_gap_en_topic_minus_ko']}  lenient EN {r['summary']['lenient']['english']['mrr']:.3f}")
        if "versus_baseline" in r:
            v = r["versus_baseline"]
            line += f"  ΔEN {v['english_mrr_diff']:+.3f} {v['english_mrr_diff_ci95']}  ΔKO {v['korean_mrr_diff']:+.3f}"
        print(line)
    if a.split == "dev":
        print("\nEnglish misses (baseline, strict):")
        for x in base_rows:
            if x["language"] == "en" and x["strict"] != 1:
                print(f"  {x['question_id']:<16} rank {x['strict']}  top {x['top']}")
    else:
        ledger = json.loads(LEDGER.read_text()) if LEDGER.exists() else []
        ledger.append(dict(at=datetime.now(UTC).isoformat(timespec="seconds"), commit=out["commit"], note=a.ledger_note,
                           settings={k: v["settings"] for k, v in results.items()},
                           summary={k: dict(strict=v["summary"]["strict"], lenient=v["summary"]["lenient"], versus_baseline=v.get("versus_baseline"))
                                    for k, v in results.items()}))
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        LEDGER.write_text(json.dumps(ledger, ensure_ascii=False, indent=1) + "\n")
        print(f"\nheld-out look #{len(ledger)} recorded in {LEDGER.relative_to(ROOT)}")
    if a.json:
        a.json.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n")


if __name__ == "__main__":
    main()
