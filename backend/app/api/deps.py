from __future__ import annotations

from fastapi import Depends, Query, Request

from app.core.config import Settings, get_settings
from app.core.errors import SupabaseNotConfigured
from app.services.container import Services


def get_services(request: Request) -> Services:
    svc = getattr(request.app.state, "services", None)
    if svc is None:
        raise SupabaseNotConfigured()
    return svc


class Pagination:
    def __init__(self, page: int = Query(1, ge=1, le=10_000), page_size: int = Query(20, ge=1, le=100)):
        self.page = page
        self.page_size = page_size

    def wrap(self, items: list, total: int) -> dict:  # type: ignore[type-arg]
        return dict(items=items, total=total, page=self.page, page_size=self.page_size)


_ = (Depends, Settings, get_settings)
