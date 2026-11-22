"""Service container wired once at startup (and injectable in tests)."""
from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings
from app.repositories.base import FileStorage, Store
from app.services.announcements import AnnouncementService
from app.services.embeddings.base import EmbeddingProvider
from app.services.indexing import IndexingService
from app.services.ingestion.fetcher import GuardedFetcher
from app.services.ingestion.pipeline import IngestionService
from app.services.llm.base import LLMProvider
from app.services.public import PublicService
from app.services.retrieval.service import RetrievalService
from app.services.review import ReviewService
from app.services.sources import SourceService


@dataclass
class Services:
    settings: Settings
    store: Store
    storage: FileStorage | None
    embedder: EmbeddingProvider
    llm: LLMProvider
    indexer: IndexingService
    ingestion: IngestionService
    review: ReviewService
    announcements: AnnouncementService
    public: PublicService
    retrieval: RetrievalService
    sources: SourceService


def build_services(settings: Settings, store: Store, storage: FileStorage | None, embedder: EmbeddingProvider,
                   llm: LLMProvider, fetcher: GuardedFetcher | None = None) -> Services:
    indexer = IndexingService(store, embedder, settings)
    announcements = AnnouncementService(store, indexer)
    return Services(
        settings=settings, store=store, storage=storage, embedder=embedder, llm=llm, indexer=indexer,
        ingestion=IngestionService(store, storage, settings, indexer, fetcher),
        review=ReviewService(store, indexer), announcements=announcements,
        public=PublicService(store, announcements), retrieval=RetrievalService(store, embedder, settings),
        sources=SourceService(store, settings),
    )
