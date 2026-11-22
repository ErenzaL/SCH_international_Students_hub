"""Application settings, loaded from environment variables (never hard-code secrets)."""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_ALLOWED_DOMAINS = (
    "sch.ac.kr,studyinkorea.go.kr,hikorea.go.kr,topik.go.kr,nhis.or.kr,moel.go.kr"
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
    cors_allowed_origins: str = "http://localhost:3000"
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

    # --- Retrieval -----------------------------------------------------------
    # Vector-only matches below this cosine similarity are dropped unless they also match a keyword.
    retrieval_min_similarity: float = 0.0

    # --- LLM (optional, later phase) ----------------------------------------
    llm_provider: str = "none"
    llm_api_key: str = Field(default="", repr=False)

    # --- Rate limits (per client IP, per minute; in-process) -----------------
    rate_limit_search_per_minute: int = 30
    rate_limit_ingest_per_minute: int = 20
    rate_limit_public_per_minute: int = 120

    @field_validator("supabase_url")
    @classmethod
    def _strip_url(cls, v: str) -> str:
        return v.strip().rstrip("/")

    @property
    def supabase_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_role_key)

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

    @property
    def allowed_domains(self) -> list[str]:
        return [d.strip().lower().lstrip(".") for d in self.allowed_source_domains.split(",") if d.strip()]

    @property
    def max_response_bytes(self) -> int:
        return self.max_response_mb * 1024 * 1024

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
