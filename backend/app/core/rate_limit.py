"""Tiny in-process sliding-window rate limiter (per client IP + bucket).

Good enough for a single Render instance; use an edge/WAF or Redis limiter if the
backend is scaled horizontally (documented in docs/architecture.md).
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import Depends, Request

from app.core.config import Settings, get_settings
from app.core.errors import AppError


class RateLimited(AppError):
    status_code, code = 429, "rate_limited"


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, bucket: str, limit: int, window: float = 60.0) -> None:
        now = time.monotonic()
        with self._lock:
            q = self._hits[(bucket, key)]
            while q and now - q[0] > window:
                q.popleft()
            if len(q) >= limit:
                retry = max(1, int(window - (now - q[0])))
                raise RateLimited(f"Too many requests. Try again in {retry}s.", details={"retry_after": retry})
            q.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = SlidingWindowLimiter()


def client_key(request: Request) -> str:
    # Render sits behind a proxy: use the first X-Forwarded-For hop when present.
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit(bucket: str):
    """FastAPI dependency factory: ``Depends(rate_limit("search"))``."""

    def dep(request: Request, s: Settings = Depends(get_settings)) -> None:
        limit = {
            "search": s.rate_limit_search_per_minute,
            "ingest": s.rate_limit_ingest_per_minute,
            "public": s.rate_limit_public_per_minute,
        }[bucket]
        limiter.check(client_key(request), bucket, limit)

    return dep
