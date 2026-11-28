#!/usr/bin/env python3
"""RAG v2 answer evaluation: the full assistant turn (rewrite → retrieval → selection → gate → generation → checks).

    backend/.venv/bin/python scripts/rag_v2/answer_eval.py --split dev,val,neg --tag A1            # local Qwen proxy
    backend/.venv/bin/python scripts/rag_v2/answer_eval.py --split test --final --tag A9           # final run only
    backend/.venv/bin/python scripts/rag_v2/answer_eval.py --provider gemini --split test --final --max-questions 40 \
        --prices "gemini-3.6-flash=IN/OUT,gemini-3.5-flash-lite=IN/OUT" --confirm-paid-run      # NEEDS OWNER APPROVAL

Provider `ollama` (default): a local model on loopback Ollama (no data leaves the server, no cost) answers AND
rewrites. It is a PROXY: results describe the pipeline with that model, never Gemini's quality.
Provider `gemini`: refuses to start without LLM_API_KEY in the environment, --max-questions, --prices and
--confirm-paid-run; prints the token-based cost estimate first. The key is read from the environment only and never
written anywhere.

Deterministic metrics per question (no LLM judge):
  abstained        evidence class none / unavailable (or the gate answered)  — expected for unanswerable questions
  figure_recall    share of the gold figures (numbers >= 2 digits found in BOTH the gold quotes and the reference
                   answer) that appear in the answer (TEST only; None when the need has no figure)
  cited_grade2     share of cited sources that are grade-2 documents;  cited_relevant: grade >= 1
  cited_has_quote  a cited source's passages contain a gold quote (TEST)
  invented_figure  an unanswerable / not-in-sources question answered with a figure (>= 2 digits)
  wrong_language   the engine's own language check on the final answer
--no-rag runs the same model closed-book on the same questions (fair baseline: real-corpus questions, no sources).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from configs import resolve  # noqa: E402
from lib import CORPUS, RESULTS, ROOT, git_rev, load_split, norm, sha256_file, summarize  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "backend"))

CLOSED_BOOK = ("You are an assistant for international students at Soonchunhyang University (SCH) in Korea. Answer the "
               "student's question in the student's language. If you do not know the answer or it depends on SCH-specific "
               "information you do not have, say so instead of guessing.")
# heuristic only (reported separately, never used for the deterministic metrics): phrases that say "not known / not found"
_REFUSAL = re.compile(r"(not (available|found|included|mentioned|stated)|(do not|don't) have (specific )?information|no (approved )?information|"
                      r"cannot (find|confirm)|could not (find|verify)|정보가 (없|포함되어 있지 않|확인되지 않)|찾을 수 없|확인할 수 없|"
                      r"tidak (ada|memiliki|dapat ditemukan|tersedia)|không (có|tìm thấy) thông tin|không được (đề cập|nêu)|"
                      r"没有(相关|具体)?(的)?信息|未(提及|找到|提供)|无法(确认|找到))", re.I)
_NUM = re.compile(r"(?<![0-9A-Za-z.])(\d{1,3}(?:[,.]\d{3})+|\d+(?:[.,]\d{1,2}(?!\d)|\.\d+)?)(?![0-9A-Za-z])")


def figures(text: str) -> set[str]:
    from app.services.assistant.engine import _norm_number
    return {x for x in (_norm_number(n) for n in _NUM.findall(text or "")) if len(x.replace(".", "")) >= 2}


def gold_figures(r: dict[str, Any], reference: str) -> set[str]:
    quoted = set().union(*(figures(q["quote"]) for q in r["quotes"])) if r["quotes"] else set()
    return quoted & figures(reference)


def make_llm(a: argparse.Namespace):  # type: ignore[no-untyped-def]
    if a.provider == "ollama":
        from app.services.llm.ollama import OllamaProvider
        return OllamaProvider(a.model, temperature=0.0, seed=7, keep_alive="30m", request_timeout=180.0, deadline=240.0)
    if not os.environ.get("LLM_API_KEY"):
        raise SystemExit("gemini: LLM_API_KEY is not set (this server has no Gemini key; the owner runs this)")
    if not (a.max_questions and a.prices and a.confirm_paid_run):
        raise SystemExit("gemini is a PAID run: needs --max-questions, --prices and --confirm-paid-run (owner approval)")
    from app.core.config import Settings
    from app.services.llm.base import build_llm_from_settings
    return build_llm_from_settings(Settings(_env_file=None, llm_provider="gemini", llm_api_key=os.environ["LLM_API_KEY"]))


def estimate(a: argparse.Namespace, n: int) -> None:
    """Token-based estimate from the local proxy run A1 (prompt sizes do not depend on the answer model)."""
    prev = RESULTS / "A1_val_memory_answers.json"
    if not prev.exists():
        print("no proxy run to estimate from; run the ollama evaluation first")
        return
    rows = json.loads(prev.read_text())["results"]["rag"]["rows"]
    tin = statistics.fmean(r.get("input_tokens") or 0 for r in rows)
    tout = statistics.fmean(r.get("output_tokens") or 0 for r in rows)
    print(f"proxy run: mean {tin:.0f} input / {tout:.0f} output tokens per answer (+ one rewrite call each)")
    for part in (a.prices or "").split(","):
        if "=" in part:
            model, io = part.split("=")
            pin, pout = (float(x) for x in io.split("/"))
            print(f"  {model}: about USD {n * (tin * pin + tout * pout) / 1e6:.4f} for {n} answers (estimate, not an invoice)")


def run(svc, l2p: dict[str, str], records: list[dict[str, Any]], refs: dict[str, str], cfg: dict[str, Any],  # type: ignore[no-untyped-def]
        llm, no_rag: bool) -> list[dict[str, Any]]:
    from app.repositories.base import Query
    from app.services.assistant.engine import _wrong_language
    engine = svc.conversations.engine
    chunk_text = {c["id"]: norm(f"{c.get('heading') or ''}\n{c['content']}")
                  for c in svc.store.select("document_chunks", Query(cols="id,heading,content", limit=100000))[0]}
    s = svc.retrieval.settings
    for k, v in cfg["settings"].items():
        setattr(s, k, v)
    engine.llm = llm
    rows = []
    for i, r in enumerate(records, 1):
        t0 = time.perf_counter()
        if no_rag:
            res = llm.complete(CLOSED_BOOK, r["question"], max_tokens=s.llm_answer_max_tokens, purpose="answer")
            out = dict(answer=res.text, evidence="closed_book", citations=[], generation=dict(
                input_tokens=res.input_tokens, output_tokens=res.output_tokens), retrieval={})
        else:
            out = engine.respond(r["question"], language=r["language"])
        ms = (time.perf_counter() - t0) * 1000
        gen = out.get("generation") or {}
        ans = out.get("answer") or ""
        cited = [c for c in out.get("citations") or [] if c.get("cited")]
        cited_docs = [l2p.get(c.get("document_id"), c.get("document_id")) for c in cited]
        row: dict[str, Any] = dict(id=r["id"], need=r["need"], language=r["language"], topic=r["topic"],
                                   answerability=r["answerability"], types=r["types"], answer=ans,
                                   evidence=out.get("evidence"), generation=gen.get("answer_generation"),
                                   fallback_reason=gen.get("fallback_reason"),
                                   gate=(out.get("retrieval") or {}).get("evidence_gate", {}).get("decision"),
                                   citation_check=gen.get("citation_check"), cited_docs=[d[:8] for d in cited_docs],
                                   input_tokens=gen.get("input_tokens"), output_tokens=gen.get("output_tokens"),
                                   ms=round(ms))
        row["abstained"] = float(out.get("evidence") in ("none", "unavailable") or gen.get("answer_generation") == "gated")
        row["wrong_language"] = float(bool(ans) and _wrong_language(ans, r["language"]))
        asked = figures(r["question"])            # a figure repeated from the question shows nothing
        row["refusal_phrase"] = float(bool(_REFUSAL.search(ans)))
        if r["answerability"] in ("answerable", "conflicting"):
            gf = gold_figures(r, refs.get(r["need"], "")) - asked
            row["figure_recall"] = (len(gf & figures(ans)) / len(gf)) if gf and not row["abstained"] else (0.0 if gf else None)
            if cited and r["relevant"]:
                row["cited_grade2"] = sum(1 for d in cited_docs if r["relevant"].get(d) == 2) / len(cited)
                row["cited_relevant"] = sum(1 for d in cited_docs if d in r["relevant"]) / len(cited)
            if cited and r["quotes"]:
                texts = [chunk_text[cid] for c in cited for cid in (c.get("chunk_ids") or []) if cid in chunk_text]
                row["cited_has_quote"] = float(any(q["quote"] in t for q in r["quotes"] for t in texts)) if texts else None
        else:
            row["invented_figure"] = float(bool(figures(ans) - asked) and not row["abstained"])
        rows.append(row)
        if i % 20 == 0:
            print(f"  {i}/{len(records)}", flush=True)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--split", required=True)
    ap.add_argument("--config", default="hub0.1", help="retrieval configuration (configs.py); the LLM rewrite is real")
    ap.add_argument("--provider", choices=["ollama", "gemini"], default="ollama")
    ap.add_argument("--model", default="qwen2.5:7b-instruct")
    ap.add_argument("--tag", required=True)
    ap.add_argument("--final", action="store_true")
    ap.add_argument("--no-rag", action="store_true", help="also run the closed-book baseline")
    ap.add_argument("--max-questions", type=int, default=0)
    ap.add_argument("--prices", default="")
    ap.add_argument("--confirm-paid-run", action="store_true")
    ap.add_argument("--chunker", choices=["v1", "v2", "v2b"], default="v1")
    a = ap.parse_args()
    splits = a.split.split(",")
    if "test" in splits and not a.final:
        raise SystemExit("TEST only in the final pre-registered run (--final)")
    if a.provider == "gemini":
        estimate(a, a.max_questions or 0)
    os.environ["CHUNKER_VERSION"] = a.chunker
    llm = make_llm(a)
    from retrieval_eval import build_memory
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    svc, l2p, info = build_memory(corpus, 1)
    cfg = resolve(a.config)
    for sp in splits:
        records, dinfo = load_split(sp, {d["id"] for d in corpus})
        if a.max_questions:
            records = records[:a.max_questions]
        refs: dict[str, str] = {}
        if sp in ("test", "neg"):
            raw = json.loads((ROOT / dinfo["file"]).read_text(encoding="utf-8"))["questions"]
            refs = {q["need_id"]: q["reference_answer"] for q in raw}
        results: dict[str, Any] = {}
        for mode in (["rag", "closed_book"] if a.no_rag else ["rag"]):
            print(f"== {sp} {mode}: {len(records)} questions", flush=True)
            t0 = time.perf_counter()
            rows = run(svc, l2p, records, refs, cfg, llm, no_rag=mode == "closed_book")
            ans = [r for r in rows if r["answerability"] in ("answerable", "conflicting")]
            neg = [r for r in rows if r["answerability"] not in ("answerable", "conflicting")]
            results[mode] = dict(
                seconds=round(time.perf_counter() - t0),
                answerable=summarize(ans, ["abstained", "refusal_phrase", "figure_recall", "cited_grade2", "cited_relevant",
                                           "cited_has_quote", "wrong_language"]) if ans else None,
                unanswerable=summarize(neg, ["abstained", "refusal_phrase", "invented_figure", "wrong_language"])
                if neg else None,
                by_language={lg: summarize([r for r in ans if r["language"] == lg], ["abstained", "figure_recall",
                                                                                     "cited_grade2", "wrong_language"],
                                           ci=False) for lg in sorted({r["language"] for r in ans})} if ans else None,
                generation=dict((k, sum(1 for r in rows if r["generation"] == k)) for k in sorted({str(r["generation"]) for r in rows})),
                rows=rows)
            print(f"   answerable {results[mode]['answerable'] and {k: v for k, v in results[mode]['answerable'].items() if not k.endswith('ci95')}}")
            print(f"   unanswerable {results[mode]['unanswerable'] and {k: v for k, v in results[mode]['unanswerable'].items() if not k.endswith('ci95')}}")
        out = dict(tag=a.tag, split=sp, final_test_run=a.final, at=datetime.now(UTC).isoformat(timespec="seconds"),
                   git=git_rev(), dataset=dinfo, corpus_sha256=sha256_file(CORPUS), index=info, config=cfg,
                   provider=a.provider, model=a.model if a.provider == "ollama" else "gemini (settings)",
                   proxy_note=("local proxy model: describes the pipeline with this model, NOT Gemini's answer quality"
                               if a.provider == "ollama" else "paid Gemini run"),
                   results=results)
        path = RESULTS / f"{a.tag}_{sp}_memory_answers.json"
        path.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        with (RESULTS / f"{a.tag}_{sp}_human_rating.csv").open("w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(["question_id", "language", "answerability", "question", "answer", "cited_documents",
                        "H1_correct(0-2)", "H2_complete(0-2)", "H3_faithful_to_sources(y/n)", "H4_citations_right(y/n)",
                        "H5_language_natural(y/n)", "H6_safe_refusal_or_referral(y/n/na)", "rater", "notes"])
            q = {r["id"]: r["question"] for r in records}
            for r in results["rag"]["rows"]:
                w.writerow([r["id"], r["language"], r["answerability"], q[r["id"]], r["answer"], " ".join(r["cited_docs"]),
                            "", "", "", "", "", "", "", ""])
        print(f"wrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
