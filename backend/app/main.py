"""FastAPI application factory."""
from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    admin_announcements,
    admin_documents,
    admin_intake,
    admin_knowledge,
    admin_sources,
    admin_system,
    agents,
    document_translations,
    health,
    public,
    support,
)
from app.core.config import Settings, get_settings
from app.core.errors import install_error_handlers
from app.core.logging import RequestLoggingMiddleware, configure_logging
from app.repositories.base import FileStorage, Store
from app.services.container import build_services
from app.services.embeddings.base import EmbeddingProvider
from app.services.embeddings.factory import build_embedding_provider
from app.services.ingestion.fetcher import GuardedFetcher
from app.services.llm.base import LLMProvider, build_llm_from_settings

log = logging.getLogger("app")


def create_app(settings: Settings | None = None, *, store: Store | None = None, storage: FileStorage | None = None,
               embedder: EmbeddingProvider | None = None, fetcher: GuardedFetcher | None = None,
               llm: LLMProvider | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
        svc = app.state.services
        if svc is not None:
            if svc.jobs.inline:
                try:  # inline mode: jobs left 'running' by a previous process can never finish -> failed (retryable)
                    n = svc.ingestion.recover_interrupted_jobs()
                    if n:
                        log.warning("marked %d interrupted ingestion job(s) as failed", n)
                except Exception:  # noqa: BLE001 - startup must not fail because the DB is briefly unreachable
                    log.exception("job recovery skipped")
            else:
                svc.jobs.start()  # resumes queued jobs; stale running ones are re-queued by the claim RPC
        yield
        if svc is not None:
            svc.jobs.stop()

    app = FastAPI(
        title="SCH International Student Hub API", version=settings.app_version, lifespan=lifespan,
        description="Multilingual information platform for international students. See docs/api-contract.md.",
    )
    app.dependency_overrides[get_settings] = lambda: settings

    app.state.services = None
    emb = embedder or build_embedding_provider(settings)  # constructing is cheap; the model loads lazily
    if store is None and settings.supabase_configured:
        from app.repositories.supabase_store import SupabaseFileStorage, SupabaseStore

        sb = SupabaseStore(settings)
        store, storage = sb, SupabaseFileStorage(sb, settings.source_files_bucket)
    app.state.store = store
    if store is not None:
        app.state.services = build_services(settings, store, storage, emb, llm or build_llm_from_settings(settings), fetcher)

    app.add_middleware(RequestLoggingMiddleware, max_body_bytes=settings.max_request_body_mb * 1024 * 1024)
    app.add_middleware(
        CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"], expose_headers=["X-Request-ID"],
    )
    install_error_handlers(app)
    for r in (health.router, public.router, admin_sources.router, admin_documents.router,
              admin_announcements.router, admin_system.router, admin_intake.router, admin_knowledge.router,
              admin_knowledge.internal, support.router, document_translations.router, agents.router):
        app.include_router(r)
    return app


app = create_app()

_ = threading
