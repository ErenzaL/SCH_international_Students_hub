"""Phase 5: end-to-end answers for pipelines A / B / C with the SAME LLM, prompt, corpus snapshot and context budget.

  A  deployed retrieval + context selection (git main, run with --backend <worktree>/backend)
  B  improved hybrid retrieval + evidence selection (working tree, no reranker)
  C  B + mMiniLM INT8 ONNX reranking over the top 20 + order-preserving selection

Every case is the full assistant path (`AssistantEngine.respond`: query rewriting, retrieval, selection, generation,
answer validation, citations) on a local in-memory index of corpus_v2. Synthetic benchmark questions only; no student
data; nothing is stored in or read from production. Every case is recorded, including failed generations.

Automatic, reference-based measures (computed here): generation success, language consistency, citation accuracy
(cited documents that are relevant under the frozen labels, and under frozen + AI-proposed labels), evidence
completeness (share of the scenario's evidence terms that appear in the answer), response latency.
Correctness and faithfulness are NOT scored automatically: `--annotation` writes a blinded worksheet (pipeline hidden,
order shuffled) for human reviewers using configs/answer_rubric_v1.md. Any LLM-as-judge score must be reported
separately and labelled AI-drafted.

    # plumbing check without any LLM call (template answers):
    cd backend && .venv/bin/python ../research/scripts/run_answer_abc.py B C --dry-run --limit 5
    # real run - uses the owner's Gemini quota; LLM_PROVIDER / LLM_API_KEY must be set in the environment:
    cd backend && .venv/bin/python ../research/scripts/run_answer_abc.py B C --pause 8
    cd <worktree>/backend && <repo>/backend/.venv/bin/python <repo>/research/scripts/run_answer_abc.py A --backend .
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "research/data/experiments/answers_abc/corpus_v2"
CORPUS = ROOT / "research/data/experiments/chunking/C0_existing/corpus.json"
MODELS = ROOT / "research/models/mminilm"
BUDGET = dict(assistant_max_sources=4, assistant_max_passages_per_source=3, assistant_context_chars=9000)


def records(limit: int | None) -> list[dict]:
    recs = json.loads((ROOT / "research/data/benchmarks/retrieval_heldout_v0.2.json").read_text())["records"]
    if limit:   # whole scenarios (all 5 languages) so per-language comparisons stay balanced
        scen = sorted({r["scenario_id"] for r in recs})[: max(1, limit // 5)]
        recs = [r for r in recs if r["scenario_id"] in scen]
    return recs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pipelines", nargs="+", choices=["A", "B", "C"])
    ap.add_argument("--backend", default=str(ROOT / "backend"))
    ap.add_argument("--dry-run", action="store_true", help="no LLM: template answers (checks the plumbing)")
    ap.add_argument("--limit", type=int, default=None, help="number of questions (rounded to whole scenarios)")
    ap.add_argument("--pause", type=float, default=0.0, help="seconds between questions (provider rate limits)")
    ap.add_argument("--annotation", action="store_true", help="write the blinded human-review worksheet and exit")
    a = ap.parse_args()
    if a.annotation:
        return write_annotation()
    sys.path.insert(0, str(Path(a.backend).resolve()))
    sys.path.insert(1, str(ROOT / "scripts"))
    sys.path.insert(2, str(ROOT / "research/scripts"))
    os.environ.setdefault("EMBEDDING_PROVIDER", "e5_onnx")
    import eval_retrieval_benchmark as ev   # note: it puts the repository backend first on sys.path

    backend = str(Path(a.backend).resolve())
    sys.path[:] = [backend] + [x for x in sys.path if Path(x).resolve() != (ROOT / "backend").resolve() or backend == str((ROOT / "backend").resolve())]
    from run_answer_eval import language_of

    from app.core.config import Settings
    from app.services.llm.base import NullLLMProvider, build_llm_from_settings

    settings = Settings()
    llm = NullLLMProvider() if a.dry_run else build_llm_from_settings(settings)
    if not a.dry_run and not llm.enabled:
        raise SystemExit("No LLM configured (set LLM_PROVIDER and LLM_API_KEY), or use --dry-run.")
    svc, l2p, info = ev.build_index(json.loads(CORPUS.read_text()), 0.80)
    eng = svc.conversations.engine
    eng.llm = llm
    eng.budget = lambda: True
    for k, v in BUDGET.items():
        setattr(eng.settings, k, v)
    prompt_sha = hashlib.sha256(eng.prompt.text.encode()).hexdigest()[:16]
    draft = {json.loads(x)["question_id"]: json.loads(x) for x in
             (ROOT / "research/data/review/passage_labels_v0.3_draft.jsonl").open(encoding="utf-8")}
    OUT.mkdir(parents=True, exist_ok=True)
    tag = "dryrun_" if a.dry_run else ""
    for name in a.pipelines:
        if name == "C":
            from app.services.retrieval.rerank import OnnxCrossEncoderReranker

            eng.reranker = OnnxCrossEncoderReranker(str(MODELS / "model_int8.onnx"), str(MODELS / "sentencepiece.bpe.model"))
            eng.settings.rerank_top_n = 20
        elif hasattr(eng, "reranker"):
            from app.services.retrieval.rerank import NoReranker

            eng.reranker = NoReranker()
        with (OUT / f"{tag}{name}.jsonl").open("w", encoding="utf-8") as f:
            for r in records(a.limit):
                t0 = time.perf_counter()
                try:
                    out, err = eng.respond(r["question"], language=r["language"]), None
                except Exception as exc:  # noqa: BLE001 - recorded, never dropped
                    out, err = {}, type(exc).__name__
                wall = (time.perf_counter() - t0) * 1000
                gen = out.get("generation") or {}
                answer = out.get("answer") or ""
                cited = [c for c in out.get("citations", []) if c.get("cited")]
                cited_ids = [l2p.get(c.get("document_id"), c.get("document_id")) for c in cited]
                frozen = set(r["expected_document_ids"])
                ai = frozen | {d["document_id"] for d in draft[r["question_id"]]["proposed_additional_documents"]}
                terms = [t.lower() for t in draft[r["question_id"]]["passage_support"]["evidence_terms"]]
                llm_ok = gen.get("answer_generation") == "llm"
                lang = language_of(answer) if llm_ok else None
                row = dict(pipeline=name, question_id=r["question_id"], scenario_id=r["scenario_id"], language=r["language"],
                           question=r["question"], error=err, answer_generation=gen.get("answer_generation"),
                           fallback_reason=gen.get("fallback_reason"), model=gen.get("model"), provider=gen.get("provider"),
                           prompt_version=eng.prompt.version, prompt_sha16=prompt_sha, wall_latency_ms=round(wall),
                           engine_latency_ms=out.get("latency_ms"), llm_latency_ms=gen.get("llm_latency_ms"),
                           input_tokens=gen.get("input_tokens"), output_tokens=gen.get("output_tokens"),
                           evidence_level=out.get("evidence"), retrieval=out.get("retrieval"), answer=answer,
                           cited_document_ids=cited_ids,
                           context_document_ids=[l2p.get(c.get("document_id"), c.get("document_id")) for c in out.get("citations", [])],
                           generation_success=llm_ok,
                           language_consistent=(lang == r["language"]) if lang else None,
                           citation_precision_frozen=(sum(c in frozen for c in cited_ids) / len(cited_ids)) if (llm_ok and cited_ids) else None,
                           citation_precision_ai=(sum(c in ai for c in cited_ids) / len(cited_ids)) if (llm_ok and cited_ids) else None,
                           citation_hit_frozen=any(c in frozen for c in cited_ids) if llm_ok else None,
                           evidence_completeness=(sum(t in answer.lower() for t in terms) / len(terms)) if (llm_ok and terms) else None)
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                f.flush()
                print(name, r["question_id"], row["answer_generation"], row["wall_latency_ms"], "ms", flush=True)
                if a.pause:
                    time.sleep(a.pause)
    (OUT / f"{tag}run_{'_'.join(a.pipelines)}.json").write_text(json.dumps(dict(
        backend="working tree backend" if Path(a.backend).resolve() == (ROOT / "backend").resolve() else "other backend tree (e.g. a git worktree of main)", pipelines=a.pipelines, dry_run=a.dry_run, budget=BUDGET, prompt_sha16=prompt_sha,
        llm=getattr(llm, "model_id", None) or type(llm).__name__, index=info, questions=len(records(a.limit))), indent=1))


def write_annotation() -> None:
    """Blinded worksheet for human review (rubric v1): pipeline hidden behind a random answer id, rows shuffled."""
    rows = []
    for f in sorted(OUT.glob("[ABC].jsonl")):
        rows += [json.loads(x) for x in f.open(encoding="utf-8")]
    rng = random.Random(20261123)
    rng.shuffle(rows)
    key = {}
    with (OUT / "annotation_blinded.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["answer_id", "question_id", "language", "question", "answer", "cited_document_ids", "correctness_0_2",
                    "relevance_0_2", "faithfulness_0_2", "citation_accuracy_0_2", "unsupported_claims", "reviewer", "notes"])
        for i, r in enumerate(rows):
            aid = f"ans-{i:04d}"
            key[aid] = r["pipeline"]
            w.writerow([aid, r["question_id"], r["language"], r["question"], r["answer"], ";".join(r["cited_document_ids"]),
                        "", "", "", "", "", "", ""])
    (OUT / "annotation_key.json").write_text(json.dumps(key, indent=1))   # keep away from reviewers until scoring is done
    print(f"{len(rows)} answers -> {OUT / 'annotation_blinded.csv'} (key: annotation_key.json)")


if __name__ == "__main__":
    main()
