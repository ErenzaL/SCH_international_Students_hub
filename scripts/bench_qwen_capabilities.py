"""What the local model can do for the agents, measured on the SYNTHETIC documents of rag_behaviour_v1: structured extraction,
categorisation, tool choice, summaries, speed and GPU memory. Loopback Ollama only.

    cd backend && .venv/bin/python ../scripts/bench_qwen_capabilities.py --json ../scripts/benchmarks/results/qwen_capabilities.json
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import re
import statistics as st
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "scripts" / "benchmarks"), str(ROOT / "scripts")]
from rag_behaviour_v1 import DOCS  # noqa: E402
from rag_lab import has_date, has_num  # noqa: E402

URL = "http://127.0.0.1:11434"
EXTRACT = {"dorm-2027": dict(deadline="2026-12-18", amount="347000"), "topik": dict(deadline="2026-12-28", amount=None),
           "scholar": dict(deadline="2026-12-09", amount="1150000"), "event": dict(deadline="2026-12-07", amount=None),
           "passed": dict(deadline="2026-09-19", amount="480000"), "course": dict(deadline=None, amount=None), "sos": dict(deadline=None, amount=None),
           "work-2026": dict(deadline=None, amount=None), "dorm-2025": dict(deadline="2025-11-14", amount="312000"), "visa": dict(deadline=None, amount="71000")}
TOOLS = [("rag_search", "Search approved guides and notices for a factual question", {"query": "string"}),
         ("upcoming_deadlines", "List deadlines in the next days", {"days": "integer"}),
         ("scholarship_search", "List published scholarships", {"q": "string"}),
         ("event_search", "List upcoming events", {"days": "integer"}),
         ("visa_checklist", "Steps and documents of an immigration procedure", {"topic": "string"}),
         ("get_support_request_status", "Status of the student's own support requests", {}),
         ("create_support_request", "Prepare a request to a human supporter", {"summary": "string"})]
ASK = [("Which deadlines are coming up in the next two weeks?", "upcoming_deadlines"), ("장학금 뭐가 있어요?", "scholarship_search"), ("Ada acara kampus apa minggu depan?", "event_search"),
       ("Tôi muốn nói chuyện với nhân viên hỗ trợ", "create_support_request"), ("我之前的求助处理到哪一步了？", "get_support_request_status"), ("What are the steps to extend my D-2 visa?", "visa_checklist"),
       ("How many credits can I register for?", "rag_search"), ("외국인등록증 발급 절차를 알려 주세요", "visa_checklist"), ("What happens if I do not pay the insurance?", "rag_search"),
       ("I need a person to help me, the chatbot does not understand", "create_support_request"), ("Beasiswa apa yang tersedia?", "scholarship_search"), ("다음 주 행사 알려줘", "event_search"),
       ("Hạn chót nào sắp tới?", "upcoming_deadlines"), ("学校附近的紧急电话是多少？", "rag_search"), ("status of my ticket", "get_support_request_status"), ("What is the weather on Mars?", None), ("Tell me a joke", None),
       ("How do I report my new address to immigration?", "visa_checklist"), ("기숙사 환불 규정이 어떻게 되나요?", "rag_search"), ("Any festival soon?", "event_search")]


def chat(model: str, messages: list, **kw) -> dict:  # type: ignore[no-untyped-def,type-arg]
    r = httpx.post(f"{URL}/api/chat", timeout=180, trust_env=False, json=dict(model=model, messages=messages, stream=False,
                   options=dict(temperature=0, num_ctx=8192, num_predict=600), **kw))
    r.raise_for_status()
    return r.json()


def gpu() -> dict:  # type: ignore[type-arg]
    out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.used,memory.total,utilization.gpu", "--format=csv,noheader,nounits"], capture_output=True, text=True).stdout
    n, used, total, util = [x.strip() for x in out.split("\n")[0].split(",")]
    return dict(name=n, memory_used_mib=int(used), memory_total_mib=int(total), utilization=int(util))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--model", default="qwen2.5:7b-instruct")
    p.add_argument("--json", type=Path)
    a = p.parse_args()
    docs = {d["id"]: d for d in DOCS}
    out: dict = dict(model=a.model, gpu_before=gpu())  # type: ignore[type-arg]
    t0 = time.time()
    chat(a.model, [dict(role="user", content="ping")])
    out["load_seconds"] = round(time.time() - t0, 1)
    out["gpu_loaded"] = gpu()
    # 1. structured extraction (JSON schema enforced by Ollama)
    schema = dict(type="object", properties=dict(deadline=dict(type=["string", "null"]), amount_won=dict(type=["integer", "null"])), required=["deadline", "amount_won"])
    rows = []
    for k, want in EXTRACT.items():
        d = docs[k]
        r = chat(a.model, [dict(role="system", content="Extract from the notice the application deadline (YYYY-MM-DD, the last day) and the main amount in won. Use null when the text does not state "
                                "an application deadline or an amount. Never guess."), dict(role="user", content=f"{d['title']}\n{d['text']}")], format=schema)
        try:
            j = json.loads(r["message"]["content"])
            ok_json = True
        except ValueError:
            j, ok_json = {}, False
        dl = str(j.get("deadline") or "")[:10] or None
        amt = str(j.get("amount_won")) if j.get("amount_won") else None
        rows.append(dict(id=k, json=ok_json, deadline_ok=dl == want["deadline"], amount_ok=amt == want["amount"], got=j))
    out["extraction"] = dict(n=len(rows), valid_json=st.mean(r["json"] for r in rows), deadline=st.mean(r["deadline_ok"] for r in rows), amount=st.mean(r["amount_ok"] for r in rows), rows=rows)
    # the same with the Hub's deterministic extractor
    from datetime import date

    from app.services.discovery.extract import analyse
    det = [(lambda f: dict(id=k, deadline_ok=(f["deadlines"][-1]["date"] if f["deadlines"] else None) == EXTRACT[k]["deadline"]))(
        analyse(docs[k]["title"], docs[k]["text"], published_on=docs[k]["pub"], today=date(2026, 11, 25))) for k in EXTRACT]
    out["deterministic_deadline"] = dict(n=len(det), deadline=st.mean(r["deadline_ok"] for r in det), wrong=[r["id"] for r in det if not r["deadline_ok"]])
    # 2. categories
    cats = sorted({d["cat"] for d in DOCS})
    hit = []
    for d in DOCS:
        r = chat(a.model, [dict(role="user", content=f"Choose one category for the notice: {', '.join(cats)}.\n\n{d['title']}\n{d['text']}")],
                 format=dict(type="object", properties=dict(category=dict(type="string", enum=cats)), required=["category"]))
        hit.append(json.loads(r["message"]["content"]).get("category") == d["cat"])
    out["category_accuracy"] = round(st.mean(hit), 3)
    # 3. tool choice
    tools = [dict(type="function", function=dict(name=n, description=desc, parameters=dict(type="object", properties={k: dict(type=v) for k, v in ps.items()}, required=[]))) for n, desc, ps in TOOLS]
    res = []
    for q, want in ASK:
        r = chat(a.model, [dict(role="system", content="You help students of a Korean university. Call one tool when it fits. If no tool fits, answer without a tool."), dict(role="user", content=q)], tools=tools)
        calls = [c["function"]["name"] for c in r["message"].get("tool_calls") or []]
        res.append(dict(q=q, want=want, got=calls, ok=(calls == [] if want is None else calls[:1] == [want]), one=len(calls) <= 1, known=all(c in {t[0] for t in TOOLS} for c in calls)))
    out["tool_choice"] = dict(n=len(res), correct=st.mean(r["ok"] for r in res), single_call=st.mean(r["one"] for r in res), known_tools=st.mean(r["known"] for r in res), wrong=[r for r in res if not r["ok"]])
    # 4. summaries keep the figures
    keep, extra = [], []
    for k, facts in (("scholar", [("num", "3.35"), ("num", "1150000"), ("date", "2026-12-09")]), ("dorm-2027", [("num", "347000"), ("date", "2026-12-18")]),
                     ("event", [("date", "2026-12-11"), ("num", "36"), ("date", "2026-12-07")]), ("course", [("num", "19"), ("date", "2027-02-19")])):
        for lang in ("English", "Indonesian", "Vietnamese", "Simplified Chinese"):
            r = chat(a.model, [dict(role="user", content=f"Summarize this notice for students in {lang} in at most four short lines. Keep every date, amount and condition exactly. Add nothing.\n\n{docs[k]['title']}\n{docs[k]['text']}")])
            s = r["message"]["content"]
            keep.append(st.mean(has_num(s, v) if t == "num" else has_date(s, v) for t, v in facts))
            src = {re.sub(r"[,.]", "", x) for x in re.findall(r"\d[\d,.]*\d|\d", docs[k]["title"] + docs[k]["text"])}
            nums = {re.sub(r"[,.]", "", x) for x in re.findall(r"\d[\d,.]*\d|\d", s)}
            extra.append(len({n for n in nums if len(n) >= 3 and n not in src and n.lstrip("0") not in src}))
    out["summaries"] = dict(n=len(keep), facts_kept=round(st.mean(keep), 3), with_new_figures=sum(e > 0 for e in extra))
    # 5. speed, alone and two at the same time
    long = "Explain in about 250 words how a student applies for a dormitory. " * 2
    t0 = time.time()
    r = chat(a.model, [dict(role="user", content=long)])
    out["speed"] = dict(tokens_per_second=round(r["eval_count"] / (r["eval_duration"] / 1e9), 1), prompt_tokens_per_second=round(r.get("prompt_eval_count", 0) / max(r.get("prompt_eval_duration", 1) / 1e9, 1e-9), 1),
                        seconds=round(time.time() - t0, 1), output_tokens=r["eval_count"])
    t0 = time.time()
    with cf.ThreadPoolExecutor(3) as ex:
        rs = list(ex.map(lambda _i: chat(a.model, [dict(role="user", content=long)]), range(3)))
    out["three_at_once"] = dict(seconds=round(time.time() - t0, 1), output_tokens=sum(x["eval_count"] for x in rs), tokens_per_second_total=round(sum(x["eval_count"] for x in rs) / (time.time() - t0), 1))
    out["gpu_after"] = gpu()
    print(json.dumps({k: v for k, v in out.items() if k != "extraction"}, ensure_ascii=False, indent=1))
    print("extraction", {k: v for k, v in out["extraction"].items() if k != "rows"})
    for r in out["extraction"]["rows"]:
        if not (r["deadline_ok"] and r["amount_ok"]):
            print("  ", r["id"], r["got"], EXTRACT[r["id"]])
    if a.json:
        a.json.write_text(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
