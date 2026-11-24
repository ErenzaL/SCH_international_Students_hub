"""End-to-end test of the GPU worker with the REAL local model and SYNTHETIC data (no Supabase, loopback only).

    cd backend && .venv/bin/python ../scripts/e2e_gpu_worker.py --worker-python .venv-gpu/bin/python

Starts the real API (in-memory store) on 127.0.0.1 and the worker as its own process, then checks: drafts in all
languages, document translation and summary, worker killed and restarted (lease), SIGTERM (job handed back), Hub
offline, cancel, pause, rotation, revocation, human approval as the only way to publication, and the logs.
"""
from __future__ import annotations

import argparse
import atexit
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

import dev_ollama_backend as dev  # refuses to run next to Supabase variables; ignores .env files
import httpx
import jwt
import uvicorn

BACKEND = Path(__file__).resolve().parents[1] / "backend"
NOTICES = [
    ("[가상] 국제학생 장학금 신청 안내", "국제학생 장학금 신청을 받습니다. 신청 기간은 2026-12-01부터 2026-12-15 18:00까지입니다.\n\n"
     "- 지원 금액: 500,000원\n- 제출 서류: 신청서, 성적증명서, 여권 사본\n\n신청서는 https://example.ac.kr/apply 에서 제출하세요.\n\n"
     "문의: intl@example.ac.kr, 041-000-1234"),
    ("[가상] D-2 체류기간 연장 안내", "D-2 체류자격 학생은 만료 전에 연장을 신청해야 합니다.\n\n- 준비 서류: 여권, 외국인등록증, 재학증명서\n"
     "- 수수료: 60,000원\n\n만료일이 지나면 과태료가 부과될 수 있습니다. 본인이 직접 신청해야 합니다."),
]
LANGS = ("en", "id", "vi", "zh-CN")
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: object, detail: object = "") -> None:
    results.append((name, bool(ok), str(detail)))
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}", flush=True)


