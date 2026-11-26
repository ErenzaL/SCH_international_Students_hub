"""Workload for a server started under scripts/render_like.py (Render free: 512 MB, 0.1 CPU): cold start, model load, indexing, large PDFs,
parallel searches, chat, agent tasks. Reports time and memory per phase. Synthetic data and public documents only; loopback only.

    python3 scripts/render_memory_test.py INFO.json --report OUT.json [--corpus backend/.eval-cache/public_corpus.json] [--pdf-mb 3,9]
    python3 scripts/render_memory_test.py --write-pdfs --pdf-mb 9 --pdf-dir DIR      # only the synthetic PDFs, e.g. to upload on staging
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import random
import re
import subprocess
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_like import tree, usage  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("info", type=Path, nargs="?")
ap.add_argument("--report", type=Path)
ap.add_argument("--write-pdfs", action="store_true", help="only write the synthetic Korean test PDFs (--pdf-mb, --pdf-dir) and exit; e.g. for staging")
ap.add_argument("--corpus", type=Path)
ap.add_argument("--pdf-mb", default="3,9")
ap.add_argument("--pdf-dir", type=Path, default=Path("/tmp"))
a = ap.parse_args()
def make_pdf(mb: int) -> Path:
    import fitz  # pymupdf, a production dependency

    p = a.pdf_dir / f"render_test_{mb}mb.pdf"
    if p.exists():
        return p
    rnd = random.Random(mb)
    words = "유학생 생활관 장학금 신청 기간 체류기간 연장 외국인등록증 수강신청 건강보험 시간제 취업 허가 서류 제출 마감 안내 학사 일정 졸업 휴학 복학 기숙사 비용 환불".split()
    doc = fitz.open()
    page_no = 0
    while True:
        page_no += 1
        page = doc.new_page()
        text = f"제{page_no}장 안내\n" + "\n".join(" ".join(rnd.choice(words) for _ in range(14)) + f" {page_no}-{i}." for i in range(38))
        page.insert_text((40, 50), text, fontname="korea", fontsize=10)
        img = bytes(rnd.getrandbits(8) for _ in range(160 * 160 * 3))
        pix = fitz.Pixmap(fitz.csRGB, 160, 160, img, False)
        page.insert_image(fitz.Rect(380, 600, 560, 780), pixmap=pix)
        if page_no % 10 == 0:
            doc.save(p, deflate=False)
            if p.stat().st_size >= mb * 1024 * 1024:
                break
    doc.close()
    return p


if a.write_pdfs:
    for mb in [int(x) for x in a.pdf_mb.split(",") if x]:
        print(make_pdf(mb))
    sys.exit(0)
if a.info is None or a.report is None:
    ap.error("INFO and --report are required unless --write-pdfs")
info = json.loads(a.info.read_text())
assert info["api"].startswith("http://127.0.0.1:"), "loopback only"
c = httpx.Client(base_url=info["api"] + "/api/v1", timeout=900, trust_env=False)
H = {"Authorization": f"Bearer {info['tokens']['super_admin']}"}
port = int(info["api"].rsplit(":", 1)[1])
server = int(re.search(r"pid=(\d+)", subprocess.run(["ss", "-ltnp", f"sport = :{port}"], capture_output=True, text=True).stdout)[1])  # type: ignore[index]
root = server
while True:     # the uppermost process of the tree below render_like
    pp = int(Path(f"/proc/{root}/stat").read_text().rsplit(")", 1)[1].split()[1])
    if "render_like" in Path(f"/proc/{pp}/cmdline").read_bytes().decode(errors="ignore"):
        break
    root = pp
phases: list[dict] = []  # type: ignore[type-arg]


def mem() -> int:
    return usage(tree(root))[0] // 1024


def phase(name: str, fn):  # type: ignore[no-untyped-def]
    t0, before, peak = time.time(), mem(), 0
    with cf.ThreadPoolExecutor(1) as ex:
        fut = ex.submit(fn)
        while not fut.done():
            peak = max(peak, mem())
            time.sleep(0.2)
        try:
            detail, ok = fut.result(), True
        except Exception as exc:  # noqa: BLE001
            detail, ok = f"{type(exc).__name__}: {str(exc)[:200]}", False
    alive = c.get("/categories").status_code == 200 if _alive() else False
    row = dict(phase=name, ok=ok and alive, seconds=round(time.time() - t0, 1), memory_before_mb=before, memory_peak_mb=max(peak, mem()), memory_after_mb=mem(),
               server_alive=alive, detail=detail)
    phases.append(row)
    print(json.dumps(row, ensure_ascii=False)[:300], flush=True)
    a.report.write_text(json.dumps(dict(phases=phases), ensure_ascii=False, indent=1))
    return row


def _alive() -> bool:
    try:
        return httpx.get(info["api"] + "/health", timeout=120).status_code == 200
    except httpx.HTTPError:
        return False


def wait_jobs(limit: float = 3000) -> dict:  # type: ignore[type-arg]
    t = time.time()
    while time.time() - t < limit:
        q = c.get("/admin/agent-operations", headers=H).json()["queues"]["jobs"]
        if not q["queued"] and not q["running"]:
            return q
        time.sleep(2)
    raise TimeoutError("jobs did not finish")


def corpus() -> str:
    docs = json.loads(a.corpus.read_text())
    for d in docs:
        s = c.post("/admin/sources", headers=H, json=dict(title=d["title"][:180] + f" {d['id'][:4]}", organization="SCH", source_type="manual_text",
                   authority_type="official_university", scope="university", category=d.get("category") or "daily-living", language=d.get("language") or "ko")).json()
        j = c.post(f"/admin/sources/{s['id']}/submit-text", headers=H, json=dict(title=d["title"], text=d["content"][:199000])).json()
        c.post(f"/admin/versions/{j['version_id']}/approve", headers=H, json={})
    wait_jobs()
    st = c.get("/admin/storage", headers=H).json()
    return f"{len(docs)} documents indexed, database {st['database_bytes'] // 1024 // 1024} MB"


def upload(mb: int) -> str:
    path = make_pdf(mb)
    s = c.post("/admin/sources", headers=H, json=dict(title=f"Render test PDF {mb} MB", organization="SYNTHETIC", source_type="pdf", authority_type="official_university",
               scope="university", category="daily-living", language="ko")).json()
    r = c.post(f"/admin/sources/{s['id']}/upload", headers=H, files={"file": (path.name, path.read_bytes(), "application/pdf")})
    if r.status_code != 202:
        return f"upload refused: {r.status_code} {r.text[:200]}"
    job = r.json()["job_id"]
    wait_jobs()
    j = c.get(f"/admin/ingestion-jobs/{job}", headers=H).json()
    if not j.get("version_id"):
        return f"extraction {j['status']} {j.get('error_code')}"
    c.post(f"/admin/versions/{j['version_id']}/approve", headers=H, json={})
    wait_jobs()
    v = c.get(f"/admin/versions/{j['version_id']}", headers=H).json()
    return f"{path.stat().st_size // 1024 // 1024} MB, {len(v.get('extracted_text') or '')} characters, {v.get('indexing_status')}"


QS = ["D-2 extension documents", "기숙사 입사 신청", "asuransi kesehatan mahasiswa", "làm thêm bao nhiêu giờ", "外国人登录证 申请", "course registration period", "TOPIK", "생활비"]


def searches() -> str:
    t = time.time()
    with cf.ThreadPoolExecutor(10) as ex:
        codes = list(ex.map(lambda i: c.post("/knowledge/search", json=dict(query=f"{QS[i % len(QS)]} {i}", top_k=5)).status_code, range(40)))
    return f"40 searches, 10 at a time, {round(time.time() - t, 1)} s, failed {sum(x != 200 for x in codes)}"


def single_search() -> str:
    t = time.perf_counter()
    r = c.post("/knowledge/search", json=dict(query="기숙사 입사 신청 기간", top_k=5))
    return f"HTTP {r.status_code} in {round((time.perf_counter() - t) * 1000)} ms"


def chat() -> str:
    out = []
    for q, lang in (("How do I extend my D-2 visa?", "en"), ("기숙사 신청은 언제까지?", "ko")):
        t = time.perf_counter()
        r = c.post("/assistant/chat", json=dict(message=q, language=lang))
        out.append(f"{lang} {r.status_code} {round((time.perf_counter() - t) * 1000)} ms")
    return ", ".join(out)


def agents() -> str:
    n = 0
    for agent, tool, p in (("immigration", "visa_checklist", {"topic": "extension"}), ("events", "event_search", {}), ("scholarship", "scholarship_search", {}), ("reception", "upcoming_deadlines", {})):
        n += c.post(f"/agents/{agent}/tools", headers=H, json=dict(tool=tool, params=p)).status_code == 200
    t = c.post("/agents/events/tasks", headers=H, json=dict(task_type="event_digest")).json()
    for _ in range(300):
        if c.get(f"/agent-tasks/{t['id']}", headers=H).json()["status"] in ("completed", "failed"):
            break
        time.sleep(1)
    status = c.get(f"/agent-tasks/{t['id']}", headers=H).json()["status"]
    return f"{n}/4 tools, task {status}, directory {c.get('/agents').status_code}"


phase("idle after start", lambda: "started")
phase("first search (loads the embedding model)", single_search)
phase("search again", single_search)
if a.corpus:
    phase("index the 27 public documents", corpus)
for mb in [int(x) for x in a.pdf_mb.split(",") if x]:
    phase(f"upload, extract and index a {mb} MB Korean PDF", lambda mb=mb: upload(mb))
phase("40 searches, 10 in parallel", searches)
phase("chat without a model (sources only)", chat)
phase("agent tools and a background task", agents)
phase("idle at the end", lambda: "done")
