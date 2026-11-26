"""Performance of a running scripts/dev_stack.py (real database): ingestion, database growth, response times, memory of the API.

    cd backend && .venv/bin/python ../scripts/perf_report.py INFO.json [--corpus .eval-cache/public_corpus.json] [--json OUT]
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import re
import subprocess
import time
from pathlib import Path

import httpx

ap = argparse.ArgumentParser()
ap.add_argument("info", type=Path)
ap.add_argument("--corpus", type=Path)
ap.add_argument("--json", type=Path)
a = ap.parse_args()
info = json.loads(a.info.read_text())
assert info["api"].startswith("http://127.0.0.1:"), "loopback only"
c = httpx.Client(base_url=info["api"] + "/api/v1", timeout=120, trust_env=False)
H = {"Authorization": f"Bearer {info['tokens']['super_admin']}"}
port = int(info["api"].rsplit(":", 1)[1])
pid = re.search(r"pid=(\d+)", subprocess.run(["ss", "-ltnp", f"sport = :{port}"], capture_output=True, text=True).stdout)[1]  # type: ignore[index]


def rss() -> int:
    return round(int(re.search(r"VmRSS:\s+(\d+)", Path(f"/proc/{pid}/status").read_text())[1]) / 1024)  # type: ignore[index]


def size() -> int:
    return c.get("/admin/storage", headers=H).json()["database_bytes"]


def timed(n: int, fn) -> dict:  # type: ignore[no-untyped-def,type-arg]
    xs = []
    for i in range(n):
        t = time.perf_counter()
        r = fn(i)
        xs.append((time.perf_counter() - t) * 1000)
        assert r.status_code < 400, (r.status_code, r.text[:200])
    xs.sort()
    return dict(n=n, p50_ms=round(xs[len(xs) // 2], 1), p95_ms=round(xs[int(.95 * (n - 1))], 1))


out: dict = dict(rss_start_mb=rss(), database_start_bytes=size())  # type: ignore[type-arg]
if a.corpus:
    docs, chars, t0 = json.loads(a.corpus.read_text()), 0, time.time()
    for d in docs:
        s = c.post("/admin/sources", headers=H, json=dict(title=d["title"][:190] + f" {d['id'][:4]}", organization=d.get("organization") or "SCH", source_type="manual_text", authority_type="official_university",
                   scope="university", category=d.get("category") or "daily-living", language=d.get("language") or "ko")).json()
        j = c.post(f"/admin/sources/{s['id']}/submit-text", headers=H, json=dict(title=d["title"], text=d["content"][:199000])).json()
        c.post(f"/admin/versions/{j['version_id']}/approve", headers=H, json={})
        chars += len(d["content"])
    while c.get("/admin/agent-operations", headers=H).json()["queues"]["jobs"]["queued"] or c.get("/admin/agent-operations", headers=H).json()["queues"]["jobs"]["running"]:
        time.sleep(1)
    secs = time.time() - t0
    st = c.get("/admin/storage", headers=H).json()
    rows = {t["table_name"]: t for t in st["tables"]}
    out["ingestion"] = dict(documents=len(docs), characters=chars, seconds=round(secs, 1), characters_per_second=round(chars / secs))
    out["database_growth"] = dict(bytes=st["database_bytes"] - out["database_start_bytes"], bytes_per_1000_characters=round((st["database_bytes"] - out["database_start_bytes"]) / chars * 1000),
                                  chunks_table=rows.get("document_chunks", {}).get("total_bytes"), chunks_indexes=rows.get("document_chunks", {}).get("index_bytes"))
out["rss_after_indexing_mb"] = rss()
QS = ["D-2 extension documents", "기숙사 입사 신청", "asuransi kesehatan mahasiswa", "làm thêm bao nhiêu giờ", "外国人登录证 申请", "course registration period", "TOPIK registration", "living costs per month"]
out["endpoints"] = dict(
    health=timed(50, lambda i: httpx.get(info["api"] + "/health")), categories=timed(40, lambda i: c.get("/categories")), announcements=timed(40, lambda i: c.get("/announcements")),
    documents=timed(40, lambda i: c.get("/knowledge/documents")), agents=timed(30, lambda i: c.get("/agents")),
    search_first=timed(len(QS), lambda i: c.post("/knowledge/search", json=dict(query=QS[i], top_k=6))), search_again=timed(len(QS) * 3, lambda i: c.post("/knowledge/search", json=dict(query=QS[i % len(QS)], top_k=6))),
    agent_tool=timed(20, lambda i: c.post("/agents/immigration/tools", headers=H, json=dict(tool="visa_checklist", params=dict(topic="extension")))),
    admin_operations=timed(20, lambda i: c.get("/admin/agent-operations", headers=H)), admin_storage=timed(10, lambda i: c.get("/admin/storage", headers=H)))
t = time.time()
with cf.ThreadPoolExecutor(10) as ex:
    codes = list(ex.map(lambda i: c.post("/knowledge/search", json=dict(query=f"{QS[i % len(QS)]} {i}", top_k=5)).status_code, range(60)))
out["concurrent_search"] = dict(requests=60, parallel=10, seconds=round(time.time() - t, 1), failed=sum(x != 200 for x in codes))
chat = []
for i, (q, lang) in enumerate(zip(QS[:6], ("en", "ko", "id", "vi", "zh-CN", "en"), strict=True)):
    t = time.perf_counter()
    r = c.post("/assistant/chat", json=dict(message=q, language=lang))
    chat.append(dict(lang=lang, status=r.status_code, ms=round((time.perf_counter() - t) * 1000), generation=(r.json().get("generation") or {}).get("answer_generation") if r.status_code == 200 else None))
out["chat_local_model"] = chat
out["tasks"] = timed(10, lambda i: c.post("/agents/events/tasks", headers=H, json=dict(task_type="event_digest")) if i < 4 else c.get("/agent-tasks", headers=H))
out["rss_end_mb"] = rss()
print(json.dumps(out, ensure_ascii=False, indent=1))
if a.json:
    a.json.write_text(json.dumps(out, ensure_ascii=False, indent=1))