class Env:
    def __init__(self, worker_python: str):
        from app.core.config import Settings
        from app.main import create_app
        from app.repositories.memory_store import MemoryFileStorage, MemoryStore, seed_categories

        secret = uuid.uuid4().hex + uuid.uuid4().hex
        self.settings = Settings(
            _env_file=None, environment="test", supabase_url="", supabase_service_role_key="", supabase_jwt_secret=secret,
            llm_provider="none", background_llm_provider="", embedding_provider="hash", job_execution="inline",
            gpu_worker_enabled=True, gpu_worker_lease_seconds=30, public_machine_translations=True,
            agent_schedules_enabled=False, auto_translate_announcements=False, allowed_source_domains="", cron_secret="")
        self.store = MemoryStore()
        seed_categories(self.store)
        self.auth = {}
        for role in ("super_admin", "admin", "student"):
            uid = str(uuid.uuid4())
            self.store.insert("profiles", dict(id=uid, email=f"{role}@example.test", display_name=role, role=role))
            self.auth[role] = {"Authorization": "Bearer " + jwt.encode(
                {"sub": uid, "aud": "authenticated", "exp": int(time.time()) + 7200}, secret, algorithm="HS256")}
        self.app = create_app(self.settings, store=self.store, storage=MemoryFileStorage())
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self.http = httpx.Client(base_url=self.url, timeout=60, trust_env=False)
        self.dir = Path(tempfile.mkdtemp(prefix="gpu-e2e-"))
        self.token, self.log = self.dir / "token", self.dir / "worker.log"
        self.worker_python = worker_python
        self.server: uvicorn.Server | None = None
        self.rss, self.cpu, self.wall = 0, 0.0, 0.0

    def up(self) -> None:
        self.server = uvicorn.Server(uvicorn.Config(self.app, host="127.0.0.1", port=self.port, log_level="warning",
                                                    lifespan="off"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        while not self.server.started:
            time.sleep(0.05)

    def down(self) -> None:
        assert self.server
        self.server.should_exit = True
        self.thread.join(10)

    def api(self, method: str, path: str, role: str | None = "super_admin", **kw):  # type: ignore[no-untyped-def]
        return self.http.request(method, "/api/v1" + path, headers=self.auth[role] if role else {}, **kw)

    def save_token(self, token: str) -> None:
        self.token.touch(mode=0o600)
        self.token.write_text(token)

    def worker(self, *args: str, **env: str) -> subprocess.Popen:  # type: ignore[type-arg]
        e = {"PATH": os.environ["PATH"], "HOME": str(self.dir), "GPU_WORKER_HUB_URL": self.url,
             "GPU_WORKER_TOKEN_FILE": str(self.token), "GPU_WORKER_IDLE_MIN_SECONDS": "5",
             "GPU_WORKER_IDLE_MAX_SECONDS": "5"} | env
        p = subprocess.Popen([self.worker_python, "-m", "app.gpu_worker", *args], cwd=BACKEND, env=e,
                                stdout=self.log.open("a"), stderr=subprocess.STDOUT)
        atexit.register(lambda: p.poll() is None and p.terminate())
        return p

    def drain(self) -> int:
        p = self.worker("--drain")
        ticks, hz = 0.0, os.sysconf("SC_CLK_TCK")
        t0 = time.time()
        while p.poll() is None:
            try:
                rss = next(int(x.split()[1]) for x in Path(f"/proc/{p.pid}/status").read_text().splitlines() if x.startswith("VmRSS"))
                f = Path(f"/proc/{p.pid}/stat").read_text().rsplit(")", 1)[1].split()
                ticks = (int(f[11]) + int(f[12])) / hz
                self.rss = max(self.rss, rss)
            except (OSError, StopIteration, ValueError):
                break
            time.sleep(0.2)
        rc = p.wait(600)
        self.cpu, self.wall = self.cpu + ticks, self.wall + time.time() - t0
        return rc

    def publish(self, title: str, body: str) -> str:
        r = self.api("POST", "/admin/announcements", json=dict(
            title=title, body=body, category="scholarships", original_language="ko", submit=True, source_type="manual_text",
            target_audience="All", evidence_note="SYNTHETIC", event_date=None, deadline=None))
        assert r.status_code == 201, r.text
        assert self.api("POST", f"/admin/announcements/{r.json()['id']}/approve", json={}).status_code == 200
        return r.json()["id"]

    def document(self, title: str, text: str) -> str:
        r = self.api("POST", "/admin/sources", json=dict(
            title=title, organization="SYNTHETIC", source_type="manual_text", authority_type="official_university",
            scope="university", category="academic-life", language="ko"))
        job = self.api("POST", f"/admin/sources/{r.json()['id']}/submit-text",
                       json=dict(title=title, text=text, authorized_by_supporter=True)).json()
        assert self.api("POST", f"/admin/versions/{job['version_id']}/approve", json={}).status_code == 202
        return job["document_id"]

    def request(self, aid: str, lang: str, **params: object) -> str:
        r = self.api("POST", f"/admin/announcements/{aid}/translations/{lang}/machine-translate", params=params)
        assert r.status_code == 202, r.text
        return r.json()["job_id"]

    def job(self, jid: str) -> dict:  # type: ignore[type-arg]
        return next(j for j in self.store.t["ingestion_jobs"] if j["id"] == jid)

    def wait(self, cond, seconds: float = 60) -> bool:  # type: ignore[no-untyped-def]
        end = time.time() + seconds
        while time.time() < end:
            if cond():
                return True
            time.sleep(0.1)
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--worker-python", default=sys.executable)
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    e = Env(str(Path(args.worker_python).absolute()))
    e.up()
    w = e.api("POST", "/admin/gpu/workers", json=dict(name="school-e2e")).json()
    e.save_token(w["token"])
    tokens = [w["token"]]
    r = e.api("POST", "/admin/gpu/jobs/queue-missing", json=dict(dry_run=False))
    check("nothing is queued before a worker was ever seen", r.status_code == 409, r.json()["error"]["code"])
    check("first contact", e.drain() == 0 and e.api("GET", "/admin/gpu/status", "admin").json()["available"])

    # 1. drafts in every language
    ids = [e.publish(*n) for n in NOTICES]
    plan = e.api("POST", "/admin/gpu/jobs/queue-missing", json={}).json()
    check("dry run lists the missing languages", plan["missing"] == 8 and plan["dry_run"])
    e.api("POST", "/admin/gpu/jobs/queue-missing", json=dict(dry_run=False, limit=50))
    t0 = time.time()
    code = e.drain()
    rows = e.store.t["announcement_translations"]
    check("8 drafts generated on the GPU", code == 0 and [r["translation_status"] for r in rows] == ["needs_review"] * 8,
          f"{time.time() - t0:.1f}s")
    clean = sum(not r["warnings"] for r in rows)
    check("drafts name the local model", all((r["provider"], r["model"]) == ("ollama", "qwen2.5:7b-instruct") for r in rows),
          f"{clean}/8 without a check warning")
    check("nothing is public", all(e.api("GET", f"/announcements/{a}", None, params={"lang": x}).json()["translation"] is None
                                   for a in ids for x in LANGS))
    # 2. only a person publishes
    tok = {"Authorization": f"Bearer {w['token']}"}
    codes = [e.http.post(f"/api/v1/admin/announcements/{ids[0]}/translations/en/approve", headers=tok,
                         json=dict(original_verified=True)).status_code,
             e.http.post(f"/api/v1/admin/announcements/{ids[0]}/approve", headers=tok, json={}).status_code,
             e.http.get("/api/v1/admin/overview", headers=tok).status_code]
    check("the worker credential cannot approve, publish or read", set(codes) <= {401, 403}, codes)
    e.api("POST", f"/admin/announcements/{ids[0]}/translations/en/approve", json=dict(original_verified=True))
    check("a reviewer can", e.api("GET", f"/announcements/{ids[0]}", None, params={"lang": "en"}).json()["translation"]["status"] == "verified")
    # 3. documents: translation and summary
    short = e.document("[가상] 기숙사 안내", "입사일은 2027-02-24이며 10:00부터 17:00까지 입사할 수 있습니다. 결핵 검사 결과서를 제출하세요.")
    long = e.document("[가상] 유학생 생활 안내", "\n\n".join(
        f"# {i}장\n\n{i}장의 내용입니다. 유학생은 도서관을 09:00부터 22:00까지 이용할 수 있습니다. 셔틀버스는 평일에 운행합니다. "
        "외국인등록은 입국 후 90일 이내에 해야 합니다. 문의는 intl@example.ac.kr 로 하세요." * 3 for i in range(1, 70)))
    for d in (short, long):
        assert e.api("POST", f"/admin/documents/{d}/translations/drafts", json=dict(languages=["en"])).status_code == 202
    e.drain()
    docs = {t["document_id"]: t for t in e.store.t["document_translations"] if t["translation_status"] != "todo"}
    check("document translation draft", docs.get(short, {}).get("scope") == "full" and docs[short]["translation_status"] == "needs_review")
    check("AI summary draft of a long document", docs.get(long, {}).get("scope") == "summary"
          and docs[long]["translation_status"] == "needs_review", f"{len(docs.get(long, {}).get('body', ''))} characters")
    # 4. power cut: killed in the middle, lease ends, restarted worker finishes
    third = e.publish("[가상] 건강보험 안내", "국민건강보험료는 매월 25일까지 납부해야 합니다.\n\n" * 12)
    jid = e.request(third, "vi")
    p = e.worker()
    ok = e.wait(lambda: e.job(jid)["status"] == "running")
    p.send_signal(signal.SIGKILL)
    p.wait()
    t0 = time.time()
    p = e.worker()
    done = e.wait(lambda: e.job(jid)["status"] == "succeeded", 90)
    check("killed worker: the job resumes after the lease", ok and done and e.job(jid)["attempts"] == 2, f"{time.time() - t0:.0f}s")
    # 5. SIGTERM hands the job back at once
    jid = e.request(third, "id")
    e.wait(lambda: e.job(jid)["status"] == "running")
    time.sleep(0.5)
    p.terminate()
    t0 = time.time()
    rc = p.wait(60)
    check("SIGTERM hands the job back", rc == 0 and (e.job(jid)["status"], e.job(jid)["attempts"]) == ("queued", 0), f"{time.time() - t0:.1f}s")
    # 6. Hub offline, then back
    e.down()
    p = e.worker()
    time.sleep(6)
    alive = p.poll() is None
    e.up()
    check("Hub offline: the worker waits and resumes", alive and e.wait(lambda: e.job(jid)["status"] == "succeeded", 120))
    # 7. cancel while running
    jid = e.request(third, "en")
    e.wait(lambda: e.job(jid)["status"] == "running")
    r = e.api("POST", f"/admin/gpu/jobs/{jid}/cancel", "admin").json()
    check("cancel", e.wait(lambda: e.job(jid)["error_code"] == "cancelled", 40) and not any(
        x["translation_status"] != "todo" for x in rows_of(e, third, "en")), r["status"])
    # 8. pause / resume
    url = f"/admin/gpu/workers/{w['id']}"
    e.api("PATCH", url, json=dict(status="paused"))
    time.sleep(6)
    r = e.api("POST", f"/admin/announcements/{third}/translations/en/machine-translate")
    check("paused and no other provider: refused, not parked", r.status_code == 409, r.json()["error"]["code"])
    e.api("PATCH", url, json=dict(status="active"))
    jid = e.request(third, "en")
    check("resume", e.wait(lambda: e.job(jid)["status"] == "succeeded", 60))
    # 9. rotation without restart, then revocation
    new = e.api("POST", url + "/rotate", json=dict(grace_minutes=5)).json()["token"]
    tokens.append(new)
    e.save_token(new)
    jid = e.request(third, "zh-CN")
    check("rotation without restart", e.wait(lambda: e.job(jid)["status"] == "succeeded", 60))
    e.api("PATCH", url, json=dict(status="revoked"))
    check("revoked worker stops", p.wait(60) == 77, f"exit {p.returncode}")
    # 10. logs
    log = e.log.read_text()
    secrets = tokens + [n[1] for n in NOTICES] + [r["body"] for r in e.store.t["announcement_translations"] if r["body"]]
    check("worker log has no token and no content", not any(s in log for s in secrets) and "status=succeeded" in log)
    st = e.api("GET", "/admin/gpu/status", "admin").json()
    print(f"\nworker process: peak RSS {e.rss / 1024:.0f} MiB, CPU {e.cpu:.1f} s in {e.wall:.0f} s ({100 * e.cpu / e.wall:.1f} %)")
    print("metrics:", json.dumps(st["last_24h"]))
    listening = subprocess.run(["ss", "-ltn"], capture_output=True, text=True).stdout
    check("Ollama listens on loopback only", "127.0.0.1:11434" in listening and "0.0.0.0:11434" not in listening and "*:11434" not in listening)
    print("\nexample drafts:")
    for r in e.store.t["announcement_translations"][:4]:
        print(f"--- {r['language_code']} {r['warnings']}\n{r['title']}\n{r['body']}")
    e.down()
    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed" + (f"; FAILED: {failed}" if failed else "") + f"; worker log: {e.log}")
    return 1 if failed else 0


def rows_of(e: Env, aid: str, lang: str) -> list[dict]:  # type: ignore[type-arg]
    return [r for r in e.store.t["announcement_translations"] if r["announcement_id"] == aid and r["language_code"] == lang]


_ = dev
if __name__ == "__main__":
    raise SystemExit(main())
