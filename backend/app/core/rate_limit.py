"""In-process rate limits and daily AI budgets (single Render instance).

Client identity behind proxies (see ``client_ip``):
  * ``X-Forwarded-For`` is read from the RIGHT: proxies append, so only the entries added by the
    ``TRUSTED_PROXY_HOPS`` trusted proxies are reliable. The left-most entry is whatever the client sent and is
    never used (it was the bypass found in the audit). ``TRUSTED_PROXY_HOPS=0`` ignores the header entirely;
  * a header the edge proxy SETS (``CLIENT_IP_HEADER``, e.g. ``true-client-ip``) is trusted first, but it is OFF
    by default: enable it only after ``GET /api/v1/admin/system/client-ip`` shows that a client-sent value does not
    pass through (otherwise every request could claim a new identity);
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
from typing import Any

from fastapi import Depends, Request

from app.core.config import Settings, get_settings
from app.core.errors import AppError

KST = timezone(timedelta(hours=9))


class RateLimited(AppError):
    status_code, code = 429, "rate_limited"


class DailyLimitReached(AppError):
    status_code, code = 429, "daily_limit"


class SlidingWindowLimiter:
    MAX_KEYS = 50_000

    def __init__(self) -> None:
        self._hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._last_sweep = 0.0

    def check(self, key: str, bucket: str, limit: int, window: float = 60.0) -> None:
        """Count one hit; RateLimited when ``limit`` hits already fall inside the window. limit <= 0 = unlimited."""
        if limit <= 0:
            return
        now = time.monotonic()
        with self._lock:
            q = self._hits[(bucket, key)]
            while q and now - q[0] > window:
                q.popleft()
            if len(q) >= limit:
                retry = max(1, int(window - (now - q[0])))
                raise RateLimited(f"Too many requests. Try again in {retry}s.", details={"retry_after": retry})
            q.append(now)
            # bound memory: sweep idle keys at most every 10 s, then evict the oldest if still above the cap
            if len(self._hits) > self.MAX_KEYS and now - self._last_sweep > 10:
                self._last_sweep = now
                for k in [k for k, v in self._hits.items() if not v or now - v[-1] > window]:
                    self._hits.pop(k, None)
                if len(self._hits) > self.MAX_KEYS:
                    oldest = sorted(self._hits.items(), key=lambda kv: kv[1][-1] if kv[1] else 0.0)
                    for k, _v in oldest[: len(self._hits) - self.MAX_KEYS]:
                        self._hits.pop(k, None)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


class DailyBudget:
    """Counts AI-generated assistant turns per key per KST day.

    ``attach(store, keys)``: those keys are counted in the database (migration 0018, ``llm_counter_take``), so a
    restart or a second process cannot reopen a spent budget. Without the migration the counters stay in-process
    (``persistent`` False). Keys in ``fail_closed`` are refused while the database cannot be asked although the
    migration exists; the others fall back to the in-process counter."""

    _MISSING = ("PGRST202", "PGRST205", "42883", "42P01")

    def __init__(self) -> None:
        self._day = ""
        self._counts: dict[str, int] = defaultdict(int)
        self._lock = threading.Lock()
        self.store: Any = None
        self.persist_keys: frozenset[str] = frozenset()
        self.fail_closed: frozenset[str] = frozenset()
        self.persistent: bool | None = None      # None = not known yet (no persisted key taken)
        self.persist_error: str | None = None

    def attach(self, store: Any, keys: set[str] | frozenset[str], fail_closed: set[str] | frozenset[str] = frozenset()
               ) -> DailyBudget:
        self.store, self.persist_keys, self.fail_closed = store, frozenset(keys), frozenset(fail_closed)
        self.persistent, self.persist_error = None, None
        return self

    def _take_db(self, key: str, limit: int) -> bool | None:
        """True / False from the database; None = the database cannot answer."""
        if self.persistent is False:
            return None
        try:
            r = self.store.rpc("llm_counter_take", dict(p_day=datetime.now(KST).date().isoformat(), p_key=key,
                                                        p_limit=int(limit)))
        except Exception as exc:  # noqa: BLE001 - classified: missing migration vs. a failing database
            code = str((getattr(exc, "details", None) or {}).get("db_code") or getattr(exc, "code", "") or "")
            if code in self._MISSING or "unknown rpc" in str(exc):
                self.persistent, self.persist_error = False, "migration 0018 is not applied"
            else:
                self.persist_error = f"database unavailable ({type(exc).__name__})"
            return None
        self.persistent, self.persist_error = True, None
        return bool(r[0] if isinstance(r, list) and r else r)

    def _take_persisted(self, key: str, limit: int) -> bool | None:
        if self.store is None or key not in self.persist_keys:
            return None
        took = self._take_db(key, limit)
        if took is not None:
            with self._lock:
                self._roll()
                if took:
                    self._counts[key] += 1          # this process's share, for snapshots
            return took
        if key in self.fail_closed and self.persistent is not False:
            return False
        return None

    def _roll(self) -> None:
        day = datetime.now(KST).date().isoformat()
        if day != self._day:
            self._day, self._counts = day, defaultdict(int)

    def available(self, key: str, limit: int) -> bool:
        """Would ``take`` succeed? (nothing is consumed)"""
        with self._lock:
            self._roll()
            return limit <= 0 or self._counts.get(key, 0) < limit

    def take(self, key: str, limit: int) -> bool:
        """Consume one unit; False (nothing consumed) when the key reached its limit. limit <= 0 = unlimited."""
        took = self._take_persisted(key, limit)
        if took is not None:
            return took
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

    def used_persisted(self, key: str) -> int | None:
        """Today's count of a persisted key across all processes; None = not persisted / not readable."""
        if self.store is None or key not in self.persist_keys or self.persistent is False:
            return None
        from app.repositories.base import Query

        try:
            rows, _ = self.store.select("llm_daily_counters", Query(
                eq={"day": datetime.now(KST).date().isoformat(), "key": key}, cols="used", limit=1))
        except Exception:  # noqa: BLE001
            return None
        return int(rows[0]["used"]) if rows else 0

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            self._roll()
            out: dict[str, Any] = dict(day=self._day, global_generated=self._counts.get("global", 0),
                                       tracked_clients=sum(1 for k in self._counts if k.startswith(("ip:", "user:"))))
        out.update(persistent=self.persistent, persisted_keys=sorted(self.persist_keys), persist_error=self.persist_error)
        return out

    def reset(self) -> None:
        with self._lock:
            self._day, self._counts = "", defaultdict(int)
        self.store, self.persist_keys, self.fail_closed = None, frozenset(), frozenset()
        self.persistent, self.persist_error = None, None


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
    n = int(s.trusted_proxy_hops if s.trusted_proxy_hops is not None else 1)
    fwd = request.headers.get("x-forwarded-for") if n > 0 else None
    if fwd:
        hops = [h for h in (x.strip() for x in fwd.split(",")) if h]
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
        key, daily = f"user:{user_id}", s.ai_daily_limit_per_user
        limiter.check(key, "chat-user", s.rate_limit_chat_user_per_minute)
        _daily(key, daily, ai_enabled)
        return
    key, daily = f"ip:{client_ip(request, s)}", s.ai_daily_limit_per_client
    # per-client checks FIRST, so one client (or a refused request) can never use up the shared global slots
    limiter.check(key, "chat-anon-ip", s.rate_limit_chat_anonymous_per_minute)
    if ai_enabled and not ai_budget.available(key, daily):
        raise _daily_error(daily)
    limiter.check("anonymous", "chat-anon-global", s.rate_limit_chat_anonymous_global_per_minute)
    _daily(key, daily, ai_enabled)


def limit_ai_action(user_id: str, s: Settings, *, ai_enabled: bool) -> None:
    """Other per-user AI calls (e.g. the supporter-handoff summary): per-minute limit + the user's daily budget."""
    limiter.check(f"user:{user_id}", "ai-action", s.rate_limit_chat_user_per_minute)
    _daily(f"user:{user_id}", s.ai_daily_limit_per_user, ai_enabled)


def _daily_error(limit: int) -> DailyLimitReached:
    return DailyLimitReached("You have reached today's limit for assistant answers. Please try again tomorrow, "
                             "or browse the Knowledge Center.", details={"limit": limit})


def _daily(key: str, limit: int, ai_enabled: bool) -> None:
    if ai_enabled and not ai_budget.take(key, limit):
        raise _daily_error(limit)
