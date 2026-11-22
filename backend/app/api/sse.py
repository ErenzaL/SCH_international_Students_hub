"""Server-sent events for streamed assistant answers.

Events: ``status`` {stage}, ``delta`` {text}, then exactly one of ``done`` {result} or ``error`` {code, message}.
The work runs in a background thread so the HTTP response can flush tokens as they arrive; clients that cannot
stream use the regular JSON endpoints instead.
"""
from __future__ import annotations

import json
import logging
import queue
import threading
from collections.abc import Callable, Iterator
from typing import Any

from fastapi.responses import StreamingResponse

from app.core.errors import AppError

log = logging.getLogger("app.assistant")
Emit = Callable[[str, dict[str, Any]], None]


def _frame(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def sse(run: Callable[[Emit], dict[str, Any]], request_id: str | None = None) -> StreamingResponse:
    q: queue.Queue[tuple[str, Any] | None] = queue.Queue()

    def emit(event: str, data: dict[str, Any]) -> None:
        q.put((event, data))

    def worker() -> None:
        try:
            q.put(("done", run(emit)))
        except AppError as exc:
            q.put(("error", {"code": exc.code, "message": exc.message, "request_id": request_id}))
        except Exception:  # noqa: BLE001 - reported to the client as a structured error, logged with a trace
            log.exception("assistant stream failed rid=%s", request_id)
            q.put(("error", {"code": "internal_error", "message": "The assistant could not answer right now. "
                                                                  "Please try again.", "request_id": request_id}))
        finally:
            q.put(None)

    threading.Thread(target=worker, name="assistant-stream", daemon=True).start()

    def body() -> Iterator[str]:
        yield ": stream open\n\n"   # flush headers through proxies immediately
        while True:
            try:
                item = q.get(timeout=15)
            except queue.Empty:
                yield ": keep-alive\n\n"
                continue
            if item is None:
                return
            yield _frame(*item)

    return StreamingResponse(body(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})
