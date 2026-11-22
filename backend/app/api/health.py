from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.core.config import Settings, get_settings

router = APIRouter(tags=["health"])


@router.get("/")
def root(settings: Settings = Depends(get_settings)) -> dict:  # type: ignore[type-arg]
    """Small landing response so visiting the bare API URL is not a 404. Touches nothing external."""
    return {
        "name": "SCH International Student Hub API",
        "status": "ok",
        "version": settings.app_version,
        "docs": "/docs",
        "health": "/health",
        "api": "/api/v1",
    }


@router.get("/health")
def health(request: Request, settings: Settings = Depends(get_settings)) -> dict:  # type: ignore[type-arg]
    """Liveness + configuration summary. Never touches the model or the database."""
    return {
        "status": "ok",
        "version": settings.app_version,
        "supabase": "configured" if settings.supabase_configured else "not_configured",
        "embedding_provider": settings.embedding_provider,
        # the model that actually runs (e.g. "...#qint8" for the ONNX provider); never loads it
        "embedding_model": _model_id(request, settings),
    }


def _model_id(request: Request, settings: Settings) -> str:
    svc = getattr(request.app.state, "services", None)
    if svc is not None:
        return str(svc.embedder.model_id)
    from app.services.embeddings.factory import build_embedding_provider

    return str(build_embedding_provider(settings).model_id)
