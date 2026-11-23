"""Application settings, loaded from environment variables (never hard-code secrets)."""
from __future__ import annotations

from functools import lru_cache

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_ALLOWED_DOMAINS = (
    "sch.ac.kr,studyinkorea.go.kr,hikorea.go.kr,topik.go.kr,nhis.or.kr,moel.go.kr,visa.go.kr,immigration.go.kr"
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore", case_sensitive=False)

    app_version: str = "0.1.0"
    environment: str = "development"
    log_level: str = "INFO"

    # --- Supabase (server side only) ---------------------------------------
    supabase_url: str = ""
    supabase_service_role_key: str = Field(default="", repr=False)
    # Legacy HS256 projects: JWT secret. Projects using asymmetric signing keys are
    # verified through the JWKS endpoint derived from SUPABASE_URL (no secret needed).
    supabase_jwt_secret: str = Field(default="", repr=False)
    supabase_jwt_audience: str = "authenticated"
    source_files_bucket: str = "source-files"

    # --- HTTP ---------------------------------------------------------------
    # Comma-separated. Read from CORS_ORIGINS or CORS_ALLOWED_ORIGINS (first one set wins).
    cors_allowed_origins: str = Field(
        default="http://localhost:3000",
        validation_alias=AliasChoices("cors_allowed_origins", "cors_origins"),
    )
    max_request_body_mb: int = 12

    # --- Ingestion / SSRF guard ---------------------------------------------
    allowed_source_domains: str = DEFAULT_ALLOWED_DOMAINS
    fetch_timeout_seconds: float = 20.0
    max_response_mb: int = 5
    max_upload_mb: int = 10
    max_redirects: int = 4
    respect_robots_txt: bool = True
    fetch_user_agent: str = "SCH-International-Hub-Bot/0.1 (+official-source ingestion; contact: site admin)"
    min_extracted_chars: int = 40

    # --- Chunking -----------------------------------------------------------
    chunk_target_tokens: int = 320
    chunk_max_tokens: int = 420
    chunk_overlap_tokens: int = 48

    # --- Embeddings ---------------------------------------------------------
    embedding_provider: str = "e5"  # "e5" (sentence-transformers) | "hash" (dev/test only, NOT semantic)
    embedding_model: str = "intfloat/multilingual-e5-small"
    embedding_dimensions: int = 384
    embedding_batch_size: int = 16
    embedding_onnx_variant: str = "qint8"   # e5_onnx: qint8 (~118 MB, default) | fp32 | o4
    embedding_onnx_batch_size: int = 1      # e5_onnx: 1 keeps peak memory lowest on 512 MB instances
    embedding_threads: int = 0              # e5_onnx: 0 = min(2, CPUs)
    embedding_cache_dir: str = ""           # model files cache (default: Hugging Face cache); set to a path inside
                                            # the deploy so the build-time prefetch is reused at runtime

    # --- Retrieval -----------------------------------------------------------
    # Vector-only matches below this cosine similarity are dropped unless they also match a keyword.
    retrieval_min_similarity: float = 0.0
    # "weighted" (default): dense and keyword candidates are fetched separately and fused in the application with
    # semantic relevance weighted above keyword overlap (keyword evidence scored by query-term rarity, so broad
    # words such as "visa" cannot dominate). "sql_rrf": the original equal-weight fusion inside search_knowledge_v2
    # (kept for benchmarking). Per request, mode="vector" | "keyword" | "hybrid" | "hybrid_legacy".
    retrieval_fusion: str = "weighted"
    retrieval_vector_weight: float = 1.0
    retrieval_keyword_weight: float = 0.35
    retrieval_candidate_pool: int = 30        # candidates fetched per leg before fusion
    retrieval_max_chunks_per_document: int = 3
    # a passage that names a different visa/status code (E-7, F-2-R ...) but not the one asked about is demoted
    retrieval_code_mismatch_penalty: float = 0.5

    # --- SCH notice board connector ------------------------------------------
    board_max_items: int = 5          # notices imported per sync unless the source config says otherwise
    board_max_items_cap: int = 30     # hard upper bound per sync (polite crawling)
    board_max_pages: int = 1
    board_request_delay_seconds: float = 1.0

    # --- OCR (screenshots, image-only PDFs) -----------------------------------
    # "none" (manual transcription), "tesseract" (local binary; Docker/dev), "ocr_space" (hosted free tier)
    ocr_provider: str = "none"
    ocr_languages: str = "kor+eng"    # tesseract language codes
    ocr_space_api_key: str = Field(default="", repr=False)
    ocr_space_language: str = "kor"
    ocr_space_engine: int = 1
    ocr_timeout_seconds: float = 60.0
    ocr_max_pdf_pages: int = 10
    max_image_mb: int = 8

    # --- Jobs ------------------------------------------------------------------
    # "worker": persisted queue claimed by an in-process worker thread (survives restarts: queued jobs
    # are picked up again, stale running jobs are re-queued). "inline": run in the request's background
    # task (tests / single-shot scripts).
    job_execution: str = "worker"
    # Pre-review content is chunked but NOT embedded; embeddings are generated by the index job after approval.
    embed_on_ingest: bool = False
    job_retry_base_seconds: int = 30
    # --- Retention (private student data) -----------------------------------
    conversation_retention_days: int = 365   # AI conversations deleted after this many days without activity
    support_retention_days: int = 365        # resolved support tickets (and their threads) deleted after this   # transient failures re-queue after 30 s, 60 s, 120 s ... (max_attempts)
    job_poll_seconds: float = 10.0
    # running jobs heartbeat every job_heartbeat_seconds (a background ticker, also during long extractions);
    # a job without a heartbeat for job_stale_seconds belongs to a dead worker and is re-queued (or failed after
    # max_attempts). Right after a restart the first claim uses the shorter job_startup_stale_seconds.
    job_heartbeat_seconds: float = 15.0
    job_stale_seconds: int = 180
    job_startup_stale_seconds: int = 90
    job_max_runtime_seconds: int = 1800     # heartbeats stop after this, so a hung job goes stale and is recovered
    # --- Assistant ----------------------------------------------------------------
    # without an LLM: passages at/above this similarity (or keyword/exact matches) count as sufficient evidence
    assistant_strong_similarity: float = 0.84
    assistant_anonymous_chat: bool = True     # visitors who are not signed in can chat (no history, no handoff)
    assistant_history_turns: int = 6          # earlier messages given to rewriting and generation
    # behavioral specification: app/services/assistant/prompts/<version>.txt (recorded with every answer)
    assistant_prompt_version: str = "system_v2"
    # follow-up suggestion chips under answers (off: answers end when they are complete)
    assistant_follow_up_suggestions: bool = False
    assistant_max_sources: int = 4            # distinct source documents given to the model per answer
    assistant_max_passages_per_source: int = 3
    assistant_context_chars: int = 9000       # total passage text sent to the model
    # evidence-sufficiency layer (app/services/assistant/evidence.py). OFF by default: chat behaviour is unchanged
    # unless enabled. When on: neighbouring chunks / one targeted search for missing information types, and an
    # ``evidence_check`` report in the response's retrieval metadata (still-missing information is recorded).
    assistant_evidence_check: bool = False
    assistant_evidence_adjacent: bool = True
    assistant_evidence_second_search: bool = True
    assistant_evidence_max_added_passages: int = 4
    assistant_evidence_max_added_chars: int = 3000
    # optional cross-encoder reranking of the first-stage hybrid results (app/services/retrieval/rerank.py). OFF by
    # default; needs a local ONNX export and measured memory/latency on the target instance before it is enabled.
    rerank_provider: str = "none"            # none | onnx
    rerank_model_path: str = ""              # e.g. /models/mminilm/model_int8.onnx
    rerank_tokenizer_path: str = ""          # its sentencepiece.bpe.model
    rerank_top_n: int = 20                   # first-stage passages scored by the cross-encoder
    rerank_batch_size: int = 4               # pairs per forward pass (activation memory grows with it)
    rerank_threads: int = 1
    rerank_max_length: int = 512
    # --- PDF extraction --------------------------------------------------------
    # subprocess: a child process per PDF with a hard timeout (a crash or OOM fails the job, not the service)
    pdf_extraction_isolation: str = "subprocess"     # subprocess | inline (tests)
    pdf_extract_timeout_seconds: float = 300.0
    pdf_extract_memory_mb: int = 0          # address-space cap for the child (Linux); 0 = no extra cap
    pdf_table_detection: str = "off"        # off | auto (find_tables() costs ~230 MB; enable only on larger plans)
    pdf_max_table_items: int = 1500         # auto mode: skip table detection on pages with more drawing operations
    pdf_max_pages: int = 300
    # new versions whose publication date / declared edition is older than this get a reviewer warning to verify
    # time-sensitive guidance (nothing is changed or hidden automatically)
    source_review_age_days: int = 3 * 365
    # Shared secret for POST /api/v1/internal/sync/run-due (external scheduler). Empty = endpoint disabled.
    cron_secret: str = Field(default="", repr=False)

    # --- LLM (optional): answer generation + translation drafts -------------
    llm_provider: str = "none"               # none | anthropic | gemini
    # server-side secret; empty = the SDK reads its own variable (ANTHROPIC_API_KEY / GEMINI_API_KEY)
    llm_api_key: str = Field(default="", repr=False)
    llm_model: str = "claude-opus-5-5"       # anthropic only
    llm_effort: str = "medium"               # low | medium | high | xhigh | max
    llm_timeout_seconds: float = 120.0
    # Gemini (LLM_PROVIDER=gemini). gemini-3.5-flash is deprecated and routed by Google to gemini-3.6-flash, so the
    # stable successor is the default primary (verify with `python -m app.cli check-llm`).
    gemini_primary_model: str = "gemini-3.6-flash"
    gemini_fallback_model: str = "gemini-3.5-flash-lite"   # empty = no fallback model
    gemini_thinking_level: str = "low"       # minimal | low | medium | high ("" = model default)
    llm_temperature: float | None = None     # None = the model's default (recommended for Gemini 3 models)
    llm_answer_max_tokens: int = 2048        # answer generation output cap (thinking tokens count separately)
    llm_request_timeout_seconds: float = 30.0   # per attempt (assistant answers); translation jobs use llm_timeout
    llm_max_attempts_per_model: int = 2      # primary: 1 try + 1 retry on retryable errors; fallback: same bound
    llm_retry_base_seconds: float = 0.8      # exponential backoff with full jitter
    llm_retry_max_delay_seconds: float = 8.0  # a server-requested delay above this is not waited for (fail over)
    llm_request_deadline_seconds: float = 45.0  # interactive calls: no new attempt starts after this much time
    llm_fast_timeout_seconds: float = 12.0    # query rewriting: one quick attempt (fast model first)
    # --- AI usage budgets (in-process, reset at 00:00 KST; one instance) -------------------------------------
    ai_daily_limit_per_client: int = 40      # anonymous visitors, per client IP
    ai_daily_limit_per_user: int = 150       # signed-in students
    ai_daily_limit_global: int = 1500        # all generated answers; beyond it answers degrade, never fail open
    # translation drafts: documents are translated in chunks of about this many characters (one job per language)
    translation_chunk_chars: int = 6000
    # create AI drafts automatically when a new original version is approved (needs an LLM provider)
    auto_translate_documents: bool = False
    # show unreviewed machine drafts to students (clearly labelled as machine translation). Off = original only.
    public_machine_translations: bool = False
    # --- automatic machine translation (app/services/translation/auto.py) -------------------------------------
    auto_translate_announcements: bool = False    # queue machine translations when an announcement is published
    auto_translate_languages: str = "ko,en"       # target languages generated automatically (others: by request)
    translation_model: str = ""                   # Gemini model for translation jobs ("" = the assistant's models)
    translation_full_max_chars: int = 12000       # longer documents: title + AI summary only (labelled as summary)
    translation_summary_source_chars: int = 40000  # text given to the summarizer (plus all section headings)
    translation_max_requests_per_job: int = 6      # model calls per job (title + parts); longer -> human translation
    translation_daily_job_limit: int = 60          # translation jobs started per UTC day; more wait until tomorrow
    translation_quota_retry_seconds: int = 3600    # provider quota exhausted: try the job again after this long
    translation_max_deferrals: int = 24            # ... at most this many times, then the job fails visibly
    # unreviewed machine translations of immigration / employment / insurance / fee / legal content:
    # 'label' = shown with a prominent "unverified" label; 'review' = hidden until a reviewer approves it
    machine_translation_high_risk: str = "label"

    # --- Rate limits (per client IP, per minute; in-process) -----------------
    rate_limit_search_per_minute: int = 30
    rate_limit_ingest_per_minute: int = 20
    rate_limit_public_per_minute: int = 120
    rate_limit_chat_user_per_minute: int = 12      # signed-in assistant turns, per user id
    rate_limit_chat_anonymous_per_minute: int = 6           # anonymous assistant turns per client IP
    rate_limit_chat_anonymous_global_per_minute: int = 60   # all anonymous assistant turns together (spoof-proof cap)
    # Client IP resolution behind proxies. X-Forwarded-For is read from the RIGHT: the entry appended by the
    # outermost of `trusted_proxy_hops` trusted proxies (0 = ignore X-Forwarded-For, use the socket peer). The
    # left-most entry is client-controlled and never used. A header the edge proxy SETS (overwriting any client
    # value), e.g. "true-client-ip" or "cf-connecting-ip", can be trusted instead - but ONLY after verifying on the
    # deployment that a client-sent value does not pass through (GET /api/v1/admin/system/client-ip). Empty = off.
    client_ip_header: str = ""
    trusted_proxy_hops: int = 1

    @field_validator("supabase_url")
    @classmethod
    def _strip_url(cls, v: str) -> str:
        return v.strip().rstrip("/")

    @property
    def supabase_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_role_key)

    @property
    def cors_origins(self) -> list[str]:
        # Browsers send Origin without a trailing slash, so "https://x.onrender.com/" must still match.
        return [o.strip().rstrip("/") for o in self.cors_allowed_origins.split(",") if o.strip()]

    @property
    def allowed_domains(self) -> list[str]:
        return [d.strip().lower().lstrip(".") for d in self.allowed_source_domains.split(",") if d.strip()]

    @property
    def max_response_bytes(self) -> int:
        return self.max_response_mb * 1024 * 1024

    @property
    def max_image_bytes(self) -> int:
        return self.max_image_mb * 1024 * 1024

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
