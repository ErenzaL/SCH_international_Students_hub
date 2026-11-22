"""Request logging with request ids. Never logs headers, bodies or tokens."""
from __future__ import annotations

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger("app.request")


def configure_logging(level: str) -> None:
    logging.basicConfig(level=level.upper(), format="%(asctime)s %(levelname)s %(name)s %(message)s")
    # httpx logs full URLs (may include query strings); keep it quiet
    logging.getLogger("httpx").setLevel(logging.WARNING)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_body_bytes: int):  # type: ignore[no-untyped-def]
        super().__init__(app)
        self.max_body_bytes = max_body_bytes

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.request_id = request.headers.get("x-request-id", "")[:64] or uuid.uuid4().hex[:12]
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > self.max_body_bytes:
            return JSONResponse(
                {
                    "error": {"code": "request_too_large", "message": "Request body too large", "details": None},
                    "request_id": request.state.request_id,
                },
                status_code=413,
            )
        started = time.perf_counter()
        response: Response = await call_next(request)
        elapsed = (time.perf_counter() - started) * 1000
        response.headers["x-request-id"] = request.state.request_id
        # path only: query strings may contain search text; no headers / auth values are logged
        logger.info(
            "%s %s -> %s %.0fms rid=%s", request.method, request.url.path, response.status_code, elapsed,
            request.state.request_id,
        )
        return response
