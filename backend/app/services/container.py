"""Service container wired once at startup (and injectable in tests)."""
from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings
from app.core.rate_limit import DailyBudget
from app.repositories.base import FileStorage, Store
from app.services.agents.tasks import AgentTaskService
from app.services.announcements import AnnouncementService
from app.services.conversations import ConversationService
from app.services.discovery.service import DiscoveryService
from app.services.document_translations import DocumentTranslationService
from app.services.domains import DomainPolicy
from app.services.embeddings.base import EmbeddingProvider
from app.services.gpu_worker import GpuWorkerService
from app.services.indexing import IndexingService
from app.services.ingestion.fetcher import GuardedFetcher
from app.services.ingestion.pipeline import IngestionService
from app.services.intake import IntakeService
from app.services.jobs import JobRunner
from app.services.llm.base import LLMProvider
from app.services.notifications import NotificationService, UserNotificationService
from app.services.ocr.providers import OCRProvider, build_ocr_provider
from app.services.public import PublicService
from app.services.rag_health import RagHealthService
from app.services.retrieval.service import RetrievalService
from app.services.review import DocumentLifecycleService, ReviewService
from app.services.source_lifecycle import SourceLifecycleService
from app.services.sources import SourceService
from app.services.support import SupportService
from app.services.translation.auto import AnnouncementAutoTranslator, translation_llm
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
    rag_health: RagHealthService
    announcement_translator: AnnouncementAutoTranslator
    discovery: DiscoveryService = None  # type: ignore[assignment]
    agents: AgentTaskService = None  # type: ignore[assignment]  # set right after construction (needs Services)
    gpu: GpuWorkerService = None  # type: ignore[assignment]  # set right after construction (needs Services)
    #: per-day attempt budget of background AI work (the chatbot's quota reserve)
    background_budget: DailyBudget | None = None


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
                                        llm=llm, settings=settings)
    support = SupportService(store, conversations, user_notes, retention_days=settings.support_retention_days)
    background_budget = DailyBudget()                 # per process / Services (one instance in production)
    # background AI (translations, summaries) has its own provider and a daily attempt budget: the chatbot's reserve
    tr_llm = translation_llm(settings, llm, background_budget)
    doc_translations = DocumentTranslationService(store, tr_llm, user_notes, settings)
    jobs = JobRunner(store, ingestion, settings)
    doc_translations.ingestion, doc_translations.jobs = ingestion, jobs
    ingestion.translations = doc_translations
    translations = TranslationReviewService(store, announcements, user_notes)
    ann_auto = AnnouncementAutoTranslator(store, tr_llm, settings, user_notes)
    ann_auto.ingestion, ann_auto.jobs, ann_auto.reviews = ingestion, jobs, translations
    translations.auto = ingestion.announcement_translator = ann_auto
    public = PublicService(store, announcements, storage)
    public.announcement_translator = ann_auto
    ann_auto.public = doc_translations.public = public
    rag_health = RagHealthService(store, embedder.model_id, notifications)
    ingestion.rag_health = announcements.rag_health = rag_health
    services = Services(
        settings=settings, store=store, storage=storage, embedder=embedder, llm=llm, indexer=indexer,
        ingestion=ingestion, review=ReviewService(store, indexer, storage), announcements=announcements,
        public=public, retrieval=retrieval,
        sources=SourceService(store, settings, domains), domains=domains, ocr=ocr,
        intake=IntakeService(store, storage, settings, ingestion, ocr), jobs=jobs,
        notifications=notifications, user_notifications=user_notes, conversations=conversations, support=support,
        translations=translations,
        lifecycle=DocumentLifecycleService(store, storage),
        source_lifecycle=SourceLifecycleService(store, storage),
        doc_translations=doc_translations, rag_health=rag_health, announcement_translator=ann_auto,
    )
    discovery = DiscoveryService(store, settings, fetcher, domains, notifications)
    discovery.sources_service, discovery.ingestion, discovery.jobs, discovery.llm = services.sources, ingestion, jobs, tr_llm
    services.discovery = discovery
    services.background_budget = background_budget
    services.agents = jobs.agents = AgentTaskService(services)
    services.gpu = GpuWorkerService(services)
    services.agents.worker_id = jobs.worker_id
    return services
