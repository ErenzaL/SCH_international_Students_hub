"""Retrieval error analysis (local, read-only) -> data/results/error_analysis_<dataset>.jsonl

For every question and method (B0, E1, E2) records the top passages, the rank of the expected document, a deep
dense-retrieval probe without the similarity threshold (is the expected document filtered out?), passage-level
evidence ranks (held-out: chunks containing the scenario's evidence terms) and rule-based failure categories.

    cd backend && .venv/bin/python ../research/scripts/run_error_analysis.py
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))
os.environ.setdefault("EMBEDDING_PROVIDER", "e5_onnx")
sys.path.insert(0, str(ROOT / "research/scripts"))
from snapshot_paths import CORPUS, RESULTS  # noqa: E402
MODES = {"B0": "vector", "E1": "hybrid_legacy", "E2": "hybrid"}
LONG_DOC_CHUNKS = 100

# category -> (rule description, possible improvement); order = priority for the primary category
CATEGORIES = {
    "below_similarity_threshold": ("expected document's best dense similarity < 0.80, so dense-only hits are filtered",
                                   "lower/learn the threshold per language; rely on reranking of a wider pool"),
    "visa_code_confusion": ("question names a visa code; the top passage is about a different code",
                            "stronger code-mismatch handling; code-aware reranking"),
    "same_script_distractor": ("top document shares the question's script/language while the expected document is in "
                               "another language", "cross-lingual reranker; query translation (ko/en variants)"),
    "long_document_dominance": (f"top document is a long multi-topic guide (>= {LONG_DOC_CHUNKS} chunks) and is not the "
                                "expected primary source", "per-document caps; section-level titles; reranking"),
    "cross_language_miss": ("question language differs from the expected document and it is not in the top 5",
                            "multilingual reranker; translated query variants; glossary coverage"),
    "keyword_ambiguity": ("top passage wins on keyword coverage (>= 0.5) but is the wrong document",
                          "down-weight keyword leg for generic terms; reranking"),
    "competing_topical_document": ("top document is in the same category as the expected one (topically adjacent)",
                                   "reranking; better section granularity; review labels"),
    "possible_label_gap": ("the top passage contains the scenario's evidence terms but its document is not labelled",
                           "human label review (may be a correct answer)"),
    "other": ("no rule matched", "manual inspection"),
}


def main() -> None:
    import eval_retrieval_benchmark as ev
    from app.services.retrieval.query_analysis import code_matches, find_codes, normalize_codes

    corpus = json.loads(CORPUS.read_text())
    svc, l2p, _ = ev.build_index(corpus, 0.80)
    meta = {d["id"]: d for d in corpus}
    chunk_count: dict[str, int] = {}
    for c in svc.store.select("document_chunks")[0]:
        chunk_count[c["version_id"]] = chunk_count.get(c["version_id"], 0) + 1
    docs = {d["id"]: d for d in svc.store.select("source_documents")[0]}
    doc_chunks = {l2p[d]: chunk_count.get(docs[d]["current_version_id"], 0) for d in l2p}

    def passage(h: dict) -> dict:
        pid = l2p.get(h["document_id"])
        return dict(document_id=pid, title=(meta.get(pid) or {}).get("title", "")[:70], heading=(h.get("heading") or "")[:70],
                    language=(meta.get(pid) or {}).get("language"), similarity=h.get("similarity"),
                    keyword_rank=h.get("keyword_rank"), lexical_coverage=h.get("lexical_coverage"),
                    code_mismatch=h.get("code_mismatch"), text=re.sub(r"\s+", " ", h.get("passage") or "")[:300])

    for ds in ("pilot_v0.1", "heldout_v0.2"):
        bench = json.loads((ROOT / f"research/data/benchmarks/retrieval_{ds}.json").read_text())
        out = (RESULTS / f"error_analysis_{ds}.jsonl").open("w", encoding="utf-8")
        for r in bench["records"]:
            q, expected = r["question"], set(r["expected_document_ids"])
            primary = r["primary_document_id"]
            terms = [t.lower() for t in r.get("evidence_terms") or []]
            # deep dense probe without threshold
            svc.retrieval.settings.retrieval_min_similarity = 0.0
            deep = svc.retrieval.search(q, top_k=20, mode="vector")["results"]
            svc.retrieval.settings.retrieval_min_similarity = 0.80
            best_sim = max((h["similarity"] for h in deep if l2p.get(h["document_id"]) in expected), default=None)
            deep_docs = list(dict.fromkeys(l2p.get(h["document_id"]) for h in deep))
            deep_rank = next((i + 1 for i, d in enumerate(deep_docs) if d in expected), None)
            # passage-level evidence in a wide E2 pool
            pool = svc.retrieval.search(q, top_k=20, mode="hybrid", max_per_document=20)["results"]
            ev_rank = next((i + 1 for i, h in enumerate(pool) if terms and l2p.get(h["document_id"]) in expected
                            and any(t in (h.get("passage") or "").lower() for t in terms)), None) if terms else None
            for method, mode in MODES.items():
                res = svc.retrieval.search(q, top_k=10, mode=mode)["results"]
                ranked = list(dict.fromkeys(l2p.get(h["document_id"]) for h in res))
                rank = next((i + 1 for i, d in enumerate(ranked) if d in expected), None)
                top = [passage(h) for h in res[:3]]
                cats = []
                if rank != 1:
                    t1 = top[0] if top else {}
                    qlang = r["language"]
                    plang = (meta.get(primary) or {}).get("language")
                    asked = find_codes(normalize_codes(q))
                    t1codes = find_codes(normalize_codes(t1.get("text", ""))) if t1 else set()
                    if best_sim is not None and best_sim < 0.80 and method == "B0":
                        cats.append("below_similarity_threshold")
                    if asked and t1codes and not code_matches(asked, t1codes):
                        cats.append("visa_code_confusion")
                    script = lambda lang: "ko" if lang == "ko" else ("zh" if lang == "zh-CN" else "latin")  # noqa: E731
                    if t1 and script(t1.get("language")) == script(qlang) and script(plang) != script(qlang):
                        cats.append("same_script_distractor")
                    if t1 and doc_chunks.get(t1.get("document_id"), 0) >= LONG_DOC_CHUNKS and t1.get("document_id") != primary \
                            and doc_chunks.get(primary, 0) < LONG_DOC_CHUNKS:
                        cats.append("long_document_dominance")
                    if qlang != plang and (rank is None or rank > 5):
                        cats.append("cross_language_miss")
                    if t1 and (t1.get("lexical_coverage") or 0) >= 0.5:
                        cats.append("keyword_ambiguity")
                    if t1 and (meta.get(t1.get("document_id")) or {}).get("category") == (meta.get(primary) or {}).get("category"):
                        cats.append("competing_topical_document")
                    if t1 and terms and any(t in t1.get("text", "").lower() for t in terms):
                        cats.append("possible_label_gap")
                    if not cats:
                        cats.append("other")
                    primary_cat = next(c for c in CATEGORIES if c in cats)
                else:
                    primary_cat = None
                out.write(json.dumps(dict(
                    dataset_version=r["dataset_version"], question_id=r["question_id"], scenario_id=r["scenario_id"],
                    language=r["language"], category=r["category"], difficulty=r["difficulty"], question=q, method=method,
                    expected=[(meta.get(e) or {}).get("title", e)[:60] for e in r["expected_document_ids"]],
                    primary_title=(meta.get(primary) or {}).get("title", "")[:60],
                    primary_language=(meta.get(primary) or {}).get("language"), primary_chunks=doc_chunks.get(primary),
                    rank=rank, top3=top, deep_dense_rank_no_threshold=deep_rank, expected_best_dense_similarity=best_sim,
                    evidence_passage_rank_e2_pool=ev_rank, categories=cats, primary_category=primary_cat,
                    improvement=CATEGORIES[primary_cat][1] if primary_cat else None), ensure_ascii=False) + "\n")
        out.close()
        print("wrote", out.name)
    (RESULTS / "error_taxonomy_definitions.json").write_text(
        json.dumps({k: {"rule": v[0], "possible_improvement": v[1]} for k, v in CATEGORIES.items()}, indent=1))


if __name__ == "__main__":
    main()
