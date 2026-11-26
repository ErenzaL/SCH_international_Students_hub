"""Render memory probe: the real API in production mode (worker thread, int8 e5 model, PDF extraction in a child process, the same
ingestion and indexing code) with an IN-MEMORY store and file storage instead of Supabase. It exists to measure the real 512 MB / 0.1 CPU
limit of a free Render instance without a database project (docs/owner/STAGING.md, tier 2).

    PROBE_KEY=<random> PROBE_JWT_SECRET=<random> uvicorn app.memory_probe:app --host 0.0.0.0 --port $PORT

Safety, enforced at start-up:
  * refuses to start when any Supabase, Gemini, OCR, cron or database credential is set: it must never see production secrets;
  * every request except GET /health needs the header ``X-Probe-Key`` (otherwise 404), so the public URL serves nobody else;
  * no outgoing requests: website fetching is replaced by a refusal, no language model, no GPU worker, no schedules;
  * only data uploaded by the test itself (synthetic), lost at every restart; one made-up super_admin account whose tokens are signed
    with PROBE_JWT_SECRET (scripts/memory_probe_info.py makes them).
The in-memory store keeps chunks and vectors in this process, so the probe uses somewhat MORE memory than the real API: a pass is
conservative (measured locally in docs/development/RENDER-MEMORY.md).
"""
from __future__ import annotations

import os
import secrets

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.config import Settings, get_settings
from app.main import create_app
from app.repositories.memory_store import MemoryFileStorage, MemoryStore, seed_categories
from app.services.ingestion.fetcher import GuardedFetcher

#: anything that could connect the probe to real data or paid services
FORBIDDEN = ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_JWT_SECRET", "SUPABASE_ANON_KEY", "LLM_API_KEY", "GEMINI_API_KEY",
             "OCR_SPACE_API_KEY", "CRON_SECRET", "DATABASE_URL", "STAGING_DB_URL", "STAGING_SERVICE_KEY", "GPU_WORKER_TOKEN")
ADMIN_ID = "00000000-0000-4000-8000-00000000a001"
ADMIN_EMAIL = "probe-admin@memory-probe.example.com"


def refuse_secrets(env: dict[str, str]) -> None:
    bad = [k for k in FORBIDDEN if env.get(k)]
    if bad:
        raise SystemExit(f"memory probe refuses to start: {', '.join(bad)} set. It must never see real credentials; remove them.")


def build(env: dict[str, str] | None = None):  # type: ignore[no-untyped-def]
    env = dict(os.environ if env is None else env)
    refuse_secrets(env)
    key, jwt_secret = env.get("PROBE_KEY", ""), env.get("PROBE_JWT_SECRET", "")
    if len(key) < 32 or len(jwt_secret) < 32:
        raise SystemExit("set PROBE_KEY and PROBE_JWT_SECRET (at least 32 random characters each, e.g. python -c 'import secrets;print(secrets.token_urlsafe(32))')")
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None, environment="memory-probe", supabase_url="", supabase_service_role_key="", supabase_jwt_secret=jwt_secret,
        job_execution="worker", llm_provider="none", background_llm_provider="none", gpu_worker_enabled=False, agent_schedules_enabled=False,
        auto_translate_announcements=False, auto_translate_documents=False, public_machine_translations=False, cron_secret="",
        embedding_provider=env.get("EMBEDDING_PROVIDER", "e5_onnx"), embedding_cache_dir=env.get("EMBEDDING_CACHE_DIR", ""),
        retrieval_min_similarity=float(env.get("RETRIEVAL_MIN_SIMILARITY", "0.80")),
        ingestion_max_concurrent_jobs=int(env.get("INGESTION_MAX_CONCURRENT_JOBS", "1")),
        cors_allowed_origins="https://memory-probe.invalid")
    store = MemoryStore()
    seed_categories(store)
    store.insert("profiles", dict(id=ADMIN_ID, email=ADMIN_EMAIL, display_name="Memory probe", role="super_admin"))
    nowhere = GuardedFetcher(settings, transport=httpx.MockTransport(lambda r: httpx.Response(403, text="memory probe: no outgoing requests")),
                             resolver=lambda h: ["93.184.216.34"])
    app = create_app(settings, store=store, storage=MemoryFileStorage(), fetcher=nowhere)
    app.dependency_overrides[get_settings] = lambda: settings

    @app.middleware("http")
    async def probe_key(request: Request, call_next):  # type: ignore[no-untyped-def]
        if not (request.url.path == "/health" and request.method in ("GET", "HEAD")) and \
                not secrets.compare_digest(request.headers.get("x-probe-key", ""), key):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        response = await call_next(request)
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        return response

    return app


app = build() if os.environ.get("PROBE_KEY") else None
