"""Persistent job execution.

Every ingestion job is a row in ``ingestion_jobs`` first. Execution modes:
  * ``worker`` (production): a daemon thread claims queued jobs with the ``claim_ingestion_job``
    RPC (``FOR UPDATE SKIP LOCKED``) and runs them one at a time (bounded memory on small instances). Agent tasks
    run in a second thread (``AGENT_TASK_WORKER``, default on) so the two queues never block each other; at most
    one job and one agent task run at the same time.
    After a restart or a Render free-tier sleep, queued jobs are simply claimed again; jobs that were
    running when the process died stop heart-beating and are re-queued (up to ``max_attempts``).
  * ``inline`` (tests, scripts): the job runs in the request's background task.
"""
from __future__ import annotations

import logging
import os
import socket
import threading
import uuid
from typing import Any

from fastapi import BackgroundTasks

from app.core.config import Settings
from app.repositories.base import Store

log = logging.getLogger("app.jobs")


class JobRunner:
    def __init__(self, store: Store, ingestion: Any, settings: Settings):
        self.store = store
        self.ingestion = ingestion
        self.settings = settings
        self.worker_id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"
        self._wake = threading.Event()
        self._agent_wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._agent_thread: threading.Thread | None = None
        self.agents: Any = None          # AgentTaskService: agent tasks share this worker (one at a time)

    @property
    def inline(self) -> bool:
        return self.settings.job_execution != "worker"

    # ----------------------------------------------------------- enqueue
    def enqueue(self, job: dict[str, Any], background: BackgroundTasks | None = None) -> None:
        if job.get("executor") == "gpu":
            return                      # waits for a GPU worker (never run in this process)
        if self.inline:
            if background is not None:
                background.add_task(self.ingestion.run_job, job["id"])
            else:
                self.ingestion.run_job(job["id"])
            return
        self.start()
        self._wake.set()

    def kick(self) -> None:
        """Wake the workers (e.g. a new agent task, the scheduler hook) so queued/retry work is processed now."""
        if not self.inline:
            self.start()
            self._wake.set()
            self._agent_wake.set()

    # ------------------------------------------------------------ worker
    def claim(self, stale_seconds: int | None = None) -> dict[str, Any] | None:
        """Claim the oldest due job. Running jobs without a heartbeat for ``stale_seconds`` (a dead worker) are
        re-queued first (or failed once max_attempts is reached) by the same RPC."""
        rows = self.store.rpc("claim_ingestion_job", dict(
            p_worker=self.worker_id, p_stale_seconds=stale_seconds or self.settings.job_stale_seconds))
        if isinstance(rows, dict):
            rows = [rows]
        rows = [r for r in (rows or []) if r and r.get("id")]
        return rows[0] if rows else None

    @property
    def agent_lane(self) -> bool:
        """Agent tasks have their own worker thread (worker mode with AGENT_TASK_WORKER on)."""
        return not self.inline and self.settings.agent_task_worker

    def run_once(self, stale_seconds: int | None = None) -> bool:
        """Claim and execute one job. Returns True if a job was processed."""
        job = self.claim(stale_seconds)
        if job is None:
            # with an agent lane, the ingestion thread never picks up agent tasks (so it is always free for content)
            return False if self.agent_lane else self.run_agent_task_once(stale_seconds)
        log.info("worker %s claimed job %s (attempt %s)", self.worker_id, job["id"], job.get("attempts"))
        self.ingestion.execute(job)
        return True

    def run_agent_task_once(self, stale_seconds: int | None = None) -> bool:
        """Claim and execute one agent task (after ingestion jobs: content processing keeps priority)."""
        if self.agents is None:
            return False
        task = self.agents.claim(self.worker_id, stale_seconds or self.settings.job_stale_seconds)
        if task is None:
            return False
        log.info("worker %s claimed agent task %s (%s/%s)", self.worker_id, task["id"], task["agent_id"], task["task_type"])
        self.agents.execute(task)
        return True

    def _loop(self) -> None:
        log.info("job worker %s started", self.worker_id)
        # right after a (re)start, jobs still 'running' without a recent heartbeat belonged to the previous process
        # (live jobs heartbeat every job_heartbeat_seconds): recover them quickly instead of after job_stale_seconds
        first = True
        while not self._stop.is_set():
            try:
                while not self._stop.is_set() and self.run_once(self.settings.job_startup_stale_seconds if first else None):
                    first = False
                first = False
            except Exception:  # noqa: BLE001 - keep the worker alive; the job row records failures
                log.exception("job worker iteration failed")
            self._wake.wait(self.settings.job_poll_seconds)
            self._wake.clear()
        log.info("job worker %s stopped", self.worker_id)

    def _agent_loop(self) -> None:
        log.info("agent task worker %s started", self.worker_id)
        first = True
        while not self._stop.is_set():
            try:
                stale = self.settings.job_startup_stale_seconds if first else None
                while not self._stop.is_set() and self.run_agent_task_once(stale):
                    stale = None
                first = False
            except Exception:  # noqa: BLE001 - keep the worker alive; the task row records failures
                log.exception("agent task worker iteration failed")
            self._agent_wake.wait(self.settings.job_poll_seconds)
            self._agent_wake.clear()
        log.info("agent task worker %s stopped", self.worker_id)

    def start(self) -> None:
        if self.inline:
            return
        self._stop.clear()
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._loop, name="ingestion-worker", daemon=True)
            self._thread.start()
        if self.agent_lane and self.agents is not None and (self._agent_thread is None or not self._agent_thread.is_alive()):
            self._agent_thread = threading.Thread(target=self._agent_loop, name="agent-task-worker", daemon=True)
            self._agent_thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self._wake.set()
        self._agent_wake.set()
        for t in (self._thread, self._agent_thread):
            if t is not None:
                t.join(timeout)
