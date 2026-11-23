"""Production readiness analysis: reranker runtime (Phase 4) and A/B/C retrieval + context quality (Phases 3, 5).

Reads research/data/experiments/reranker_runtime/*.json and research/data/experiments/readiness/corpus_v2/*.jsonl,
writes research/reports/production_readiness/*.csv. Statistics: paired cluster bootstrap over scenarios (4000
resamples, seed 20261123), two-sided bootstrap p-values, Holm correction within each table. Labels: frozen v0.1/v0.2
(document relevance, official) and the v0.3-draft passage criteria with AI-proposed documents (pending human review).

    research/.venv/bin/python research/scripts/readiness_analysis.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research/scripts"))
RT = ROOT / "research/data/experiments/reranker_runtime"
RD = ROOT / "research/data/experiments/readiness/corpus_v2"
REP = ROOT / "research/reports/production_readiness"
SEED, N = 20261123, 4000
GB = "d60bc363-0aae-44e5-b0c3-df8c61ad6f66"


def load_labels() -> tuple[dict, dict, dict, dict]:
    rec, draft = {}, {}
    for ds in ("pilot_v0.1", "heldout_v0.2"):
        for r in json.loads((ROOT / f"research/data/benchmarks/retrieval_{ds}.json").read_text())["records"]:
            rec[r["question_id"]] = dict(r, dataset=ds)
    for line in (ROOT / "research/data/review/passage_labels_v0.3_draft.jsonl").open(encoding="utf-8"):
        d = json.loads(line)
        draft[d["question_id"]] = d
    frozen = {q: set(r["expected_document_ids"]) for q, r in rec.items()}
    ai = {q: frozen[q] | {d["document_id"] for d in draft[q]["proposed_additional_documents"]} for q in rec}
    return rec, draft, frozen, ai


REC, DRAFT, FROZEN, AI = load_labels()


def doc_metrics(docs: list[str], exp: set[str]) -> dict:
    ranks = [i for i, d in enumerate(docs, 1) if d in exp]
    first = ranks[0] if ranks else None
    dcg = sum(1 / np.log2(r + 1) for r in ranks if r <= 5)
    ideal = sum(1 / np.log2(i + 1) for i in range(1, min(len(exp), 5) + 1))
    return dict(rr=1 / first if first else 0.0, r1=float(first == 1), r5=float(bool(first and first <= 5)),
                ndcg5=dcg / ideal if ideal else 0.0)


def boot(df: pd.DataFrame, col: str, a: str, b: str, key: str = "pipeline") -> dict:
    w = df.pivot_table(index=["scenario_id", "question_id"], columns=key, values=col).dropna(subset=[a, b]).reset_index()
    d = (w[a] - w[b]).to_numpy()
    groups = [d[(w.scenario_id == s).to_numpy()] for s in w.scenario_id.unique()]
    sums, counts = np.array([g.sum() for g in groups]), np.array([len(g) for g in groups])
    idx = np.random.default_rng(SEED).integers(0, len(groups), size=(N, len(groups)))
    bs = sums[idx].sum(1) / counts[idx].sum(1)
    p = min(1.0, 2 * min((bs <= 0).mean(), (bs >= 0).mean()))
    return dict(metric=col, a=a, b=b, n=len(w), mean_a=w[a].mean(), mean_b=w[b].mean(), diff=d.mean(),
                lo=np.percentile(bs, 2.5), hi=np.percentile(bs, 97.5), p_boot=p, a_better=int((d > 0).sum()),
                b_better=int((d < 0).sum()))


def holm(t: pd.DataFrame) -> pd.DataFrame:
    t = t.sort_values("p_boot").reset_index(drop=True)
    m = len(t)
    adj, run = [], 0.0
    for i, p in enumerate(t.p_boot):
        run = max(run, min(1.0, (m - i) * p))
        adj.append(run)
    t["p_holm"] = adj
    t["significant_holm"] = t.p_holm < 0.05
    return t


def ci(df: pd.DataFrame, col: str) -> tuple[float, float, float]:
    d = df.dropna(subset=[col])
    groups = [g[col].to_numpy() for _, g in d.groupby("scenario_id")]
    sums, counts = np.array([g.sum() for g in groups]), np.array([len(g) for g in groups])
    idx = np.random.default_rng(SEED).integers(0, len(groups), size=(N, len(groups)))
    bs = sums[idx].sum(1) / counts[idx].sum(1)
    return d[col].mean(), np.percentile(bs, 2.5), np.percentile(bs, 97.5)


# ------------------------------------------------------------------------------------------------ Phase 4
def runtime() -> None:
    from bench_reranker_runtime import workload

    work = {w["question_id"]: w for w in workload()}
    runs = {p.stem: json.loads(p.read_text()) for p in sorted(RT.glob("*.json")) if not p.stem.startswith("api")}
    ref = runs["torch_fp32_t1_b4"]["scores"]
    rows, quality = [], []
    for name, r in runs.items():
        agree = []
        for q, sc in r["scores"].items():
            a, b = np.array(ref[q]), np.array(sc)
            ra, rb = a.argsort()[::-1].argsort(), b.argsort()[::-1].argsort()
            n = len(a)
            conc = sum(np.sign(a[i] - a[j]) == np.sign(b[i] - b[j]) for i in range(n) for j in range(i + 1, n))
            pairs = n * (n - 1) / 2
            agree.append(dict(spearman=1 - 6 * ((ra - rb) ** 2).sum() / (n * (n * n - 1)), kendall=2 * conc / pairs - 1,
                              top1=float(a.argmax() == b.argmax()),
                              top5=len(set(a.argsort()[::-1][:5]) & set(b.argsort()[::-1][:5])) / 5,
                              max_abs_diff=float(np.abs(a - b).max())))
            order = sorted(range(n), key=lambda i: (-sc[i], i))
            docs = list(dict.fromkeys(work[q]["candidates"][i]["public_document_id"] for i in order))
            quality.append(dict(run=name, question_id=q, scenario_id=REC[q]["scenario_id"], dataset=REC[q]["dataset"],
                                language=REC[q]["language"], **doc_metrics(docs, FROZEN[q])))
        ag = pd.DataFrame(agree)
        rows.append(dict(run=name, variant=r["variant"], threads=r["threads"], batch=r["batch"], model_file_mb=r["model_file_mb"],
                         load_s=r["load_seconds"], rss_before_mb=r["rss_before_mb"], rss_after_load_mb=r["rss_after_load_mb"],
                         peak_rss_mb=r["peak_rss_mb"], latency_median_ms=r["latency_ms"]["median"],
                         latency_p90_ms=r["latency_ms"]["p90"], queries_per_s=r["throughput"]["queries_per_s"],
                         pairs_per_s=r["throughput"]["pairs_per_s"], spearman_mean=ag.spearman.mean(),
                         kendall_mean=ag.kendall.mean(), kendall_min=ag.kendall.min(), top1_agreement=ag.top1.mean(),
                         top5_overlap=ag.top5.mean(), max_abs_score_diff=ag.max_abs_diff.max()))
    t = pd.DataFrame(rows)
    Q = pd.DataFrame(quality)
    held = Q[Q.dataset == "heldout_v0.2"]
    qual = []
    for name in runs:
        g = held[held.run == name]
        row = dict(run=name)
        for m in ("rr", "r1", "r5", "ndcg5"):
            row[m], row[f"{m}_lo"], row[f"{m}_hi"] = ci(g, m)
        qual.append(row)
    qual = pd.DataFrame(qual)
    tests = holm(pd.DataFrame([boot(held, m, n, "torch_fp32_t1_b4", key="run") for n in runs if n.startswith("onnx")
                               and n.endswith("_t1_b4") for m in ("rr", "r1")]))
    api = [json.loads(p.read_text()) for p in sorted(RT.glob("api_footprint_*.json"))]
    REP.mkdir(parents=True, exist_ok=True)
    t.round(4).to_csv(REP / "reranker_runtime.csv", index=False)
    qual.round(4).to_csv(REP / "reranker_quality_heldout.csv", index=False)
    tests.round(4).to_csv(REP / "reranker_quality_paired.csv", index=False)
    pd.DataFrame(api).to_csv(REP / "reranker_api_footprint.csv", index=False)
    pd.set_option("display.width", 250)
    print(t.drop(columns=["rss_before_mb"]).round(3).to_string(index=False))
    print(qual.round(3).to_string(index=False))
    print(tests[["metric", "a", "b", "diff", "lo", "hi", "p_holm"]].round(4).to_string(index=False))
    print(pd.DataFrame(api).to_string(index=False))


# ------------------------------------------------------------------------------------------------ Phase 3 / 5
def supports(q: str, doc: str, p: dict) -> bool:
    if doc not in AI[q]:
        return False
    ps = DRAFT[q]["passage_support"]
    text = (p["text"] or "").lower()
    return any(t.lower() in text for t in ps["evidence_terms"]) or (doc == GB and p.get("page") in set(ps["guidebook_pages"]))


def context() -> None:
    rows = []
    for f in sorted(RD.glob("*.jsonl")):
        for line in f.open(encoding="utf-8"):
            r = json.loads(line)
            q = r["question_id"]
            docs = [s["document_id"] for s in r["sources"]]
            ps = [(s["document_id"], p) for s in r["sources"] for p in s["passages"]]
            crit = DRAFT[q]["passage_support"]
            terms = [t.lower() for t in crit["evidence_terms"]]
            joined = " ".join((p["text"] or "").lower() for _, p in ps)
            rows.append(dict(pipeline=r["pipeline"], question_id=q, scenario_id=r["scenario_id"], dataset=r["dataset"],
                             language=r["language"], **doc_metrics(docs, FROZEN[q]),
                             rr_ai=doc_metrics(docs, AI[q])["rr"],
                             support=float(any(supports(q, d, p) for d, p in ps)) if (crit["evidence_terms"] or crit["guidebook_pages"]) else np.nan,
                             term_coverage=sum(t in joined for t in terms) / len(terms) if terms else np.nan,
                             sources=len(r["sources"]), passages=len(ps), context_chars=sum(p["chars"] for _, p in ps),
                             max_share_one_doc=max((sum(p["chars"] for p in s["passages"]) for s in r["sources"]), default=0)
                             / max(1, sum(p["chars"] for _, p in ps)),
                             first_stage_ms=r["first_stage_ms"], rerank_ms=r["rerank_ms"], select_ms=r["select_ms"], pool=r["pool"]))
    D = pd.DataFrame(rows)
    held = D[D.dataset == "heldout_v0.2"]
    summ = []
    for name, g in held.groupby("pipeline"):
        row = dict(pipeline=name, n=len(g))
        for m in ("rr", "r1", "r5", "ndcg5", "rr_ai", "support", "term_coverage"):
            row[m], row[f"{m}_lo"], row[f"{m}_hi"] = ci(g, m)
        row.update(context_chars_median=g.context_chars.median(), sources_mean=g.sources.mean(), passages_mean=g.passages.mean(),
                   max_share_one_doc_median=g.max_share_one_doc.median(), pool_median=g.pool.median(),
                   rerank_ms_median=g.rerank_ms.median(), rerank_ms_p90=g.rerank_ms.quantile(.9),
                   select_ms_median=g.select_ms.median(), first_stage_ms_median=g.first_stage_ms.median())
        summ.append(row)
    S = pd.DataFrame(summ)
    lang = held.groupby(["pipeline", "language"]).rr.mean().unstack(1)
    comps = [("B", "A"), ("C", "B"), ("C", "A"), ("C", "C_noprs")]
    tests = holm(pd.DataFrame([boot(held, m, a, b) for a, b in comps if {a, b} <= set(held.pipeline)
                               for m in ("rr", "support", "term_coverage")]))
    REP.mkdir(parents=True, exist_ok=True)
    S.round(4).to_csv(REP / "abc_context_summary_heldout.csv", index=False)
    tests.round(4).to_csv(REP / "abc_paired_heldout.csv", index=False)
    lang.round(3).to_csv(REP / "abc_mrr_by_language_heldout.csv")
    D.to_csv(REP / "abc_per_question.csv", index=False)
    pd.set_option("display.width", 250)
    print(S[["pipeline", "n", "rr", "rr_lo", "rr_hi", "r1", "ndcg5", "rr_ai", "support", "term_coverage", "context_chars_median",
             "passages_mean", "max_share_one_doc_median", "pool_median", "rerank_ms_median", "rerank_ms_p90",
             "select_ms_median"]].round(3).to_string(index=False))
    print(lang.round(3).to_string())
    print(tests[["metric", "a", "b", "mean_a", "mean_b", "diff", "lo", "hi", "p_holm", "significant_holm"]].round(4).to_string(index=False))


if __name__ == "__main__":
    what = sys.argv[1:] or ["runtime", "context"]
    if "runtime" in what:
        runtime()
    if "context" in what:
        context()
