"""Shared analysis helpers for the research notebooks (pure pandas / numpy / scipy / matplotlib; no backend imports).

Metric definitions (document level, binary relevance; a question's ranked list = its top-k retrieved documents):
  Recall@k   1 if any expected document is ranked <= k, else 0; averaged over questions
  MRR        1 / rank of the first expected document (0 if none in the top-k)
  nDCG@5     sum over expected documents ranked <= 5 of 1/log2(rank+1), divided by the ideal DCG for
             min(#expected, 5) relevant documents
Uncertainty: 95% percentile intervals from a CLUSTER bootstrap that resamples scenarios (the five language
versions of one scenario are not independent), 4,000 resamples, fixed seed. Paired comparisons resample scenarios
for the difference; exact McNemar (binomial) tests on Recall@1 discordant pairs are reported as supporting evidence.
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

SEED = 20261123
RESEARCH = Path(__file__).resolve().parents[1]
DATA = RESEARCH / "data"
# Dataset snapshot selection: RAG_SNAPSHOT=corpus_v1 (Milestone 4) | corpus_v2 (default, current). Each snapshot reads
# its own statistics and results and writes its own figures/reports, so earlier outputs are never overwritten.
import os as _os
SNAPSHOT = _os.environ.get("RAG_SNAPSHOT", "corpus_v2")
SNAP = DATA / "snapshots" / SNAPSHOT
_LEGACY = SNAPSHOT == "corpus_v1"          # Milestone 4 outputs live at the top level
RESULTS = DATA / "results" if _LEGACY else DATA / "results" / SNAPSHOT
FIGURES = RESEARCH / "figures" if _LEGACY else RESEARCH / "figures" / SNAPSHOT
REPORTS = RESEARCH / "reports" if _LEGACY else RESEARCH / "reports" / SNAPSHOT
LANGS = ["ko", "en", "id", "vi", "zh-CN"]
LANG_NAMES = {"ko": "Korean", "en": "English", "id": "Indonesian", "vi": "Vietnamese", "zh-CN": "Chinese (Simpl.)"}
METHODS = {"B0": "B0 Vector-only", "E1": "E1 Original hybrid", "E2": "E2 Improved hybrid",
           "E2S": "E2S + evidence selection"}
# validated categorical order (dataviz reference palette, light mode): slots 1-4
COLORS = {"B0": "#2a78d6", "E1": "#eb6834", "E2": "#1baf7a", "E2S": "#eda100"}
SINGLE = "#2a78d6"                       # one-series charts: slot 1
INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"


# ----------------------------------------------------------------------------------------------- data
def load_retrieval(name: str) -> pd.DataFrame:
    df = pd.read_csv(RESULTS / name)
    df["rank"] = pd.to_numeric(df["rank_first_relevant"], errors="coerce")
    df["relevant_ranks"] = df["relevant_ranks"].apply(json.loads)
    df["r1"] = (df["rank"] == 1).astype(float)
    df["r3"] = (df["rank"] <= 3).astype(float)
    df["r5"] = (df["rank"] <= 5).astype(float)
    df["r10"] = (df["rank"] <= 10).astype(float)
    df["rr"] = (1.0 / df["rank"]).fillna(0.0)
    df["ndcg5"] = [ndcg_at_k(r, n, 5) for r, n in zip(df["relevant_ranks"], df["n_relevant"], strict=True)]
    df["ndcg10"] = [ndcg_at_k(r, n, 10) for r, n in zip(df["relevant_ranks"], df["n_relevant"], strict=True)]
    if "error" in df.columns:
        df.loc[df["error"].fillna("").astype(str) != "", ["r1", "r3", "r5", "r10", "rr", "ndcg5", "ndcg10"]] = np.nan
    return df


def score_rankings(df: pd.DataFrame, expected: dict[str, set[str]]) -> pd.DataFrame:
    """(Re)compute rank metrics from the saved document rankings (`retrieved_documents`, top 10) for a given label
    set {question_id: expected document ids}. Used for label-sensitivity analyses without re-running retrieval."""
    out = df.copy()
    docs = out["retrieved_documents"].apply(json.loads)
    out["relevant_ranks"] = [[i + 1 for i, d in enumerate(ds) if d in expected[q]] for ds, q in zip(docs, out["question_id"], strict=True)]
    out["n_relevant"] = out["question_id"].map(lambda q: len(expected[q]))
    out["rank"] = out["relevant_ranks"].map(lambda r: r[0] if r else np.nan)
    out["r1"] = (out["rank"] == 1).astype(float)
    out["r3"] = (out["rank"] <= 3).astype(float)
    out["r5"] = (out["rank"] <= 5).astype(float)
    out["r10"] = (out["rank"] <= 10).astype(float)
    out["rr"] = (1.0 / out["rank"]).fillna(0.0)
    out["ndcg5"] = [ndcg_at_k(r, n, 5) for r, n in zip(out["relevant_ranks"], out["n_relevant"], strict=True)]
    out["ndcg10"] = [ndcg_at_k(r, n, 10) for r, n in zip(out["relevant_ranks"], out["n_relevant"], strict=True)]
    return out


def ndcg_at_k(ranks: list[int], n_relevant: int, k: int = 5) -> float:
    dcg = sum(1.0 / np.log2(r + 1) for r in ranks if r <= k)
    ideal = sum(1.0 / np.log2(i + 1) for i in range(1, min(int(n_relevant), k) + 1))
    return float(dcg / ideal) if ideal else 0.0


# ----------------------------------------------------------------------------------------- statistics
def cluster_bootstrap(df: pd.DataFrame, col: str, n: int = 4000, seed: int = SEED) -> tuple[float, float, float]:
    """Mean and 95% CI of `col`, resampling scenario clusters."""
    d = df.dropna(subset=[col])
    groups = [g[col].to_numpy() for _, g in d.groupby("scenario_id")]
    if not groups:
        return (np.nan, np.nan, np.nan)
    rng = np.random.default_rng(seed)
    sums = np.array([g.sum() for g in groups])
    counts = np.array([len(g) for g in groups])
    idx = rng.integers(0, len(groups), size=(n, len(groups)))
    boots = sums[idx].sum(axis=1) / counts[idx].sum(axis=1)
    return float(d[col].mean()), float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))


def summarize(df: pd.DataFrame, by: list[str] | None = None, metrics=("r1", "r5", "rr", "ndcg5")) -> pd.DataFrame:
    rows = []
    keys = by or []
    for key, g in (df.groupby(keys) if keys else [((), df)]):
        key = key if isinstance(key, tuple) else (key,)
        row = dict(zip(keys, key, strict=False))
        row["n"] = int(g[list(metrics)[0]].notna().sum())
        for m in metrics:
            mean, lo, hi = cluster_bootstrap(g, m)
            row[m], row[f"{m}_lo"], row[f"{m}_hi"] = mean, lo, hi
        rows.append(row)
    return pd.DataFrame(rows)


def paired_difference(df: pd.DataFrame, a: str, b: str, col: str, n: int = 4000, seed: int = SEED) -> dict:
    """Difference a - b in `col` (same questions), cluster-bootstrap CI over scenarios; McNemar for binary cols."""
    wide = df.pivot_table(index=["scenario_id", "question_id"], columns="method", values=col).dropna(subset=[a, b])
    wide = wide.reset_index()
    diff = (wide[a] - wide[b])
    groups = [g.to_numpy() for _, g in diff.groupby(wide["scenario_id"])]
    rng = np.random.default_rng(seed)
    sums = np.array([g.sum() for g in groups]); counts = np.array([len(g) for g in groups])
    idx = rng.integers(0, len(groups), size=(n, len(groups)))
    boots = sums[idx].sum(axis=1) / counts[idx].sum(axis=1)
    out = dict(metric=col, a=a, b=b, n=len(wide), mean_a=float(wide[a].mean()), mean_b=float(wide[b].mean()),
               diff=float(diff.mean()), lo=float(np.percentile(boots, 2.5)), hi=float(np.percentile(boots, 97.5)),
               a_better=int((diff > 0).sum()), b_better=int((diff < 0).sum()))
    out["relative_pct"] = 100 * out["diff"] / out["mean_b"] if out["mean_b"] else np.nan
    if set(np.unique(wide[[a, b]].to_numpy())) <= {0.0, 1.0}:
        k, m = out["a_better"], out["a_better"] + out["b_better"]
        out["mcnemar_p"] = float(stats.binomtest(k, m, 0.5).pvalue) if m else 1.0
    out["ci_excludes_zero"] = bool(out["lo"] > 0 or out["hi"] < 0)
    return out


# -------------------------------------------------------------------------------------------- figures
KOREAN_FALLBACKS = ["Noto Sans KR", "Noto Sans CJK KR", "Apple SD Gothic Neo", "AppleGothic", "Malgun Gothic",
                    "NanumGothic"]


def _register_fonts() -> list[str]:
    """Korean (한글) glyphs: research/fonts/*.ttf (scripts/get_fonts.sh) or an installed system font. matplotlib uses
    the font.family list as a per-glyph fallback chain, so Latin text keeps DejaVu Sans and only Hangul uses these."""
    from matplotlib import font_manager as fm

    for f in sorted((RESEARCH / "fonts").glob("*.[to]tf")):
        fm.fontManager.addfont(str(f))
    installed = {f.name for f in fm.fontManager.ttflist}
    found = [name for name in KOREAN_FALLBACKS if name in installed]
    if not found:
        print("warning: no Korean font found - run research/scripts/get_fonts.sh (Hangul would show as boxes)")
    return found


def style() -> None:
    korean = _register_fonts()
    matplotlib.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "axes.edgecolor": GRID, "axes.labelcolor": INK2, "axes.titlecolor": INK, "axes.titleweight": "semibold",
        "axes.titlesize": 12, "axes.labelsize": 10, "xtick.color": INK2, "ytick.color": INK2,
        "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "axes.grid.axis": "y",
        "grid.color": GRID, "grid.linewidth": 0.8, "axes.axisbelow": True, "legend.frameon": False,
        "font.size": 10, "font.family": ["DejaVu Sans", *korean, "sans-serif"], "svg.fonttype": "path"})


def save(fig: plt.Figure, name: str, folder: Path | None = None) -> list[str]:
    """Write PNG + SVG to figures/<snapshot>/ (or to ``folder`` for experiments outside the snapshot series)."""
    target = folder or FIGURES
    target.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    paths = []
    for ext in ("png", "svg"):
        p = target / f"{name}.{ext}"
        fig.savefig(p, dpi=200 if ext == "png" else None, bbox_inches="tight")
        paths.append(str(p.relative_to(RESEARCH)))
    return paths


def grouped_bars(ax, table: pd.DataFrame, groups: list[str], series: list[str], value: str, labels: dict | None = None,
                 colors: dict | None = None, fmt: str = "{:.2f}", ylim=(0, 1.05)) -> None:
    """Grouped bars with 95% CI whiskers and value labels (relief for low-contrast hues). table: series x group."""
    width = 0.8 / len(series)
    x = np.arange(len(groups))
    for i, s in enumerate(series):
        vals = [table.loc[(s, g), value] if (s, g) in table.index else np.nan for g in groups]
        lo = [table.loc[(s, g), f"{value}_lo"] if (s, g) in table.index else np.nan for g in groups]
        hi = [table.loc[(s, g), f"{value}_hi"] if (s, g) in table.index else np.nan for g in groups]
        pos = x - 0.4 + width * (i + 0.5)
        ax.bar(pos, vals, width * 0.92, color=(colors or COLORS).get(s, SINGLE), label=(labels or METHODS).get(s, s),
               zorder=2)
        err = np.array([np.subtract(vals, lo), np.subtract(hi, vals)])
        ax.errorbar(pos, vals, yerr=err, fmt="none", ecolor=INK2, elinewidth=1, capsize=2.5, zorder=3)
        for px, v, h in zip(pos, vals, hi, strict=True):
            if not np.isnan(v):
                ax.text(px, (h if not np.isnan(h) else v) + 0.015, fmt.format(v), ha="center", va="bottom",
                        fontsize=7.5, color=INK)
    ax.set_xticks(x, groups)
    ax.set_ylim(*ylim)
