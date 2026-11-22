"""Persistent job execution.

Every ingestion job is a row in ``ingestion_jobs`` first. Execution modes:
  * ``worker`` (production): a single daemon thread claims queued jobs with the ``claim_ingestion_job``
    RPC (``FOR UPDATE SKIP LOCKED``) and runs them one at a time (bounded memory on small instances).
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
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def inline(self) -> bool:
        return self.settings.job_execution != "worker"

    # ----------------------------------------------------------- enqueue
    def enqueue(self, job: dict[str, Any], background: BackgroundTasks | None = None) -> None:
        if self.inline:
            if background is not None:
                background.add_task(self.ingestion.run_job, job["id"])
            else:
                self.ingestion.run_job(job["id"])
            return
        self.start()
        self._wake.set()

    def kick(self) -> None:
        """Wake the worker (e.g. from the scheduler hook) so queued/retry jobs are processed now."""
        if not self.inline:
            self.start()
            self._wake.set()

    # ------------------------------------------------------------ worker
    def claim(self) -> dict[str, Any] | None:
        rows = self.store.rpc("claim_ingestion_job", dict(p_worker=self.worker_id,
                                                           p_stale_seconds=self.settings.job_stale_seconds))
        if isinstance(rows, dict):
            rows = [rows]
        rows = [r for r in (rows or []) if r and r.get("id")]
        return rows[0] if rows else None

    def run_once(self) -> bool:
        """Claim and execute one job. Returns True if a job was processed."""
        job = self.claim()
        if job is None:
            return False
        log.info("worker %s claimed job %s (attempt %s)", self.worker_id, job["id"], job.get("attempts"))
        self.ingestion.execute(job)
        return True

    def _loop(self) -> None:
        log.info("job worker %s started", self.worker_id)
        while not self._stop.is_set():
            try:
                while not self._stop.is_set() and self.run_once():
                    pass
            except Exception:  # noqa: BLE001 - keep the worker alive; the job row records failures
                log.exception("job worker iteration failed")
            self._wake.wait(self.settings.job_poll_seconds)
            self._wake.clear()
        log.info("job worker %s stopped", self.worker_id)

    def start(self) -> None:
        if self.inline or (self._thread is not None and self._thread.is_alive()):
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="ingestion-worker", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout)
