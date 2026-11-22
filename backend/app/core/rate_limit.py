"""In-process rate limits and daily AI budgets (single Render instance).

Client identity behind proxies (see ``client_ip``):
  * a header the edge proxy SETS (``CLIENT_IP_HEADER``, default ``true-client-ip`` from Cloudflare in front of
    Render) is trusted first - verify on the deployment with ``GET /api/v1/admin/system/client-ip``;
  * otherwise ``X-Forwarded-For`` is read from the RIGHT: proxies append, so only the entries added by the
    ``TRUSTED_PROXY_HOPS`` trusted proxies are reliable. The left-most entry is whatever the client sent and is
    never used (it was the bypass found in the audit).
Spoofing can still never exceed the GLOBAL anonymous cap (``rate_limit_chat_anonymous_global_per_minute``) or the
global daily AI budget, so a misconfigured proxy setting degrades fairness, not cost safety.

Counters live in memory (reset on restart; one instance). Scale-out needs a shared store (Redis / a database
table) - see docs/assistant.md.
"""
from __future__ import annotations

import ipaddress
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from fastapi import Depends, Request

from app.core.config import Settings, get_settings
from app.core.errors import AppError

KST = timezone(timedelta(hours=9))


class RateLimited(AppError):
    status_code, code = 429, "rate_limited"


class DailyLimitReached(AppError):
    status_code, code = 429, "daily_limit"


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
            if len(self._hits) > 50_000:   # bound memory: drop idle keys
                for k in [k for k, v in self._hits.items() if not v or now - v[-1] > window][:25_000]:
                    self._hits.pop(k, None)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


class DailyBudget:
    """Counts AI-generated assistant turns per key per KST day."""

    def __init__(self) -> None:
        self._day = ""
        self._counts: dict[str, int] = defaultdict(int)
        self._lock = threading.Lock()

    def _roll(self) -> None:
        day = datetime.now(KST).date().isoformat()
        if day != self._day:
            self._day, self._counts = day, defaultdict(int)

    def take(self, key: str, limit: int) -> bool:
        """Consume one unit; False (nothing consumed) when the key reached its limit. limit <= 0 = unlimited."""
        with self._lock:
            self._roll()
            if limit > 0 and self._counts[key] >= limit:
                return False
            self._counts[key] += 1
            return True

    def used(self, key: str) -> int:
        with self._lock:
            self._roll()
            return self._counts.get(key, 0)

    def snapshot(self) -> dict[str, int | str]:
        with self._lock:
            self._roll()
            return dict(day=self._day, global_generated=self._counts.get("global", 0),
                        tracked_clients=sum(1 for k in self._counts if k.startswith(("ip:", "user:"))))

    def reset(self) -> None:
        with self._lock:
            self._day, self._counts = "", defaultdict(int)


limiter = SlidingWindowLimiter()
ai_budget = DailyBudget()


def _valid_ip(v: str | None) -> str | None:
    if not v:
        return None
    v = v.strip().strip('"')
    if v.startswith("[") and "]" in v:      # [v6]:port
        v = v[1:v.index("]")]
    elif v.count(":") == 1 and "." in v:    # v4:port
        v = v.split(":")[0]
    try:
        return str(ipaddress.ip_address(v))
    except ValueError:
        return None


def client_ip(request: Request, settings: Settings | None = None) -> str:
    s = settings or get_settings()
    header = (s.client_ip_header or "").strip().lower()
    if header:
        ip = _valid_ip(request.headers.get(header))
        if ip:
            return ip
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        hops = [h for h in (x.strip() for x in fwd.split(",")) if h]
        n = max(1, int(s.trusted_proxy_hops or 1))
        if hops:
            ip = _valid_ip(hops[-n] if len(hops) >= n else hops[0])
            if ip:
                return ip
    # uvicorn --proxy-headers --forwarded-allow-ips="*" rewrites request.client from the LEFT-most entry
    # (client-controlled), so the socket peer is only used when no forwarding header exists at all
    return request.client.host if request.client else "unknown"


def client_key(request: Request) -> str:   # backwards-compatible name
    return client_ip(request)


def rate_limit(bucket: str):
    """FastAPI dependency factory: ``Depends(rate_limit("search"))``."""

    def dep(request: Request, s: Settings = Depends(get_settings)) -> None:
        limit = {
            "search": s.rate_limit_search_per_minute,
            "ingest": s.rate_limit_ingest_per_minute,
            "public": s.rate_limit_public_per_minute,
        }[bucket]
        limiter.check(client_ip(request, s), bucket, limit)

    return dep


def limit_assistant_turn(request: Request, s: Settings, *, user_id: str | None, ai_enabled: bool) -> None:
    """Per-minute and per-day limits for one assistant turn (call before any retrieval or generation).

    Signed-in students are limited per account; anonymous visitors per client IP AND by a global anonymous cap
    that header spoofing cannot get around. Daily limits apply only when answers are AI-generated."""
    if user_id:
        limiter.check(f"user:{user_id}", "chat-user", s.rate_limit_chat_user_per_minute)
        key, daily = f"user:{user_id}", s.ai_daily_limit_per_user
    else:
        limiter.check("anonymous", "chat-anon-global", s.rate_limit_chat_anonymous_global_per_minute)
        key, daily = f"ip:{client_ip(request, s)}", s.ai_daily_limit_per_client
    if ai_enabled and not ai_budget.take(key, daily):
        raise DailyLimitReached("You have reached today's limit for assistant answers. Please try again tomorrow, "
                                "or browse the Knowledge Center.", details={"limit": daily})
