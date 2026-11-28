"""RAG lab: the Hub's real retrieval and answer engine, with one or several ways to answer.

    cd backend
    .venv/bin/python ../scripts/rag_lab.py                                   # benchmark, Qwen + RAG, all languages
    .venv/bin/python ../scripts/rag_lab.py --modes retrieval,qwen,nocontext,gemini --langs en,vi
    .venv/bin/python ../scripts/rag_lab.py --ask "D-2 연장 수수료는?" --language ko   # one question, side by side
    .venv/bin/python ../scripts/rag_lab.py --corpus .eval-cache/public_corpus.json --ask "..."   # on the public Hub documents

Modes: retrieval = excerpts only (no model), qwen = local Ollama + RAG, gemini = Gemini + RAG (needs GEMINI_LAB_KEY in the
environment; sends the question and the passages to Google), nocontext = the local model without any source (what it invents).
Data: the SYNTHETIC benchmark (scripts/benchmarks/rag_behaviour_v1.py) or a corpus file of public documents, in memory.
Never reads .env and never connects to Supabase.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics as st
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _k in list(os.environ):
    if _k.upper().startswith(("SUPABASE", "LLM_", "NEXT_PUBLIC")):
        del os.environ[_k]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "scripts" / "benchmarks")]
import app.core.config as config  # noqa: E402

config.Settings.model_config["env_file"] = None
from rag_behaviour_v1 import DOCS, LANGS, Q  # noqa: E402

MONTHS = {"en": "january february march april may june july august september october november december".split(),
          "id": "januari februari maret april mei juni juli agustus september oktober november desember".split()}


def has_date(text: str, iso: str) -> bool:
    d, low = date.fromisoformat(iso), text.lower()
    m, day = d.month, d.day
    forms = [rf"0?{m}\s*월\s*0?{day}\s*일", rf"0?{m}\s*月\s*0?{day}\s*[日号]", rf"{d.year}\s*[-./]\s*0?{m}\s*[-./]\s*0?{day}(?!\d)",
             rf"(?<!\d)0?{day}\s*[-./]\s*0?{m}\s*[-./]\s*{d.year}", rf"ngày\s*0?{day}\s*(?:tháng|/|-)\s*0?{m}(?!\d)", rf"0?{day}\s+tháng\s+0?{m}(?!\d)",
             rf"(?<![\d.])0?{m}\s*[./]\s*0?{day}(?![\d])", rf"(?<![\d.])0?{day}\s*/\s*0?{m}(?![\d])"]
    for names in MONTHS.values():
        n = names[m - 1]
        forms += [rf"{n[:3]}[a-z]*\.?\s+0?{day}(?!\d)", rf"(?<!\d)0?{day}(?:st|nd|rd|th|\.)?\s+(?:of\s+)?{n[:3]}[a-z]*"]
    return any(re.search(f, low) for f in forms)


def has_num(text: str, n: str) -> bool:
    t = re.sub(r"(?<=\d)[,.\s](?=\d{3}(?!\d))", "", text)
    return bool(re.search(rf"(?<![\d.]){re.escape(n)}(?![\d]|\.\d)", t))


def met(text: str, fact: dict) -> bool:  # type: ignore[type-arg]
    if "num" in fact:
        return has_num(text, fact["num"]) or (fact["num"].endswith("000") and has_num(text, fact["num"][:-3] + " nghìn"))
    if "date" in fact:
        return has_date(text, fact["date"])
    return any(x.lower() in text.lower() for x in fact["any"])


def build(corpus: Path | None, embedding: str):  # type: ignore[no-untyped-def]
    from app.core.config import Settings
    from app.repositories.base import Query
    from app.repositories.memory_store import MemoryFileStorage, MemoryStore, seed_categories
    from app.services.container import build_services
    from app.services.embeddings.factory import build_embedding_provider
    from app.services.llm.base import NullLLMProvider

    s = Settings(_env_file=None, embedding_provider=embedding, job_execution="inline", environment="test",  # type: ignore[call-arg]
                 supabase_jwt_secret="x" * 32, retrieval_min_similarity=0.80 if embedding != "hash" else 0.0, min_extracted_chars=1,
                 board_request_delay_seconds=0)
    store = MemoryStore()
    seed_categories(store)
    svc = build_services(s, store, MemoryFileStorage(), build_embedding_provider(s), NullLLMProvider())
    admin = store.insert("profiles", dict(id="00000000-0000-0000-0000-00000000ad01", email="lab@example.test", display_name="Lab", role="admin"))
    docs = DOCS if corpus is None else [dict(id=d["id"], lang=d.get("language") or "ko", cat=d.get("category") or "daily-living", pub=None,
                                             org=d.get("organization"), auth=d.get("authority_type"), title=d["title"], text=d["content"])
                                        for d in json.loads(corpus.read_text())]
    ids: dict[str, str] = {}
    for d in docs:
        src = store.insert("knowledge_sources", dict(title=d["title"][:200], organization=d.get("org") or "SCH (SYNTHETIC)", source_type="manual_text",
                                                     authority_type=d.get("auth") or "official_university", scope="university",
                                                     category=d["cat"], language=d["lang"]))
        job = svc.ingestion.ingest_text(src, title=d["title"], text=d["text"], requested_by=admin["id"], external_id=d["id"],
                                        source_published_at=__import__("datetime").datetime.fromisoformat(d["pub"] + "T00:00:00+00:00") if d.get("pub") else None)
        v = store.select("document_versions", Query(eq={"id": job["version_id"]}))[0][0]
        store.update("document_versions", {"verification_status": "pending_review"}, {"id": v["id"]})
        v["verification_status"] = "pending_review"
        svc.ingestion.run_job(svc.ingestion.request_activation(v, admin["id"], "lab")["id"])
        ids[job["document_id"]] = d["id"]
    return svc, ids


def provider(mode: str, svc):  # type: ignore[no-untyped-def]
    from app.services.llm.base import NullLLMProvider

    if mode in ("qwen", "nocontext"):
        from app.services.llm.ollama import OllamaProvider

        return OllamaProvider(os.environ.get("LAB_MODEL", "qwen2.5:7b-instruct"))
    if mode == "gemini":
        key = os.environ.get("GEMINI_LAB_KEY")
        if not key:
            return None
        from app.services.llm.gemini import GeminiProvider

        return GeminiProvider(api_key=key, primary=svc.settings.gemini_primary_model, fallback=svc.settings.gemini_fallback_model)
    return NullLLMProvider()


def run_mode(mode: str, svc, ids, question: str, lang: str, llm) -> dict:  # type: ignore[no-untyped-def,type-arg]
    from app.services.assistant.engine import AssistantEngine
    from app.services.llm.base import LLMError

    t0 = time.perf_counter()
    if mode == "nocontext":
        try:
            r = llm.complete(f"Answer the student's question about a Korean university in {lang}. Be specific.", question, max_tokens=500)
            return dict(answer=r.text, cited=[], evidence=None, ms=int((time.perf_counter() - t0) * 1000), gen={}, docs=[])
        except LLMError as exc:
            return dict(answer="", cited=[], evidence=None, ms=0, gen={"fallback_reason": exc.code}, docs=[])
    out = AssistantEngine(svc.retrieval, llm, svc.settings).respond(question, language=lang)
    return dict(answer=out["answer"], cited=[ids.get(c["document_id"]) for c in out["citations"] if c["cited"]], evidence=out["evidence"],
                docs=[ids.get(c["document_id"]) for c in out["citations"]], gen=out["generation"], ms=int((time.perf_counter() - t0) * 1000),
                offer=out["offer_handoff"])


def score(rec: tuple, res: dict, lang: str) -> dict:  # type: ignore[type-arg]
    from app.services.assistant.engine import _wrong_language
    from app.services.assistant.texts import TEXT

    _id, kind, expected, facts, wrong, _q = rec
    a = res["answer"]
    refused = res["evidence"] == "none" or a == TEXT["none"].get(lang)
    fallback = res["gen"].get("answer_generation") == "fallback"
    r = dict(kind=kind, lang=lang, language_ok=not _wrong_language(a, lang), fallback=fallback, ms=res["ms"], reason=res["gen"].get("fallback_reason"))
    if kind == "unanswerable":
        r["correct"] = refused or (fallback and not re.search(r"\d", a)) or (res["evidence"] in ("none", "partial") and not re.search(r"\d{2,}", a))
        r["refused"] = refused
        return r
    r["facts"] = sum(met(a, f) for f in facts) / len(facts)
    r["stale_or_wrong"] = any((has_num(a, w) if w.isdigit() and w != "2025" else w.lower() in a.lower()) for w in wrong)
    r["cited_ok"] = bool(set(expected) & set(res["cited"])) if res["evidence"] is not None else None
    r["retrieved_ok"] = bool(set(expected) & set(res["docs"])) if res["evidence"] is not None else None
    r["correct"] = r["facts"] == 1 and not r["stale_or_wrong"]
    return r


def summary(rows: list[dict]) -> dict:  # type: ignore[type-arg]
    ans = [r for r in rows if r["kind"] != "unanswerable"]
    un = [r for r in rows if r["kind"] == "unanswerable"]
    mean = lambda xs: round(st.mean(xs), 3) if xs else None  # noqa: E731
    ms = sorted(r["ms"] for r in rows)
    cited = [r["cited_ok"] for r in ans if r.get("cited_ok") is not None]
    return dict(n=len(rows), correct=mean([r["correct"] for r in rows]), answerable_correct=mean([r["correct"] for r in ans]),
                fact_recall=mean([r["facts"] for r in ans]), retrieved=mean([r["retrieved_ok"] for r in ans if r.get("retrieved_ok") is not None]),
                cited=mean(cited), stale_or_wrong=mean([r["stale_or_wrong"] for r in ans]), unanswerable_safe=mean([r["correct"] for r in un]),
                language_ok=mean([r["language_ok"] for r in rows]), fallback=mean([r["fallback"] for r in rows]),
                ms_median=ms[len(ms) // 2] if ms else None, ms_p95=ms[int(.95 * (len(ms) - 1))] if ms else None)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--modes", default="qwen")
    p.add_argument("--langs", default=",".join(LANGS))
    p.add_argument("--only", help="question ids, comma separated")
    p.add_argument("--ask")
    p.add_argument("--language", default="en")
    p.add_argument("--corpus", type=Path)
    p.add_argument("--embedding", default="e5_onnx")
    p.add_argument("--json", type=Path)
    a = p.parse_args()
    svc, ids = build(a.corpus, a.embedding)
    out: dict = {"benchmark": "rag_behaviour_v1", "synthetic": a.corpus is None, "today": date.today().isoformat(), "modes": {}}  # type: ignore[type-arg]
    for mode in a.modes.split(","):
        llm = provider(mode, svc)
        if llm is None:
            print(f"{mode}: NOT TESTED (GEMINI_LAB_KEY is not set)")
            out["modes"][mode] = "not_tested"
            continue
        if a.ask:
            r = run_mode(mode, svc, ids, a.ask, a.language, llm)
            print(f"\n===== {mode}  ({r['ms']} ms, evidence {r['evidence']}, cited {r['cited']}, {r['gen'].get('fallback_reason', '')})\n{r['answer']}")
            continue
        from app.services.llm.usage import usage

        usage.reset()                    # provider-reported tokens of this mode only (for the cost model)
        rows, answers = [], []
        for rec in Q:
            if a.only and rec[0] not in a.only.split(","):
                continue
            for lang in a.langs.split(","):
                res = run_mode(mode, svc, ids, rec[5][lang], lang, llm)
                s = score(rec, res, lang)
                rows.append(s)
                answers.append(dict(id=rec[0], lang=lang, question=rec[5][lang], answer=res["answer"], cited=res["cited"], docs=res["docs"], evidence=res["evidence"],
                                    **{k: s.get(k) for k in ("correct", "facts", "stale_or_wrong", "language_ok", "fallback", "reason", "ms")}))
                if not s["correct"]:
                    print(f"  MISS {mode} {rec[0]} {lang} [{s.get('reason') or res['evidence']}] docs={res['docs'][:3]} :: {res['answer'][:140]!r}", flush=True)
        per = {lg: summary([r for r in rows if r["lang"] == lg]) for lg in a.langs.split(",")}
        kinds = {k: summary([r for r in rows if r["kind"] == k])["correct"] for k in sorted({r["kind"] for r in rows})}
        snap = usage.snapshot()
        tok = {k: sum(c.get(k, 0) for c in snap["tokens"].values()) for k in ("input", "output", "thinking")}
        n = max(1, len(rows))
        cost_basis = dict(answers=len(rows), model_attempts=sum(snap["attempts"].values()),
                          attempts_per_answer=round(sum(snap["attempts"].values()) / n, 2),
                          input_tokens_per_answer=round(tok["input"] / n), output_tokens_per_answer=round(tok["output"] / n),
                          thinking_tokens_per_answer=round(tok["thinking"] / n), by_purpose=snap["by_purpose"],
                          note="token counts as reported by the local model's tokenizer (Gemini counts differ somewhat)")
        out["modes"][mode] = dict(overall=summary(rows), per_language=per, per_kind=kinds, cost_basis=cost_basis, answers=answers)
        print(f"\n{mode}: {json.dumps(summary(rows))}\n  by language: " + ", ".join(f"{k} {v['correct']}" for k, v in per.items()) + f"\n  by kind: {kinds}", flush=True)
    if a.json:
        a.json.parent.mkdir(parents=True, exist_ok=True)
        a.json.write_text(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
