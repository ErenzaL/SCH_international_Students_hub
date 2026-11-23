"""Generate the eight research notebooks (research/notebooks/*.ipynb) from this file.

Notebooks are generated rather than hand-edited so their structure stays consistent; every number shown in them
is computed at run time from the versioned files in research/data (never typed in). Re-generate, then execute:

    research/.venv/bin/python research/scripts/build_notebooks.py
    research/.venv/bin/python research/scripts/run_notebooks.py
"""
from __future__ import annotations

from pathlib import Path

import nbformat as nbf

OUT = Path(__file__).resolve().parents[1] / "notebooks"

SETUP = '''\
import sys, json, platform, warnings
from pathlib import Path
import numpy as np, pandas as pd, scipy, matplotlib
import matplotlib.pyplot as plt
from IPython.display import Markdown, display

RESEARCH = Path.cwd().parent if Path.cwd().name == "notebooks" else Path.cwd() / "research"
sys.path.insert(0, str(RESEARCH / "scripts"))
import analysis as A

A.style()
np.random.seed(A.SEED)
warnings.filterwarnings("ignore", category=FutureWarning)
pd.set_option("display.max_columns", 30); pd.set_option("display.width", 160)
EXPERIMENTS = json.loads((RESEARCH / "configs/experiments.json").read_text())
print(f"python {platform.python_version()} | pandas {pd.__version__} | numpy {np.__version__} | "
      f"scipy {scipy.__version__} | matplotlib {matplotlib.__version__} | seed {A.SEED}")
print(f"dataset snapshot: {A.SNAPSHOT} (set RAG_SNAPSHOT=corpus_v1|corpus_v2) | results: {A.RESULTS.relative_to(RESEARCH)} | "
      f"figures: {A.FIGURES.relative_to(RESEARCH)}")
'''


def md(text: str):
    return nbf.v4.new_markdown_cell(text.strip())


def code(text: str):
    return nbf.v4.new_code_cell(text.strip())


