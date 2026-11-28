"""Hosted memory test for STAGING (or a local server): synthetic uploads, asynchronous processing, and what happens to the API meanwhile.

    backend/.venv/bin/python scripts/staging_bootstrap.py info --info ~/sch-staging.json     # fresh tokens first (they last an hour)
    backend/.venv/bin/python scripts/staging_memory_check.py ~/sch-staging.json --report ~/staging-memory.json

What it does, only with invented data (scripts/synthetic_docs.py) and only on loopback or a hosted copy marked ``staging`` in the info
file (never the production addresses):
  1. wakes the API, loads the model with one search, takes a baseline;
  2. uploads synthetic Korean PDFs (default 3 and 9 MB) and submits synthetic text documents, all at once: every request must be
     answered at once (202/201) while the work waits in the queue;
  3. approves what was extracted, so the indexing jobs run too;
  4. every POLL seconds until everything finished: /health and a search (responsiveness), /api/v1/admin/system/runtime (memory,
     container out-of-memory counter, instance id = restarts, ingestion slots in use, stale running jobs, stuck queues);
  5. waits IDLE seconds and takes the final snapshot (memory recovery).
Checks: asynchronous uploads, jobs succeeded, concurrency within the limit, responsiveness, no restart, no out-of-memory kill, peak
memory, recovery after the work, nothing stuck, MALLOC_ARENA_MAX set. Exit code 1 when any check FAILs. Without the runtime endpoint
(an older build) memory and restarts are SKIPped: read them in Render → Metrics and Events instead.
The synthetic documents stay on staging as pending/approved test content titled "Synthetic test …"; nothing is deleted.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
import synthetic_docs  # noqa: E402

PRODUCTION = ("sch-hub-api.onrender.com", "sch-international-students-hub.onrender.com")
TERMINAL = ("succeeded", "failed", "cancelled")
QUERIES = ["기숙사 입사 신청", "D-2 extension documents", "장학금 신청 기간", "part-time work permit", "건강보험", "course registration period"]


def target(info: dict[str, Any]) -> str:
    """The API base URL, or SystemExit for anything that is not loopback or a hosted staging copy."""
    api = str(info.get("api") or "").rstrip("/")
    host = urlparse(api).hostname or ""
    prod_ref = str(info.get("production_ref") or "")
    if host in PRODUCTION or (prod_ref and prod_ref in api):
        raise SystemExit(f"REFUSED: {host} is production")
    if api.startswith("http://127.0.0.1:"):
        return api
    if info.get("staging") is True and api.startswith("https://") and "staging" in host:
        return api
    raise SystemExit("REFUSED: loopback or a hosted copy marked staging (written by staging_bootstrap.py) only")


def auth_ok(info: dict[str, Any]) -> bool:
    """Where the password may be sent: the local sign-in stub or the staging project, never production."""
    auth = str(info.get("auth") or "").rstrip("/")
    ref, prod = str(info.get("staging_ref") or ""), str(info.get("production_ref") or "")
    if prod and prod in auth:
        return False
    return auth.startswith("http://127.0.0.1:") or bool(ref and info.get("staging") is True and auth == f"https://{ref}.supabase.co")


def pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    return round(s[min(len(s) - 1, int(round(q * (len(s) - 1))))], 2)


class Check:
    def __init__(self, info: dict[str, Any], a: argparse.Namespace):
        self.a = a
        self.api = target(info)
        # the Render memory probe (backend/app/memory_probe.py) answers only with its key; never sent anywhere but target()
        extra = {"X-Probe-Key": str(info["probe_key"])} if info.get("probe_key") else {}
        self.c = httpx.Client(base_url=self.api, timeout=a.timeout, trust_env=False, headers=extra)
        token = (info.get("tokens") or {}).get("super_admin") or (info.get("tokens") or {}).get("admin")
        if not token:
            raise SystemExit("the info file has no admin token: run staging_bootstrap.py info first")
        self.h = {"Authorization": f"Bearer {token}"}
        self.info = info
        self.samples: list[dict[str, Any]] = []
        self.requests: list[dict[str, Any]] = []
        self.runtime_available = True

    # ----------------------------------------------------------------- probes
    def timed(self, method: str, path: str, **kw: Any) -> tuple[httpx.Response | None, float]:
        t = time.perf_counter()
        try:
            r = self.c.request(method, path, **kw)
            if r.status_code == 401 and "headers" in kw and self.relogin():     # sign-in tokens last about an hour; the test runs longer
                kw["headers"] = self.h
                r = self.c.request(method, path, **kw)
        except httpx.HTTPError:
            r = None
        return r, round(time.perf_counter() - t, 2)

    def relogin(self) -> bool:
        """Sign the made-up super_admin in again (password from the info file, same way as staging_bootstrap.py info)."""
        i = self.info
        if not (i.get("auth") and i.get("password")) or not auth_ok(i):
            return False
        email = f"super_admin@{i.get('email_domain') or 'example.test'}"
        try:
            r = httpx.post(f"{i['auth'].rstrip('/')}/auth/v1/token", params={"grant_type": "password"}, headers={"apikey": i.get("anon_key") or "local"},
                           json=dict(email=email, password=i["password"]), timeout=30, trust_env=False)
        except httpx.HTTPError:
            return False
        if r.status_code != 200:
            return False
        self.h["Authorization"] = f"Bearer {r.json()['access_token']}"
        print("  signed in again (the previous token expired)")
        return True

    def runtime(self) -> dict[str, Any] | None:
        if not self.runtime_available:
            return None
        r, _ = self.timed("GET", "/api/v1/admin/system/runtime", headers=self.h)
        if r is not None and r.status_code == 404:
            self.runtime_available = False
            print("  the API has no /admin/system/runtime (an older build): memory and restarts come from Render's Metrics/Events")
            return None
        if r is None or r.status_code == 401:
            if r is not None:
                raise SystemExit("not signed in and signing in again failed: run staging_bootstrap.py info again, then restart this check")
            return None
        return r.json() if r.status_code == 200 else None

    def sample(self, label: str, search: bool = True) -> dict[str, Any]:
        h, ht = self.timed("GET", "/health")
        s, st = (self.timed("POST", "/api/v1/knowledge/search", json=dict(query=QUERIES[len(self.samples) % len(QUERIES)], top_k=5))
                 if search else (None, None))
        rt = self.runtime()
        row: dict[str, Any] = dict(t=round(time.time() - self.t0, 1), label=label, health_ok=bool(h is not None and h.status_code == 200),
                                   health_s=ht, search_ok=None if not search else bool(s is not None and s.status_code == 200), search_s=st)
        if rt:
            cg = rt.get("cgroup") or {}
            row.update(instance=rt["instance"]["instance_id"], rss_mb=rt["memory"].get("rss_mb"), pss_mb=rt["memory"].get("pss_mb"),
                       peak_rss_mb=rt["memory"].get("peak_rss_mb"),     # high-water mark: also catches spikes between two polls
                       container_mb=cg.get("current_mb") if cg.get("is_container") else None,
                       container_peak_mb=cg.get("peak_mb") if cg.get("is_container") else None,
                       oom_kill=cg.get("oom_kill") if cg.get("is_container") else None,
                       slots_active=(rt.get("ingestion") or {}).get("active"), slots_limit=(rt.get("ingestion") or {}).get("limit"),
                       jobs_running=((rt.get("queues") or {}).get("jobs") or {}).get("running"),
                       stale=sum(((rt.get("stale") or {}).get(k) or {}).get("stale", 0) for k in ("jobs", "agent_tasks")),
                       stuck=any((q or {}).get("stuck") for q in (rt.get("queues") or {}).values()),
                       arena=(rt.get("allocator") or {}).get("malloc_arena_max"), worker_alive=(rt.get("workers") or {}).get("ingestion_alive"))
        self.samples.append(row)
        return row

    # ----------------------------------------------------------------- work
    def submit(self) -> list[dict[str, Any]]:
        salt = uuid.uuid4().hex[:8]
        items: list[dict[str, Any]] = []
        for mb in [int(x) for x in self.a.pdf_mb.split(",") if x]:
            path = synthetic_docs.make_pdf(mb, self.a.pdf_dir, salt=salt)
            s, _ = self.timed("POST", "/api/v1/admin/sources", headers=self.h, json=dict(
                title=f"Synthetic test PDF {mb} MB {salt}", organization="SYNTHETIC TEST", source_type="pdf",
                authority_type="official_university", scope="university", category="daily-living", language="ko"))
            if s is None or s.status_code not in (200, 201):
                items.append(dict(kind="pdf", name=path.name, accepted=False, http=None if s is None else s.status_code, seconds=None))
                continue
            r, sec = self.timed("POST", f"/api/v1/admin/sources/{s.json()['id']}/upload", headers=self.h,
                                files={"file": (path.name, path.read_bytes(), "application/pdf")})
            items.append(dict(kind="pdf", name=path.name, bytes=path.stat().st_size, http=None if r is None else r.status_code, seconds=sec,
                              accepted=bool(r is not None and r.status_code == 202), job=(r.json().get("job_id") if r is not None and r.status_code == 202 else None)))
        for title, text in synthetic_docs.text_documents(self.a.text_docs, salt=salt):
            s, _ = self.timed("POST", "/api/v1/admin/sources", headers=self.h, json=dict(
                title=title, organization="SYNTHETIC TEST", source_type="manual_text", authority_type="official_university",
                scope="university", category="daily-living", language="ko"))
            if s is None or s.status_code not in (200, 201):
                items.append(dict(kind="text", name=title, accepted=False, http=None if s is None else s.status_code, seconds=None))
                continue
            r, sec = self.timed("POST", f"/api/v1/admin/sources/{s.json()['id']}/submit-text", headers=self.h, json=dict(title=title, text=text))
            ok = r is not None and r.status_code in (200, 201)
            items.append(dict(kind="text", name=title, chars=len(text), http=None if r is None else r.status_code, seconds=sec, accepted=ok,
                              version=(r.json().get("version_id") if ok else None)))
        return items

    def job(self, job_id: str) -> dict[str, Any] | None:
        r, _ = self.timed("GET", f"/api/v1/admin/ingestion-jobs/{job_id}", headers=self.h)
        return r.json() if r is not None and r.status_code == 200 else None

    def approve(self, version_id: str) -> str | None:
        r, _ = self.timed("POST", f"/api/v1/admin/versions/{version_id}/approve", headers=self.h, json={})
        return r.json().get("indexing_job_id") if r is not None and r.status_code in (200, 202) else None

    def run(self) -> dict[str, Any]:
        self.t0 = time.time()
        woke = None
        for _ in range(60):                                      # a sleeping free service takes about a minute
            r, _s = self.timed("GET", "/health")
            if r is not None and r.status_code == 200:
                woke = round(time.time() - self.t0, 1)
                break
            time.sleep(5)
        if woke is None:
            raise SystemExit("the API did not answer /health within 5 minutes")
        print(f"  awake after {woke} s")
        warm = self.sample("model load (first search)")
        print(f"  first search {warm['search_s']} s")
        base = self.sample("baseline")
        items = self.submit()
        print(f"  submitted {sum(i['accepted'] for i in items)}/{len(items)}: " + ", ".join(f"{i['name'][:28]} {i['http']} {i['seconds']} s" for i in items))
        pending = {i["job"]: i for i in items if i.get("job")}
        for i in items:                                      # text submissions: approve now (indexing job)
            if i["kind"] == "text" and i.get("version"):
                ij = self.approve(i["version"])
                if ij:
                    pending[ij] = dict(i, kind="text-index")
        jobs: dict[str, dict[str, Any]] = {}
        deadline = time.time() + self.a.max_minutes * 60
        n = 0
        while pending and time.time() < deadline:
            time.sleep(self.a.poll)
            n += 1
            row = self.sample("working", search=n % 2 == 0)
            for jid in list(pending):
                j = self.job(jid)
                if j is None or j["status"] not in TERMINAL:
                    continue
                item = pending.pop(jid)
                jobs[jid] = dict(kind=item["kind"], name=item["name"], status=j["status"], error=j.get("error_code"),
                                 attempts=j.get("attempts"), done_after_s=round(time.time() - self.t0))
                if item["kind"] == "pdf" and j["status"] == "succeeded" and j.get("version_id"):
                    ij = self.approve(j["version_id"])
                    if ij:
                        pending[ij] = dict(item, kind="pdf-index")
            print(f"  {row['t']:>6} s  memory {row.get('container_mb') or row.get('rss_mb')} MB  health {row['health_s']} s  "
                  f"slots {row.get('slots_active')}/{row.get('slots_limit')}  waiting {len(pending)}  done {len(jobs)}", flush=True)
        for jid, item in pending.items():
            j = self.job(jid) or {}
            jobs[jid] = dict(kind=item["kind"], name=item["name"], status=j.get("status", "unknown"), error="timeout", attempts=j.get("attempts"))
        print(f"  idle {self.a.idle} s for the recovery snapshot")
        time.sleep(self.a.idle)
        final = self.sample("after idle")
        return dict(api=self.api, woke_after_s=woke, warm=warm, baseline=base, final=final, items=items, jobs=jobs, samples=self.samples,
                    checks=evaluate(self.samples, items, jobs, warm, base, final, self.a), runtime_endpoint=self.runtime_available)


def evaluate(samples: list[dict[str, Any]], items: list[dict[str, Any]], jobs: dict[str, dict[str, Any]], warm: dict[str, Any],
             base: dict[str, Any], final: dict[str, Any], a: Any) -> list[dict[str, str]]:
    """PASS / WARN / FAIL / SKIP per check, from the recorded samples only (no network): unit-tested."""
    out: list[dict[str, str]] = []

    def add(name: str, status: str, detail: str) -> None:
        out.append(dict(check=name, status=status, detail=detail))

    pdfs = [i for i in items if i["kind"] == "pdf"]
    slow = [i for i in pdfs if i.get("seconds") is not None and i["seconds"] > a.max_submit_seconds]
    refused = [i for i in items if not i.get("accepted")]
    add("uploads are asynchronous", "FAIL" if refused or slow or not pdfs else "PASS",
        f"{len(items) - len(refused)}/{len(items)} accepted; slowest PDF upload answered in {max((i['seconds'] or 0) for i in pdfs) if pdfs else None} s "
        f"(limit {a.max_submit_seconds} s, the work itself is queued)")
    texts = [i["seconds"] for i in items if i["kind"] == "text" and i.get("seconds") is not None]
    if texts:   # pasted text is split into passages inside the request (by design); embedding waits for approval
        add("pasted text is processed in the request", "WARN" if max(texts) > a.max_submit_seconds else "PASS",
            f"slowest {max(texts)} s for {max(i.get('chars', 0) for i in items if i['kind'] == 'text'):,} characters")
    bad = [f"{j['name'][:30]} {j['status']} {j.get('error') or ''}".strip() for j in jobs.values() if j["status"] != "succeeded"]
    add("all jobs succeeded", "FAIL" if bad or not jobs else "PASS", f"{len(jobs) - len(bad)}/{len(jobs)}" + (f"; {'; '.join(bad[:5])}" if bad else ""))
    rt = [s for s in samples if "instance" in s]
    if rt:
        over = [s for s in rt if (s.get("slots_active") or 0) > (s.get("slots_limit") or 1) or (s.get("jobs_running") or 0) > (s.get("slots_limit") or 1)]
        add("ingestion concurrency within the limit", "FAIL" if over else "PASS",
            f"most at once: {max((s.get('jobs_running') or 0) for s in rt)} running job(s), limit {rt[-1].get('slots_limit')}")
    else:
        add("ingestion concurrency within the limit", "SKIP", "no runtime endpoint")
    health = [s["health_s"] for s in samples if s["health_s"] is not None]
    hfail = sum(1 for s in samples if not s["health_ok"])
    p95 = pct(health, 0.95)
    add("API stays responsive (/health)", "FAIL" if hfail or (p95 or 0) > a.max_health_seconds else "WARN" if (p95 or 0) > a.max_health_seconds / 2 else "PASS",
        f"{hfail} failed of {len(samples)}; p95 {p95} s, worst {max(health) if health else None} s (limit {a.max_health_seconds} s)")
    srch = [s["search_s"] for s in samples[2:] if s.get("search_s") is not None and s.get("search_ok")]
    sfail = sum(1 for s in samples[2:] if s.get("search_ok") is False)
    sp95 = pct(srch, 0.95)
    add("search stays usable during processing", "FAIL" if sfail or (sp95 or 0) > a.max_search_seconds else "PASS",
        f"{sfail} failed of {len([s for s in samples[2:] if s.get('search_ok') is not None])}; p95 {sp95} s, median "
        f"{round(statistics.median(srch), 2) if srch else None} s (limit {a.max_search_seconds} s)")
    if rt:
        instances = list(dict.fromkeys(s["instance"] for s in rt))
        add("no restart", "FAIL" if len(instances) > 1 else "PASS", f"{len(instances) - 1} restart(s) seen ({len(rt)} snapshots)")
        kills = [s["oom_kill"] for s in rt if s.get("oom_kill") is not None]
        if kills:
            add("no out-of-memory kill (container)", "FAIL" if kills[-1] > kills[0] else "PASS",
                f"oom_kill {kills[0]} → {kills[-1]} (a PDF extraction child killed by the kernel counts too)")
        else:
            add("no out-of-memory kill (container)", "SKIP", "the host does not expose the container's memory events: check Render → Events")
        cont = [s.get("container_peak_mb") or s.get("container_mb") for s in rt if s.get("container_mb") is not None]
        mem = cont or [max(s.get("rss_mb") or 0, s.get("peak_rss_mb") or 0) for s in rt if s.get("rss_mb") is not None]
        what = "container (includes the PDF child process)" if cont else "API process RSS (without the PDF child process)"
        peak = max(mem) if mem else None
        add("peak memory", "SKIP" if peak is None else "PASS" if peak <= a.warn_mb else "WARN" if peak <= a.limit_mb else "FAIL",
            f"{peak} MB, {what}; pass ≤ {a.warn_mb}, limit {a.limit_mb}")
        w = warm.get("container_mb") or warm.get("rss_mb")
        f = final.get("container_mb") or final.get("rss_mb")
        if w and f and peak and peak > w:
            share = (peak - f) / (peak - w)
            add("memory recovers after the work", "PASS" if share >= 0.5 and f <= a.recovered_mb else "WARN",
                f"{w} MB after the model, {peak} MB peak, {f} MB after {a.idle} s idle: {round(share * 100)} % given back "
                f"(pass ≥ 50 % and ≤ {a.recovered_mb} MB)")
        else:
            add("memory recovers after the work", "SKIP", "not enough memory samples")
        stale_end = final.get("stale") or 0
        stuck = any(s.get("stuck") for s in rt)
        dead = any(s.get("worker_alive") is False for s in rt[1:])
        left = [j for j in jobs.values() if j["status"] not in TERMINAL]
        add("nothing stuck", "FAIL" if stale_end or stuck or left or dead else "PASS",
            f"stale running at the end {stale_end}; stuck queue {stuck}; unfinished {len(left)}; worker thread stopped {dead}")
        arena = rt[-1].get("arena")
        add("MALLOC_ARENA_MAX=2 is set", "PASS" if arena == "2" else "WARN", f"MALLOC_ARENA_MAX={arena!r}")
    else:
        for name in ("no restart", "no out-of-memory kill (container)", "peak memory", "memory recovers after the work", "MALLOC_ARENA_MAX=2 is set"):
            add(name, "SKIP", "no runtime endpoint: read Render → Metrics (memory) and Events (restarts, 'Out of memory')")
        left = [j for j in jobs.values() if j["status"] not in TERMINAL]
        add("nothing stuck", "FAIL" if left else "PASS", f"unfinished {len(left)}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("info", type=Path)
    ap.add_argument("--report", type=Path, required=True)
    ap.add_argument("--pdf-mb", default="3,9")
    ap.add_argument("--text-docs", type=int, default=12)
    ap.add_argument("--pdf-dir", type=Path, default=Path.home() / "sch-test-pdfs")
    ap.add_argument("--poll", type=float, default=20.0)
    ap.add_argument("--idle", type=float, default=180.0)
    ap.add_argument("--max-minutes", type=float, default=120.0)
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--max-submit-seconds", type=float, default=30.0)
    ap.add_argument("--max-health-seconds", type=float, default=5.0)
    ap.add_argument("--max-search-seconds", type=float, default=20.0)
    ap.add_argument("--warn-mb", type=int, default=470)
    ap.add_argument("--limit-mb", type=int, default=512)
    ap.add_argument("--recovered-mb", type=int, default=420)
    a = ap.parse_args()
    info = json.loads(a.info.read_text())
    out = Check(info, a).run()
    a.report.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print()
    for c in out["checks"]:
        print(f"  {c['status']:<4}  {c['check']}: {c['detail']}")
    print(f"\n  report: {a.report}")
    sys.exit(1 if any(c["status"] == "FAIL" for c in out["checks"]) else 0)


if __name__ == "__main__":
    main()
