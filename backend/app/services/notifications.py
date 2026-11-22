"""Admin notifications (stored rows, shown in the admin dashboard). Writing one must never break the caller."""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from app.repositories.base import Query, Store, get_one

log = logging.getLogger("app.notifications")


class NotificationService:
    def __init__(self, store: Store):
        self.store = store

    def notify(self, kind: str, title: str, message: str | None = None, *, severity: str = "info",
               entity_type: str | None = None, entity_id: str | None = None, link: str | None = None) -> None:
        try:
            self.store.insert("admin_notifications", dict(kind=kind, severity=severity, title=title[:300],
                                                          message=(message or None) and message[:2000],
                                                          entity_type=entity_type, entity_id=entity_id, link=link))
        except Exception:  # noqa: BLE001
            log.warning("could not store notification %s", kind)

    def list(self, user_id: str, limit: int = 50) -> dict[str, Any]:
        rows, _ = self.store.select("admin_notifications", Query(order=[("created_at", True)], limit=min(limit, 200)))
        read = get_one(self.store, "notification_reads", user_id=user_id)
        last = (read or {}).get("last_read_at")
        items = [{**r, "unread": last is None or r["created_at"] > last} for r in rows]
        return dict(items=items, unread=sum(1 for i in items if i["unread"]), last_read_at=last)

    def mark_read(self, user_id: str) -> None:
        now = datetime.now(UTC).isoformat()
        if get_one(self.store, "notification_reads", user_id=user_id):
            self.store.update("notification_reads", {"last_read_at": now}, {"user_id": user_id})
        else:
            self.store.insert("notification_reads", {"user_id": user_id, "last_read_at": now})
