"""Service container wired once at startup (and injectable in tests)."""
from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings
from app.repositories.base import FileStorage, Store
from app.services.announcements import AnnouncementService
from app.services.domains import DomainPolicy
from app.services.embeddings.base import EmbeddingProvider
from app.services.indexing import IndexingService
from app.services.ingestion.fetcher import GuardedFetcher
from app.services.ingestion.pipeline import IngestionService
from app.services.intake import IntakeService
from app.services.jobs import JobRunner
from app.services.llm.base import LLMProvider
from app.services.notifications import NotificationService
from app.services.ocr.providers import OCRProvider, build_ocr_provider
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
    domains: DomainPolicy
    ocr: OCRProvider
    intake: IntakeService
    jobs: JobRunner
    notifications: NotificationService


def build_services(settings: Settings, store: Store, storage: FileStorage | None, embedder: EmbeddingProvider,
                   llm: LLMProvider, fetcher: GuardedFetcher | None = None, ocr: OCRProvider | None = None) -> Services:
    indexer = IndexingService(store, embedder, settings)
    announcements = AnnouncementService(store, indexer)
    domains = DomainPolicy(store, settings)
    fetcher = fetcher or GuardedFetcher(settings)
    fetcher.domains = domains.domains  # environment allowlist + admin-managed domains
    ocr = ocr or build_ocr_provider(settings)
    notifications = NotificationService(store)
    ingestion = IngestionService(store, storage, settings, indexer, fetcher, ocr, notifications=notifications)
    return Services(
        settings=settings, store=store, storage=storage, embedder=embedder, llm=llm, indexer=indexer,
        ingestion=ingestion, review=ReviewService(store, indexer, storage), announcements=announcements,
        public=PublicService(store, announcements), retrieval=RetrievalService(store, embedder, settings),
        sources=SourceService(store, settings, domains), domains=domains, ocr=ocr,
        intake=IntakeService(store, storage, settings, ingestion, ocr), jobs=JobRunner(store, ingestion, settings),
        notifications=notifications,
    )
