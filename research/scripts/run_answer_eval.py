"""Answer-generation evaluation against the DEPLOYED assistant (real Gemini) -> JSONL.  Synthetic questions only.

Uses the anonymous chat endpoint (nothing is stored server-side, no personal data). Every case is recorded,
including failed or unavailable generations (answer_generation != "llm") - nothing is silently excluded.
Only reference-free, automatic metrics are computed here; correctness / relevance / faithfulness need human
review (research/configs/answer_rubric_v1.md, research/data/review/answer_annotation_template.csv).

    python3 research/scripts/run_answer_eval.py --out research/data/results/answers_production_heldout_v0.2.jsonl
"""
from __future__ import annotations

import argparse
import datetime as dt
import http.client
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = ["H04", "H06", "H09", "H11", "H12"]       # high-stakes immigration / work / residence questions
OUT_OF_SCOPE = [("OOS-1-en", "en", "What will the weather be like in Seoul tomorrow?"),
                ("OOS-2-en", "en", "Can you recommend a good kimchi stew recipe?")]
TEMPLATE_ENDINGS = ["Would you like me to prepare a request for a Global Supporter", "Nothing is sent unless you confirm",
                    "only the responsible office can decide", "Whether this applies to you depends",
                    "Here is what the approved official sources say", "Let me know if"]


def language_of(text: str) -> str | None:
    """Heuristic dominant language of an answer (scripts + function words); None if unclear."""
    letters = [c for c in text if c.isalpha()]
    if len(letters) < 20:
        return None
    hangul = sum("가" <= c <= "힣" for c in letters) / len(letters)
    han = sum("一" <= c <= "鿿" for c in letters) / len(letters)
    if hangul > 0.5:
        return "ko"
    if han > 0.4:
        return "zh-CN"
    low = text.lower()
    if re.search(r"[ăâđêôơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]", low) and \
            len(re.findall(r"\b(và|của|được|không|bạn|cho|các|là)\b", low)) >= 2:
        return "vi"
    ind = len(re.findall(r"\b(yang|dan|untuk|anda|dengan|tidak|dapat|harus|ini|di)\b", low))
    eng = len(re.findall(r"\b(the|and|you|your|to|of|is|are|for|with)\b", low))
    if ind >= 3 and ind > eng:
        return "id"
    if eng >= 3:
        return "en"
    return None


def ask(api: str, message: str, language: str) -> tuple[dict | None, float, str | None]:
    body = json.dumps({"message": message, "language": language, "history": []}).encode()
    t0 = time.perf_counter()
    for attempt in range(3):
        try:
            req = urllib.request.Request(api.rstrip("/") + "/api/v1/assistant/chat", data=body,
                                         headers={"Content-Type": "application/json", "User-Agent": "sch-hub-research-eval"})
            return json.load(urllib.request.urlopen(req, timeout=180)), (time.perf_counter() - t0) * 1000, None
        except urllib.error.HTTPError as exc:
            err = f"http_{exc.code}"
            if exc.code == 429:
                try:
                    code = json.loads(exc.read()).get("error", {}).get("code")
                    if code == "daily_limit":
                        return None, (time.perf_counter() - t0) * 1000, "daily_limit"
                except (ValueError, OSError):
                    pass
                time.sleep(30)
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as exc:
            err = type(exc).__name__
            time.sleep(10)
        t0 = time.perf_counter()
    return None, float("nan"), err          # failed: no latency measured


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", type=Path, default=ROOT / "research/data/benchmarks/retrieval_heldout_v0.2.json")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--api", default="https://sch-hub-api.onrender.com")
    ap.add_argument("--pause", type=float, default=12.0, help="seconds between requests (anonymous chat limit 6/min)")
    a = ap.parse_args()
    bench = json.loads(a.dataset.read_text())
    cases = [(r["question_id"], r["language"], r["question"], r) for r in bench["records"] if r["scenario_id"] in SCENARIOS]
    cases += [(qid, lang, q, None) for qid, lang, q in OUT_OF_SCOPE]
    a.out.parent.mkdir(parents=True, exist_ok=True)
    started = dt.datetime.now(dt.UTC).isoformat()
    with a.out.open("w", encoding="utf-8") as f:
        for qid, lang, question, rec in cases:
            d, wall_ms, err = ask(a.api, question, lang)
            m = (d or {}).get("metadata", {})
            answer = (d or {}).get("answer", "")
            cited = [c for c in (d or {}).get("citations", []) if c.get("cited")]
            expected = set(rec["expected_document_ids"]) if rec else set()
            cited_ids = [c.get("document_id") for c in cited]
            row = dict(
                question_id=qid, dataset_version=bench["dataset_version"] if rec else "out-of-scope-0.1",
                scenario_id=rec["scenario_id"] if rec else "OOS", language=lang, question=question,
                expected_document_ids=sorted(expected), request_error=err, wall_latency_ms=None if wall_ms != wall_ms else round(wall_ms),
                answer_generation=m.get("answer_generation"), provider=m.get("provider"), model=m.get("model"),
                fallback_used=m.get("fallback_used"), fallback_reason=m.get("fallback_reason"),
                prompt_version=m.get("prompt_version"), llm_latency_ms=m.get("llm_latency_ms"),
                input_tokens=m.get("input_tokens"), output_tokens=m.get("output_tokens"),
                total_tokens=m.get("total_tokens"), evidence_level=m.get("evidence_level"),
                offer_handoff=m.get("offer_handoff"), handoff_reasons=m.get("handoff_reasons"),
                removed_unsupported=m.get("removed_unsupported") or 0, answer=answer,
                cited_document_ids=cited_ids, cited_titles=[c.get("document_title") for c in cited],
                # automatic, reference-free checks
                detected_language=language_of(answer) if m.get("answer_generation") == "llm" else None,
                language_consistent=((language_of(answer) == lang) if language_of(answer) else None)
                if m.get("answer_generation") == "llm" else None,     # None = undetermined (too short), not a failure
                citation_precision=(sum(1 for c in cited_ids if c in expected) / len(cited_ids))
                if (rec and cited_ids and m.get("answer_generation") == "llm") else None,
                citation_hit=(any(c in expected for c in cited_ids) if rec and m.get("answer_generation") == "llm"
                              else None),
                raw_markers=bool(re.search(r"\[\d{1,2}\]", answer)),
                template_endings=[e for e in TEMPLATE_ENDINGS if e.lower() in answer.lower()],
                evaluated_at=dt.datetime.now(dt.UTC).isoformat())
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            print(f"{qid:10} gen={row['answer_generation']} model={row['model']} lang_ok={row['language_consistent']} "
                  f"cite_hit={row['citation_hit']} wall={row['wall_latency_ms']}ms err={err}")
            if err == "daily_limit":
                print("daily anonymous AI limit reached; stopping (remaining cases not run)")
                break
            time.sleep(a.pause)
    Path(str(a.out) + ".manifest.json").write_text(json.dumps(dict(
        started_at=started, finished_at=dt.datetime.now(dt.UTC).isoformat(), api=a.api, cases=len(cases),
        scenarios=SCENARIOS, out_of_scope=[x[0] for x in OUT_OF_SCOPE], dataset_version=bench["dataset_version"],
        note="real production answers (deployed code); synthetic questions; automatic metrics only"), indent=1))


if __name__ == "__main__":
    main()