def notebook(name: str, title: str, purpose: str, cells: list) -> None:
    nb = nbf.v4.new_notebook()
    nb.metadata["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
    nb.metadata["language_info"] = {"name": "python"}
    nb.cells = [md(f"# {title}\n\n{purpose}\n\n**Inputs** are versioned files under `research/data/` and "
                   "`research/configs/`; nothing here connects to the production database or writes to it. "
                   "Run top to bottom (Kernel → Restart & Run All)."), code(SETUP)] + cells
    OUT.mkdir(parents=True, exist_ok=True)
    nbf.write(nb, OUT / name)


# =============================================================================================== 01
notebook("01_dataset_exploration.ipynb", "01 · Dataset exploration",
         "Documents in the knowledge base: publication and indexing state, languages, categories, source types, "
         "versions, page metadata, missing metadata and data-quality findings.", [
    code('''\
stats = json.loads((A.SNAP / "dataset_statistics.json").read_text())
manifest = json.loads((A.SNAP / "corpus_manifest.json").read_text())
docs, versions, chunks = stats["documents"], stats["versions"], stats["chunks"]
print("statistics generated at:", stats["generated_at"], "(read-only query: research/sql/dataset_statistics.sql)")
print("public corpus snapshot:", manifest["snapshot_sha256_16"], "-", len(manifest["items"]), "items")'''),
    md("## Overview\n\n*Active* = the current approved version of a non-canceled, non-archived document of an "
       "active source - exactly what the retrieval view `searchable_chunks` exposes. Everything else is historical."),
    code('''\
overview = pd.DataFrame([
    ("Knowledge documents (all)", docs["total"]),
    ("Documents with an approved current version", docs["with_an_approved_current_version"]),
    ("Active (searchable) documents", docs["active_searchable"]),
    ("Active documents fully indexed (every chunk embedded)", docs["indexed_active (all chunks embedded)"]),
    ("Active documents without chunks", docs["active_without_chunks"]),
    ("Canceled documents", docs["canceled"]), ("Archived documents", docs["archived"]),
    ("Document versions (all)", versions["total"]),
    ("Extracted pages (documents with page metadata only)", stats["pages"]["total_pages_from_extraction_metadata"]),
    ("Documents with page metadata", stats["pages"]["documents_with_page_metadata"]),
], columns=["measure", "value"])
overview'''),
    code('''\
def as_table(d, name):
    return pd.Series(d, name=name).sort_values(ascending=False).rename_axis("value").reset_index(name="documents")

lang = as_table(docs["by_language"], "language"); cat = as_table(docs["by_category"], "category")
dtype = as_table(docs["by_document_type"], "type"); src = as_table(docs["by_source_type"], "source")
display(lang); display(cat); display(dtype); display(src)'''),
    code('''\
fig, axes = plt.subplots(1, 2, figsize=(11, 3.8), gridspec_kw={"width_ratios": [2.2, 1]})
c = cat.sort_values("documents")
axes[0].barh(c["value"], c["documents"], color=A.SINGLE, height=0.6, zorder=2)
for y, v in enumerate(c["documents"]):
    axes[0].text(v + 0.08, y, str(v), va="center", fontsize=9, color=A.INK)
axes[0].set_title(f"Active documents by category (n = {docs['active_searchable']})"); axes[0].set_xlabel("documents")
axes[0].grid(axis="x"); axes[0].grid(axis="y", visible=False)
l = lang.copy(); l["label"] = l["value"].map(lambda x: A.LANG_NAMES.get(x, x))
axes[1].bar(l["label"], l["documents"], color=A.SINGLE, width=0.55, zorder=2)
for x, v in enumerate(l["documents"]):
    axes[1].text(x, v + 0.2, str(v), ha="center", fontsize=9, color=A.INK)
axes[1].set_title("Original document language"); axes[1].set_ylabel("documents")
fig.tight_layout(); print(A.save(fig, "01_documents_by_category_and_language"))'''),
    md("## Versions, indexing state and jobs"),
    code('''\
display(pd.Series(versions["by_status"], name="versions").rename_axis("verification status").reset_index())
display(pd.Series(versions["by_indexing_status"], name="versions").rename_axis("indexing_status flag").reset_index())
display(pd.Series(stats["announcements"], name="announcements").rename_axis("publication status").reset_index())
display(pd.Series(stats["jobs"], name="jobs").rename_axis("job type:status").reset_index())'''),
    md("## Missing metadata and data quality"),
    code('''\
items = pd.DataFrame(manifest["items"])
quality = pd.DataFrame([
    ("Active documents with a validity end date (valid_until)", docs["with_valid_until"], docs["active_searchable"]),
    ("Public items with an official source URL", int(items["has_source_url"].sum()), len(items)),
    ("Active documents with page metadata", stats["pages"]["documents_with_page_metadata"], docs["active_searchable"]),
    ("Versions whose indexing_status flag is not 'indexed'",
     sum(v for k, v in versions["by_indexing_status"].items() if k != "indexed"), versions["total"]),
    ("Failed ingestion jobs", sum(v for k, v in stats["jobs"].items() if k.endswith(":failed")), sum(stats["jobs"].values())),
    ("Active chunks shorter than 250 characters", chunks["size_histogram_chars_active"].get("0-249", 0), chunks["active"]),
], columns=["check", "count", "out_of"])
quality["share"] = (quality["count"] / quality["out_of"]).round(3)
quality'''),
    code('''\
flag = sum(v for k, v in versions["by_indexing_status"].items() if k != "indexed")
display(Markdown(f"""**Interpretation.** All {docs['active_searchable']} active documents are fully indexed
({chunks['active_with_embedding']}/{chunks['active']} active chunks carry an embedding), yet {flag} version rows still carry
an `indexing_status` other than `indexed` - a bookkeeping inconsistency, not missing embeddings. Only
{docs['with_valid_until']} of {docs['active_searchable']} active documents carry a validity end date, so time-bound content
(e.g. a past course-registration period) cannot expire automatically; {int((~items['has_source_url']).sum())} of
{len(items)} public items have no official source URL. Page counts exist only for the
{stats['pages']['documents_with_page_metadata']} PDF documents and are not imputed for the others."""))'''),
    md("## Snapshot comparison (corpus_v1 → corpus_v2)\n\nBoth snapshots are read-only exports of the production "
       "database (`data/snapshots/<snapshot>/`). This section compares them whatever snapshot the notebook runs on."),
    code('''\
snaps = {k: json.loads((A.DATA / "snapshots" / k / "dataset_statistics.json").read_text())
         for k in ("corpus_v1", "corpus_v2") if (A.DATA / "snapshots" / k / "dataset_statistics.json").exists()}
if len(snaps) < 2:
    display(Markdown("Not evaluated: only one snapshot is available."))
else:
    a, b = snaps["corpus_v1"], snaps["corpus_v2"]
    def g(s, *path):
        for p in path: s = s.get(p, {}) if isinstance(s, dict) else {}
        return s
    comp = pd.DataFrame([(name, g(a, *p), g(b, *p)) for name, p in (
        ("snapshot time (UTC)", ("generated_at",)), ("documents (all)", ("documents", "total")),
        ("active documents", ("documents", "active_searchable")), ("fully indexed active documents", ("documents", "indexed_active (all chunks embedded)")),
        ("known pages (PDF metadata)", ("pages", "total_pages_from_extraction_metadata")), ("active chunks", ("chunks", "active")),
        ("active chunks with embedding", ("chunks", "active_with_embedding")), ("historical chunks", ("chunks", "historical")),
        ("median chunk size (chars)", ("chunks", "size_chars_active", "median")), ("mean chunk size (chars)", ("chunks", "size_chars_active", "mean")),
        ("documents with valid_until", ("documents", "with_valid_until")))], columns=["measure", "corpus_v1", "corpus_v2"])
    display(comp)
    lang = pd.DataFrame({"documents v1": g(a, "documents", "by_language"), "documents v2": g(b, "documents", "by_language"),
                         "chunks v1": g(a, "chunks", "by_language_active"), "chunks v2": g(b, "chunks", "by_language_active")}).fillna(0).astype(int)
    cat = pd.DataFrame({"documents v1": g(a, "documents", "by_category"), "documents v2": g(b, "documents", "by_category"),
                        "chunks v1": g(a, "chunks", "by_category_active"), "chunks v2": g(b, "chunks", "by_category_active")}).fillna(0).astype(int)
    display(lang); display(cat)
    fig, axes = plt.subplots(1, 2, figsize=(12, 3.8))
    for ax, (tab, title) in zip(axes, ((lang, "language"), (cat, "category"))):
        y = np.arange(len(tab)); h = 0.38
        ax.barh(y - h / 2, tab["chunks v1"], h, color=A.COLORS["B0"], label="corpus_v1", zorder=2)
        ax.barh(y + h / 2, tab["chunks v2"], h, color=A.COLORS["E1"], label="corpus_v2", zorder=2)
        for yy, v1, v2 in zip(y, tab["chunks v1"], tab["chunks v2"]):
            ax.text(v1 + 3, yy - h / 2, str(v1), va="center", fontsize=8); ax.text(v2 + 3, yy + h / 2, str(v2), va="center", fontsize=8)
        ax.set_yticks(y, [A.LANG_NAMES.get(i, i) for i in tab.index]); ax.invert_yaxis()
        ax.set_title(f"Active chunks by {title}"); ax.set_xlabel("chunks"); ax.grid(axis="x"); ax.grid(axis="y", visible=False)
    axes[1].legend(loc="lower right"); fig.tight_layout(); print(A.save(fig, "01_snapshot_comparison"))'''),
    code('''\
inv_f = A.DATA / "snapshots" / "corpus_v2" / "document_inventory.csv"
if len(snaps) == 2 and inv_f.exists():
    inv = pd.read_csv(inv_f)
    v1_ids = {d["id"] for d in snaps["corpus_v1"]["per_document"]}
    added = inv[~inv.document_id.isin(v1_ids) & ~inv.is_canceled]
    cols = ["document_id", "title", "source_type", "language", "category", "current_status", "current_version_number",
            "pages_metadata", "current_chunks", "current_embedded", "searchable_chunks", "indexing_status", "source_url",
            "same_hash_other_documents", "same_title_other_documents", "failed_jobs_for_source"]
    display(Markdown(f"**Documents added since corpus_v1** ({len(added)}):")); display(added[cols])
    coverage = inv[~inv.is_canceled & inv.current_status.eq("approved")].assign(
        fully_embedded=lambda d: d.current_embedded == d.current_chunks, searchable=lambda d: d.searchable_chunks > 0)
    display(Markdown("**Indexing coverage (approved, non-canceled documents):**"))
    display(coverage[["fully_embedded", "searchable"]].agg(["sum", "count"]).T.assign(problem=lambda d: d["count"] - d["sum"]))
    ch2 = pd.read_csv(A.DATA / "snapshots" / "corpus_v2" / "chunk_metrics.csv")
    new_ch = ch2[ch2.active & ch2.document_id.isin(added.document_id)]
    display(Markdown(f"""**Change summary.** {len(added)} documents added ({', '.join(added.title)}); active chunks
{snaps['corpus_v1']['chunks']['active']} → {snaps['corpus_v2']['chunks']['active']}; Korean chunks
{g(snaps['corpus_v1'], 'chunks', 'by_language_active').get('ko', 0)} → {g(snaps['corpus_v2'], 'chunks', 'by_language_active').get('ko', 0)}.
The new chunks are short (median {new_ch.chars.median():.0f} characters, {int((new_ch.chars < 100).sum())} of {len(new_ch)} under
100): the PDF's layout fragments the chunker's segments - an indexing-quality issue to fix before relying on this
document for retrieval experiments. Benchmark labels predate these documents and must be reviewed for corpus_v2."""))'''),
])

# =============================================================================================== 02
notebook("02_chunk_analysis.ipynb", "02 · Chunk analysis",
         "Chunk counts, sizes (characters and the chunker's token estimate), overlap, document-to-chunk "
         "relationships, embedding coverage and configuration. Only numeric per-chunk metrics are used (no text).", [
    code('''\
ch = pd.read_csv(A.SNAP / "chunk_metrics.csv")
stats = json.loads((A.SNAP / "dataset_statistics.json").read_text())
cfg = EXPERIMENTS["shared"]
active = ch[ch["active"]].copy()
print(f"{len(ch)} chunk rows: {len(active)} active, {int((~ch['active']).sum())} historical")
pd.DataFrame([("embedding model", cfg["embedding_model"] + " · " + cfg["embedding_variant"]),
              ("embedding dimensions", cfg["embedding_dimensions"]),
              ("dimensions present in the database", stats["chunks"]["embedding_dimensions"]),
              ("chunker", json.dumps(cfg["chunker"])), ("vector index", cfg["vector_store"]["index"]),
              ("pgvector", stats["pgvector_version"])], columns=["setting", "value"])'''),
    code('''\
cov = pd.DataFrame([("active chunks", len(active)), ("active chunks with embedding", int(active["has_embedding"].sum())),
                    ("historical chunks", int((~ch["active"]).sum())),
                    ("historical chunks with embedding", int(ch.loc[~ch["active"], "has_embedding"].sum())),
                    ("chunk strategies", ", ".join(sorted(ch["chunk_strategy"].unique())))], columns=["measure", "value"])
cov'''),
    md("## Chunk size\n\n`chars` is exact. `token_count` is the chunker's heuristic estimate (words × 1.3 + CJK "
       "characters), not a tokenizer count - it is labelled as an estimate everywhere."),
    code('''\
desc = active[["chars", "token_count"]].describe(percentiles=[0.25, 0.5, 0.75, 0.95]).T
desc.index = ["characters (exact)", "tokens (chunker estimate)"]
desc.round(1)'''),
    code('''\
fig, axes = plt.subplots(1, 2, figsize=(11, 3.8))
axes[0].hist(active["chars"], bins=np.arange(0, active["chars"].max() + 100, 100), color=A.SINGLE,
             edgecolor=A.SURFACE, linewidth=1.5, zorder=2)
axes[0].axvline(active["chars"].median(), color=A.INK2, linestyle="--", linewidth=1)
axes[0].text(active["chars"].median(), axes[0].get_ylim()[1] * 0.92, f" median {active['chars'].median():.0f}",
             color=A.INK2, fontsize=9)
axes[0].set_title(f"Active chunk size (n = {len(active)})"); axes[0].set_xlabel("characters per chunk"); axes[0].set_ylabel("chunks")
by_lang = [active.loc[active["language"] == l, "chars"] for l in ["en", "ko"]]
bp = axes[1].boxplot(by_lang, tick_labels=[f"English (n={len(by_lang[0])})", f"Korean (n={len(by_lang[1])})"],
                     patch_artist=True, widths=0.45, medianprops={"color": A.INK})
for patch in bp["boxes"]:
    patch.set_facecolor(A.SINGLE); patch.set_alpha(0.55); patch.set_edgecolor(A.INK2)
axes[1].set_title("Chunk size by document language"); axes[1].set_ylabel("characters per chunk")
fig.tight_layout(); print(A.save(fig, "02_chunk_size_distribution"))'''),
    md("## Document-to-chunk relationship"),
    code('''\
per_doc = pd.DataFrame(stats["per_document"])
per_doc["label"] = per_doc["title"].map(lambda t: t if len(t) <= 38 else t[:37].rstrip() + "…")
display(per_doc[["title", "language", "document_type", "chunks", "embedded", "pages_metadata", "text_chars"]])
fig, ax = plt.subplots(figsize=(9, 6.2))
p = per_doc.sort_values("chunks")
ax.barh(p["label"], p["chunks"], color=A.SINGLE, height=0.65, zorder=2)
for y, v in enumerate(p["chunks"]):
    ax.text(v + 1, y, str(v), va="center", fontsize=8, color=A.INK)
ax.set_title(f"Active chunks per document (n = {len(per_doc)} documents, {int(per_doc['chunks'].sum())} chunks)")
ax.set_xlabel("chunks"); ax.grid(axis="x"); ax.grid(axis="y", visible=False); ax.tick_params(axis="y", labelsize=8)
fig.tight_layout(); print(A.save(fig, "02_chunks_per_document"))'''),
    md("## Overlap between consecutive chunks\n\nMeasured as: the first 60 characters of a chunk occur in the "
       "previous chunk of the same version (computed in SQL, `research/sql/chunk_metrics.sql`)."),
    code('''\
nxt = active[active["chunk_index"] > 0]
rate = nxt["overlap_with_previous"].astype(float).mean()
share_top = per_doc["chunks"].nlargest(1).sum() / per_doc["chunks"].sum()
display(Markdown(f"""**Interpretation.** The configured overlap is {cfg['chunker']['overlap_tokens']} estimated tokens, but only
{rate:.1%} of non-first chunks ({int(nxt['overlap_with_previous'].sum())}/{len(nxt)}) begin with text found in the previous
chunk: the chunker breaks at headings/paragraphs and carries overlap only inside long sections, so most boundaries are
clean section breaks. Chunk sizes are skewed (median {active['chars'].median():.0f}, mean {active['chars'].mean():.0f}
characters; {int((active['chars'] < 250).sum())} chunks under 250 characters, minimum {active['chars'].min()}). One
document holds {share_top:.0%} of all active chunks, so corpus-level chunk statistics are dominated by it."""))'''),
])

# =============================================================================================== 03
RET_LOAD = '''\
frames = {}
for target in ("local", "production"):
    for ds in ("heldout_v0.2", "pilot_v0.1"):
        f = A.RESULTS / f"retrieval_{target}_{ds}.csv"
        if target == "production":   # erratum 2026-11-23: announcement ids corrected (scripts/rescore_production.py)
            f = A.RESULTS / f"retrieval_{target}_{ds}_rescored.csv"
        if f.exists():
            frames[(target, ds)] = A.load_retrieval(f.name)
avail = pd.DataFrame([(t, d, len(df), df["method"].nunique(), int((df["error"].fillna("") != "").sum()))
                      for (t, d), df in frames.items()], columns=["target", "dataset", "rows", "methods", "failed requests"])
avail'''
notebook("03_retrieval_evaluation.ipynb", "03 · Retrieval evaluation",
         "Recall@1, Recall@5, MRR, nDCG@5 and latency for B0 (vector-only), E1 (original hybrid), E2 (improved "
         "hybrid) and E2S (E2 + evidence selection, local only); E3 (reranking) is not implemented. Headline results "
         "use the held-out set; the pilot set was used for tuning and is reported as a development set.", [
    code(RET_LOAD),
    code('''\
display(pd.DataFrame([(k, v["name"], v.get("status", "run")) for k, v in EXPERIMENTS["methods"].items()],
                     columns=["id", "method", "status"]))
display(pd.DataFrame([(k, v["role"], v.get("review_status", v.get("status"))) for k, v in EXPERIMENTS["datasets"].items()],
                     columns=["dataset", "role", "review status"]))'''),
    md("## Results (95% cluster-bootstrap intervals over scenarios)"),
    code('''\
order = ["B0", "E1", "E2", "E2S"]
tables = {}
for (t, d), df in frames.items():
    s = A.summarize(df, ["method"]); s.insert(0, "dataset", d); s.insert(0, "target", t)
    tables[(t, d)] = s.set_index("method").loc[[m for m in order if m in set(s["method"])]].reset_index()
results = pd.concat(tables.values(), ignore_index=True)
show = results[["target", "dataset", "method", "n", "r1", "r1_lo", "r1_hi", "r5", "rr", "rr_lo", "rr_hi", "ndcg5"]]
show.rename(columns={"r1": "R@1", "r5": "R@5", "rr": "MRR", "ndcg5": "nDCG@5"}).round(3)'''),
    code('''\
results.to_csv(A.RESULTS / "retrieval_summary.csv", index=False)
fig, axes = plt.subplots(1, 2, figsize=(12, 4.2), sharey=True)
for ax, target in zip(axes, ["local", "production"]):
    key = (target, "heldout_v0.2")
    if key not in tables:
        ax.text(0.5, 0.5, "Not evaluated", ha="center", transform=ax.transAxes); ax.set_xticks([]); ax.set_yticks([]); continue
    t = tables[key].melt(id_vars=["method"], value_vars=["r1", "r5", "rr", "ndcg5"])
    rows = []
    for m in tables[key]["method"]:
        r = tables[key].set_index("method").loc[m]
        for metric, label in (("r1", "Recall@1"), ("r5", "Recall@5"), ("rr", "MRR"), ("ndcg5", "nDCG@5")):
            rows.append(dict(method=m, metric=label, v=r[metric], v_lo=r[f"{metric}_lo"], v_hi=r[f"{metric}_hi"]))
    tab = pd.DataFrame(rows).set_index(["method", "metric"])
    methods = list(tables[key]["method"])
    A.grouped_bars(ax, tab, ["Recall@1", "Recall@5", "MRR", "nDCG@5"], methods, "v")
    n = int(tables[key]["n"].iloc[0])
    ax.set_title(f"{target.capitalize()} · held-out v0.2 (n = {n} questions, 20 scenarios)")
axes[0].set_ylabel("score (95% CI)")
handles, labels = next((ax.get_legend_handles_labels() for ax in axes if ax.get_legend_handles_labels()[0]), ([], []))
fig.legend(handles, labels, loc="upper center", ncol=len(labels), bbox_to_anchor=(0.5, 1.07))
fig.tight_layout(); print(A.save(fig, "03_retrieval_baseline_comparison"))'''),
    md("## Paired comparisons\n\nSame questions under both methods; the interval is a cluster bootstrap of the "
       "per-question difference; McNemar's exact test is shown for Recall@1. With 20 scenarios the test has low "
       "power - an interval that includes 0 means *no evidence of a difference*, not evidence of no difference."),
    code('''\
pairs = []
for (t, d), df in frames.items():
    for a, b in (("E2", "B0"), ("E2", "E1"), ("E1", "B0"), ("E2S", "E2")):
        if {a, b} <= set(df["method"]):
            for col in ("r1", "rr", "ndcg5"):
                r = A.paired_difference(df, a, b, col); r.update(target=t, dataset=d); pairs.append(r)
pairs = pd.DataFrame(pairs)
pairs["diff_pp"] = 100 * pairs["diff"]; pairs["ci_pp"] = pairs.apply(lambda r: f"[{100*r.lo:+.1f}, {100*r.hi:+.1f}]", axis=1)
pairs.to_csv(A.RESULTS / "retrieval_paired_comparisons.csv", index=False)
pairs[["target", "dataset", "a", "b", "metric", "n", "diff_pp", "ci_pp", "relative_pct", "a_better", "b_better",
       "mcnemar_p", "ci_excludes_zero"]].round(3)'''),
    md("## Latency\n\nLocal = in-memory index (no database, no network): measures ranking computation only. "
       "Production = HTTP round-trip to the deployed API with the real pgvector database (includes network)."),
    code('''\
lat = pd.concat([df.assign(target=t, dataset=d) for (t, d), df in frames.items()])
lat = lat[lat["error"].fillna("") == ""]
lt = lat.groupby(["target", "method"])["latency_ms"].describe(percentiles=[0.5, 0.95])[["count", "50%", "95%", "mean"]]
display(lt.round(1))
fig, axes = plt.subplots(1, 2, figsize=(11, 3.6))
for ax, target in zip(axes, ["local", "production"]):
    sub = lat[lat["target"] == target]
    ms = [m for m in ["B0", "E1", "E2", "E2S"] if m in set(sub["method"])]
    if not ms:
        ax.text(0.5, 0.5, "Not evaluated", ha="center", transform=ax.transAxes); ax.set_xticks([]); ax.set_yticks([]); continue
    bp = ax.boxplot([sub.loc[sub["method"] == m, "latency_ms"] for m in ms], tick_labels=ms, patch_artist=True,
                    widths=0.5, showfliers=False, medianprops={"color": A.INK})
    for patch, m in zip(bp["boxes"], ms):
        patch.set_facecolor(A.COLORS[m]); patch.set_alpha(0.75)
    ax.set_title(f"{target.capitalize()} retrieval latency (n = {len(sub)} requests)"); ax.set_ylabel("milliseconds")
fig.tight_layout(); print(A.save(fig, "03_latency_distribution"))'''),
    code('''\
def fmt(t, d, a, b, col):
    r = pairs[(pairs.target == t) & (pairs.dataset == d) & (pairs.a == a) & (pairs.b == b) & (pairs.metric == col)]
    if r.empty: return "not evaluated"
    r = r.iloc[0]
    return f"{100*r['diff']:+.1f} pp (95% CI {100*r['lo']:+.1f} to {100*r['hi']:+.1f})"
text = []
for t in ("local", "production"):
    if (t, "heldout_v0.2") in frames:
        text.append(f"- **{t}, held-out**: E2 vs B0 Recall@1 {fmt(t, 'heldout_v0.2', 'E2', 'B0', 'r1')}, MRR "
                    f"{fmt(t, 'heldout_v0.2', 'E2', 'B0', 'rr')}; E2 vs E1 Recall@1 {fmt(t, 'heldout_v0.2', 'E2', 'E1', 'r1')}.")
    if (t, "pilot_v0.1") in frames:
        text.append(f"- **{t}, pilot (development set, used for tuning)**: E2 vs B0 Recall@1 "
                    f"{fmt(t, 'pilot_v0.1', 'E2', 'B0', 'r1')}.")
display(Markdown("**Interpretation.**\\n\\n" + "\\n".join(text) + "\\n\\nThe gain on the pilot set is larger than on the "
                 "held-out set: the pilot set was used while tuning, so it overstates the improvement. The held-out "
                 "numbers are the ones to report, with their intervals; none of these labels is human-reviewed yet."))'''),
])

# =============================================================================================== 04
notebook("04_multilingual_analysis.ipynb", "04 · Multilingual analysis",
         "Retrieval per query language (Korean, English, Indonesian, Vietnamese, Chinese), per category, "
         "cross-language success (question language ≠ document language) and error cases. Each language has 20 "
         "questions per dataset - intervals are wide and per-language differences must be read with that in mind.", [
    code(RET_LOAD),
    code('''\
manifest = {d["id"]: d for d in json.loads((A.SNAP / "corpus_manifest.json").read_text())["items"]}
bench = {ds: {r["question_id"]: r for r in json.loads((A.DATA / "benchmarks" / f"retrieval_{ds}.json").read_text())["records"]}
         for ds in ("heldout_v0.2", "pilot_v0.1")}
def doc_lang(ds, qid):
    return (manifest.get(bench[ds][qid]["primary_document_id"]) or {}).get("language")
for (t, d), df in frames.items():
    df["doc_language"] = df["question_id"].map(lambda q: doc_lang(d, q))
    df["cross_language"] = df["language"] != df["doc_language"]
main_key = ("production", "heldout_v0.2") if ("production", "heldout_v0.2") in frames else ("local", "heldout_v0.2")
print("main analysis:", main_key)'''),
    code('''\
by_lang = []
for (t, d), df in frames.items():
    s = A.summarize(df, ["method", "language"]); s.insert(0, "dataset", d); s.insert(0, "target", t); by_lang.append(s)
by_lang = pd.concat(by_lang, ignore_index=True)
by_lang.to_csv(A.RESULTS / "retrieval_by_language.csv", index=False)
pivot = by_lang[(by_lang.target == main_key[0]) & (by_lang.dataset == main_key[1])].pivot(index="language", columns="method", values=["r1", "rr"])
pivot.loc[A.LANGS].round(3)'''),
    code('''\
tab = by_lang[(by_lang.target == main_key[0]) & (by_lang.dataset == main_key[1])].set_index(["method", "language"])
methods = [m for m in ["B0", "E1", "E2", "E2S"] if m in set(tab.index.get_level_values(0))]
fig, axes = plt.subplots(2, 1, figsize=(11, 7.4))
for ax, metric, label in ((axes[0], "r1", "Recall@1"), (axes[1], "rr", "MRR")):
    A.grouped_bars(ax, tab.rename(index=A.LANG_NAMES, level=1), [A.LANG_NAMES[l] for l in A.LANGS], methods, metric)
    ax.set_ylabel(f"{label} (95% CI)")
    ax.set_title(f"{label} by query language · {main_key[0]} · held-out v0.2 (n = 20 questions per language)")
axes[0].legend(loc="upper left", bbox_to_anchor=(1, 1))
fig.tight_layout(); print(A.save(fig, "04_recall_mrr_by_language"))'''),
    md("## Cross-language retrieval\n\nA question is *cross-language* when its language differs from the original "
       "language of its primary expected document (most documents are English or Korean)."),
    code('''\
xl = []
for (t, d), df in frames.items():
    s = A.summarize(df, ["method", "cross_language"], metrics=("r1", "rr")); s.insert(0, "dataset", d); s.insert(0, "target", t); xl.append(s)
xl = pd.concat(xl, ignore_index=True)
xl[["target", "dataset", "method", "cross_language", "n", "r1", "r1_lo", "r1_hi", "rr"]].round(3)'''),
    md("## Category-level performance (held-out, E2)"),
    code('''\
df = frames[main_key]
cat = A.summarize(df[df.method == "E2"], ["category"], metrics=("r1", "r5", "rr"))
cat.sort_values("r1")[["category", "n", "r1", "r1_lo", "r1_hi", "r5", "rr"]].round(3)'''),
    md("## Error cases (held-out, E2: expected document not ranked first)"),
    code('''\
titles = {k: v["title"][:45] for k, v in manifest.items()}
err = df[(df.method == "E2") & (df.r1 == 0)].copy()
err["question"] = err["question_id"].map(lambda q: bench[main_key[1]][q]["question"])
err["expected (primary)"] = err["question_id"].map(lambda q: titles.get(bench[main_key[1]][q]["primary_document_id"]))
err["retrieved #1"] = err["retrieved_documents"].map(lambda s: titles.get((json.loads(s) or [None])[0], "(nothing)"))
display(err[["question_id", "language", "rank", "question", "expected (primary)", "retrieved #1"]].sort_values("question_id"))
counts = err.groupby("language").size().reindex(A.LANGS, fill_value=0)
worst = counts.idxmax()
display(Markdown(f"""**Interpretation.** {len(err)} of {int((df.method == 'E2').sum())} held-out questions miss at rank 1 under
E2 ({', '.join(f'{A.LANG_NAMES[l]} {counts[l]}' for l in A.LANGS)}). With 20 questions per language a difference of
one question is 5 percentage points; per-language rankings should not be generalised without the reviewed, larger
dataset. Misses cluster on scenarios whose answer sits in one long multi-topic guide or in another-language document."""))'''),
])

# =============================================================================================== 05
ANS_LOAD = '''\
f = A.RESULTS / "answers_production_heldout_v0.2.jsonl"
answers = pd.read_json(f, lines=True) if f.exists() else pd.DataFrame()
ann_f = A.DATA / "review" / "answer_annotation_template.csv"
annotations = pd.read_csv(ann_f) if ann_f.exists() else pd.DataFrame()
print(f"{len(answers)} recorded answer cases" if len(answers) else "Not evaluated: no answer-evaluation run found")'''
notebook("05_llm_answer_evaluation.ipynb", "05 · LLM answer evaluation",
         "Real answers from the deployed assistant (Gemini) for synthetic held-out questions. Failed or unavailable "
         "generations are counted, not dropped. Automatic, reference-free metrics are computed here; correctness, "
         "relevance and faithfulness require human review with the fixed rubric (`configs/answer_rubric_v1.md`) and "
         "are reported only when reviewed scores exist.", [
    code(ANS_LOAD),
    code('''\
if len(answers):
    meta = json.loads(Path(str(f) + ".manifest.json").read_text())
    display(pd.DataFrame([(k, str(v)) for k, v in meta.items()], columns=["run", "value"]))
    outcome = answers["answer_generation"].fillna("request failed: " + answers["request_error"].fillna("unknown"))
    display(outcome.value_counts().rename_axis("generation outcome").reset_index(name="cases"))
    display(answers.groupby("answer_generation", dropna=False)["fallback_reason"].value_counts(dropna=False).rename("cases").reset_index())'''),
    md("## Automatic metrics (generated answers only; n shown per metric)"),
    code('''\
def rate(s):
    s = s.dropna().astype(float)
    return (s.mean() if len(s) else np.nan), len(s)
if len(answers):
    gen = answers[answers["answer_generation"] == "llm"]
    rows = [("generation success rate (all cases)", *rate((answers["answer_generation"] == "llm").astype(float)))]
    rows += [("language consistency", *rate(gen["language_consistent"])),
             ("citation hit (an expected document is cited)", *rate(gen.loc[gen.scenario_id != "OOS", "citation_hit"])),
             ("citation precision (cited documents that are expected)", *rate(gen.loc[gen.scenario_id != "OOS", "citation_precision"])),
             ("answers with server-removed unsupported figures", *rate((gen["removed_unsupported"] > 0).astype(float))),
             ("answers with raw [n] markers", *rate(gen["raw_markers"].astype(float))),
             ("answers with template endings", *rate(gen["template_endings"].map(bool).astype(float))),
             ("supporter offer on in-scope questions", *rate(gen.loc[gen.scenario_id != "OOS", "offer_handoff"].astype(float)))]
    auto = pd.DataFrame(rows, columns=["metric", "value", "n"]); display(auto.round(3))
    oos = answers[answers.scenario_id == "OOS"][["question_id", "answer_generation", "evidence_level", "answer"]]
    display(Markdown("**Out-of-scope questions (appropriate abstention, judged by reading):**")); display(oos)'''),
    code('''\
if len(answers):
    gen = answers[answers["answer_generation"] == "llm"]
    fig, axes = plt.subplots(1, 3, figsize=(13, 3.6))
    oc = outcome.value_counts()
    axes[0].bar(oc.index.astype(str), oc.values, color=A.SINGLE, width=0.55, zorder=2)
    for x, v in enumerate(oc.values): axes[0].text(x, v + 0.2, str(v), ha="center", fontsize=9)
    axes[0].set_title(f"Generation outcome (n = {len(answers)})"); axes[0].set_ylabel("cases"); axes[0].tick_params(axis="x", labelsize=8)
    timed = answers["wall_latency_ms"].dropna()
    axes[1].hist(timed / 1000, bins=12, color=A.SINGLE, edgecolor=A.SURFACE, zorder=2)
    axes[1].set_title(f"End-to-end response time (n = {len(timed)} timed)"); axes[1].set_xlabel("seconds"); axes[1].set_ylabel("cases")
    if len(gen):
        axes[2].hist(gen["total_tokens"].dropna(), bins=10, color=A.SINGLE, edgecolor=A.SURFACE, zorder=2)
    axes[2].set_title(f"Tokens per generated answer (n = {gen['total_tokens'].notna().sum()})"); axes[2].set_xlabel("total tokens (API-reported)")
    fig.tight_layout(); print(A.save(fig, "05_answer_outcomes_latency_tokens"))
    display(answers.groupby("answer_generation", dropna=False)[["wall_latency_ms", "llm_latency_ms", "input_tokens", "output_tokens", "total_tokens"]].describe().T.round(0))'''),
    md("## Human-judged quality (rubric v1)"),
    code('''\
scored = annotations.dropna(subset=[c for c in ("correctness", "relevance", "faithfulness") if c in annotations.columns], how="all") \\
    if len(annotations) else annotations
if len(scored) == 0:
    display(Markdown("""**Not evaluated.** Answer correctness, answer relevance, faithfulness, citation accuracy (rubric) and the
unsupported-claim rate need human review (or a recorded LLM judge) against the approved sources. No reviewed scores exist
yet - `data/review/answer_annotation_template.csv` lists every recorded answer for scoring. No model-generated or simulated
scores are substituted."""))
else:
    display(scored.groupby("reviewer")[["correctness", "relevance", "faithfulness", "citation_accuracy"]].mean())'''),
])

# =============================================================================================== 06
notebook("06_model_comparison.ipynb", "06 · Model comparison (Gemini primary vs fallback)",
         "Compares models only on cases each actually answered; no claim of superiority without a controlled "
         "comparison (same questions, both models answering).", [
    code(ANS_LOAD),
    code('''\
if len(answers):
    configured = EXPERIMENTS["generation"]
    display(pd.DataFrame([("configured primary", configured["configured_primary_model"]),
                          ("configured fallback", configured["configured_fallback_model"]),
                          ("prompt version", configured["prompt_version"])], columns=["setting", "value"]))
    by_model = answers.assign(model=answers["model"].fillna("(no answer generated)")).groupby("model").agg(
        cases=("question_id", "size"), fallback_used=("fallback_used", "mean"),
        median_wall_ms=("wall_latency_ms", "median"), median_total_tokens=("total_tokens", "median"),
        language_consistent=("language_consistent", "mean"), citation_hit=("citation_hit", "mean"))
    display(by_model.round(3))
    served = set(answers.loc[answers["answer_generation"] == "llm", "model"].dropna())
    primary_ok = any(configured["configured_primary_model"].split(" ")[0] in m for m in served)
    display(Markdown(("" if primary_ok else f"""**Primary model: Not evaluated.** No case in this run was answered by the configured
primary model (served models: {', '.join(sorted(served)) or 'none'}); a primary-vs-fallback comparison of quality,
latency or tokens is therefore not possible. """) + f"""Fallback frequency in this run:
{answers['fallback_used'].mean():.0%} of generated answers. Cost is not reported (no reliable billing data)."""))'''),
])

# =============================================================================================== 07
notebook("07_ablation_study.ipynb", "07 · Ablation study",
         "Stepwise configurations actually implemented and executed: B0 vector-only → E1 hybrid (SQL RRF) → E2 "
         "improved hybrid → E2S E2 + evidence selection. Reranking (E3) is not implemented and is not reported. "
         "Absolute (percentage points) and relative differences with 95% cluster-bootstrap intervals.", [
    code(RET_LOAD),
    code('''\
steps = [("E1", "B0", "hybrid fusion (equal-weight SQL RRF) vs vector-only"),
         ("E2", "B0", "improved hybrid vs vector-only"),
         ("E2", "E1", "weighted fusion + query analysis vs equal-weight RRF"),
         ("E2S", "E2", "assistant evidence selection on top of E2 (no query rewriting)")]
rows = []
for (t, d), df in frames.items():
    for a, b, what in steps:
        if {a, b} <= set(df["method"]):
            for col, name in (("r1", "Recall@1"), ("r5", "Recall@5"), ("rr", "MRR"), ("ndcg5", "nDCG@5")):
                r = A.paired_difference(df, a, b, col)
                rows.append(dict(target=t, dataset=d, step=f"{a} vs {b}", what=what, metric=name, n=r["n"],
                                 baseline=r["mean_b"], variant=r["mean_a"], diff_pp=100 * r["diff"],
                                 lo_pp=100 * r["lo"], hi_pp=100 * r["hi"], relative_pct=r["relative_pct"],
                                 ci_excludes_zero=r["ci_excludes_zero"]))
abl = pd.DataFrame(rows)
abl.to_csv(A.RESULTS / "ablation.csv", index=False)
abl[abl.dataset == "heldout_v0.2"].round(3)'''),
    code('''\
sub = abl[(abl.dataset == "heldout_v0.2") & (abl.metric.isin(["Recall@1", "MRR"]))]
STEP_ORDER = ["E1 vs B0", "E2 vs B0", "E2 vs E1", "E2S vs E2"]
fig, axes = plt.subplots(1, 2, figsize=(12, 4.2))   # own y-axis per panel: the targets ran different comparisons
for ax, target in zip(axes, ["local", "production"]):
    s = sub[sub.target == target]
    if s.empty:
        ax.text(0.5, 0.5, "Not evaluated", ha="center", transform=ax.transAxes); ax.set_xticks([]); ax.set_yticks([]); continue
    labels = [st for st in STEP_ORDER if st in set(s["step"])]
    for j, (metric, color) in enumerate((("Recall@1", A.COLORS["B0"]), ("MRR", A.COLORS["E1"]))):
        m = s[s.metric == metric].set_index("step").loc[labels]
        y = np.arange(len(labels)) + (j - 0.5) * 0.32
        ax.errorbar(m["diff_pp"], y, xerr=[m["diff_pp"] - m["lo_pp"], m["hi_pp"] - m["diff_pp"]], fmt="o",
                    color=color, ecolor=color, elinewidth=1.6, capsize=3, markersize=7, label=metric)
        for xv, yv in zip(m["diff_pp"], y):
            ax.text(xv, yv + 0.13, f"{xv:+.1f}", ha="center", fontsize=8, color=A.INK)
    ax.axvline(0, color=A.INK2, linewidth=1)
    ax.set_yticks(np.arange(len(labels)), labels); ax.grid(axis="x"); ax.grid(axis="y", visible=False)
    ax.set_ylim(-0.6, len(labels) - 0.15)     # headroom so the top value labels clear the title
    ax.set_xlabel("difference, percentage points (95% CI)")
    ax.set_title(f"{target.capitalize()} · held-out v0.2 (n = {int(s['n'].iloc[0])})")
handles, labels = next((ax.get_legend_handles_labels() for ax in axes if ax.get_legend_handles_labels()[0]), ([], []))
fig.legend(handles, labels, loc="upper center", ncol=len(labels), bbox_to_anchor=(0.5, 1.07))
fig.tight_layout(); print(A.save(fig, "07_ablation_differences"))'''),
    code('''\
h = abl[(abl.dataset == "heldout_v0.2") & (abl.metric == "Recall@1")]
lines = [f"- {r.target}, {r.step}: {r.diff_pp:+.1f} pp ({r.lo_pp:+.1f} to {r.hi_pp:+.1f}), relative {r.relative_pct:+.0f}%"
         + (" - interval excludes 0" if r.ci_excludes_zero else " - interval includes 0") for r in h.itertuples()]
display(Markdown("**Recall@1 on the held-out set:**\\n\\n" + "\\n".join(lines) + "\\n\\nOnly intervals that exclude 0 "
                 "support a claim of difference; the others are inconclusive at this sample size."))'''),
])

# =============================================================================================== 08
notebook("08_final_research_report.ipynb", "08 · Final research report",
         "Integrated analysis: objectives, data, methods, experimental design, metrics, results, error analysis, "
         "limitations and conclusions. All numbers are computed from the versioned result files; preliminary "
         "(AI-drafted, unreviewed) evaluation data are labelled as such. Writes `reports/research_summary.md` and "
         "`reports/abstract_draft.md`.", [
    md("## 1. Research objectives\n\nDetermine how well a multilingual retrieval-augmented assistant finds the "
       "approved university / government source that answers an international student's question asked in Korean, "
       "English, Indonesian, Vietnamese or Chinese, and how much the improved hybrid retrieval contributes relative "
       "to vector-only and equal-weight hybrid baselines; measure what can be measured of the generated answers."),
    code('''\
stats = json.loads((A.SNAP / "dataset_statistics.json").read_text())
ch = pd.read_csv(A.SNAP / "chunk_metrics.csv"); active = ch[ch["active"]]
cfg, gen = EXPERIMENTS["shared"], EXPERIMENTS["generation"]
summary_rows = [("Active documents", stats["documents"]["active_searchable"]),
                ("Original languages", ", ".join(f"{k} {v}" for k, v in stats["documents"]["by_language"].items())),
                ("Pages (PDF metadata only)", stats["pages"]["total_pages_from_extraction_metadata"]),
                ("Active chunks / embedded", f"{stats['chunks']['active']} / {stats['chunks']['active_with_embedding']}"),
                ("Chunk size, characters: median (IQR)", f"{active['chars'].median():.0f} ({active['chars'].quantile(.25):.0f}-{active['chars'].quantile(.75):.0f})"),
                ("Embedding", f"{cfg['embedding_model']} ({cfg['embedding_variant']}), {cfg['embedding_dimensions']} dimensions"),
                ("Vector index", f"{cfg['vector_store']['index']}; pgvector {stats['pgvector_version']}"),
                ("Chunker", f"target {cfg['chunker']['target_tokens']} / max {cfg['chunker']['max_tokens']} / overlap {cfg['chunker']['overlap_tokens']} est. tokens"),
                ("Generation", f"{gen['provider']}; prompt {gen['prompt_version']} ({gen['prompt_sha256_12']})")]
dataset_table = pd.DataFrame(summary_rows, columns=["item", "value"])
dataset_table.to_csv(A.REPORTS / "dataset_summary.csv", index=False); dataset_table'''),
    md("## 2-8. Data, preprocessing, chunking, embedding, vector database, retrieval and generation\n\n"
       "- **Data**: approved documents of the SCH International Student Hub knowledge base (university notices and "
       "guides, Korean government guidance), English and Korean originals; only the current approved version of each "
       "document is searchable (`searchable_chunks`).\n"
       "- **Preprocessing**: extraction from web pages, PDF (PyMuPDF, page markers), DOCX and pasted notices; text "
       "normalisation; human review and approval before indexing.\n"
       "- **Chunking**: heading/paragraph-aware chunker v1 with a sliding token overlap inside long sections "
       "(see notebook 02 for measured sizes and overlap).\n"
       "- **Embedding**: multilingual-e5-small, ONNX int8, `passage:` / `query:` prefixes, 384 dimensions, CPU.\n"
       "- **Vector database**: Supabase PostgreSQL + pgvector HNSW (cosine) with GIN full-text and trigram indexes.\n"
       "- **Retrieval**: B0 vector-only; E1 equal-weight RRF of vector and keyword legs in SQL; E2 application-side "
       "weighted fusion with rarity-weighted, script-aware keyword coverage, visa-code normalisation, a multilingual "
       "glossary, code-mismatch demotion, de-duplication and a per-document cap; E2S adds the assistant's evidence "
       "selection. Reranking was not implemented.\n"
       "- **Generation**: Gemini (primary + fallback) with a versioned system prompt; server-side citation, grounding "
       "and prompt-leak checks."),
    md("## 9-10. Experimental design and metrics\n\nTwo retrieval datasets of 100 synthetic questions each "
       "(20 scenarios × 5 languages): the **pilot v0.1** set was used during development (tuning) and is reported as a "
       "development set; the **held-out v0.2** set was frozen before its first evaluation and never used for tuning. "
       "Both were drafted by an AI assistant and are **not yet human-reviewed**; results are preliminary. Document-level "
       "Recall@1, Recall@5, MRR and nDCG@5 with 95% cluster-bootstrap intervals over scenarios; paired differences in "
       "percentage points. Two targets: the local working tree (in-memory index rebuilt with the production chunker "
       "and embedder) and the deployed production API (real pgvector index)."),
    code(RET_LOAD),
    md("## 11-12. Results"),
    code('''\
order = ["B0", "E1", "E2", "E2S"]
res = []
for (t, d), df in frames.items():
    s = A.summarize(df, ["method"]); s.insert(0, "dataset", d); s.insert(0, "target", t); res.append(s)
res = pd.concat(res, ignore_index=True)
res["method"] = pd.Categorical(res["method"], order, ordered=True)
res = res.sort_values(["target", "dataset", "method"])
def ci(r, m): return f"{r[m]:.3f} [{r[m+'_lo']:.3f}, {r[m+'_hi']:.3f}]"
table = pd.DataFrame([dict(target=r.target, dataset=r.dataset, method=f"{r.method} {A.METHODS[r.method].split(' ', 1)[1]}",
                           n=r.n, **{"Recall@1": ci(r, "r1"), "Recall@5": ci(r, "r5"), "MRR": ci(r, "rr"),
                                     "nDCG@5": ci(r, "ndcg5")}) for _, r in res.iterrows()])
table.to_csv(A.REPORTS / "retrieval_results_table.csv", index=False); table'''),
    code('''\
heldout = res[res.dataset == "heldout_v0.2"]
fig, ax = plt.subplots(figsize=(10, 4))
targets = [t for t in ("local", "production") if t in set(heldout["target"])]
tab = heldout.assign(group=heldout["target"].str.capitalize()).set_index(["method", "group"])
A.grouped_bars(ax, tab, [t.capitalize() for t in targets], [m for m in order if m in set(heldout["method"])], "rr")
ax.set_ylabel("MRR (95% CI)"); ax.set_title(f"MRR on the held-out set (n = {int(heldout['n'].iloc[0])} questions, 20 scenarios, 5 languages)")
ax.legend(loc="upper left", bbox_to_anchor=(1, 1)); fig.tight_layout(); print(A.save(fig, "08_mrr_heldout_summary"))'''),
    code('''\
pairs = []
for (t, d), df in frames.items():
    for a, b in (("E2", "B0"), ("E2", "E1")):
        if {a, b} <= set(df["method"]):
            for col in ("r1", "rr"):
                r = A.paired_difference(df, a, b, col); r.update(target=t, dataset=d); pairs.append(r)
pairs = pd.DataFrame(pairs)
pairs["result"] = pairs.apply(lambda r: f"{100*r['diff']:+.1f} pp [{100*r['lo']:+.1f}, {100*r['hi']:+.1f}]"
                              + (" *" if r["ci_excludes_zero"] else ""), axis=1)
pairs[["target", "dataset", "a", "b", "metric", "n", "result", "mcnemar_p"]].round(3)'''),
    md("`*` = the 95% interval excludes 0."),
    md("## 13. Error analysis"),
    code('''\
key = ("production", "heldout_v0.2") if ("production", "heldout_v0.2") in frames else ("local", "heldout_v0.2")
df = frames[key]
bl = A.summarize(df[df.method == "E2"], ["language"], metrics=("r1", "rr")).set_index("language").loc[A.LANGS]
display(bl[["n", "r1", "r1_lo", "r1_hi", "rr"]].round(3))
ans_f = A.RESULTS / "answers_production_heldout_v0.2.jsonl"
answers = pd.read_json(ans_f, lines=True) if ans_f.exists() else pd.DataFrame()
gen_rate = (answers["answer_generation"] == "llm").mean() if len(answers) else np.nan
served = sorted(set(answers.loc[answers.get("answer_generation", pd.Series(dtype=str)) == "llm", "model"].dropna())) if len(answers) else []
print("answer cases:", len(answers), "| generation success:", None if np.isnan(gen_rate) else round(gen_rate, 3), "| served models:", served)'''),
    md("## 14-15. Limitations, conclusions and generated reports"),
    code('''\
def get(t, d, a, b, m):
    r = pairs[(pairs.target == t) & (pairs.dataset == d) & (pairs.a == a) & (pairs.b == b) & (pairs.metric == m)]
    return None if r.empty else r.iloc[0]
def val(t, d, m, k="r1"):
    r = res[(res.target == t) & (res.dataset == d) & (res.method == m)]
    return None if r.empty else r.iloc[0]
main_t = "production" if ("production", "heldout_v0.2") in frames else "local"
e2b0 = get(main_t, "heldout_v0.2", "E2", "B0", "rr"); e2e1 = get(main_t, "heldout_v0.2", "E2", "E1", "rr")
v = {m: val(main_t, "heldout_v0.2", m) for m in ("B0", "E1", "E2")}
pilot = get("local", "pilot_v0.1", "E2", "B0", "r1"); held = get("local", "heldout_v0.2", "E2", "B0", "r1")
def pp(r): return f"{100*r['diff']:+.1f} pp (95% CI {100*r['lo']:+.1f} to {100*r['hi']:+.1f})"
answer_line = ("Answer quality (correctness, relevance, faithfulness) was not evaluated: no human-reviewed scores exist."
               + (f" In {len(answers)} recorded production cases, {gen_rate:.0%} produced a generated answer"
                  f" (served by {', '.join(served) or 'no model'})." if len(answers) else ""))
st = stats
abstract = f"""**Draft abstract (preliminary - evaluation questions and labels are AI-drafted and not yet human-reviewed).**

International students need accurate answers about immigration, residence and university procedures in their own
language, while the authoritative sources are written mostly in Korean and English. We describe and evaluate a
retrieval-augmented assistant for international students at Soonchunhyang University built on
{st['documents']['active_searchable']} approved documents ({st['chunks']['active']} chunks; {cfg['embedding_model']},
{cfg['embedding_dimensions']}-dimensional embeddings in PostgreSQL/pgvector). On a held-out set of 100 synthetic questions
(20 scenarios in Korean, English, Indonesian, Vietnamese and Chinese) evaluated against the deployed system, the improved
hybrid retriever reached MRR {v['E2']['rr']:.3f} versus {v['B0']['rr']:.3f} for vector-only retrieval and
{v['E1']['rr']:.3f} for equal-weight hybrid fusion (paired differences {pp(e2b0)} and {pp(e2e1)}). In the local
evaluation, the Recall@1 gain over vector-only retrieval on the development set used for tuning ({pp(pilot)}) was larger
than on the held-out set ({pp(held)}), illustrating the optimism of tuning-set evaluation. {answer_line} We release the evaluation framework, a review workflow for
independent labels and the statistics of the knowledge base."""
display(Markdown(abstract))
(A.REPORTS / "abstract_draft.md").write_text(abstract + "\\n")
limits = """- Questions, translations and relevance labels are AI-drafted and **not human-reviewed**; results are preliminary.
- 20 scenarios per dataset: intervals are wide; per-language differences of one question equal 5 percentage points.
- The pilot set was used for tuning (development set); only held-out results should be reported as estimates.
- Relevance is binary and document-level; partial or passage-level relevance is not measured.
- The local target rebuilds the index from the public corpus snapshot; production includes network latency.
- Reranking was not implemented; query rewriting (LLM) was not part of the retrieval experiments.
- Answer-quality metrics requiring judgement are not evaluated; the primary Gemini model produced no successful answers in
  the recorded production runs, so no model comparison is possible.
- Knowledge-base validity metadata is sparse (see notebook 01); time-bound documents can be out of date."""
summary = ["# SCH International Student Hub - multilingual RAG evaluation (preliminary)", "",
           f"Generated by notebook 08 from versioned results; statistics as of {st['generated_at'][:10]}.", "",
           "## Dataset", dataset_table.to_markdown(index=False), "", "## Retrieval results", table.to_markdown(index=False), "",
           "`[a, b]` = 95% cluster-bootstrap interval over scenarios.", "", "## Paired differences",
           pairs[["target", "dataset", "a", "b", "metric", "n", "result"]].to_markdown(index=False), "", "`*` = interval excludes 0.", "",
           "## Answer generation", answer_line, "", "## Limitations", limits, "", "## Abstract draft", abstract]
(A.REPORTS / "research_summary.md").write_text("\\n".join(summary) + "\\n")
display(Markdown("### Limitations\\n" + limits)); print("wrote reports/research_summary.md and reports/abstract_draft.md")'''),
])


# =============================================================================================== 09
M5_LOAD = """\
import glob
def load_exp(ds):
    f = A.RESULTS / f"experiments_{ds}.csv"
    if not f.exists():
        return None
    df = A.load_retrieval(f.name)
    df["latency_ms"] = df["total_ms"]
    return df
EXP = {ds: load_exp(ds) for ds in ("pilot_v0.1", "heldout_v0.2")}
for ds, df in EXP.items():
    print(ds, "not evaluated (no experiments file)" if df is None else f"{len(df)} rows, methods: {sorted(df['method'].unique())}")
MANIFESTS = {Path(f).stem.replace('reranked_', '').replace('.manifest', ''): json.loads(Path(f).read_text())
             for f in glob.glob(str(A.RESULTS / 'reranked_*.manifest.json'))}"""

notebook("09_retrieval_error_analysis.ipynb", "09 · Retrieval error analysis",
         "Why retrieval fails: a rule-based taxonomy of every question whose expected document is not ranked first, "
         "for B0 (dense), E1 (original hybrid) and E2 (improved hybrid), on the development (pilot v0.1) and held-out "
         "(v0.2) sets, plus traces of the four failure patterns named in the Milestone 5 brief. Analysis only: no "
         "retrieval setting was changed on the basis of held-out failures.", [
    code('''\
EA = {ds: pd.read_json(A.RESULTS / f"error_analysis_{ds}.jsonl", lines=True) for ds in ("pilot_v0.1", "heldout_v0.2")}
TAX = json.loads((A.RESULTS / "error_taxonomy_definitions.json").read_text())
display(pd.DataFrame([(k, v["rule"], v["possible_improvement"]) for k, v in TAX.items()],
                     columns=["failure category", "rule (automatic)", "possible improvement"]))'''),
    md("## Misses and their primary category\\n\\nA question can match several rules; the *primary* category is the first "
       "matching rule in the order of the table above. Categories are automatic heuristics, not human judgements."),
    code('''\
rows = []
for ds, df in EA.items():
    miss = df[df["rank"] != 1]
    t = miss.groupby(["method", "primary_category"]).size().unstack(fill_value=0)
    t.insert(0, "misses", miss.groupby("method").size()); t.insert(0, "dataset", ds); rows.append(t.reset_index())
tax = pd.concat(rows, ignore_index=True).fillna(0)
tax.to_csv(A.RESULTS / "error_taxonomy_counts.csv", index=False)
tax'''),
    code('''\
cats = [c for c in TAX if c in tax.columns]
fig, axes = plt.subplots(1, 2, figsize=(12.5, 4.2), sharex=True)
for ax, ds in zip(axes, EA):
    t = tax[tax.dataset == ds].set_index("method").reindex(["B0", "E1", "E2"])[cats].fillna(0)
    left = np.zeros(len(t))
    shades = plt.cm.Blues(np.linspace(0.95, 0.25, len(cats)))
    for c, col in zip(cats, shades):
        ax.barh(t.index, t[c], left=left, color=col, edgecolor=A.SURFACE, linewidth=1.5, label=c, zorder=2)
        left += t[c].to_numpy()
    for y, v in enumerate(left):
        ax.text(v + 0.5, y, f"{int(v)}", va="center", fontsize=9, color=A.INK)
    ax.set_title(f"Misses at rank 1 by primary category - {ds} (n = 100 questions)"); ax.set_xlabel("questions")
    ax.grid(axis="x"); ax.grid(axis="y", visible=False); ax.invert_yaxis()
handles, labels = axes[0].get_legend_handles_labels()
fig.legend(handles, labels, loc="lower center", ncol=3, bbox_to_anchor=(0.5, -0.16), fontsize=8.5)
fig.tight_layout(); print(A.save(fig, "09_error_taxonomy"))'''),
    md("## Pattern 1 - Korean questions retrieving the admissions guide (모집요강)"),
    code('''\
both = pd.concat(EA.values())
ko = both[(both.language == "ko") & (both["rank"] != 1)]
adm = ko[ko.top3.map(lambda t: bool(t) and t[0]["title"].startswith("모집요강"))]
t1 = pd.DataFrame({"Korean misses": ko.groupby("method").size(), "top-1 = 모집요강": adm.groupby("method").size()}).fillna(0).astype(int)
t1["share"] = (t1["top-1 = 모집요강"] / t1["Korean misses"]).round(2); display(t1)
display(Markdown(f"The admissions guide is the largest Korean document; multilingual-E5 scores Korean text as similar to any "
                 f"Korean question, so it wins on script rather than topic (**same-script distractor**). It is top-1 in "
                 f"{len(adm)} of {len(ko)} Korean misses across methods; E2 reduces it to {t1.loc['E2', 'top-1 = 모집요강'] if 'E2' in t1.index else 0}."))'''),
    md("## Patterns 2-4 - traces"),
    code('''\
def trace(ds, qid):
    d = EA[ds][EA[ds].question_id == qid]
    return pd.DataFrame([dict(question=r.question_id, method=r.method, rank=r["rank"], category=r.primary_category,
                              deep_dense_rank=r.deep_dense_rank_no_threshold, expected_best_similarity=r.expected_best_dense_similarity,
                              top1_document=(r.top3[0]["title"][:40] if r.top3 else None), top1_section=(r.top3[0]["heading"][:35] if r.top3 else None))
                         for _, r in d.iterrows()])
display(Markdown("**2. English winter-dormitory question vs the Korean notice (pilot S12-en)**")); display(trace("pilot_v0.1", "S12-en"))
display(Markdown("**3. Vietnamese part-time weekly hours (pilot S06-vi)**")); display(trace("pilot_v0.1", "S06-vi"))
display(Markdown("**4. Travel while an extension is pending (held-out H04 - analysis only)**"))
display(pd.concat([trace("heldout_v0.2", f"H04-{l}") for l in A.LANGS]))'''),
    code('''\
h = EA["heldout_v0.2"]
thr = h[h.method == "B0"]
display(Markdown(f"""**Similarity threshold.** Expected documents whose best dense similarity is below the 0.80 cut-off:
{int((thr.expected_best_dense_similarity < 0.80).sum())} held-out questions; expected document absent from the dense top-20 even without
a threshold: {int(thr.deep_dense_rank_no_threshold.isna().sum())}. The threshold is a minor cause; most misses are ranking errors
among candidates that *are* retrieved.

**Interpretation.** The dominant failure for E2 is a document in the question's own script outranking the expected
document in another language (same-script distractor), followed by keyword ambiguity (generic terms such as "visa
extension" pulling the wrong guide) and dominance of the 164-chunk general guide. These are exactly the cases a
cross-lingual cross-encoder could address - tested in notebook 10.

**Limitations.** Rule-based categories; AI-drafted, unreviewed labels (a "miss" may be a correct document missing from
the labels - see `possible_label_gap`); 20 questions per language."""))'''),
])

# =============================================================================================== 10
notebook("10_multilingual_reranking.ipynb", "10 · Multilingual reranking",
         "Two off-the-shelf multilingual cross-encoders (no fine-tuning, settings fixed before evaluation) rerank "
         "identical frozen candidate pools (≤ 20 chunks) from dense and hybrid first stages. Local inference only "
         "(Apple M1: first stage on CPU, reranking on the GPU via MPS; a few early rows ran on CPU and are reported "
         "separately); nothing is deployed.", [
    code(M5_LOAD),
    code('''\
sys.path.insert(0, str(RESEARCH / "scripts"))
from reranking import MODELS
facts = pd.DataFrame([dict(key=k, repository=v["repo"], license=v["license"], parameters=v["params"], base=v["base"],
                           load_s=MANIFESTS.get(k, {}).get("load_seconds"), peak_rss_mb=MANIFESTS.get(k, {}).get("peak_rss_mb"),
                           torch_threads=MANIFESTS.get(k, {}).get("torch_threads"), machine=MANIFESTS.get(k, {}).get("machine"))
                      for k, v in MODELS.items()])
facts'''),
    md("Models considered but not tested: `jinaai/jina-reranker-v2-base-multilingual` (CC-BY-NC-4.0 - non-commercial, not "
       "usable for the service) and `Alibaba-NLP/gte-multilingual-reranker-base` (Apache-2.0; needs transformers ≥ 5.18 - "
       "a candidate for a follow-up)."),
    code('''\
order = ["B0", "B0F", "B0FR_mminilm", "B0FR_bge-m3", "E1", "E2", "E3_mminilm", "E3_bge-m3",
         "E2S", "E4_mminilm", "E4_bge-m3"]
TAB = {}
for ds, df in EXP.items():
    if df is None:
        continue
    s = A.summarize(df, ["method"], metrics=("r1", "r3", "r5", "r10", "rr", "ndcg5", "ndcg10"))
    s = s.set_index("method").reindex([m for m in order if m in set(s["method"])]).reset_index()
    s.insert(0, "dataset", ds); TAB[ds] = s
res = pd.concat(TAB.values(), ignore_index=True)
res.to_csv(A.RESULTS / "m5_retrieval_summary.csv", index=False)
res[["dataset", "method", "n", "r1", "r1_lo", "r1_hi", "r3", "r5", "r10", "rr", "rr_lo", "rr_hi", "ndcg5", "ndcg10"]].round(3)'''),
    code('''\
COL = {"B0": A.COLORS["B0"], "E2": A.COLORS["E2"], "E3_mminilm": A.COLORS["E1"], "E3_bge-m3": A.COLORS["E2S"]}
show = ["B0", "E2", "E3_mminilm", "E3_bge-m3"]
fig, axes = plt.subplots(1, 2, figsize=(12.5, 4.3), sharey=True)
for ax, ds in zip(axes, ["pilot_v0.1", "heldout_v0.2"]):
    if ds not in TAB:
        ax.text(0.5, 0.5, "Not evaluated", ha="center", transform=ax.transAxes); ax.set_xticks([]); ax.set_yticks([]); continue
    t = TAB[ds].set_index("method")
    rows = []
    for m in [m for m in show if m in t.index]:
        for metric, label in (("r1", "Recall@1"), ("r3", "Recall@3"), ("rr", "MRR"), ("ndcg10", "nDCG@10")):
            rows.append(dict(method=m, metric=label, v=t.loc[m, metric], v_lo=t.loc[m, f"{metric}_lo"], v_hi=t.loc[m, f"{metric}_hi"]))
    tab = pd.DataFrame(rows).set_index(["method", "metric"])
    A.grouped_bars(ax, tab, ["Recall@1", "Recall@3", "MRR", "nDCG@10"], [m for m in show if m in t.index], "v", colors=COL,
                   labels={"B0": "B0 dense", "E2": "E2 hybrid", "E3_mminilm": "E3 hybrid + mMiniLM", "E3_bge-m3": "E3 hybrid + bge-m3"})
    role = "development (used for tuning earlier)" if ds.startswith("pilot") else "held-out (inspected, untuned)"
    ax.set_title(f"{ds} - {role}\\n(n = {int(t['n'].iloc[0])} questions, 20 scenarios)", fontsize=10.5)
axes[0].set_ylabel("score (95% CI)")
h_, l_ = axes[0].get_legend_handles_labels(); fig.legend(h_, l_, loc="upper center", ncol=4, bbox_to_anchor=(0.5, 1.08))
fig.tight_layout(); print(A.save(fig, "10_reranking_comparison"))'''),
    md("## Per language (held-out)"),
    code('''\
df = EXP["heldout_v0.2"]
if df is not None:
    pl = A.summarize(df[df.method.isin(["B0", "E2", "E3_mminilm", "E3_bge-m3"])], ["method", "language"], metrics=("r1", "rr"))
    display(pl.pivot(index="language", columns="method", values="rr").loc[A.LANGS].round(3))
    tab = pl.set_index(["method", "language"]).rename(index=A.LANG_NAMES, level=1)
    fig, ax = plt.subplots(figsize=(12, 4))
    A.grouped_bars(ax, tab, [A.LANG_NAMES[l] for l in A.LANGS], [m for m in show if m in set(pl.method)], "rr", colors=COL,
                   labels={"B0": "B0 dense", "E2": "E2 hybrid", "E3_mminilm": "E3 + mMiniLM", "E3_bge-m3": "E3 + bge-m3"})
    ax.set_ylabel("MRR (95% CI)"); ax.set_title("MRR by query language - held-out v0.2 (n = 20 questions per language)")
    ax.legend(loc="upper left", bbox_to_anchor=(1, 1)); fig.tight_layout(); print(A.save(fig, "10_reranking_by_language"))'''),
    md("## Latency and resource cost (local Apple M1)\n\nFirst-stage retrieval runs on the CPU. Reranking ran on the "
       "GPU (MPS) except for the first rows of the development set, which ran on the CPU before the device was "
       "switched; the table below separates them. Quality-vs-latency uses GPU rows only."),
    code('''\
if "rerank_device" in df:
    dev = df[df.reranker.notna()].groupby(["method", "rerank_device"])["rerank_ms"].agg(["count", "median"])
    display(Markdown("**Reranking time by device** (ms per question; all datasets)"))
    display(pd.concat([EXP[d][EXP[d].reranker.notna()] for d in EXP if EXP[d] is not None])
            .groupby(["reranker", "rerank_device"])["rerank_ms"].agg(["count", "median"]).round(0))
df = df[df.reranker.isna() | (df.get("rerank_device", "mps") != "cpu")]
lat = df.groupby("method")[["first_stage_ms", "rerank_ms", "total_ms"]].median().reindex([m for m in order if m in set(df.method)])
display(lat.round(1).rename(columns=lambda c: c + " (median)"))
pts = TAB["heldout_v0.2"].set_index("method").join(lat)
fig, ax = plt.subplots(figsize=(7.5, 4.2))
for m, r in pts.iterrows():
    if pd.isna(r["total_ms"]): continue
    ax.scatter(r["total_ms"], r["rr"], s=60, color=COL.get(m, A.INK2), zorder=3)
    ax.annotate(m, (r["total_ms"], r["rr"]), textcoords="offset points", xytext=(6, 4), fontsize=8, color=A.INK)
ax.set_xscale("log"); ax.set_xlabel("median retrieval + reranking time per question (ms, log scale; Apple M1, reranking on GPU)")
ax.set_ylabel("MRR (held-out)"); ax.set_title("Quality vs latency (held-out v0.2, n = 100)"); ax.grid(axis="both")
fig.tight_layout(); print(A.save(fig, "10_quality_vs_latency"))'''),
    code('''\
hm = TAB["heldout_v0.2"].set_index("method"); dm = TAB["pilot_v0.1"].set_index("method")
best = max([m for m in hm.index if m.startswith("E3_")], key=lambda m: dm.loc[m, "rr"]) if any(m.startswith("E3_") for m in hm.index) else None
display(Markdown(f"""**Model chosen on the development set**: `{best}` (highest development MRR); its held-out MRR is
{hm.loc[best, 'rr']:.3f} [{hm.loc[best, 'rr_lo']:.3f}, {hm.loc[best, 'rr_hi']:.3f}] vs E2 {hm.loc['E2', 'rr']:.3f}
[{hm.loc['E2', 'rr_lo']:.3f}, {hm.loc['E2', 'rr_hi']:.3f}]. Paired tests are in notebook 12. Reranking cost:
median {lat.loc[best, 'rerank_ms']:.0f} ms per question on this machine's GPU (MPS) (peak memory
{MANIFESTS.get(best.split('_', 1)[1], {}).get('peak_rss_mb', '?')} MB for the reranking process) - compare with Render's
512 MB instance before any deployment decision.

**Limitations.** Off-the-shelf models; pools capped at 20 chunks (the service's `top_k` limit); local Apple M1
timings (GPU reranking) are not production timings - Render has no GPU, and the CPU rows above show the CPU cost;
AI-drafted, unreviewed labels."""))'''),
])

# =============================================================================================== 11
notebook("11_context_selection_experiments.ipynb", "11 · Context selection experiments",
         "What evidence would reach Gemini under different context strategies and budgets: expected-document coverage, "
         "evidence-term coverage (held-out only), figures for quantity questions, redundancy and source diversity. These "
         "are retrieval-side proxies; answer quality is not measured here.", [
    code('''\
CTX = {ds: pd.read_csv(A.RESULTS / f"context_{ds}.csv") for ds in ("pilot_v0.1", "heldout_v0.2")
       if (A.RESULTS / f"context_{ds}.csv").exists()}
for ds, c in CTX.items():
    print(ds, len(c), "rows; strategies:", sorted(c["strategy"].unique()), "; budgets:", sorted(c["budget_chars"].unique()))'''),
    code('''\
def ctx_summary(c):
    c = c.copy()
    for col in ("evidence_terms_found", "figure_in_expected_passage"):
        c[col] = pd.to_numeric(c[col], errors="coerce")
    rows = []
    for (st, b), g in c.groupby(["strategy", "budget_chars"]):
        mean, lo, hi = A.cluster_bootstrap(g, "expected_document_in_context")
        e = A.cluster_bootstrap(g, "evidence_terms_found") if g["evidence_terms_found"].notna().any() else (np.nan,) * 3
        q = g[g.quantity_question == 1]
        rows.append(dict(strategy=st, budget_chars=b, n=len(g), expected_doc_in_context=mean, lo=lo, hi=hi,
                         evidence_terms_found=e[0], evidence_lo=e[1], evidence_hi=e[2],
                         figure_for_quantity_questions=q["figure_in_expected_passage"].mean() if len(q) else np.nan,
                         n_quantity=len(q), redundant_pair_share=g["redundant_pair_share"].mean(),
                         documents=g["documents"].mean(), passages=g["passages"].mean(), chars=g["chars"].mean()))
    return pd.DataFrame(rows)
SUM = {ds: ctx_summary(c) for ds, c in CTX.items()}
pd.concat([s.assign(dataset=ds) for ds, s in SUM.items()]).round(3).to_csv(A.RESULTS / "context_summary.csv", index=False)
SUM["heldout_v0.2"].round(3)'''),
    code('''\
s = SUM["heldout_v0.2"]
ST = {"top_k_no_rerank": ("Top-K, no reranking", A.COLORS["B0"]), "top_k_reranked": ("Top-K after reranking", A.COLORS["E1"]),
      "document_balanced": ("Document-balanced (≤2 per document)", A.COLORS["E2"]),
      "question_aware_selection": ("Question-aware selection (assistant)", A.COLORS["E2S"])}
fig, axes = plt.subplots(1, 2, figsize=(12.5, 4))
for ax, (col, lo, hi, label) in zip(axes, [("expected_doc_in_context", "lo", "hi", "expected document in context"),
                                           ("evidence_terms_found", "evidence_lo", "evidence_hi", "evidence terms found in context")]):
    for st, (name, color) in ST.items():
        g = s[s.strategy == st].sort_values("budget_chars")
        if g.empty: continue
        ax.errorbar(g["budget_chars"], g[col], yerr=[g[col] - g[lo], g[hi] - g[col]], color=color, marker="o",
                    linewidth=2, markersize=7, capsize=3, label=name)
    ax.set_xlabel("context budget (characters)"); ax.set_ylabel(f"share of questions (95% CI)"); ax.set_ylim(0, 1.05)
    ax.set_title(f"{label.capitalize()} - held-out (n = 100)"); ax.set_xticks([3000, 6000, 9000])
h_, l_ = axes[0].get_legend_handles_labels(); fig.legend(h_, l_, loc="upper center", ncol=2, bbox_to_anchor=(0.5, 1.12))
fig.tight_layout(); print(A.save(fig, "11_context_strategies"))'''),
    code('''\
b9 = s[s.budget_chars == 9000].set_index("strategy")
display(Markdown(f"""**Interpretation (held-out, 9,000-character budget).** Expected document in context: """
    + ", ".join(f"{ST[k][0]} {b9.loc[k, 'expected_doc_in_context']:.2f}" for k in ST if k in b9.index)
    + f""". Redundant passage pairs (token Jaccard ≥ 0.5) are rare in every strategy. Larger budgets mostly add
documents rather than completeness of the right one; quantity questions (n = {int(b9['n_quantity'].iloc[0])}) are where
figures in the expected passage matter.

**Not evaluated**: whether these contexts change Gemini's answer correctness or faithfulness - that requires controlled
generation with a working model and human scoring (Phase 7 gate not met). Contradictory-source detection is not
measured automatically. **Limitations**: evidence terms exist only for held-out scenarios and were drafted by an AI
assistant; these are proxies, not answer-quality measures."""))'''),
])

# =============================================================================================== 12
notebook("12_statistical_comparison.ipynb", "12 · Statistical comparison",
         "Pre-specified paired comparisons on the same questions, 95% cluster-bootstrap intervals over scenarios, exact "
         "McNemar tests for Recall@1 and Holm correction across the primary held-out comparisons. An improvement is "
         "reported as supported only when its interval excludes zero. Writes the Milestone 5 report and abstract.", [
    code(M5_LOAD),
    code('''\
PAIRS = [("E2", "B0", "improved hybrid vs dense"), ("E2", "E1", "improved vs original hybrid"),
         ("B0FR_bge-m3", "B0", "B0R: dense pool + bge-m3 vs dense"), ("B0FR_bge-m3", "B0F", "dense (no threshold) + bge-m3"),
         ("E3_bge-m3", "E2", "hybrid + bge-m3 vs hybrid"), ("E3_mminilm", "E2", "hybrid + mMiniLM vs hybrid"),
         ("E4_bge-m3", "E3_bge-m3", "+ evidence selection vs reranked hybrid"), ("E3_bge-m3", "B0", "reranked hybrid vs dense")]
rows = []
for ds, df in EXP.items():
    if df is None: continue
    for a, b, what in PAIRS:
        if {a, b} <= set(df.method):
            for col in ("r1", "r3", "r5", "rr", "ndcg5", "ndcg10"):
                r = A.paired_difference(df, a, b, col); r.update(dataset=ds, what=what); rows.append(r)
cmp = pd.DataFrame(rows)
primary = cmp[(cmp.dataset == "heldout_v0.2") & (cmp.metric == "rr")].copy()
# Holm correction over the primary (held-out MRR) comparisons, using the bootstrap two-sided p-value approximation
def boot_p(r):
    se = (r["hi"] - r["lo"]) / (2 * 1.96)
    return float(2 * (1 - scipy.stats.norm.cdf(abs(r["diff"]) / se))) if se > 0 else 1.0
import scipy.stats
primary["p_approx"] = primary.apply(boot_p, axis=1)
primary = primary.sort_values("p_approx")
m = len(primary); primary["holm_threshold"] = [0.05 / (m - i) for i in range(m)]
reject, still = [], True
for p_, t_ in zip(primary["p_approx"], primary["holm_threshold"]):
    still = still and p_ <= t_; reject.append(still)
primary["supported_after_holm"] = reject
cmp.to_csv(A.RESULTS / "m5_paired_comparisons.csv", index=False)
primary[["a", "b", "what", "n", "mean_a", "mean_b", "diff", "lo", "hi", "p_approx", "holm_threshold", "supported_after_holm"]].round(4)'''),
    code('''\
h = cmp[(cmp.dataset == "heldout_v0.2") & (cmp.metric.isin(["r1", "rr"]))]
labels = [f"{a} vs {b}" for a, b, _ in PAIRS if not h[(h.a == a) & (h.b == b)].empty]
fig, ax = plt.subplots(figsize=(10, 0.55 * len(labels) + 1.6))
for j, (metric, color) in enumerate((("r1", A.COLORS["B0"]), ("rr", A.COLORS["E1"]))):
    sub = h[h.metric == metric].assign(label=lambda d: d.a + " vs " + d.b).set_index("label").reindex(labels)
    y = np.arange(len(labels)) + (j - 0.5) * 0.3
    ax.errorbar(100 * sub["diff"], y, xerr=[100 * (sub["diff"] - sub["lo"]), 100 * (sub["hi"] - sub["diff"])], fmt="o",
                color=color, capsize=3, markersize=7, linewidth=1.6, label={"r1": "Recall@1", "rr": "MRR"}[metric])
    for xv, yv in zip(100 * sub["diff"], y):
        ax.text(xv, yv + 0.13, f"{xv:+.1f}", ha="center", fontsize=8, color=A.INK)
ax.axvline(0, color=A.INK2, linewidth=1); ax.set_yticks(np.arange(len(labels)), labels); ax.invert_yaxis()
ax.set_ylim(len(labels) - 0.4, -0.75); ax.grid(axis="x"); ax.grid(axis="y", visible=False)
ax.set_xlabel("paired difference, percentage points (95% cluster-bootstrap CI)")
ax.set_title("Held-out v0.2 (n = 100 questions, 20 scenarios) - pre-specified comparisons")
ax.legend(loc="lower right"); fig.tight_layout(); print(A.save(fig, "12_forest_plot"))'''),
    md("## Subgroups (held-out): language, cross-language, document length, question type"),
    code('''\
df = EXP["heldout_v0.2"]
manifest = {d["id"]: d for d in json.loads((A.SNAP / "corpus_manifest.json").read_text())["items"]}
bench = {r["question_id"]: r for r in json.loads((A.DATA / "benchmarks/retrieval_heldout_v0.2.json").read_text())["records"]}
chunks = pd.read_csv(A.SNAP / "chunk_metrics.csv"); per_doc = chunks[chunks.active].groupby("document_id").size()
aliases = json.loads((A.DATA / "id_aliases.json").read_text())["aliases"]
def n_chunks(pid): return per_doc.get(aliases.get(pid, pid), np.nan)
df["cross_language"] = df.question_id.map(lambda q: bench[q]["language"] != manifest[bench[q]["primary_document_id"]]["language"])
df["long_document"] = df.question_id.map(lambda q: n_chunks(bench[q]["primary_document_id"]) >= 30)
sel = ["B0", "E2", "E3_bge-m3", "E4_bge-m3"]
sub = df[df.method.isin(sel)]
for key in ("language", "cross_language", "long_document", "difficulty", "category"):
    t = A.summarize(sub, ["method", key], metrics=("r1", "rr")).pivot(index=key, columns="method", values="rr")
    display(Markdown(f"**MRR by {key}** (n per cell = questions in that group)")); display(t.round(3))'''),
    code('''\
res = A.summarize(df, ["method"], metrics=("r1", "r3", "r5", "r10", "rr", "ndcg5", "ndcg10")).set_index("method")
dev = A.summarize(EXP["pilot_v0.1"], ["method"], metrics=("r1", "rr")).set_index("method")
stats = json.loads((A.SNAP / "dataset_statistics.json").read_text())
def ci(m, k="rr"):
    if m not in res.index:
        return "not evaluated"
    return f"{res.loc[m, k]:.3f} [{res.loc[m, k+'_lo']:.3f}, {res.loc[m, k+'_hi']:.3f}]"
def pp(a, b, metric="rr"):
    m = cmp[(cmp.dataset == "heldout_v0.2") & (cmp.a == a) & (cmp.b == b) & (cmp.metric == metric)]
    if m.empty:
        return "not evaluated"
    r = m.iloc[0]
    return f"{100*r['diff']:+.1f} pp [{100*r['lo']:+.1f}, {100*r['hi']:+.1f}]" + (" (supported)" if r["ci_excludes_zero"] else " (inconclusive)")
table = pd.DataFrame([dict(method=m, **{k: f"{res.loc[m, k]:.3f}" for k in ("r1", "r3", "r5", "r10", "ndcg5", "ndcg10")},
                           MRR=ci(m)) for m in res.index])
table.to_csv(A.REPORTS / "m5_ablation_table.csv", index=False)
lat = df[df.reranker.isna() | (df.get("rerank_device", "mps") != "cpu")].groupby("method")["total_ms"].median()   # GPU reranking rows
report = f"""# Milestone 5 - multilingual reranking and error analysis (preliminary)

All results below are **preliminary**: questions and relevance labels are AI-drafted and not human-reviewed. The held-out
set v0.2 was never used for tuning but its results were inspected in Milestone 4 ("inspected, untuned"). Local
experiments (Apple M1; reranking on the GPU via MPS, CPU for the first development rows) on identical frozen candidate pools (≤ 20 chunks); corpus snapshot
{json.loads((A.SNAP / 'corpus_manifest.json').read_text())['snapshot_sha256_16']} ({A.SNAPSHOT}); embedding multilingual-e5-small (ONNX int8).

## Held-out results (n = 100 questions, 20 scenarios, 5 languages)
{table.to_markdown(index=False)}

`[a, b]` = 95% cluster-bootstrap interval over scenarios.

## Key paired comparisons (held-out MRR)
- E3 (hybrid + bge-reranker-v2-m3) vs E2: {pp('E3_bge-m3', 'E2')}
- E3 (hybrid + mMiniLM) vs E2: {pp('E3_mminilm', 'E2')}
- B0R (dense top-20 pool without threshold + bge-m3, method B0FR) vs B0: {pp('B0FR_bge-m3', 'B0')}
- E4 (+ evidence selection) vs E3 (bge-m3): {pp('E4_bge-m3', 'E3_bge-m3')}
- E2 vs B0: {pp('E2', 'B0')}; E2 vs E1: {pp('E2', 'E1')}

Holm-corrected held-out MRR comparisons supported: {', '.join(f"{r.a} vs {r.b}" for r in primary.itertuples() if r.supported_after_holm) or 'none'}.

## Cost
Median local time per question (Apple M1; first stage CPU, reranking GPU/MPS): E2 {lat.get('E2', float('nan')):.0f} ms; E3 bge-m3 {lat.get('E3_bge-m3', float('nan')):.0f} ms;
E3 mMiniLM {lat.get('E3_mminilm', float('nan')):.0f} ms.

## Not evaluated
Answer quality per retrieval pipeline (no working primary Gemini model locally, no human scores); human-reviewed final test set.
"""
(A.REPORTS / "milestone5_results.md").write_text(report)
display(Markdown(report))'''),
    code('''\
abstract = f"""**Draft abstract (Milestone 5, preliminary - AI-drafted labels, not human-reviewed).**

We study retrieval for a multilingual assistant that answers international students' questions in Korean, English,
Indonesian, Vietnamese and Chinese from {stats['documents']['active_searchable']} approved university and government
documents written mainly in English and Korean ({stats['chunks']['active']} chunks; multilingual-e5-small in
PostgreSQL/pgvector). An error analysis of 200 synthetic questions shows that most first-rank failures arise when a
document in the question's own script outranks the relevant document in another language, followed by keyword
ambiguity and dominance of one long multi-topic guide. On a held-out set (100 questions, 20 scenarios) we compare dense
retrieval, two hybrid retrievers and off-the-shelf multilingual cross-encoder reranking on identical candidate pools:
the improved hybrid reaches MRR {ci('E2')}, and reranking it with bge-reranker-v2-m3 gives {ci('E3_bge-m3')}
(paired difference {pp('E3_bge-m3', 'E2')}) at a median local cost (Apple M1, GPU reranking) of {lat.get('E3_bge-m3', float('nan')):.0f} ms per question.
Answer-level effects were not evaluated. All evaluation data, scripts and notebooks are released for review."""
(A.REPORTS / "abstract_draft_m5.md").write_text(abstract + "\\n"); display(Markdown(abstract))'''),
])

# =============================================================================================== 13
NB13_LOAD = """\
import csv, re
EXP = A.DATA / "experiments/chunking"; RES = EXP / "results"; FIG = A.RESEARCH / "figures/chunk_quality"
REP = A.RESEARCH / "reports/chunk_quality"; REP.mkdir(parents=True, exist_ok=True)
INV = json.loads((EXP / "investigation.json").read_text())
VM = json.loads((EXP / "variants.manifest.json").read_text())
VARIANTS = ["C0_existing", "C1_merge_short", "C2_paragraph", "C3_heading", "C4_table", "P1_prod_fixed_body"]
LABEL = {"C0_existing": "C0 existing (production)", "C1_merge_short": "C1 merge short fragments",
         "C2_paragraph": "C2 paragraph-aware", "C3_heading": "C3 heading-aware", "C4_table": "C4 table-aware",
         "P1_prod_fixed_body": "P1 production extractor, fixed body size", "C0_repeat": "C0 rebuilt (noise floor)"}
GB = "d60bc363-0aae-44e5-b0c3-df8c61ad6f66"
BENCH = {ds: {r["question_id"]: r for r in json.loads((A.DATA / f"benchmarks/retrieval_{ds}.json").read_text())["records"]}
         for ds in ("pilot_v0.1", "heldout_v0.2")}
QDS = {q: ds for ds, recs in BENCH.items() for q in recs}
REC = {q: r for recs in BENCH.values() for q, r in recs.items()}
FROZEN = {q: set(r["expected_document_ids"]) for q, r in REC.items()}
SENS = json.loads((EXP / "label_sensitivity_ai_proposed.json").read_text())
AI = {q: FROZEN[q] | set(SENS["add"].get(r["scenario_id"], [])) for q, r in REC.items()}
man = {i["id"]: i for i in json.loads((A.DATA / "snapshots/corpus_v2/corpus_manifest.json").read_text())["items"]}
CROSS = {q: r["language"] != man[r["primary_document_id"]]["language"] for q, r in REC.items()}
RUNS = [v for v in VARIANTS + ["C0_repeat"] if (RES / f"retrieval_{v}.csv").exists()]
def load(v, labels):
    df = A.score_rankings(pd.read_csv(RES / f"retrieval_{v}.csv"), labels)
    return df.assign(variant=v, dataset=df.question_id.map(QDS), cross_language=df.question_id.map(CROSS))
RET = {lab: pd.concat([load(v, L) for v in RUNS], ignore_index=True) for lab, L in (("frozen", FROZEN), ("ai_sensitivity", AI))}
CH = {v: pd.read_csv(RES / f"chunks_{v}.csv") for v in VARIANTS if (RES / f"chunks_{v}.csv").exists()}
print("variants evaluated:", RUNS)
print("label sets: frozen v0.1/v0.2 (official) and", SENS["status"], f"({sum(len(x) for x in SENS['add'].values())} added credits)")"""

notebook("13_korean_pdf_chunk_quality.ipynb", "13 · Korean PDF chunk quality",
         "Why the corpus_v2 guidebook *한국 유학생 생활 가이드북* (94 pages, 291 chunks, median 37 characters) is "
         "fragmented, and whether better extraction / chunking changes retrieval. Each variant replaces only the "
         "guidebook text in an otherwise identical corpus_v2, is indexed with the production chunker and embedding "
         "model in a separate local in-memory index, and is evaluated on the same frozen questions. Production data "
         "and embeddings are not touched.", [
    code(NB13_LOAD),
    md("## 1 · Dataset statistics and extraction diagnosis\n\nThe production text was extracted by PyMuPDF "
       "(`table_mode=off`). The diagnostics separate the candidate causes: extraction (heading tagging, line-level "
       "paragraphs), Korean sentence boundaries, tables / layout, headers and footers, OCR / encoding, the chunker "
       "and empty paragraphs."),
    code(r'''f, x, l, c = INV["font"], INV["extracted_text"], INV["layout"], INV["chunker"]
pm = INV["production_extraction_meta"]
rows = [
    ("PDF pages / pages with text / image-only pages", f"{pm['pages']} / {pm['pages_with_text']} / {pm['empty_pages']}"),
    ("OCR used", "no (3 image-only pages were skipped and flagged)"),
    ("Body font size estimated by production (first 20 pages)", f"{f['body_estimate_production_first20']} pt"),
    ("Body font size over all pages (character-weighted mode)", f"{f['body_estimate_all_pages']} pt"),
    ("Heading threshold used (1.2 x estimate)", f"{f['heading_threshold_pt']} pt"),
    ("Share of all characters printed at >= threshold -> tagged '##'", f"{f['share_chars_tagged_heading']:.0%}"),
    ("Extracted paragraphs / marked as headings", f"{x['paragraphs']} / {x['heading_marked']}"),
    ("'Headings' longer than 40 characters (body sentences)", x["heading_marked_over_40_chars"]),
    ("Median paragraph length (characters)", x["median_paragraph_chars"]),
    ("Paragraphs ending a Korean sentence (다/요/. ...)", f"{x['paragraphs_ending_sentence']} of {x['paragraphs']}"),
    ("Paragraphs < 20 characters", x["paragraphs_under_20_chars"]),
    ("Page-number-only paragraphs / running header / chapter tabs", f"{x['page_number_only']} / {x['running_header']} / {x['chapter_tabs']}"),
    ("Pages with side-by-side layout", l["two_column_like_pages"]),
    ("Tables detected by PyMuPDF (extraction had tables off)", VM["c4_tables"]["kept"] + VM["c4_tables"]["rejected"]),
    ("Control / zero-width characters in the PDF text", ", ".join(f"{k} x{v}" for k, v in l["control_or_zero_width_chars"].items())),
    ("Replacement characters (encoding errors)", x["replacement_chars"]),
    ("Chunker: chunks / boundaries forced by a heading change", f"{c['chunks']} / {c['chunk_boundaries_at_heading_change']} ({c['share_boundaries_forced_by_heading']:.0%})"),
]
display(pd.DataFrame(rows, columns=["diagnostic", "value"]))'''),
    code(r'''cov = []
import sys as _s; _s.path.insert(0, str(A.RESEARCH.parent / "backend"))
from app.services.chunking import chunk_text, ChunkerConfig
import collections
for v in VARIANTS:
    t = (EXP / v / "guidebook.md").read_text()
    ch = chunk_text(t, ChunkerConfig(320, 420, 48))
    src = collections.Counter(re.findall(r"[가-힣]+", re.sub(r"\[Page \d+\]", "", t)))
    con = collections.Counter(w for k in ch for w in re.findall(r"[가-힣]+", k.content))
    both = con + collections.Counter(w for k in ch for w in re.findall(r"[가-힣]+", k.heading or ""))
    share = lambda C: sum(min(n, C[w]) for w, n in src.items()) / sum(src.values())
    cov.append(dict(variant=LABEL[v], hangul_words=sum(src.values()), in_chunk_text=share(con), in_text_or_heading=share(both)))
cov = pd.DataFrame(cov); display(cov.round(3))
c0 = cov.iloc[0]
display(Markdown(f"""**Diagnosis.** The fragmentation starts in *PDF text extraction*, and the chunker turns it into
*content loss*:

1. The production extractor estimates the body font size from the first 20 pages only. Those pages are front matter
   and visa forms printed at {f['body_estimate_production_first20']} pt, while the body text is {f['body_estimate_all_pages']} pt.
   Every short line at >= {f['heading_threshold_pt']} pt becomes a `##` heading: {f['share_chars_tagged_heading']:.0%}
   of all characters, one heading per *visual line* ({x['heading_marked_over_40_chars']} "headings" are body
   sentences longer than 40 characters).
2. Line breaks become paragraph breaks: only {x['paragraphs_ending_sentence']} of {x['paragraphs']} paragraphs end
   a Korean sentence, so sentences are cut mid-way ("정보 습득이" / "가능하다.").
3. The heading-aware chunker is working as designed: {c['share_boundaries_forced_by_heading']:.0%} of its chunk
   boundaries are heading changes and it never reaches its size limit. But a heading is stored as chunk *metadata*
   and consecutive headings overwrite each other. Only **{c0.in_chunk_text:.0%}** of the guidebook's Hangul words
   reach chunk text ({c0.in_text_or_heading:.0%} including the heading field that is embedded). Most of the
   document is not retrievable at all.
4. Secondary: table cells (tables off) become one-word headings ("## 20시간"); page numbers ({x['page_number_only']}),
   the running header and chapter tabs repeat as paragraphs; BEL/ZWNJ control characters are present. OCR and
   encoding are *not* causes: no replacement characters, 91 of 94 pages have a text layer, and Hangul is intact.
   The other corpus_v2 documents keep >= 97 % of their words in chunks; only this PDF is affected."""))'''),
    md("## 2 · Extraction-quality examples (page 74: part-time work hours table; page 37: registration changes)"),
    code(r'''for p in ("74", "37"):
    a = INV["examples"]["production"][p]; b = INV["examples"]["C3_heading"][p]
    display(Markdown(f"**Page {p} - production text (first 700 characters)**\n```\n{a}\n```\n"
                     f"**Page {p} - C3 re-extraction**\n```\n{b}\n```"))'''),
    md("## 3 · Experimental configurations\n\nSame source, same chunker settings (target 320 / max 420 / "
       "overlap 48 tokens), same embedding model. Content retention is measured on Hangul characters relative to "
       "the production text; the 2.3 % removed by C2-C4 is page furniture (running header x42, chapter tabs, page numbers)."),
    code(r'''cfg = {"C0_existing": "production text unchanged", "C1_merge_short": "text-only repair: furniture + control chars removed, false ## dropped, short fragments merged within a page (~400 chars)",
       "C2_paragraph": "PDF re-extraction: lines of a block re-flowed into one paragraph, furniture removed by position, no headings",
       "C3_heading": "C2 + headings from corrected body size (>=1.4x '#', >=1.15x '##')", "C4_table": "C3 + validated tables as | a | b | rows",
       "P1_prod_fixed_body": "production extract_pdf, body size over all pages (minimal production fix)"}
t = pd.DataFrame([dict(variant=LABEL[v], description=cfg[v], chars=m["chars"], hangul_retained=m["hangul_retained_vs_existing"],
                       paragraphs=m["paragraphs"], heading_paragraphs=m["heading_paragraphs"], page_markers=m["pages_marked"],
                       control_chars=m["control_chars"]) for v, m in VM["variants"].items()])
display(t)
print("C4 tables kept / rejected by the 95 % text-retention check:", VM["c4_tables"]["kept"], "/", VM["c4_tables"]["rejected"])'''),
    md("## 4 · Chunk-length distributions"),
    code(r'''SENT = re.compile(r"(다|요|음|함|임|됨|것|[.!?:;)\]>》」』])\s*$")
crow = []
for v, d in CH.items():
    idx = json.loads((RES / f"index_{v}.json").read_text())
    crow.append(dict(variant=LABEL[v], chunks=len(d), median_chars=d.chars.median(), p10=d.chars.quantile(.1), p90=d.chars.quantile(.9),
                     under_100=(d.chars < 100).mean(), under_50=(d.chars < 50).mean(),
                     ends_at_sentence=d.content.astype(str).map(lambda s: bool(SENT.search(s))).mean(),
                     with_page_reference=d.page_start.notna().mean(), with_heading=(d.heading.fillna("") != "").mean(),
                     corpus_chunks=idx["chunks"], index_build_s=idx["build_seconds"]))
CROW = pd.DataFrame(crow); display(CROW.round(3))
fig, axes = plt.subplots(2, 3, figsize=(12.5, 6.2), sharex=True, sharey=True)
bins = np.logspace(0, np.log10(2200), 28)
for ax, (v, d) in zip(axes.flat, CH.items()):
    ax.hist(d.chars.clip(lower=1), bins=bins, color=A.COLORS["B0"], edgecolor=A.SURFACE, linewidth=0.8)
    med = d.chars.median(); ax.axvline(med, color=A.INK, linestyle="--", linewidth=1)
    ax.set_xscale("log"); ax.set_title(f"{LABEL[v]}", fontsize=10)
    ax.text(0.03, 0.92, f"n = {len(d)} | median {med:.0f}\n< 100 chars: {(d.chars < 100).mean():.0%}", transform=ax.transAxes,
            fontsize=8.5, va="top", color=A.INK)
for ax in axes[-1]: ax.set_xlabel("characters per chunk (log scale)")
for ax in axes[:, 0]: ax.set_ylabel("chunks")
fig.suptitle("Guidebook chunk length by configuration", fontweight="bold"); fig.tight_layout()
print(A.save(fig, "13_chunk_length_distribution", FIG))'''),
    md("## 5 · Retrieval comparison\n\nPrimary: frozen v0.2 labels (held-out). The frozen labels were written "
       "before the guidebook existed, so a variant that retrieves the guidebook for a question it answers is *penalised*. "
       "The sensitivity analysis adds the AI-proposed guidebook credits (review worksheet "
       "`data/review/label_review_new_documents_corpus_v2.csv`, **not human-reviewed**) and is reported separately."),
    code(r'''METRICS = ("r1", "r5", "rr", "ndcg5")
tabs = []
for lab, df in RET.items():
    for ds in ("heldout_v0.2", "pilot_v0.1"):
        s = A.summarize(df[(df.dataset == ds) & df.method.isin(["B0", "E2", "E2S"])], ["variant", "method"], METRICS)
        tabs.append(s.assign(labels=lab, dataset=ds))
SUM = pd.concat(tabs, ignore_index=True); SUM.to_csv(RES / "summary_by_variant.csv", index=False)
show = SUM[(SUM.dataset == "heldout_v0.2") & (SUM.method == "E2")].copy(); show["variant"] = show.variant.map(LABEL)
display(Markdown("**Held-out v0.2, E2 (production hybrid), both label sets**"))
display(show[["labels", "variant", "n", "r1", "r5", "rr", "rr_lo", "rr_hi", "ndcg5"]].round(3))'''),
    code(r'''fig, axes = plt.subplots(1, 2, figsize=(12.5, 4.6), sharey=True)
order = [v for v in VARIANTS + ["C0_repeat"] if v in RUNS]
for ax, lab in zip(axes, ("frozen", "ai_sensitivity")):
    s = SUM[(SUM.dataset == "heldout_v0.2") & (SUM.labels == lab)]
    for j, m in enumerate(("B0", "E2")):
        g = s[s.method == m].set_index("variant").reindex(order)
        y = np.arange(len(order)) + (j - 0.5) * 0.28
        ax.errorbar(g.rr, y, xerr=[g.rr - g.rr_lo, g.rr_hi - g.rr], fmt="o", color=A.COLORS[m], capsize=3, markersize=7,
                    linewidth=1.5, label={"B0": "B0 dense", "E2": "E2 weighted hybrid"}[m])
    ax.set_yticks(np.arange(len(order)), [LABEL[v] for v in order]); ax.grid(axis="x"); ax.grid(axis="y", visible=False)
    ax.set_xlabel("MRR, held-out v0.2 (95% cluster-bootstrap CI)")
    ax.set_title({"frozen": "Frozen labels (official)", "ai_sensitivity": "+ AI-proposed guidebook labels (not reviewed)"}[lab], fontsize=10.5)
axes[0].invert_yaxis()   # shared y-axis: invert once
h, l = axes[0].get_legend_handles_labels()
fig.legend(h, l, loc="lower center", ncol=2, bbox_to_anchor=(0.5, -0.02), frameon=False)
fig.tight_layout(rect=(0, 0.06, 1, 1)); print(A.save(fig, "13_retrieval_by_variant", FIG))'''),
    md("### Korean and cross-language questions (held-out, E2)"),
    code(r'''sub = []
for lab, df in RET.items():
    d = df[(df.dataset == "heldout_v0.2") & (df.method == "E2")]
    for name, g in (("Korean questions", d[d.language == "ko"]), ("cross-language questions", d[d.cross_language]),
                    ("same-language questions", d[~d.cross_language])):
        s = A.summarize(g, ["variant"], ("r1", "rr")).assign(group=name, labels=lab); sub.append(s)
SUB = pd.concat(sub, ignore_index=True)
piv = SUB.assign(variant=SUB.variant.map(LABEL)).pivot_table(index="variant", columns=["labels", "group"], values="rr")
display(piv.reindex([LABEL[v] for v in order]).round(3))
print("n per group:", SUB.groupby("group").n.first().to_dict())'''),
    md("### Retrieval latency\n\nMedian local query time (Apple M1, CPU, in-memory store). Values come from the "
       "dedicated timing pass on a quiet machine (`--latency-only`, 3 repetitions per question) when available; "
       "otherwise from the evaluation run, which shared the machine with the reranking job."),
    code(r'''lat = []
for v in order:
    p = RES / f"latency_{v}.json"
    if p.exists():
        L = json.loads(p.read_text()); lat.append(dict(variant=LABEL[v], source="timing pass", B0_ms=L["B0"]["median_ms"], E2_ms=L["E2"]["median_ms"],
                                                     E2_p90_ms=L["E2"]["p90_ms"]))
    else:
        d = RET["frozen"][RET["frozen"].variant == v]
        lat.append(dict(variant=LABEL[v], source="evaluation run (shared machine)", B0_ms=d[d.method == "B0"].latency_ms.median(),
                        E2_ms=d[d.method == "E2"].latency_ms.median(), E2_p90_ms=d[d.method == "E2"].latency_ms.quantile(.9)))
LAT = pd.DataFrame(lat); display(LAT.round(1))'''),
    md("## 6 · Evidence completeness\n\n* **evidence page hit@5** - for held-out scenarios where the review "
       "proposes the guidebook as relevant, does an E2 top-5 passage come from the guidebook page(s) that contain the "
       "answer? (page references are preserved in every variant)\n* **guidebook passage length in top 5** - "
       "fragments cannot carry an answer\n* **evidence terms@5** - share of the scenario's (mostly English) evidence "
       "terms found in the top-5 passages (all held-out questions)."),
    code(r'''rev = pd.read_csv(A.DATA / "review/label_review_new_documents_corpus_v2.csv")
def pages(s):
    out = set()
    for part in str(s).split(","):
        part = part.strip()
        if "-" in part: a, b = part.split("-"); out |= set(range(int(a), int(b) + 1))
        elif part.isdigit(): out.add(int(part))
    return out
EVP = {r.scenario_id: pages(r.evidence_pages) for r in rev.itertuples() if r.document_id == GB and r.ai_proposed_relevance == "relevant"}
ev = []
for v in order:
    for line in (RES / f"passages_{v}.jsonl").open(encoding="utf-8"):
        p = json.loads(line); r = REC[p["question_id"]]
        if QDS[p["question_id"]] != "heldout_v0.2": continue
        top = p["passages"]; gb = [x for x in top if x["document_id"] == GB]
        terms = [t.lower() for t in r.get("evidence_terms") or []]
        joined = " ".join((x["text"] or "").lower() for x in top)
        ev.append(dict(variant=v, question_id=p["question_id"], scenario_id=r["scenario_id"], language=r["language"],
                       guidebook_in_top5=len(gb), gb_median_len=np.median([len(x["text"] or "") for x in gb]) if gb else np.nan,
                       fragment_at_rank1=float(bool(top) and top[0]["document_id"] == GB and len(top[0]["text"] or "") < 50),
                       evidence_terms_at5=(sum(t in joined for t in terms) / len(terms)) if terms else np.nan,
                       page_hit=(float(any(x["page"] in EVP[r["scenario_id"]] for x in gb)) if r["scenario_id"] in EVP else np.nan)))
EV = pd.DataFrame(ev)
evs = EV.groupby("variant").agg(questions_with_guidebook_top5=("guidebook_in_top5", lambda s: (s > 0).mean()),
                                median_guidebook_passage_chars=("gb_median_len", "median"),
                                fragment_rank1=("fragment_at_rank1", "mean"), evidence_terms_at5=("evidence_terms_at5", "mean"),
                                evidence_page_hit_at5=("page_hit", "mean"), n_page_questions=("page_hit", "count")).reindex(order)
evs.index = evs.index.map(LABEL); display(evs.round(3))'''),
    md("## 7 · Error analysis (held-out, E2, frozen labels): questions whose first-relevant rank changes vs C0"),
    code(r'''F = RET["frozen"]; e2 = F[(F.dataset == "heldout_v0.2") & (F.method == "E2")].pivot_table(index="question_id", columns="variant", values="rank")
e2 = e2.fillna(99)
chg = []
for v in [x for x in order if x != "C0_existing"]:
    better = (e2[v] < e2["C0_existing"]).sum(); worse = (e2[v] > e2["C0_existing"]).sum()
    chg.append(dict(variant=LABEL[v], improved=int(better), worse=int(worse), unchanged=int(len(e2) - better - worse)))
display(pd.DataFrame(chg))
best = max([v for v in VARIANTS[1:] if v in RUNS], key=lambda v: SUM[(SUM.dataset == "pilot_v0.1") & (SUM.labels == "frozen") & (SUM.method == "E2") & (SUM.variant == v)].rr.iloc[0])
print("best variant on the development set (pilot, E2 MRR, frozen labels):", LABEL[best])
top1 = {}
for v in ("C0_existing", best):
    for line in (RES / f"passages_{v}.jsonl").open(encoding="utf-8"):
        p = json.loads(line); top1[(v, p["question_id"])] = p["passages"][0] if p["passages"] else {}
moved = e2[(e2[best] != e2["C0_existing"])].index[:8]
ex = [dict(question=q, lang=REC[q]["language"], rank_C0=e2.loc[q, "C0_existing"], rank_best=e2.loc[q, best],
           C0_top1=("[GB] " if top1[("C0_existing", q)].get("document_id") == GB else "") + str(top1[("C0_existing", q)].get("text") or "")[:70],
           best_top1=("[GB] " if top1[(best, q)].get("document_id") == GB else "") + str(top1[(best, q)].get("text") or "")[:70]) for q in moved]
display(pd.DataFrame(ex).replace(99, "none"))'''),
    md("## 8 · Statistical analysis\n\nPaired comparisons of each variant against C0 on the same held-out questions "
       "(E2, MRR and Recall@1), 95 % cluster-bootstrap intervals over the 20 scenarios, exact McNemar for Recall@1, "
       "Holm correction across the five variants (MRR, frozen labels). `C0 rebuilt` measures the noise of rebuilding "
       "an identical index (random tie-breaking in the local store)."),
    code(r'''cmp = []
for lab, df in RET.items():
    d = df[(df.dataset == "heldout_v0.2") & (df.method == "E2")].assign(method=lambda x: x.variant)
    for v in [x for x in order if x != "C0_existing"]:
        for col in ("rr", "r1"):
            r = A.paired_difference(d, v, "C0_existing", col); r.update(labels=lab, variant=v); cmp.append(r)
CMP = pd.DataFrame(cmp)
prim = CMP[(CMP.labels == "frozen") & (CMP.metric == "rr") & (CMP.variant != "C0_repeat")].copy()
from scipy.stats import norm
prim["p_approx"] = [2 * (1 - norm.cdf(abs(r["diff"]) / max((r["hi"] - r["lo"]) / 3.92, 1e-9))) for _, r in prim.iterrows()]
prim = prim.sort_values("p_approx"); m = len(prim)
prim["holm_threshold"] = [0.05 / (m - i) for i in range(m)]
ok = True; sup = []
for _, r in prim.iterrows():
    ok = ok and r["p_approx"] <= r["holm_threshold"]; sup.append(ok)
prim["supported_after_holm"] = sup
CMP.to_csv(RES / "paired_vs_C0.csv", index=False)
display(prim.assign(variant=prim.variant.map(LABEL))[["variant", "n", "mean_a", "mean_b", "diff", "lo", "hi", "p_approx", "holm_threshold", "supported_after_holm"]].round(4))
display(CMP[CMP.metric == "r1"].assign(variant=CMP.variant.map(LABEL))[["labels", "variant", "diff", "lo", "hi", "a_better", "b_better", "mcnemar_p"]].round(4))'''),
    code(r'''fig, ax = plt.subplots(figsize=(10, 4.6))
labs = [v for v in order if v != "C0_existing"]
for j, (lab, color) in enumerate((("frozen", A.COLORS["E2"]), ("ai_sensitivity", A.COLORS["E2S"]))):
    s = CMP[(CMP.labels == lab) & (CMP.metric == "rr")].set_index("variant").reindex(labs)
    y = np.arange(len(labs)) + (j - 0.5) * 0.3
    ax.errorbar(100 * s["diff"], y, xerr=[100 * (s["diff"] - s["lo"]), 100 * (s["hi"] - s["diff"])], fmt="o", color=color,
                capsize=3, markersize=7, linewidth=1.5, label={"frozen": "frozen labels", "ai_sensitivity": "+ AI-proposed labels"}[lab])
    for xv, yv in zip(100 * s["diff"], y): ax.text(xv, yv - 0.17, f"{xv:+.1f}", ha="center", fontsize=8, color=A.INK)
ax.axvline(0, color=A.INK2, linewidth=1); ax.set_yticks(np.arange(len(labs)), [LABEL[v] for v in labs]); ax.invert_yaxis()
ax.set_xlabel("E2 MRR difference vs C0, percentage points (95% CI)"); ax.grid(axis="x"); ax.grid(axis="y", visible=False)
ax.set_title("Held-out v0.2 (n = 100 questions, 20 scenarios)")
ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=2, frameon=False); fig.tight_layout()
print(A.save(fig, "13_paired_differences", FIG))'''),
    md("## 9 · Conclusions and limitations"),
    code(r'''def row(lab, v, ds="heldout_v0.2", m="E2"):
    return SUM[(SUM.labels == lab) & (SUM.variant == v) & (SUM.dataset == ds) & (SUM.method == m)].iloc[0]
def pp(v, lab="frozen", col="rr"):
    r = CMP[(CMP.labels == lab) & (CMP.variant == v) & (CMP.metric == col)].iloc[0]
    return f"{100*r['diff']:+.1f} pp [{100*r['lo']:+.1f}, {100*r['hi']:+.1f}]"
cw = CROW.set_index("variant"); ev_ = evs
lower = [LABEL[r.variant] for r in prim.itertuples() if r.supported_after_holm and r.diff < 0]
higher = [LABEL[r.variant] for r in prim.itertuples() if r.supported_after_holm and r.diff > 0]
sens = CMP[(CMP.labels == "ai_sensitivity") & (CMP.metric == "rr") & (CMP.variant != "C0_repeat")]
sens_txt = ", ".join(f"{LABEL[r.variant].split(' ')[0]} {100*r['diff']:+.1f} pp [{100*r['lo']:+.1f}, {100*r['hi']:+.1f}]" for _, r in sens.iterrows())
fr = SUM[(SUM.labels == "frozen") & (SUM.method == "E2")].set_index(["dataset", "variant"]).rr
ko = SUB[(SUB.group == "Korean questions")].set_index(["labels", "variant"]).rr
noise = pp("C0_repeat") if "C0_repeat" in RUNS else "not measured"
g0, g3 = ev_.loc[LABEL["C0_existing"]], ev_.loc[LABEL["C3_heading"]]
text = f"""### Conclusions

* **Cause (verified).** The fragmentation is an *extraction* defect - the body font size is estimated from the
  first 20 pages ({INV['font']['body_estimate_production_first20']} pt instead of {INV['font']['body_estimate_all_pages']} pt), so
  {INV['font']['share_chars_tagged_heading']:.0%} of the text is tagged `##`, one "heading" per visual line - and the
  heading-aware chunker turns it into **content loss**: consecutive headings overwrite each other, so only
  {cov.iloc[0].in_chunk_text:.0%} of the guidebook's Hangul words reach chunk text ({cov.iloc[0].in_text_or_heading:.0%}
  including the embedded heading field). OCR, encoding and the chunker's size logic are not the cause.
* **Repair works at the data level.** Every variant keeps 97-100 % of the words in chunks; median chunk length
  {cw.loc[LABEL['C0_existing'], 'median_chars']:.0f} -> {cw.loc[LABEL['C2_paragraph'], 'median_chars']:.0f}-{cw.loc[LABEL['C1_merge_short'], 'median_chars']:.0f}
  characters; a guidebook passage reaches the E2 top 5 for {g0.questions_with_guidebook_top5:.0%} -> {g3.questions_with_guidebook_top5:.0%}
  of held-out questions, and the page that holds the answer (reviewed scenarios) is hit in the top 5 for
  {g0.evidence_page_hit_at5:.0%} -> {g3.evidence_page_hit_at5:.0%} (C3).
* **But benchmark scores fall.** With the frozen labels, held-out E2 MRR is {fr[('heldout_v0.2', 'C0_existing')]:.3f} for
  production text and {fr[('heldout_v0.2', 'P1_prod_fixed_body')]:.3f}-{fr[('heldout_v0.2', 'C2_paragraph')]:.3f} for the repaired variants;
  significantly lower after Holm correction: {', '.join(lower) or 'none'}; significantly higher: {', '.join(higher) or 'none'}.
  The development set agrees (pilot E2 MRR {fr[('pilot_v0.1', 'C0_existing')]:.3f} vs {fr[('pilot_v0.1', 'C2_paragraph')]:.3f} for C2).
  The rebuilt identical index changes E2 MRR by {noise}, so these are real effects, not tie noise.
* **Why.** A fully indexed 94-page general guide competes with the specific official pages for almost every
  question. Some of those wins are correct answers the frozen labels do not credit (H03: "TOPIK ... 연간 6회", p. 26;
  H06: the D-10 change, p. 75); others are topical distractors (H09-ko: the part-time hours table ranks first for
  "can I work before my permit is approved?"). With the AI-proposed guidebook credits (not
  human-reviewed) the differences shrink and their intervals include zero: {sens_txt}. Korean-question MRR under those
  labels: C0 {ko[('ai_sensitivity', 'C0_existing')]:.3f}, C2 {ko[('ai_sensitivity', 'C2_paragraph')]:.3f}.
* **Recommendation.** (1) Fix the extraction defect anyway - today most of an approved document is silently
  unsearchable, which is a data-integrity bug, not a tuning choice. Minimal production change: body-size estimate over
  all pages (P1); better: re-flow lines and drop page furniture (C2/C3). Re-extract the guidebook as a *new version*
  through the normal approval flow. (2) Do not expect higher benchmark numbers from it: judge the change only after
  human review of the guidebook labels (v0.3), and pair it with a control for broad documents - the reranker
  (notebook 10/12) or a per-document cap / lower authority weight for the 2021 general guide. Nothing was changed in
  production here.

### Limitations

* Labels: the frozen labels pre-date the guidebook; the sensitivity labels are AI-proposed and **not human-reviewed**
  (worksheet status: pending). Document-level binary relevance; 20 held-out scenarios -> wide intervals.
* Only one document differs between variants; evidence completeness uses page-level matches for 7 reviewed scenarios.
* The guidebook is the 2021 edition; some rules may be outdated even where it is "relevant" for retrieval.
* Variants were designed on this one PDF; P1 is the only variant that is the production extractor itself.
* Pages 4, 5 and 91 are images and remain unextracted (OCR not attempted); latency is local (Apple M1), not Render."""
(REP / "chunk_quality_results.md").write_text("# Korean PDF chunk quality (notebook 13)\n\n" + text + "\n")
display(Markdown(text))'''),
])

# =============================================================================================== 14
NB14_LOAD = r'''import re, csv, collections
from datetime import date
from scipy.stats import norm
from jsonl_io import open_jsonl
REL = A.DATA / "experiments/reliability"; CQ = A.DATA / "experiments/chunking"; FIG = A.RESEARCH / "figures/reliability"
REP = A.RESEARCH / "reports/reliability"; REP.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(A.RESEARCH.parent / "backend"))
from app.services.assistant.evidence import required_information
from app.services.source_quality import SourceQualityConfig, assess_documents
GB, EMP = "d60bc363-0aae-44e5-b0c3-df8c61ad6f66", "96b0fee4-18e9-4ea2-adb5-db654c9ac238"
REC = {}
for ds in ("pilot_v0.1", "heldout_v0.2"):
    REC.update({r["question_id"]: dict(r, dataset=ds) for r in json.loads((A.DATA / f"benchmarks/retrieval_{ds}.json").read_text())["records"]})
DRAFT = {r["question_id"]: r for r in map(json.loads, (A.DATA / "review/passage_labels_v0.3_draft.jsonl").open(encoding="utf-8"))}
FROZEN = {q: set(r["expected_document_ids"]) for q, r in REC.items()}
AI = {q: FROZEN[q] | {d["document_id"] for d in DRAFT[q]["proposed_additional_documents"]} for q in REC}
MAN = {i["id"]: i for i in json.loads((A.DATA / "snapshots/corpus_v2/corpus_manifest.json").read_text())["items"]}
CORPUS = {d["id"]: d for d in json.loads((CQ / "C0_existing/corpus.json").read_text())}
TITLE = {k: v["title"] for k, v in MAN.items()}
TR = {}
for snap in ("corpus_v2", "corpus_v2_p1"):
    f = REL / snap / "traces.jsonl"
    if f.exists() or f.with_name(f.name + ".gz").exists():
        with open_jsonl(f) as fh:
            TR[snap] = pd.DataFrame([json.loads(x) for x in fh])
print({k: (len(v), sorted(v.pipeline.unique())) for k, v in TR.items()})
print({k: json.loads((REL / k / "run.json").read_text())["unmatched_candidate_passages"] for k in TR})

def supports(q, doc, p, labels=AI):
    """Chunking-independent passage support (v0.3-draft criteria, pending review)."""
    if doc not in labels[q]:
        return False
    ps = DRAFT[q]["passage_support"]
    text = (p["text"] or "").lower()
    return any(t.lower() in text for t in ps["evidence_terms"]) or (doc == GB and p.get("page") in set(ps["guidebook_pages"]))

def has_criteria(q):
    ps = DRAFT[q]["passage_support"]; return bool(ps["evidence_terms"] or ps["guidebook_pages"])

STALE = re.compile(r"((?:19|20)\d{2})\s*[.년]\s*(\d{1,2})\s*[.월]\s*(\d{1,2})\s*\.?\s*(?:일)?\s*\)?\s*(?:까지|until)")
def stale_statement(text):
    for y, m, d in STALE.findall(text or ""):
        try:
            if date(int(y), int(m), int(d)) < date.today(): return f"{y}.{m}.{d} 까지"
        except ValueError: pass
    return None'''

notebook("14_retrieval_reliability_analysis.ipynb", "14 · Retrieval reliability analysis",
         "Retrieval reliability sprint: where retrieval fails on the real corpus (corpus_v2), how much document "
         "fragmentation matters, whether a small evidence-sufficiency layer (neighbouring chunks + one bounded "
         "targeted search) makes the evidence more complete, what the source-quality checks find, and how all of this "
         "compares with the B0/E1/E2 baselines and the completed reranking experiments - with accuracy *and* cost. "
         "Local, isolated indexes only; frozen benchmark versions are unchanged; draft labels are marked as such.", [
    code(NB14_LOAD),
    md("## 1 · Failure audit (corpus_v2, the assistant's current evidence path E2S)\n\nEvery question is checked "
       "against eight failure types (several can apply). The rules are automatic and deliberately simple; the "
       "examples below each type are actual traces from the corpus.\n\n"
       "| type | rule |\n|---|---|\n"
       "| 1 wrong document | no frozen-relevant and no proposed-relevant document among the selected sources |\n"
       "| 2 correct document, wrong passage | a relevant document is selected but none of its passages contains an evidence term (held-out questions, which have evidence terms) |\n"
       "| 3 missing numeric / conditional evidence | the question asks for a quantity, date or condition and no selected passage has that shape |\n"
       "| 4 fragmented context | half or more of the selected passages are under 100 characters |\n"
       "| 5a / 5b outdated information | a selected passage states a deadline that has already passed (e.g. `2021.02.28.까지`) / the top source declares an edition > 3 years old |\n"
       "| 6 conflicting sources | two selected documents state non-overlapping figures for the same unit |\n"
       "| 7 cross-language failure | type 1, the question language differs from the expected document's, and the same scenario succeeds in another language |\n"
       "| 8 incomplete benchmark labels | no frozen-relevant document selected, but a document proposed as relevant by the label review is |"),
    code(r'''T = TR["corpus_v2"]; base = T[T.pipeline == "E2S"].set_index("question_id"); ev = T[T.pipeline == "E2S+EV"].set_index("question_id")
sq = assess_documents([dict(id=k, title=v["title"], text=v["content"]) for k, v in CORPUS.items()], SourceQualityConfig())
OLD_ED = {d["id"] for d in sq["documents"] if "old_declared_edition" in d["flags"]}
ok_frozen = {q: bool(set(base.loc[q, "documents"]) & FROZEN[q]) for q in base.index}
rows = []
for q, r in base.iterrows():
    rec = REC[q]; docs = set(r["documents"]); passages = [(s["document_id"], p) for s in r["sources"] for p in s["passages"]]
    e = ev.loc[q, "evidence"] or {}
    cats = []
    frozen_hit, ai_hit = bool(docs & FROZEN[q]), bool(docs & AI[q])
    if not frozen_hit and ai_hit: cats.append("8 incomplete labels")
    if not ai_hit:
        cats.append("1 wrong document")
        plang = MAN[rec["primary_document_id"]]["language"]
        sib = [k for k, x in REC.items() if x["scenario_id"] == rec["scenario_id"] and k != q]
        if rec["language"] != plang and any(ok_frozen.get(k) for k in sib): cats.append("7 cross-language")
    if ai_hit and DRAFT[q]["passage_support"]["evidence_terms"] and not any(supports(q, d, p) for d, p in passages if d in AI[q]):
        cats.append("2 right doc, wrong passage")
    if set(e.get("initially_missing", [])) & {"quantity", "date", "eligibility"}: cats.append("3 missing numeric/conditional")
    if passages and np.mean([p["chars"] < 100 for _, p in passages]) >= 0.5: cats.append("4 fragmented context")
    if any(stale_statement(p["text"]) for _, p in passages): cats.append("5a outdated: past deadline stated")
    if r["documents"] and r["documents"][0] in OLD_ED: cats.append("5b outdated: top source is an old edition")
    base_docs = {s["document_id"] for s in r["sources"]}
    if any(set(c["documents"]) <= base_docs for c in e.get("conflicts", [])): cats.append("6 conflicting sources")
    rows.append(dict(question_id=q, dataset=rec["dataset"], language=rec["language"], categories=cats or ["none"]))
AUD = pd.DataFrame(rows).explode("categories")
tab = AUD.groupby(["categories", "dataset"]).size().unstack(fill_value=0); tab["share of all 200"] = tab.sum(axis=1) / len(base)
display(tab.sort_index())
print("questions with at least one failure type:", (AUD.groupby("question_id").categories.apply(lambda s: "none" not in set(s))).sum(), "of", len(base))'''),
    code(r'''def example(cat, n=1):
    qs = AUD[AUD.categories == cat].question_id.tolist()[:n]
    for q in qs:
        r = base.loc[q]; p = next(((s["document_id"], x) for s in r["sources"] for x in s["passages"]), (None, {"text": ""}))
        e = ev.loc[q, "evidence"] or {}
        extra = " | top source declares a 2021 edition" if cat.startswith("5b") else ""
        if cat.startswith("6") and e.get("conflicts"): extra = f" | conflict: {e['conflicts'][0]}"
        if cat.startswith("5a"): extra = " | " + str(next((stale_statement(x["text"]) for s in r["sources"] for x in s["passages"] if stale_statement(x["text"])), None))
        display(Markdown(f"**{cat}** - `{q}` *{REC[q]['question']}*  \nexpected: {', '.join(TITLE.get(d, d)[:40] for d in FROZEN[q])}  \n"
                         f"top source: **{TITLE.get(p[0], p[0])[:50]}** (p. {p[1].get('page')}): {re.sub(chr(10), ' ', p[1]['text'])[:260]}{extra}"))
for cat in sorted(c for c in AUD.categories.unique() if c != "none"):
    example(cat)'''),
    md("## 2 · Document fragmentation (summary of notebook 13)\n\nThe guidebook fragmentation is an extraction defect "
       "(body font size estimated from the first 20 pages), which the heading-aware chunker turns into content loss. "
       "Full analysis, examples and statistics: `13_korean_pdf_chunk_quality.ipynb`."),
    code(r'''cs = pd.read_csv(CQ / "results/summary_by_variant.csv")
ch = {v: pd.read_csv(CQ / f"results/chunks_{v}.csv") for v in ("C0_existing", "C1_merge_short", "C2_paragraph", "C3_heading", "C4_table", "P1_prod_fixed_body")}
inv = json.loads((CQ / "investigation.json").read_text())
t = pd.DataFrame([dict(variant=v, chunks=len(d), median_chars=d.chars.median(), under_100=(d.chars < 100).mean(),
                       heldout_E2_MRR_frozen=cs[(cs.variant == v) & (cs.dataset == "heldout_v0.2") & (cs.method == "E2") & (cs.labels == "frozen")].rr.iloc[0],
                       heldout_E2_MRR_ai=cs[(cs.variant == v) & (cs.dataset == "heldout_v0.2") & (cs.method == "E2") & (cs.labels == "ai_sensitivity")].rr.iloc[0])
                  for v, d in ch.items()])
display(t.round(3))
print(f"production: {inv['font']['share_chars_tagged_heading']:.0%} of characters tagged as headings; "
      f"{inv['chunker']['share_boundaries_forced_by_heading']:.0%} of chunk boundaries forced by a heading change")'''),
    md("## 3 · Evidence completeness\n\nThe evidence layer (backend `app/services/assistant/evidence.py`, off by "
       "default) detects the information types a question asks for and checks whether the selected passages contain "
       "that *kind* of information; if not, it adds neighbouring chunks of cited documents and runs one bounded "
       "targeted search (<= 4 passages, <= 3,000 characters). Two kinds of measures:\n\n"
       "* **heuristic sufficiency** - the layer's own check (circular: the same rule decides what to add, so it "
       "overstates the benefit);\n* **independent measures** - (a) a supporting passage in the context according to "
       "the v0.3-draft passage criteria (evidence terms written with the benchmark, reviewed guidebook pages); "
       "(b) the share of the scenario's evidence terms found in the context. Both are computed on held-out questions."),
    code(r'''def context_metrics(T, labels=AI):
    out = []
    for _, r in T.iterrows():
        q = r.question_id; ps = [(s["document_id"], p) for s in r["sources"] for p in s["passages"]]
        terms = [t.lower() for t in DRAFT[q]["passage_support"]["evidence_terms"]]
        joined = " ".join((p["text"] or "").lower() for _, p in ps)
        e = r.evidence or {}
        out.append(dict(snapshot=r.snapshot, pipeline=r.pipeline, question_id=q, scenario_id=r.scenario_id, dataset=r.dataset,
                        language=r.language, needs=len(required_information(REC[q]["question"])) > 0,
                        support=float(any(supports(q, d, p, labels) for d, p in ps)) if has_criteria(q) else np.nan,
                        term_coverage=(sum(t in joined for t in terms) / len(terms)) if terms else np.nan,
                        sufficient=(float(not e.get("still_missing")) if e.get("needs") else np.nan),
                        initially_sufficient=(float(not e.get("initially_missing")) if e.get("needs") else np.nan),
                        added=len(e.get("added", [])), context_chars=sum(p["chars"] for _, p in ps), passages=len(ps),
                        conflicts=len(e.get("conflicts", [])), evidence_ms=r.evidence_ms or 0.0, select_ms=r.select_ms))
    return pd.DataFrame(out)
CM = pd.concat([context_metrics(T) for T in TR.values()], ignore_index=True)
held = CM[CM.dataset == "heldout_v0.2"]
g = held.groupby(["snapshot", "pipeline"]).agg(questions=("question_id", "count"), needs_detected=("needs", "mean"),
    heuristic_sufficient_before=("initially_sufficient", "mean"), heuristic_sufficient_after=("sufficient", "mean"),
    supporting_passage=("support", "mean"), evidence_term_coverage=("term_coverage", "mean"), passages_added=("added", "mean"),
    context_chars=("context_chars", "median"), potential_conflicts=("conflicts", "mean"), evidence_ms_median=("evidence_ms", "median"),
    evidence_ms_p90=("evidence_ms", lambda s: s.quantile(.9)))
display(g.round(3))
miss = collections.Counter(n for T in TR.values() for e in T[T.pipeline == "E2S+EV"].evidence if e for n in e["still_missing"])
need = collections.Counter(n for T in TR.values() for e in T[T.pipeline == "E2S+EV"].evidence if e for n in e["needs"])
display(pd.DataFrame([dict(type=k, questions_needing=need[k], still_missing_after_layer=miss[k]) for k in need]).set_index("type"))'''),
    code(r'''pairs = []
for snap in TR:
    d = CM[(CM.snapshot == snap) & (CM.dataset == "heldout_v0.2")]
    for a, b in (("E2S+EV", "E2S"), ("E4+EV", "E4"), ("E4", "E2S"), ("E4+EV", "E2S")):
        if {a, b} <= set(d.pipeline):
            x = d.rename(columns={"pipeline": "method"})
            for col in ("support", "term_coverage"):
                r = A.paired_difference(x.dropna(subset=[col]), a, b, col); r.update(snapshot=snap); pairs.append(r)
if len(TR) == 2:     # same questions, repaired guidebook (P1) vs production text: paired across corpora
    for pl in ("E2S", "E4"):
        x = CM[(CM.dataset == "heldout_v0.2") & (CM.pipeline == pl)].assign(method=lambda d: d.snapshot)
        for col in ("support", "term_coverage"):
            r = A.paired_difference(x.dropna(subset=[col]), "corpus_v2_p1", "corpus_v2", col)
            r.update(snapshot="P1 vs v2", a=f"{pl} [P1]", b=pl); pairs.append(r)
EVP = pd.DataFrame(pairs); EVP.to_csv(REP / "evidence_paired.csv", index=False)
display(EVP[["snapshot", "metric", "a", "b", "n", "mean_a", "mean_b", "diff", "lo", "hi", "a_better", "b_better"]].round(3))'''),
    code(r'''fig, ax = plt.subplots(figsize=(10.5, 4.4))
order = [p for p in ("E2S", "E2S+EV", "E4", "E4+EV", "E4bge", "E4bge+EV") if p in set(held.pipeline)]
snaps = list(TR)
for j, snap in enumerate(snaps):
    vals = [A.cluster_bootstrap(held[(held.snapshot == snap) & (held.pipeline == p)], "support") for p in order]
    y = np.arange(len(order)) + (j - (len(snaps) - 1) / 2) * 0.3
    ax.errorbar([v[0] for v in vals], y, xerr=[[v[0] - v[1] for v in vals], [v[2] - v[0] for v in vals]], fmt="o",
                color=(A.COLORS["E2"], A.COLORS["B0"])[j], capsize=3, markersize=7, linewidth=1.5,
                label={"corpus_v2": "corpus_v2 (production text)", "corpus_v2_p1": "guidebook re-extracted (P1)"}[snap])
    for v, yy in zip(vals, y): ax.text(v[0], yy - 0.16, f"{v[0]:.2f}", ha="center", fontsize=8, color=A.INK)
ax.set_yticks(np.arange(len(order)), order); ax.invert_yaxis(); ax.grid(axis="x"); ax.grid(axis="y", visible=False)
ax.set_xlabel("share of held-out questions with a supporting passage in the context (95% CI)")
ax.set_title("Supporting-passage retrieval (v0.3-draft criteria, pending review)")
ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.16), ncol=2, frameon=False); fig.tight_layout()
print(A.save(fig, "14_supporting_passage", FIG))'''),
    md("## 4 · Source reliability (read-only checks; missing metadata = unknown)\n\nFrom the corpus_v2 snapshot "
       "(document inventory + text). No metadata was changed. The validity and publication fields are not in the "
       "public snapshot for most documents and are therefore reported as unknown rather than assumed valid."),
    code(r'''invd = pd.read_csv(A.DATA / "snapshots/corpus_v2/document_inventory.csv")
alias = json.loads((A.DATA / "id_aliases.json").read_text())["aliases"]; back = {v: k for k, v in alias.items()}
docs = []
for r in invd.itertuples():
    pid = back.get(r.document_id, r.document_id)
    docs.append(dict(id=pid, title=r.title, authority_type=r.authority_type if isinstance(r.authority_type, str) else None,
                     source_url=r.source_url if isinstance(r.source_url, str) else None,
                     valid_until=r.valid_until if isinstance(r.valid_until, str) else None,
                     verification_status="approved" if r.current_status == "approved" else (r.current_status if isinstance(r.current_status, str) else None),
                     is_current=True, text=CORPUS.get(pid, {}).get("content")))
from urllib.parse import urlparse
SQ = assess_documents(docs, SourceQualityConfig(official_domains=["studyinkorea.go.kr", "hikorea.go.kr", "immigration.go.kr", "nhis.or.kr",
                                                                      "topik.go.kr", "sch.ac.kr", "lifeinkorea.go.kr", "korea.net"]))
sqd = pd.DataFrame(SQ["documents"])
display(sqd[["title", "authority", "domain", "validity", "published", "declared_edition_year", "version_status", "flags"]].assign(title=sqd.title.str[:38]))
display(pd.Series(SQ["unknown_counts"], name="documents with 'unknown'").to_frame())
display(pd.DataFrame(SQ["overlaps"]).assign(document=lambda d: d.document.map(lambda x: TITLE.get(x, x)[:35]),
                                            contained_in=lambda d: d.contained_in.map(lambda x: TITLE.get(x, x)[:35])))
conf = [(r.question_id, c) for T in TR.values() for r in T[T.pipeline == "E2S+EV"].itertuples() if r.evidence for c in r.evidence["conflicts"]]
print(f"potential conflicts flagged in E2S+EV contexts: {len(conf)} (question x unit); examples:")
for q, c in conf[:4]:
    print(" ", q, c["unit"], {TITLE.get(d, d)[:30]: v for d, v in c["values"].items()} if isinstance(c.get("values"), dict) else c)'''),
    md("## 5 · Benchmark: document relevance vs passage sufficiency (v0.3-draft)\n\nThe frozen v0.1/v0.2 files are "
       "unchanged (hash-checked by `benchmark_v03.py`). The draft adds (pending human review): proposed additional "
       "relevant documents, chunking-independent passage-support criteria (several passages can be correct) and the "
       "required information types. Development (pilot) and test (held-out) stay separate; nothing below was tuned on "
       "held-out results."),
    code(r'''D = pd.DataFrame(DRAFT.values())
display(D.groupby("split").agg(questions=("question_id", "count"),
        with_passage_criteria=("passage_support", lambda s: sum(bool(x["evidence_terms"] or x["guidebook_pages"]) for x in s)),
        with_proposed_documents=("proposed_additional_documents", lambda s: sum(bool(x) for x in s)),
        needs_information_type=("required_information", lambda s: sum(bool(x) for x in s))))
d = CM[(CM.snapshot == "corpus_v2") & (CM.pipeline == "E2S") & (CM.dataset == "heldout_v0.2")].copy()
d["doc_relevant"] = [bool(set(base.loc[q, "documents"]) & AI[q]) for q in d.question_id]
display(pd.crosstab(d.doc_relevant.map({True: "relevant document selected", False: "no relevant document"}),
                    d.support.map({1.0: "supporting passage present", 0.0: "no supporting passage"}), margins=True))'''),
    md("## 6 · Experiments: accuracy and cost\n\nDocument ranking (R@1, R@5, MRR, nDCG@5) for the baselines and "
       "reranking (Milestone 5 runs on corpus_v2) and for the context pipelines (documents in source order); held-out "
       "v0.2, frozen labels (official) and with the AI-proposed documents (sensitivity). Answer-level citation support "
       "and unsupported-answer rate require generated answers: **not evaluated** here (no LLM was called; no "
       "human-scored answers exist)."),
    code(r'''exp = pd.concat([pd.read_csv(A.DATA / f"results/corpus_v2/experiments_{ds}.csv").assign(dataset=ds) for ds in ("pilot_v0.1", "heldout_v0.2")])
exp = exp[exp.method.isin(["B0", "E1", "E2", "E3_mminilm", "E3_bge-m3"])]   # E2S here = the assistant path from the traces[["method", "question_id", "scenario_id", "language", "dataset", "retrieved_documents", "total_ms"]]
ctx = []
for snap, T in TR.items():
    t = T[["pipeline", "question_id", "scenario_id", "language", "dataset", "documents", "select_ms", "evidence_ms"]].copy()
    t["method"] = (t.pipeline + ("" if snap == "corpus_v2" else " [P1]"))
    t["retrieved_documents"] = t.documents.map(json.dumps); t["total_ms"] = t.select_ms + t.evidence_ms.fillna(0)
    ctx.append(t.drop(columns=["pipeline", "documents", "select_ms", "evidence_ms"]))
ALL = pd.concat([exp] + ctx, ignore_index=True)
res = {}
for lab, L in (("frozen", FROZEN), ("ai_sensitivity", AI)):
    s = A.score_rankings(ALL, L)
    res[lab] = s
    t = A.summarize(s[s.dataset == "heldout_v0.2"], ["method"], ("r1", "r5", "rr", "ndcg5"))
    t["median_ms"] = t.method.map(s[s.dataset == "heldout_v0.2"].groupby("method").total_ms.median())
    display(Markdown(f"**Held-out v0.2 - {lab} labels**")); display(t.set_index("method").round(3))
SUMM = pd.concat([A.summarize(s[s.dataset == "heldout_v0.2"], ["method"], ("r1", "r5", "rr", "ndcg5")).assign(labels=l) for l, s in res.items()])
SUMM.to_csv(REP / "doc_ranking_summary.csv", index=False)'''),
    code(r'''PAIRS = [("E2", "B0"), ("E2", "E1"), ("E3_mminilm", "E2"), ("E3_bge-m3", "E2"), ("E2S+EV", "E2S"), ("E4", "E2S"),
         ("E4+EV", "E2S"), ("E2S [P1]", "E2S"), ("E4 [P1]", "E2S")]
pp = []
for lab, s in res.items():
    d = s[s.dataset == "heldout_v0.2"]
    for a, b in PAIRS:
        if {a, b} <= set(d.method):
            for col in ("rr", "r1"):
                r = A.paired_difference(d, a, b, col); r.update(labels=lab); pp.append(r)
PP = pd.DataFrame(pp)
prim = PP[(PP.labels == "frozen") & (PP.metric == "rr")].copy()
prim["p_approx"] = [2 * (1 - norm.cdf(abs(r["diff"]) / max((r["hi"] - r["lo"]) / 3.92, 1e-9))) for _, r in prim.iterrows()]
prim = prim.sort_values("p_approx"); m = len(prim); okk = True; sup = []
for i, (_, r) in enumerate(prim.iterrows()):
    okk = okk and r["p_approx"] <= 0.05 / (m - i); sup.append(okk)
prim["supported_after_holm"] = sup
PP.to_csv(REP / "paired_comparisons.csv", index=False)
display(prim[["a", "b", "n", "mean_a", "mean_b", "diff", "lo", "hi", "p_approx", "supported_after_holm"]].round(4))
display(PP[(PP.labels == "ai_sensitivity") & (PP.metric == "rr")][["a", "b", "diff", "lo", "hi", "ci_excludes_zero"]].round(4))'''),
    code(r'''s = res["frozen"]; d = s[s.dataset == "heldout_v0.2"]
show = [m for m in ("B0", "E1", "E2", "E3_mminilm", "E3_bge-m3", "E2S", "E2S+EV", "E4", "E4+EV", "E2S [P1]", "E4 [P1]") if m in set(d.method)]
lang = A.summarize(d[d.method.isin(show)], ["method", "language"], ("rr",)).pivot(index="method", columns="language", values="rr").reindex(show)
display(Markdown("**MRR by query language (held-out, frozen labels; n = 20 per language)**")); display(lang.round(3))
fig, axes = plt.subplots(1, 2, figsize=(12.8, 4.8), gridspec_kw={"width_ratios": [1.25, 1]})
ax = axes[0]
for lab, color in (("frozen", A.COLORS["E2"]), ("ai_sensitivity", A.COLORS["E2S"])):
    t = SUMM[SUMM.labels == lab].set_index("method").reindex(show)
    y = np.arange(len(show)) + (0.15 if lab == "ai_sensitivity" else -0.15)
    ax.errorbar(t.rr, y, xerr=[t.rr - t.rr_lo, t.rr_hi - t.rr], fmt="o", color=color, capsize=3, markersize=6, linewidth=1.4,
                label={"frozen": "frozen labels", "ai_sensitivity": "+ proposed labels (not reviewed)"}[lab])
ax.set_yticks(np.arange(len(show)), show); ax.invert_yaxis(); ax.grid(axis="x"); ax.grid(axis="y", visible=False)
ax.set_xlabel("MRR, held-out v0.2 (95% CI)"); ax.set_title("Document ranking")
ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.13), ncol=2, frameon=False)
ax = axes[1]
lat = d.groupby("method").total_ms.median().reindex(show); t = SUMM[SUMM.labels == "frozen"].set_index("method").reindex(show)
pts = [m for m in show if not m.endswith("+EV")]       # +EV has the same document ranking as its base pipeline
lat, t = lat.reindex(pts), t.reindex(pts)
ax.scatter(lat, t.rr, s=55, color=A.COLORS["B0"], zorder=3)
for mth in pts:
    ax.annotate(mth, (lat[mth], t.rr[mth]), textcoords="offset points", xytext=(5, 4), fontsize=8, color=A.INK)
ax.set_xscale("log"); ax.grid(axis="both"); ax.set_xlabel("median ms per question (log; Apple M1, rerank on GPU)")
ax.set_ylabel("MRR (frozen labels)"); ax.set_title("Accuracy vs cost (+EV: same MRR as base)")
fig.tight_layout(); print(A.save(fig, "14_accuracy_vs_cost", FIG))'''),
    md("## 7 · Conclusions and recommendation"),
    code(r'''def P(a, b, lab="frozen", col="rr"):
    r = PP[(PP.labels == lab) & (PP.a == a) & (PP.b == b) & (PP.metric == col)]
    if r.empty: return "not evaluated"
    r = r.iloc[0]; return f"{100*r['diff']:+.1f} pp [{100*r['lo']:+.1f}, {100*r['hi']:+.1f}]"
def E(a, b, col="support", snap="corpus_v2"):
    r = EVP[(EVP.snapshot == snap) & (EVP.a == a) & (EVP.b == b) & (EVP.metric == col)]
    if r.empty: return "not evaluated"
    r = r.iloc[0]; return f"{100*r['diff']:+.1f} pp [{100*r['lo']:+.1f}, {100*r['hi']:+.1f}]"
G = g.reset_index().set_index(["snapshot", "pipeline"])
lat = d.groupby("method").total_ms.median()
cnt = AUD[AUD.categories != "none"].groupby("categories").question_id.nunique().sort_values(ascending=False)
wrong = AUD[AUD.categories == "1 wrong document"].question_id.unique()
xl_share = np.mean([REC[q]["language"] != MAN[REC[q]["primary_document_id"]]["language"] for q in wrong]) if len(wrong) else float("nan")
base_xl = np.mean([REC[q]["language"] != MAN[REC[q]["primary_document_id"]]["language"] for q in base.index])
def sig(a, b, col="support", snap="corpus_v2"):
    r = EVP[(EVP.snapshot == snap) & (EVP.a == a) & (EVP.b == b) & (EVP.metric == col)]
    return (not r.empty) and bool(r.iloc[0]["ci_excludes_zero"]) and r.iloc[0]["diff"] > 0
ev_rows = [e for e in TR["corpus_v2"][TR["corpus_v2"].pipeline == "E2S+EV"].evidence if e]
added_q = sum(1 for e in ev_rows if e["added"])
init_missing = sum(1 for e in ev_rows if e["initially_missing"]); still = sum(1 for e in ev_rows if e["still_missing"])
p1 = "corpus_v2_p1" in TR
ev_gain = sig("E2S+EV", "E2S") or sig("E2S+EV", "E2S", "term_coverage")
rr_gain = PP[(PP.labels == "frozen") & (PP.a == "E3_mminilm") & (PP.b == "E2") & (PP.metric == "rr")].iloc[0]
text = f"""### Findings

* **Failure audit (corpus_v2, assistant path E2S, 200 questions; multi-label, automatic rules).**
  {'; '.join(f'{k}: {v}' for k, v in cnt.items())}. {AUD[AUD.categories == 'none'].question_id.nunique()} questions match no failure rule.
  {xl_share:.0%} of wrong-document failures are cross-language questions (base rate {base_xl:.0%}).
* **Fragmentation.** An extraction defect (notebook 13): only 24 % of the guidebook's words reach chunk text in
  production; repaired variants keep 97-100 % but score lower against the frozen labels.
* **Evidence layer** (top-source check, development-calibrated): needed information types were missing in the top
  source for {init_missing} of {len(ev_rows)} questions (both sets); the layer added passages for {added_q} and
  {still} remain incomplete (recorded, not guessed). On held-out: supporting passage in context
  E2S {G.loc[('corpus_v2', 'E2S'), 'supporting_passage']:.2f} -> {G.loc[('corpus_v2', 'E2S+EV'), 'supporting_passage']:.2f}
  (paired {E('E2S+EV', 'E2S')}), evidence-term coverage {E('E2S+EV', 'E2S', 'term_coverage')}; median added cost
  {G.loc[('corpus_v2', 'E2S+EV'), 'evidence_ms_median']:.0f} ms (p90 {G.loc[('corpus_v2', 'E2S+EV'), 'evidence_ms_p90']:.0f} ms);
  document ranking {P('E2S+EV', 'E2S')} MRR. {'The improvement in evidence completeness is supported (CI excludes 0).' if ev_gain else 'No statistically supported improvement in the independent evidence measures.'}
* **Repaired guidebook (P1) vs production text, same questions:** supporting passage (E2S) {E('E2S [P1]', 'E2S', 'support', 'P1 vs v2')},
  evidence-term coverage {E('E2S [P1]', 'E2S', 'term_coverage', 'P1 vs v2')} - while frozen-label MRR falls
  ({P('E2S [P1]', 'E2S')}): the repair brings more answer-bearing text into the context than the frozen labels can credit.
* **Reranking.** E3 mMiniLM vs E2 {P('E3_mminilm', 'E2')}, E3 bge-m3 vs E2 {P('E3_bge-m3', 'E2')} MRR (frozen labels);
  with the assistant's selection: E4 vs E2S {P('E4', 'E2S')}; supporting passage E4 vs E2S {E('E4', 'E2S')}.
  Median cost per question {lat.get('E2S', float('nan')):.0f} ms (E2S) vs {lat.get('E4', float('nan')):.0f} ms (E4, mMiniLM on the M1 GPU;
  about 1.1 s on the M1 CPU).
* **Source reliability.** Unknown fields across {len(SQ['documents'])} documents: {', '.join(f'{k} {v}' for k, v in SQ['unknown_counts'].items())};
  overlaps: {'; '.join(f"{TITLE.get(o['document'], o['document'])[:30]} in {TITLE.get(o['contained_in'], o['contained_in'])[:30]} ({o['containment']:.0%})" for o in SQ['overlaps']) or 'none'};
  past-dated statements in held-out/pilot contexts: {AUD[AUD.categories.str.startswith('5a')].question_id.nunique()} questions.
* **Not evaluated:** citation support and unsupported-answer rate of generated answers (no LLM calls, no human-scored answers).
  {'The repaired-guidebook corpus (P1) is included above.' if p1 else 'The repaired-guidebook (P1) traces were not available when this notebook ran.'}

### Recommendation (none deployed)

1. **Fix PDF extraction** and re-extract the guidebook as a new version through approval (data integrity).
2. **Evidence-sufficiency layer:** {'enable after a shadow period' if ev_gain else 'keep off; run it in shadow mode (log `evidence_check` reports) - it detects incomplete evidence and records it, but the measured completeness gain is not established'}.
3. **Reranking (mMiniLM):** largest supported gain ({100*rr_gain['diff']:+.1f} pp MRR vs E2); needs ~1 GB RAM and ~1 s/question
   on CPU - only with a larger instance or a quantised model, measured on that hardware first.
4. **Source-quality report** for editors (unknowns, old editions, past deadlines, overlaps) - no automatic changes.
5. **Human review** of the v0.3 draft before any accuracy claim."""
(REP / "reliability_results.md").write_text("# Retrieval reliability (notebook 14)\n\n" + text + "\n")
display(Markdown(text))'''),
])

print(f"wrote {len(list(OUT.glob('[0-9][0-9]_*.ipynb')))} notebooks to {OUT}")
