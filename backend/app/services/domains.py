"""Source-domain allowlist = ALLOWED_SOURCE_DOMAINS (environment, immutable at runtime) + admin-managed rows."""
from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any

from app.core.config import Settings
from app.core.errors import Conflict, InvalidState, NotFound, ValidationFailed
from app.repositories.base import Query, Store, get_one

log = logging.getLogger("app.domains")
_DOMAIN = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$")
CACHE_SECONDS = 60.0


def normalize_domain(value: str) -> str:
    d = value.strip().lower()
    d = re.sub(r"^https?://", "", d).split("/")[0].split(":")[0].lstrip(".").removeprefix("www.")
    if not _DOMAIN.match(d) or "." not in d:
        raise ValidationFailed(f"'{value}' is not a valid domain name (example: hikorea.go.kr).")
    if d.count(".") < 1 or d in ("go.kr", "ac.kr", "or.kr", "co.kr", "com", "kr"):
        raise ValidationFailed("Register a specific organization's domain, not a public suffix.")
    return d


class DomainPolicy:
    def __init__(self, store: Store | None, settings: Settings):
        self.store = store
        self.settings = settings
        self._cache: tuple[float, list[str]] | None = None
        self._lock = threading.Lock()

    def _db_domains(self) -> list[str]:
        if self.store is None:
            return []
        try:
            rows, _ = self.store.select("allowed_source_domains", Query(cols="domain"))
        except Exception:  # noqa: BLE001 - DB hiccup: fall back to the environment allowlist only
            log.warning("could not read allowed_source_domains; using environment allowlist only")
            return []
        return [r["domain"] for r in rows]

    def domains(self) -> list[str]:
        with self._lock:
            if self._cache and time.monotonic() - self._cache[0] < CACHE_SECONDS:
                return self._cache[1]
            merged = list(dict.fromkeys(self.settings.allowed_domains + self._db_domains()))
            self._cache = (time.monotonic(), merged)
            return merged

    def invalidate(self) -> None:
        with self._lock:
            self._cache = None

    def list(self) -> list[dict[str, Any]]:
        out = [dict(domain=d, origin="environment", note=None, added_by=None, created_at=None, removable=False)
               for d in self.settings.allowed_domains]
        env = set(self.settings.allowed_domains)
        if self.store is not None:
            rows, _ = self.store.select("allowed_source_domains", Query(order=[("domain", False)]))
            out += [dict(domain=r["domain"], origin="admin", note=r.get("note"), added_by=r.get("added_by"),
                         created_at=r.get("created_at"), removable=True) for r in rows if r["domain"] not in env]
        return out

    def add(self, domain: str, note: str | None, actor_id: str) -> dict[str, Any]:
        d = normalize_domain(domain)
        if d in self.settings.allowed_domains:
            raise Conflict(f"{d} is already allowed by the environment configuration.")
        if self.store is None:
            raise InvalidState("Database is not configured.")
        if get_one(self.store, "allowed_source_domains", domain=d):
            raise Conflict(f"{d} is already on the allowlist.")
        row = self.store.insert("allowed_source_domains", dict(domain=d, note=(note or None), added_by=actor_id))
        self.store.insert("audit_log", dict(action="domain.allow", entity_type="allowed_source_domain", entity_id=None,
                                            actor_id=actor_id, details={"domain": d, "note": note}))
        self.invalidate()
        return row

    def remove(self, domain: str, actor_id: str) -> None:
        d = domain.strip().lower()
        if d in self.settings.allowed_domains:
            raise InvalidState("Environment-configured domains can only be changed in ALLOWED_SOURCE_DOMAINS.")
        if self.store is None or not get_one(self.store, "allowed_source_domains", domain=d):
            raise NotFound("Domain is not on the admin allowlist.")
        self.store.delete("allowed_source_domains", {"domain": d})
        self.store.insert("audit_log", dict(action="domain.remove", entity_type="allowed_source_domain", entity_id=None,
                                            actor_id=actor_id, details={"domain": d}))
        self.invalidate()
