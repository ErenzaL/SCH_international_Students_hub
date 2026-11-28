"""Server for scripts/e2e_review.mjs: the real API (in-memory store, SYNTHETIC data, a fake notice board) and a stand-in for
Supabase login. Loopback only; the signing secret and the password are made for this run.

    cd backend && .venv/bin/python ../scripts/e2e_review_server.py --api 8031 --auth 8032 --web 3031 --info /tmp/e2e.json
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
for k in list(os.environ):
    if k.upper().startswith(("SUPABASE", "LLM_", "GEMINI")):
        del os.environ[k]
ap = argparse.ArgumentParser()
for name in ("api", "auth", "web"):
    ap.add_argument(f"--{name}", type=int, required=True)
ap.add_argument("--info", required=True)
a = ap.parse_args()
os.environ["CORS_ORIGINS"] = f"http://127.0.0.1:{a.web}"
import tests.conftest as conf  # noqa: E402

conf.JWT_SECRET = secrets.token_urlsafe(48)
import jwt  # noqa: E402
import uvicorn  # noqa: E402
from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from app.repositories.base import get_one  # noqa: E402
from app.services.ingestion.normalize import content_hash  # noqa: E402
from app.services.llm.base import ScriptedLLMProvider  # noqa: E402
from tests.test_document_attachments import NO, setup  # noqa: E402
from tests.test_phase2 import make_board_source  # noqa: E402

PASSWORD = secrets.token_urlsafe(16)
settings_real = conf.make_settings
conf.make_settings = lambda **kw: settings_real(supabase_jwt_secret=conf.JWT_SECRET, **kw)
conf.make_token = lambda uid, **kw: jwt.encode({"sub": uid, "aud": "authenticated", "exp": int(time.time()) + 7200, "email": "x@example.test"},
                                               conf.JWT_SECRET, algorithm="HS256")
env = conf.Env()
for uid in env.users.values():      # no first-login language dialog over the pages
    env.store.update("profiles", {"preferred_language_confirmed": True}, {"id": uid})
prompts: list[str] = []
svc = env.app.state.services
svc.doc_translations.llm = svc.announcement_translator.llm = ScriptedLLMProvider(
    lambda s, p: (prompts.append(p), "Storage notice 2026-12-01")[1])


def session(role: str) -> dict:  # type: ignore[type-arg]
    uid = env.users[role]
    user = dict(id=uid, aud="authenticated", role="authenticated", email=f"{role}@example.test", app_metadata={}, user_metadata={},
                created_at="2026-01-01T00:00:00Z")
    return dict(access_token=conf.make_token(uid), token_type="bearer", expires_in=7200, expires_at=int(time.time()) + 7200,
                refresh_token="r", user=user)


auth = FastAPI()
auth.add_middleware(CORSMiddleware, allow_origins=[f"http://127.0.0.1:{a.web}"], allow_methods=["*"], allow_headers=["*"])


@auth.post("/auth/v1/token")
async def token(request: Request) -> dict:  # type: ignore[type-arg]
    body = await request.json()
    role = str(body.get("email", "")).split("@")[0]
    if role not in env.users or body.get("password") != PASSWORD:
        raise HTTPException(400, "invalid login")
    return session(role)


@auth.get("/auth/v1/user")
def user(request: Request) -> dict:  # type: ignore[type-arg]
    try:
        claims = jwt.decode(request.headers.get("authorization", "")[7:], conf.JWT_SECRET, algorithms=["HS256"], audience="authenticated")
    except jwt.PyJWTError as exc:
        raise HTTPException(401, "invalid") from exc
    return session(next(r for r, u in env.users.items() if u == claims["sub"]))["user"]


@auth.post("/control/{what}")
async def control(what: str, request: Request) -> dict:  # type: ignore[type-arg]
    """Only with this run's password: change the fake board, look at what the model was given."""
    b = await request.json()
    if b.get("password") != PASSWORD:
        raise HTTPException(403, "no")
    if what == "board":
        setup(env, *b["files"], body=f"<p>{b['body']}</p>", title=b["title"])
        return {}
    if what == "announcement-edit":
        ann = get_one(env.store, "announcements", id=b["id"])
        v = env.store.insert("document_versions", dict(document_id=ann["document_id"], version_number=2, extracted_text=b["text"],
                                                       content_hash=content_hash(b["text"]), verification_status="pending_review"))
        svc.indexer.index_version(v["id"])
        return dict(document_id=ann["document_id"])
    out = list(prompts)
    prompts.clear()
    return dict(prompts=out)


def serve(app: FastAPI, port: int) -> None:
    uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="off")).run()


setup(env, "x.pdf")
src = make_board_source(env)
fd = os.open(a.info, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w") as f:
    json.dump(dict(password=PASSWORD, source=src["id"], notice=str(NO), token=conf.make_token(env.users["super_admin"])), f)
threading.Thread(target=serve, args=(auth, a.auth), daemon=True).start()
serve(env.app, a.api)
