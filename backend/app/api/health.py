from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.config import Settings, get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health(settings: Settings = Depends(get_settings)) -> dict:  # type: ignore[type-arg]
    """Liveness + configuration summary. Never touches the model or the database."""
    return {
        "status": "ok",
        "version": settings.app_version,
        "supabase": "configured" if settings.supabase_configured else "not_configured",
        "embedding_provider": settings.embedding_provider,
        "embedding_model": settings.embedding_model if settings.embedding_provider == "e5" else "hash-dev-384",
    }
