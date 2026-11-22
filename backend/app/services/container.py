"""Service container wired once at startup (and injectable in tests)."""
from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings
from app.repositories.base import FileStorage, Store
from app.services.announcements import AnnouncementService
from app.services.conversations import ConversationService
from app.services.document_translations import DocumentTranslationService
from app.services.domains import DomainPolicy
from app.services.embeddings.base import EmbeddingProvider
from app.services.indexing import IndexingService
from app.services.ingestion.fetcher import GuardedFetcher
from app.services.ingestion.pipeline import IngestionService
from app.services.intake import IntakeService
from app.services.jobs import JobRunner
from app.services.llm.base import LLMProvider
from app.services.notifications import NotificationService, UserNotificationService
from app.services.ocr.providers import OCRProvider, build_ocr_provider
from app.services.public import PublicService
from app.services.retrieval.service import RetrievalService
from app.services.review import DocumentLifecycleService, ReviewService
from app.services.source_lifecycle import SourceLifecycleService
from app.services.sources import SourceService
from app.services.support import SupportService
from app.services.translations import TranslationReviewService


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
    user_notifications: UserNotificationService
    conversations: ConversationService
    support: SupportService
    translations: TranslationReviewService
    lifecycle: DocumentLifecycleService
    source_lifecycle: SourceLifecycleService
    doc_translations: DocumentTranslationService


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
    user_notes = UserNotificationService(store)
    retrieval = RetrievalService(store, embedder, settings)
    conversations = ConversationService(store, retrieval, retention_days=settings.conversation_retention_days,
                                        llm=llm)
    support = SupportService(store, conversations, user_notes, retention_days=settings.support_retention_days)
    doc_translations = DocumentTranslationService(store, llm, user_notes, settings)
    jobs = JobRunner(store, ingestion, settings)
    doc_translations.ingestion, doc_translations.jobs = ingestion, jobs
    ingestion.translations = doc_translations
    return Services(
        settings=settings, store=store, storage=storage, embedder=embedder, llm=llm, indexer=indexer,
        ingestion=ingestion, review=ReviewService(store, indexer, storage), announcements=announcements,
        public=PublicService(store, announcements), retrieval=retrieval,
        sources=SourceService(store, settings, domains), domains=domains, ocr=ocr,
        intake=IntakeService(store, storage, settings, ingestion, ocr), jobs=jobs,
        notifications=notifications, user_notifications=user_notes, conversations=conversations, support=support,
        translations=TranslationReviewService(store, announcements, user_notes),
        lifecycle=DocumentLifecycleService(store, storage),
        source_lifecycle=SourceLifecycleService(store, storage),
        doc_translations=doc_translations,
    )
