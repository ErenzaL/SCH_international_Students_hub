"""Runtime snapshot for the hosted memory test, and the ingestion concurrency limit."""
from __future__ import annotations

import threading
import time
import uuid
from datetime import UTC, datetime, timedelta

from app.services import runtime


def test_process_memory_reads_proc_files(tmp_path):
    (tmp_path / "smaps_rollup").write_text("Rss:      204800 kB\nPss:      153600 kB\nAnonymous: 102400 kB\n")
    (tmp_path / "status").write_text("VmRSS:\t 204800 kB\nVmHWM:\t 307200 kB\n")
    assert runtime.process_memory(tmp_path) == dict(rss_mb=200, pss_mb=150, anonymous_mb=100, peak_rss_mb=300)
    assert runtime.process_memory(tmp_path / "missing") == dict(rss_mb=None, pss_mb=None, anonymous_mb=None, peak_rss_mb=None)


def test_cgroup_v2_with_limit_and_oom_counters(tmp_path):
    proc, root = tmp_path / "proc", tmp_path / "cg"
    proc.mkdir()
    (root / "svc").mkdir(parents=True)
    (proc / "cgroup").write_text("0::/svc\n")
    (root / "svc/memory.current").write_text(str(300 * 1024 * 1024))
    (root / "svc/memory.max").write_text(str(512 * 1024 * 1024))
    (root / "svc/memory.peak").write_text(str(480 * 1024 * 1024))
    (root / "svc/memory.events").write_text("low 0\nhigh 0\nmax 7\noom 1\noom_kill 1\n")
    cg = runtime.container_memory(runtime.cgroup_memory(root, proc))
    assert cg == dict(version=2, current_mb=300, limit_mb=512, peak_mb=480, oom=1, oom_kill=1, max_events=7, is_container=True)


def test_cgroup_without_limit_is_not_a_container(tmp_path):
    proc, root = tmp_path / "proc", tmp_path / "cg"
    proc.mkdir()
    root.mkdir()
    (proc / "cgroup").write_text("0::/\n")
    (root / "memory.current").write_text("1048576")
    (root / "memory.max").write_text("max\n")
    cg = runtime.container_memory(runtime.cgroup_memory(root, proc))
    assert cg is not None and cg["limit_mb"] is None and cg["is_container"] is False
    assert runtime.cgroup_memory(tmp_path / "none", proc) is None


def test_runtime_endpoint_is_admin_only_and_stable(env):
    url = "/api/v1/admin/system/runtime"
    assert env.client.get(url).status_code == 401
    assert env.client.get(url, headers=env.auth("student")).status_code == 403
    a = env.client.get(url, headers=env.auth("admin")).json()
    b = env.client.get(url, headers=env.auth("admin")).json()
    assert a["instance"]["instance_id"] == b["instance"]["instance_id"]       # changes only with a new process
    assert a["ingestion"] == dict(limit=1, active=0, waiting=0)
    assert set(a) >= {"memory", "cgroup", "allocator", "workers", "queues", "stale"}


def test_stale_running_jobs_are_counted_not_changed(env):
    old = (datetime.now(UTC) - timedelta(seconds=600)).isoformat()
    fresh = datetime.now(UTC).isoformat()
    for hb in (old, fresh):
        env.store.insert("ingestion_jobs", dict(id=str(uuid.uuid4()), source_id=str(uuid.uuid4()), status="running", heartbeat_at=hb,
                                                trigger="manual", payload={}, statistics={}, job_type="ingest"))
    s = runtime.stale_running(env.store, env.settings)
    assert s["jobs"]["running"] == 2 and s["jobs"]["stale"] == 1 and s["jobs"]["oldest_heartbeat_seconds"] >= 600
    from app.repositories.base import Query

    assert env.store.select("ingestion_jobs", Query(eq={"status": "running"}, limit=10), count=True)[1] == 2


def _queued_jobs(env, n):
    ids = []
    for _ in range(n):
        jid = str(uuid.uuid4())
        env.store.insert("ingestion_jobs", dict(id=jid, source_id=str(uuid.uuid4()), status="queued", trigger="manual", payload={}, statistics={},
                                                job_type="ingest"))
        ids.append(jid)
    return ids


def test_at_most_one_ingestion_job_runs_at_a_time(env, monkeypatch):
    ing = env.app.state.services.ingestion
    now, peak, lock = [0], [0], threading.Lock()

    def slow(job):
        with lock:
            now[0] += 1
            peak[0] = max(peak[0], now[0])
        time.sleep(0.05)
        with lock:
            now[0] -= 1
        return job

    monkeypatch.setattr(ing, "_execute", slow)
    threads = [threading.Thread(target=ing.run_job, args=(j,)) for j in _queued_jobs(env, 4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    assert peak[0] == 1 and ing.slots() == dict(limit=1, active=0, waiting=0)


def test_a_job_started_inside_a_running_job_does_not_deadlock(env, monkeypatch):
    ing = env.app.state.services.ingestion
    outer, inner = _queued_jobs(env, 2)
    seen = []

    def body(job):
        seen.append(job["id"])
        if job["id"] == outer:
            ing.run_job(inner)          # e.g. an inline enqueue from inside a job
        return job

    monkeypatch.setattr(ing, "_execute", body)
    t = threading.Thread(target=ing.run_job, args=(outer,))
    t.start()
    t.join(5)
    assert not t.is_alive() and seen == [outer, inner]
