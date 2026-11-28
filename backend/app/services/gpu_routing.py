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


ANNOUNCEMENT = "translate_announcement"


def gemini_fallback(settings: Settings) -> bool:
    """TRANSLATION_FALLBACK_TO_GEMINI: may announcement translations use the server's own (paid) model at all?"""
    return bool(settings.translation_fallback_to_gemini)


def announcement_route(store: Store, settings: Settings, llm_enabled: bool) -> tuple[str | None, str | None]:
    """Where a NEW announcement translation job runs: ('gpu' | 'local', None) or (None, reason it cannot run).

    * GPU worker on for announcements: always 'gpu' - the job waits while the worker is offline. Only with
      TRANSLATION_FALLBACK_TO_GEMINI and no usable worker does it go to the server's model.
    * GPU worker off: the server's model only with TRANSLATION_FALLBACK_TO_GEMINI, else it cannot run."""
    on = ANNOUNCEMENT in routed_types(settings)
    fallback = gemini_fallback(settings) and llm_enabled
    if on:
        if fallback and not available_workers(store, settings):
            return "local", None
        return "gpu", None
    if fallback:
        return "local", None
    if gemini_fallback(settings):
        return None, "llm_disabled"
    return None, "translation_worker_disabled"
