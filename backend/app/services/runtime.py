"""What the API process itself can see of its memory, restarts and workers: for the hosted memory test on staging
(scripts/staging_memory_check.py) and for administrators. Read-only, no personal data, no secrets.

* process memory from /proc/self (Linux): RSS, PSS, anonymous memory, the high-water mark;
* the container's cgroup (v2, then v1), when the host exposes it: current / limit / peak and the out-of-memory event counters.
  ``oom_kill`` grows when the kernel killed a process of the container, e.g. a PDF extraction child, even without a restart;
* ``instance_id`` is new for every process start, so a client that polls sees each restart;
* the worker threads, the ingestion slots in use, and running jobs whose heartbeat stopped.
Everything that is not available on a host is ``None``, never an error.
"""
from __future__ import annotations

import os
import platform
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

INSTANCE_ID = uuid.uuid4().hex[:12]
STARTED_AT = datetime.now(UTC)
_STARTED_MONO = time.monotonic()
MB = 1024 * 1024


def _read(path: Path) -> str | None:
    try:
        return path.read_text()
    except (OSError, ValueError):
        return None


def _kv_kib(text: str | None, *keys: str) -> dict[str, int | None]:
    """'Key:   123 kB' lines -> {key: MB}."""
    out: dict[str, int | None] = dict.fromkeys(keys)
    for line in (text or "").splitlines():
        name, _, rest = line.partition(":")
        if name in out:
            try:
                out[name] = round(int(rest.split()[0]) / 1024)
            except (IndexError, ValueError):
                pass
    return out


def process_memory(proc: Path = Path("/proc/self")) -> dict[str, int | None]:
    roll = _kv_kib(_read(proc / "smaps_rollup"), "Rss", "Pss", "Anonymous")
    status = _kv_kib(_read(proc / "status"), "VmRSS", "VmHWM")
    return dict(rss_mb=roll["Rss"] if roll["Rss"] is not None else status["VmRSS"], pss_mb=roll["Pss"], anonymous_mb=roll["Anonymous"],
                peak_rss_mb=status["VmHWM"])


def _int(text: str | None) -> int | None:
    t = (text or "").strip()
    return int(t) if t.isdigit() else None


def _events(text: str | None) -> dict[str, int]:
    out: dict[str, int] = {}
    for line in (text or "").splitlines():
        k, _, v = line.partition(" ")
        if v.strip().isdigit():
            out[k] = int(v)
    return out


def cgroup_memory(root: Path = Path("/sys/fs/cgroup"), proc: Path = Path("/proc/self")) -> dict[str, Any] | None:
    """The memory controller of this process's cgroup (v2 unified, else v1); None when nothing is readable."""
    rel = ""
    for line in (_read(proc / "cgroup") or "").splitlines():
        parts = line.split(":", 2)
        if len(parts) == 3 and parts[0] == "0" and parts[1] == "":
            rel = parts[2].lstrip("/")
            break
    for base in ([root / rel, root] if rel else [root]):
        current = _int(_read(base / "memory.current"))
        if current is not None:
            limit = _read(base / "memory.max")
            events = _events(_read(base / "memory.events"))
            return dict(version=2, current_mb=round(current / MB),
                        limit_mb=None if limit is None or limit.strip() == "max" else round(int(limit) / MB),
                        peak_mb=(lambda p: round(p / MB) if p is not None else None)(_int(_read(base / "memory.peak"))),
                        oom=events.get("oom"), oom_kill=events.get("oom_kill"), max_events=events.get("max"))
    v1 = root / "memory"
    current = _int(_read(v1 / "memory.usage_in_bytes"))
    if current is not None:
        limit = _int(_read(v1 / "memory.limit_in_bytes"))
        oom = _events(_read(v1 / "memory.oom_control"))
        return dict(version=1, current_mb=round(current / MB), limit_mb=round(limit / MB) if limit and limit < 1 << 60 else None,
                    peak_mb=(lambda p: round(p / MB) if p is not None else None)(_int(_read(v1 / "memory.max_usage_in_bytes"))),
                    oom=None, oom_kill=oom.get("oom_kill"), max_events=_int(_read(v1 / "memory.failcnt")))
    return None


def container_memory(cg: dict[str, Any] | None) -> dict[str, Any] | None:
    """The cgroup figures only mean 'this service' when the cgroup has a memory limit (a container such as Render's); a desktop or
    shared server reports the whole user session instead."""
    return None if cg is None else dict(cg, is_container=cg.get("limit_mb") is not None)


def _age_seconds(v: str | None, now: datetime) -> int | None:
    try:
        return int((now - datetime.fromisoformat(v)).total_seconds()) if v else None
    except ValueError:
        return None


def stale_running(store: Any, settings: Any, now: datetime | None = None) -> dict[str, Any]:
    """Running jobs / agent tasks whose heartbeat is older than JOB_STALE_SECONDS: their worker is gone (they are re-queued on the
    next claim) or hung. Counted, never changed here."""
    from app.repositories.base import Query

    now = now or datetime.now(UTC)
    limit = settings.job_stale_seconds
    out: dict[str, Any] = {"stale_after_seconds": limit}
    for name, table in (("jobs", "ingestion_jobs"), ("agent_tasks", "agent_tasks")):
        try:
            rows, _n = store.select(table, Query(eq={"status": "running"}, cols="id,heartbeat_at,started_at", limit=50))
        except Exception:  # noqa: BLE001 - table or column missing before a migration
            out[name] = None
            continue
        ages = [_age_seconds(r.get("heartbeat_at") or r.get("started_at"), now) for r in rows]
        out[name] = dict(running=len(rows), stale=sum(1 for a in ages if a is not None and a > limit),
                         oldest_heartbeat_seconds=max((a for a in ages if a is not None), default=None))
    return out


def snapshot(svc: Any) -> dict[str, Any]:
    names = sorted(t.name for t in threading.enumerate())
    jobs = getattr(svc, "jobs", None)
    worker = getattr(jobs, "_thread", None)
    agent = getattr(jobs, "_agent_thread", None)
    ingestion = getattr(svc, "ingestion", None)
    try:
        queues = svc.operations.queues()
    except Exception:  # noqa: BLE001
        queues = None
    return dict(
        checked_at=datetime.now(UTC).isoformat(),
        instance=dict(instance_id=INSTANCE_ID, started_at=STARTED_AT.isoformat(), uptime_seconds=round(time.monotonic() - _STARTED_MONO),
                      pid=os.getpid(), python=platform.python_version()),
        memory=process_memory(), cgroup=container_memory(cgroup_memory()),
        # glibc reads it at process start; "2" is what render.yaml sets (docs/development/RENDER-MEMORY.md)
        allocator=dict(malloc_arena_max=os.environ.get("MALLOC_ARENA_MAX")),
        embedding_model_loaded=bool(getattr(getattr(svc, "embedder", None), "loaded", False)),
        workers=dict(mode=svc.settings.job_execution, ingestion_alive=bool(worker and worker.is_alive()),
                     agent_alive=bool(agent and agent.is_alive()), threads=len(names)),
        ingestion=ingestion.slots() if hasattr(ingestion, "slots") else None,
        queues=queues, stale=stale_running(svc.store, svc.settings))
