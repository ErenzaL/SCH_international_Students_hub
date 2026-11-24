"""Which translation jobs wait for the GPU worker. A job is only given to it while a usable worker exists; otherwise the
server's own model is used, exactly as with GPU_WORKER_ENABLED=false."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.config import Settings
from app.repositories.base import Query, Store

GPU_JOB_TYPES = ("translate_document", "translate_announcement")


def routed_types(settings: Settings) -> list[str]:
    wanted = [x.strip() for x in settings.gpu_worker_job_types.split(",")]
    return [t for t in GPU_JOB_TYPES if t in wanted] if settings.gpu_worker_enabled else []


def available_workers(store: Store, settings: Settings) -> list[dict[str, Any]]:
    """Active, unexpired workers that contacted the API within GPU_WORKER_ONLINE_HOURS."""
    if not settings.gpu_worker_enabled:
        return []
    now = datetime.now(UTC)
    rows, _ = store.select("gpu_workers", Query(
        eq={"status": "active"}, gt={"expires_at": now.isoformat()},
        gte={"last_seen_at": (now - timedelta(hours=settings.gpu_worker_online_hours)).isoformat()}))
    return rows


def gpu_executor(store: Store, settings: Settings, job_type: str) -> str | None:
    """'gpu' when a job of this type is left to the GPU worker; None = the server's own worker."""
    return "gpu" if job_type in routed_types(settings) and available_workers(store, settings) else None
