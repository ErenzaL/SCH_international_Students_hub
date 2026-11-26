"""The Hub API for LOCAL staging: the real application against the Supabase CLI stack on this computer, with the official websites
replaced by scripts/synthetic_web.py (no real data in, nothing out). Started by scripts/local_supabase.sh api:

    uvicorn local_api:app --app-dir scripts --host 127.0.0.1 --port 8051      (environment from local_supabase.sh)

Refuses to start unless SUPABASE_URL is an address on this computer, and when a hosted Supabase or production value is present.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

PRODUCTION = ("sch-hub-api.onrender.com", "sch-international-students-hub.onrender.com")


def check(env: dict[str, str]) -> None:
    url = env.get("SUPABASE_URL", "")
    if (urlparse(url).hostname or "") not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit("local_api refuses: SUPABASE_URL must be the Supabase stack on this computer (http://127.0.0.1:54321)")
    for k, v in env.items():
        if v and (".supabase.co" in v or ".supabase.com" in v or any(h in v for h in PRODUCTION)):
            raise SystemExit(f"local_api refuses: {k} names a hosted Supabase project or production")
    for k in ("LLM_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "OCR_SPACE_API_KEY"):
        if env.get(k):
            raise SystemExit(f"local_api refuses: {k} is set; local staging uses no paid or production keys")


def build():  # type: ignore[no-untyped-def]
    check(dict(os.environ))
    import synthetic_web

    from app.core.config import get_settings
    from app.main import create_app
    from app.services.ingestion.fetcher import GuardedFetcher

    settings = get_settings()
    app = create_app(settings, fetcher=GuardedFetcher(settings, transport=synthetic_web.transport(), resolver=lambda h: ["93.184.216.34"]))
    app.dependency_overrides[get_settings] = lambda: settings
    return app


app = build() if os.environ.get("SUPABASE_URL") else None
