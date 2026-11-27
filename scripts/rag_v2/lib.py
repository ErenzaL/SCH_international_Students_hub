"""Shared pieces of the RAG v2 evaluation: datasets, metrics, need-clustered bootstrap, result records.

Datasets are loaded into one record shape:
  id, need, language, question, topic, difficulty, answerability, types, overlap,
  relevant {public_document_id: grade 2|1}, quotes [{document_id, quote}] (TEST only), source_language

DEV / VALIDATION have document labels only: the primary document gets grade 2, the other expected documents grade 1
(the same gains as scripts/rag_research_eval.py). Labels that point outside the corpus are dropped and counted.

Metrics (document level, a ranked list of distinct documents):
  hit@k          >= 1 grade-2 document in the first k            (strict)
  hit@k_len      >= 1 document of grade >= 1 in the first k      (lenient; = "recall@k" of rag_research_eval.py)
  recall@k       share of the grade-2 documents found in the first k
  mrr / mrr_len  1 / rank of the first grade-2 (grade >= 1) document within 10, else 0
  ndcg@5, @10    gains 2 / 1, ideal from all labelled documents
  p@5            documents of grade >= 1 among the first 5, / 5
Passage level (TEST only: a passage is relevant when its normalised text contains a gold quote):
  phit@k         a gold quote in the first k passages;  qrecall@k  share of distinct quotes found
  ctx_hit / ctx_qrecall   the same over the passages actually given to the answer model (evidence selection)

Intervals: percentile bootstrap that resamples INFORMATION NEEDS (the five language versions of a need are not
independent), 5,000 resamples, seed 7. Paired differences use the same resampled needs for both systems.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import statistics
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "rag_v2"))
from build_testset import norm  # noqa: E402  (one normalisation for quotes and passages)

CORPUS = ROOT / "backend" / ".eval-cache" / "public_corpus.json"
SPLITS = {
    "dev": ROOT / "scripts" / "benchmarks" / "retrieval_pilot_v0.1.json",
    "val": ROOT / "backend" / ".eval-cache" / "heldout_v0.2.json",
    "test": ROOT / "scripts" / "benchmarks" / "rag_v2" / "testset_v0.3.json",
    "neg": ROOT / "scripts" / "benchmarks" / "rag_v2" / "dev_negatives_v0.1.json",   # DEV-only negatives (gate tuning)
}
RESULTS = ROOT / "scripts" / "benchmarks" / "results" / "rag_v2"
LANGS = ("ko", "en", "id", "vi", "zh-CN")
KS = (1, 3, 5, 10)
N_BOOT = 5000
DOC_METRICS = ([f"hit@{k}" for k in KS] + [f"hit@{k}_len" for k in KS] + [f"recall@{k}" for k in (5, 10)]
               + ["mrr", "mrr_len", "ndcg@5", "ndcg@10", "p@5"])
PASSAGE_METRICS = ["phit@1", "phit@3", "phit@5", "phit@10", "qrecall@10", "pmrr", "ctx_hit", "ctx_qrecall"]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_rev() -> str:
    out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT, capture_output=True,
                           text=True).stdout.strip()
    return out + ("+dirty" if dirty else "")


def load_split(name: str, corpus_ids: set[str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    raw = json.loads(SPLITS[name].read_text(encoding="utf-8"))
    info: dict[str, Any] = {"split": name, "file": str(SPLITS[name].relative_to(ROOT)), "sha256": sha256_file(SPLITS[name]),
                            "dataset_version": raw.get("dataset_version"), "dropped_labels": 0}
    out = []
    if name in ("test", "neg"):
        for q in raw["questions"]:
            out.append(dict(id=q["id"], need=q["need_id"], language=q["language"], question=q["question"],
                            topic=q["topic"], difficulty=q["difficulty"], answerability=q["answerability"],
                            types=q["types"], overlap=q["overlap_with_dev_validation"]["level"],
                            relevant=dict(q["relevant"]), quotes=q["evidence"], source_language=q["source_language"]))
        info["questions_sha256"] = raw["questions_sha256"]
    else:
        for r in raw["records"]:
            rel: dict[str, int] = {}
            for d in r["expected_document_ids"]:
                rel[d] = 1
            if r.get("primary_document_id"):
                rel[r["primary_document_id"]] = 2
            kept = {d: g for d, g in rel.items() if d in corpus_ids}
            info["dropped_labels"] += len(rel) - len(kept)
            if 2 not in kept.values() and kept:        # primary missing from the corpus: best remaining label counts
                kept = {d: 2 for d in kept}
            out.append(dict(id=r["question_id"], need=r["scenario"], language=r["language"], question=r["question"],
                            topic=r["category"], difficulty=str(r.get("difficulty")), answerability="answerable",
                            types=[], overlap="n/a", relevant=kept, quotes=[], source_language=None))
    info["questions"] = len(out)
    info["needs"] = len({r["need"] for r in out})
    return out, info


# ----------------------------------------------------------------------------------------------- metrics
def doc_metrics(docs: list[str], relevant: dict[str, int]) -> dict[str, float]:
    strict = {d for d, g in relevant.items() if g == 2}
    loose = set(relevant)
    rank = next((i + 1 for i, d in enumerate(docs) if d in strict), None)
    rank_len = next((i + 1 for i, d in enumerate(docs) if d in loose), None)
    ideal = sorted(relevant.values(), reverse=True)

    def ndcg(k: int) -> float:
        dcg = sum(relevant.get(d, 0) / math.log2(i + 2) for i, d in enumerate(docs[:k]))
        idcg = sum(g / math.log2(i + 2) for i, g in enumerate(ideal[:k]))
        return dcg / idcg if idcg else 0.0

    out = {f"hit@{k}": float(bool(rank and rank <= k)) for k in KS}
    out |= {f"hit@{k}_len": float(bool(rank_len and rank_len <= k)) for k in KS}
    out |= {f"recall@{k}": len(strict & set(docs[:k])) / len(strict) for k in (5, 10)} if strict else {}
    out |= dict(mrr=1.0 / rank if rank and rank <= 10 else 0.0, mrr_len=1.0 / rank_len if rank_len and rank_len <= 10 else 0.0,
                **{"ndcg@5": ndcg(5), "ndcg@10": ndcg(10)}, **{"p@5": sum(1 for d in docs[:5] if d in loose) / 5})
    return out | {"rank": rank, "rank_len": rank_len}


def quote_found(passage: str, quote: str) -> bool:
    return quote in passage


def passage_metrics(passages: list[str], context: list[str], quotes: list[dict[str, Any]]) -> dict[str, float]:
    qs = list(dict.fromkeys(q["quote"] for q in quotes))
    np_ = [norm(p) for p in passages]
    nc = [norm(p) for p in context]
    first = next((i + 1 for i, p in enumerate(np_) if any(quote_found(p, q) for q in qs)), None)
    found10 = {q for q in qs for p in np_[:10] if quote_found(p, q)}
    found_ctx = {q for q in qs for p in nc if quote_found(p, q)}
    return {**{f"phit@{k}": float(bool(first and first <= k)) for k in (1, 3, 5, 10)},
            "qrecall@10": len(found10) / len(qs), "pmrr": 1.0 / first if first and first <= 10 else 0.0,
            "ctx_hit": float(bool(found_ctx)), "ctx_qrecall": len(found_ctx) / len(qs), "prank": first}


# --------------------------------------------------------------------------------------------- statistics
def _clusters(rows: list[dict[str, Any]]) -> dict[str, list[int]]:
    groups: dict[str, list[int]] = defaultdict(list)
    for i, r in enumerate(rows):
        groups[r["need"]].append(i)
    return groups


def cluster_ci(rows: list[dict[str, Any]], metric: str, seed: int = 7) -> list[float]:
    vals = [r.get(metric) for r in rows]
    if not rows or any(v is None for v in vals):
        return []
    groups = list(_clusters(rows).values())
    rnd = random.Random(seed)
    means = []
    for _ in range(N_BOOT):
        pick = [i for _ in groups for i in groups[rnd.randrange(len(groups))]]
        means.append(statistics.fmean(vals[i] for i in pick))
    means.sort()
    return [round(means[int(0.025 * N_BOOT)], 3), round(means[int(0.975 * N_BOOT) - 1], 3)]


def summarize(rows: list[dict[str, Any]], metrics: list[str], ci: bool = True) -> dict[str, Any]:
    out: dict[str, Any] = {"n": len(rows), "needs": len({r["need"] for r in rows})}
    for m in metrics:
        vals = [r[m] for r in rows if r.get(m) is not None]
        if not vals:
            continue
        out[m] = round(statistics.fmean(vals), 3)
        if ci:
            sub = [r for r in rows if r.get(m) is not None]
            out[f"{m}_ci95"] = cluster_ci(sub, m)
    return out


def paired(a: list[dict[str, Any]], b: list[dict[str, Any]], metric: str, seed: int = 11) -> dict[str, Any]:
    """b minus a over the same questions; resamples needs."""
    assert [x["id"] for x in a] == [y["id"] for y in b]
    keep = [i for i, (x, y) in enumerate(zip(a, b)) if x.get(metric) is not None and y.get(metric) is not None]
    diffs = {i: b[i][metric] - a[i][metric] for i in keep}
    groups: dict[str, list[int]] = defaultdict(list)
    for i in keep:
        groups[a[i]["need"]].append(i)
    glist = list(groups.values())
    rnd = random.Random(seed)
    boots = []
    for _ in range(N_BOOT):
        pick = [i for _ in glist for i in glist[rnd.randrange(len(glist))]]
        boots.append(statistics.fmean(diffs[i] for i in pick))
    boots.sort()
    need_diff = {k: statistics.fmean(diffs[i] for i in v) for k, v in groups.items()}
    return dict(metric=metric, diff=round(statistics.fmean(diffs.values()), 3),
                ci95=[round(boots[int(0.025 * N_BOOT)], 3), round(boots[int(0.975 * N_BOOT) - 1], 3)],
                p_le_0=round(sum(1 for x in boots if x <= 0) / N_BOOT, 4), n=len(keep), needs=len(glist),
                questions_better=sum(1 for d in diffs.values() if d > 0), questions_worse=sum(1 for d in diffs.values() if d < 0),
                needs_better=sum(1 for d in need_diff.values() if d > 0), needs_worse=sum(1 for d in need_diff.values() if d < 0))


def breakdowns(rows: list[dict[str, Any]], metrics: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in ("language", "topic", "difficulty", "answerability", "overlap", "source_language", "cross_lingual"):
        vals = sorted({str(r.get(key)) for r in rows})
        if len(vals) > 1:
            out[key] = {v: summarize([r for r in rows if str(r.get(key)) == v], metrics, ci=False) for v in vals}
    return out


def pct(xs: list[float], q: float) -> float:
    s = sorted(xs)
    return round(s[min(len(s) - 1, max(0, int(math.ceil(q * len(s))) - 1))], 1) if s else 0.0
