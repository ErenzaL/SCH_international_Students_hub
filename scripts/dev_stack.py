"""The whole Hub on one computer, for tests and demonstrations: real PostgreSQL with all migrations and access rules, the real API with
its job worker, local Qwen (Ollama), and a stand-in for Supabase sign-in. Loopback only, synthetic users, NO production connection.

    PG_BIN=... POSTGREST=... PYTHON=... scripts/scratch_db.sh start DIR && source DIR/env
    cd backend && .venv/bin/python ../scripts/dev_stack.py --info /tmp/stack.json [--llm ollama|none] [--embedding e5_onnx|hash]
    # web: NEXT_PUBLIC_API_URL=http://127.0.0.1:8051 NEXT_PUBLIC_SUPABASE_URL=http://127.0.0.1:8052 NEXT_PUBLIC_SUPABASE_ANON_KEY=any

Official websites are fetched for real (allowlist, robots.txt) unless --offline. Schedules stay off without --schedules; the GPU worker endpoints are on.
The info file (0600) holds the made-up accounts and the password of this run.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import shlex
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
for _k in list(os.environ):
    if _k.upper().startswith(("SUPABASE", "LLM_", "GEMINI", "NEXT_PUBLIC", "CRON_")):
        del os.environ[_k]
ap = argparse.ArgumentParser()
ap.add_argument("--api", type=int, default=8051)
ap.add_argument("--auth", type=int, default=8052)
ap.add_argument("--web", type=int, default=3051)
ap.add_argument("--info", required=True)
ap.add_argument("--llm", choices=["ollama", "none"], default="ollama")
ap.add_argument("--embedding", choices=["e5_onnx", "hash"], default="e5_onnx")
ap.add_argument("--offline", action="store_true")
ap.add_argument("--schedules", action="store_true", help="agent schedules may run (an administrator still enables each one)")
a = ap.parse_args()
REST, SECRET, PSQL = os.environ["SCH_IT_REST_URL"], os.environ["SCH_IT_JWT_SECRET"], os.environ["SCH_IT_PSQL"]

import app.core.config as config  # noqa: E402

config.Settings.model_config["env_file"] = None
import httpx  # noqa: E402
import jwt  # noqa: E402
import uvicorn  # noqa: E402
from fastapi import FastAPI, HTTPException, Request, Response  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from app.core.config import Settings, get_settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.repositories.memory_store import MemoryFileStorage  # noqa: E402
from app.repositories.supabase_store import SupabaseStore  # noqa: E402
from app.services.ingestion.fetcher import GuardedFetcher  # noqa: E402

PASSWORD = secrets.token_urlsafe(16)
CRON = secrets.token_urlsafe(32)
WEB = [f"http://127.0.0.1:{a.web}", f"http://localhost:{a.web}"]


def sql(q: str) -> None:
    subprocess.run(shlex.split(PSQL) + ["-v", "ON_ERROR_STOP=1", "-c", q], check=True, capture_output=True)


users: dict[str, str] = {}
for name, role in (("super_admin", "super_admin"), ("admin", "admin"), ("supporter_vi", "supporter"), ("reviewer_id", "supporter"), ("student", "student"), ("student2", "student")):
    uid = str(uuid.uuid4())
    users[name] = uid
    sql(f"insert into auth.users (id, email) values ('{uid}', '{name}@example.test')")
    sql(f"update public.profiles set role = '{role}', display_name = '{name}', preferred_language_confirmed = true where id = '{uid}'")
for name, lang in (("supporter_vi", "vi"), ("reviewer_id", "id")):
    sql(f"insert into public.supporter_languages (supporter_id, language_code, can_support, can_review_translations) values ('{users[name]}', '{lang}', true, true)")


def token(uid: str, hours: int = 4, role: str = "authenticated") -> str:
    return jwt.encode({"sub": uid, "aud": "authenticated", "role": role, "exp": int(time.time()) + hours * 3600, "email": "x@example.test"}, SECRET, algorithm="HS256")


settings = Settings(_env_file=None, environment="development", supabase_url=REST, supabase_jwt_secret=SECRET,  # type: ignore[call-arg]
                    supabase_service_role_key=jwt.encode({"role": "service_role", "exp": int(time.time()) + 24 * 3600}, SECRET, algorithm="HS256"),
                    llm_provider=a.llm, background_llm_provider="none", embedding_provider=a.embedding, job_execution="worker",
                    cors_allowed_origins=",".join(WEB), gpu_worker_enabled=True, agent_schedules_enabled=a.schedules, cron_secret=CRON, retrieval_min_similarity=0.80 if a.embedding != "hash" else 0.0,
                    board_request_delay_seconds=1.0, rate_limit_search_per_minute=600, rate_limit_ingest_per_minute=600, rate_limit_public_per_minute=3000,
                    rate_limit_chat_user_per_minute=120, rate_limit_chat_anonymous_global_per_minute=120, agent_tool_runs_per_minute=300)
fetcher = None
if a.offline:
    fetcher = GuardedFetcher(settings, transport=httpx.MockTransport(lambda r: httpx.Response(404)), resolver=lambda h: ["93.184.216.34"])
app = create_app(settings, store=SupabaseStore(settings), storage=MemoryFileStorage(), fetcher=fetcher)
app.dependency_overrides[get_settings] = lambda: settings

auth = FastAPI()
auth.add_middleware(CORSMiddleware, allow_origins=WEB, allow_methods=["*"], allow_headers=["*"])
rest = httpx.Client(base_url=REST, timeout=30, trust_env=False)


def session(name: str) -> dict:  # type: ignore[type-arg]
    uid = users[name]
    user = dict(id=uid, aud="authenticated", role="authenticated", email=f"{name}@example.test", app_metadata={}, user_metadata={}, created_at="2026-01-01T00:00:00Z")
    return dict(access_token=token(uid), token_type="bearer", expires_in=14000, expires_at=int(time.time()) + 14000, refresh_token=f"r-{name}", user=user)


@auth.post("/auth/v1/token")
async def login(request: Request) -> dict:  # type: ignore[type-arg]
    body = await request.json()
    if body.get("refresh_token", "").startswith("r-"):
        raise HTTPException(400, "sign in again")
    name = str(body.get("email", "")).split("@")[0]
    if name not in users or not secrets.compare_digest(str(body.get("password", "")), PASSWORD):
        raise HTTPException(400, "invalid login")
    return session(name)


@auth.get("/auth/v1/user")
def me(request: Request) -> dict:  # type: ignore[type-arg]
    try:
        claims = jwt.decode(request.headers.get("authorization", "")[7:], SECRET, algorithms=["HS256"], audience="authenticated")
    except jwt.PyJWTError as exc:
        raise HTTPException(401, "invalid") from exc
    return session(next(n for n, u in users.items() if u == claims["sub"]))["user"]


@auth.post("/auth/v1/logout")
def logout() -> Response:
    return Response(status_code=204)


@auth.api_route("/rest/v1/{path:path}", methods=["GET"])
def proxy(path: str, request: Request) -> Response:
    h = {k: v for k, v in request.headers.items() if k.lower() in ("authorization", "accept", "range", "prefer")}
    if "authorization" not in h or h["authorization"].count(".") != 2:
        h.pop("authorization", None)
        h["apikey"] = os.environ["SCH_IT_ANON_KEY"]
    r = rest.get(f"/rest/v1/{path}", params=request.query_params, headers=h)
    return Response(r.content, r.status_code, media_type=r.headers.get("content-type"))


fd = os.open(a.info, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w") as f:
    json.dump(dict(password=PASSWORD, cron=CRON, schedules=a.schedules, users=users, api=f"http://127.0.0.1:{a.api}", auth=f"http://127.0.0.1:{a.auth}", web=WEB[0],
                   tokens={n: token(u) for n, u in users.items()}), f)
threading.Thread(target=lambda: uvicorn.run(auth, host="127.0.0.1", port=a.auth, log_level="warning"), daemon=True).start()
uvicorn.run(app, host="127.0.0.1", port=a.api, log_level="warning")
