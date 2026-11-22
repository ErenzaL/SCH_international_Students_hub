"""Run PDF extraction in a short-lived child process with a hard timeout (and optional memory cap).

Why: a single PDF page can make PyMuPDF allocate hundreds of MB or spin for minutes. Inside the web process (which
also hosts the job worker and the ONNX embedding model on a 512 MB instance) that killed the whole service and left
jobs stuck in ``running``. In a child process the worst case is a failed job with an actionable error:
* timeout                    -> ``extraction_timeout``
* killed (OOM / signal)      -> ``extraction_crashed``
* MuPDF error / bad file     -> the extractor's own code (``corrupt_file``, ``needs_ocr`` ...)
The parent heartbeats the job while it waits, so a long-but-healthy extraction is never mistaken for a dead worker.
"""
from __future__ import annotations

import json
import logging
import os
import queue
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from app.models.domain import ExtractedDocument
from app.services.ingestion.errors import ExtractionError

log = logging.getLogger("app.ingest.pdf")
BACKEND_ROOT = Path(__file__).resolve().parents[3]


def _reader(stream: Any, q: queue.Queue) -> None:  # type: ignore[type-arg]
    for line in iter(stream.readline, ""):
        q.put(line.rstrip("\n"))
    q.put(None)


def extract_pdf_isolated(data: bytes, filename: str, *, timeout_seconds: float, table_mode: str = "off",
                         max_table_items: int = 1500, max_pages: int | None = None, memory_limit_mb: int = 0,
                         on_progress: Callable[[int, int], None] | None = None,
                         heartbeat: Callable[[], None] | None = None,
                         heartbeat_seconds: float = 10.0) -> ExtractedDocument:
    fd, path = tempfile.mkstemp(prefix="sch-pdf-", suffix=".pdf")
    started = time.monotonic()
    proc: subprocess.Popen[str] | None = None
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        opts = json.dumps(dict(filename=filename, table_mode=table_mode, max_table_items=max_table_items,
                               max_pages=max_pages or 0, memory_limit_mb=memory_limit_mb))
        env = {**os.environ, "PYTHONPATH": str(BACKEND_ROOT) + os.pathsep + os.environ.get("PYTHONPATH", "")}
        proc = subprocess.Popen(_child_command(path, opts),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, text=True,
                                encoding="utf-8", cwd=str(BACKEND_ROOT), env=env, start_new_session=True)
        q: queue.Queue = queue.Queue()  # type: ignore[type-arg]
        threading.Thread(target=_reader, args=(proc.stdout, q), daemon=True).start()
        err_tail: list[str] = []
        threading.Thread(target=lambda: err_tail.extend(proc.stderr.read().splitlines()[-5:]),  # type: ignore[union-attr]
                         daemon=True).start()
        result: dict[str, Any] | None = None
        error: dict[str, Any] | None = None
        last_beat = 0.0
        deadline = started + timeout_seconds
        while True:
            now = time.monotonic()
            if heartbeat and now - last_beat >= heartbeat_seconds:
                heartbeat()
                last_beat = now
            if now >= deadline:
                _kill(proc)
                raise ExtractionError(
                    "extraction_timeout",
                    f"PDF text extraction did not finish within {int(timeout_seconds)} s and was stopped. The file is "
                    "probably very large or drawn with an extreme number of vector shapes. Split the PDF, upload "
                    "screenshots of the relevant pages, or paste the text instead.")
            try:
                line = q.get(timeout=min(1.0, max(0.05, deadline - now)))
            except queue.Empty:
                continue
            if line is None:
                break
            kind, _, payload = line.partition(" ")
            if kind == "P" and on_progress:
                done, _, total = payload.partition(" ")
                if done.isdigit() and total.isdigit():
                    on_progress(int(done), int(total))
            elif kind == "R":
                result = json.loads(payload)
            elif kind == "E":
                error = json.loads(payload)
        code = proc.wait(timeout=10)
        if error:
            raise ExtractionError(error.get("code") or "extraction_failed", error.get("message") or "Extraction failed.")
        if result is None:
            reason = (f"was killed by signal {-code}" if code < 0 else f"exited with code {code}")
            oom = code in (-signal.SIGKILL, 137)
            log.error("pdf child %s after %.1fs (stderr tail: %s)", reason, time.monotonic() - started,
                      " | ".join(x[:200] for x in err_tail)[:600])
            raise ExtractionError(
                "extraction_crashed",
                "PDF extraction stopped unexpectedly"
                + (" - most likely it ran out of memory" if oom else f" ({reason})")
                + ". The service itself kept running. Try a smaller or re-exported PDF, screenshots, or pasted text.")
        published = result.get("source_published_at")
        return ExtractedDocument(title=result["title"], text=result["text"], language=result.get("language"),
                                 source_published_at=datetime.fromisoformat(published) if published else None,
                                 metadata=result.get("metadata") or {})
    finally:
        if proc is not None and proc.poll() is None:
            _kill(proc)
        try:
            os.unlink(path)
        except OSError:
            pass


def _child_command(path: str, opts: str) -> list[str]:
    return [sys.executable, "-m", "app.services.ingestion.pdf_child", path, opts]


def _kill(proc: subprocess.Popen[str]) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, AttributeError):
        proc.kill()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
