"""HTTPS client of the Hub API (outbound only). Retries what is safe to repeat; never logs tokens or content."""
from __future__ import annotations

import logging
import random
import threading
import time
from collections.abc import Callable
from typing import Any

import httpx

log = logging.getLogger("gpu_worker")
RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}


class HubError(Exception):
    """``code``: from the API, or 'unreachable'."""

    def __init__(self, code: str, status: int = 0):
        super().__init__(code)
        self.code, self.status = code, status


class CredentialRejected(HubError):
    pass


class LeaseLost(HubError):
    pass


class Hub:
    def __init__(self, base_url: str, token: Callable[[], str], *, transport: httpx.BaseTransport | None = None,
                 timeout: float = 90.0):
        self._token = token
        # 90 s: a sleeping free Render instance needs about a minute for its first answer. Redirects are not followed
        # (they could carry the token elsewhere).
        self._http = httpx.Client(base_url=base_url, transport=transport, follow_redirects=False,
                                  timeout=httpx.Timeout(timeout, connect=20.0),
                                  headers={"User-Agent": "sch-gpu-worker/1"})

    def close(self) -> None:
        self._http.close()

    def post(self, path: str, body: dict[str, Any], *, deadline: float = 0.0,
             stop: threading.Event | None = None) -> dict[str, Any]:
        """``deadline``: keep retrying for this many seconds (0 = one try). Every endpoint is safe to repeat."""
        started, attempt = time.monotonic(), 0
        while True:
            attempt += 1
            wait: float | None = None
            try:
                r = self._http.post(f"/api/v1/gpu{path}", json=body, headers={"Authorization": f"Bearer {self._token()}"})
                if r.status_code == 200:
                    return _object(r)
                code, wait = _error(r)
                if r.status_code == 401:
                    raise CredentialRejected(code, 401)
                if code in ("lease_lost", "not_found") and r.status_code in (404, 409) and path.startswith("/jobs/"):
                    raise LeaseLost(code, r.status_code)
                err = HubError(code, r.status_code)
                if r.status_code not in RETRY_STATUS and code != "submission_in_progress":
                    raise err
            except httpx.HTTPError as exc:
                err = HubError("unreachable")
                log.warning("hub path=%s attempt=%d error=%s", path.split("/")[-1], attempt, type(exc).__name__)
            delay = max(wait or 0.0, random.uniform(0.5, 1.0) * min(60.0, 2.0 ** min(attempt, 6)))
            if time.monotonic() - started + delay > deadline or (stop is not None and stop.is_set()):
                raise err
            if stop is not None:
                stop.wait(delay)
            else:
                time.sleep(delay)


def _object(r: httpx.Response) -> dict[str, Any]:
    try:
        data = r.json()
    except ValueError:
        raise HubError("invalid_response", r.status_code) from None
    if not isinstance(data, dict):
        raise HubError("invalid_response", r.status_code)
    return data


def _error(r: httpx.Response) -> tuple[str, float | None]:
    """(code, seconds to wait). Only a short identifier is taken from the response."""
    try:
        err = r.json()["error"]
        code = str(err["code"])[:40]
        wait = (err.get("details") or {}).get("retry_after")
        return (code if code.replace("_", "").isalnum() else "http_error"), \
            float(wait) if isinstance(wait, (int, float)) else None
    except (ValueError, KeyError, TypeError, AttributeError):
        return "http_error", None
