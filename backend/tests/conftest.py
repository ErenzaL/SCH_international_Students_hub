from __future__ import annotations

import time
import uuid
from collections.abc import Callable

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.rate_limit import ai_budget, limiter
from app.main import create_app
from app.repositories.memory_store import MemoryFileStorage, MemoryStore, seed_categories
from app.services.embeddings.hash_provider import HashEmbeddingProvider
from app.services.ingestion.fetcher import GuardedFetcher

JWT_SECRET = "unit-test-secret-unit-test-secret-1234"
PUBLIC_IP = "93.184.216.34"


def make_settings(**overrides) -> Settings:  # type: ignore[no-untyped-def]
    base = dict(
        _env_file=None, supabase_jwt_secret=JWT_SECRET, embedding_provider="hash", environment="test",
        job_execution="inline", board_request_delay_seconds=0,
        rate_limit_search_per_minute=1000, rate_limit_ingest_per_minute=1000, rate_limit_public_per_minute=1000,
    )
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def make_token(user_id: str, *, secret: str = JWT_SECRET, aud: str = "authenticated", exp_in: int = 3600,
               alg: str = "HS256", **claims) -> str:  # type: ignore[no-untyped-def]
    payload = {"sub": user_id, "aud": aud, "exp": int(time.time()) + exp_in, "email": f"{user_id[:6]}@example.test",
               **claims}
    return jwt.encode(payload, secret, algorithm=alg)


class Env:
    """Everything a test needs: app, client, store, users, and a scriptable fake website."""

    def __init__(self) -> None:
        self.settings = make_settings()
        self.store = MemoryStore()
        seed_categories(self.store)
        self.storage = MemoryFileStorage()
        self.embedder = HashEmbeddingProvider()
        self.pages: dict[str, Callable[[httpx.Request], httpx.Response]] = {}
        self.requests: list[str] = []
        self.users: dict[str, str] = {}
        for role in ("super_admin", "admin", "supporter", "student"):
            uid = str(uuid.uuid4())
            self.users[role] = uid
            self.store.insert("profiles", dict(id=uid, email=f"{role}@example.test", display_name=role.title(), role=role))
        fetcher = GuardedFetcher(self.settings, transport=httpx.MockTransport(self._handler),
                                 resolver=lambda host: [PUBLIC_IP])
        self.app = create_app(self.settings, store=self.store, storage=self.storage, embedder=self.embedder,
                              fetcher=fetcher)
        self.client = TestClient(self.app)

    def _handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requests.append(url)
        if url in self.pages:
            return self.pages[url](request)
        if url.endswith("/robots.txt"):
            return httpx.Response(404)
        return httpx.Response(404, text="not found")

    def page(self, url: str, html: str | bytes, content_type: str = "text/html; charset=utf-8", status: int = 200) -> None:
        body = html.encode() if isinstance(html, str) else html
        self.pages[url] = lambda req: httpx.Response(status, content=body, headers={"content-type": content_type})

    def auth(self, role: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {make_token(self.users[role])}"}


@pytest.fixture
def env() -> Env:
    limiter.reset()
    ai_budget.reset()
    return Env()


ARTICLE_URL = "https://www.studyinkorea.go.kr/en_US/plan/visaAndStay.do"
ARTICLE_HTML = """<html><head><title>Visa and Stay - Study in Korea</title></head><body>
<nav><a href="/home">Home</a><a href="/about">About</a></nav>
<div id="content"><h1>Visa and Stay</h1>
<p>International students should keep their residence status valid while studying. This sample page text is test
content for the extraction pipeline and is not official guidance.</p>
<h2>Alien registration</h2>
<p>Registration happens at the immigration office. Bring your passport and documents listed on the official site.</p>
<ul><li>Passport</li><li>Photo</li></ul>
<table><tr><th>Item</th><th>Note</th></tr><tr><td>Fee</td><td>See official site</td></tr></table>
<a href="/en_US/plan/guide.do">Official guide</a></div>
<footer>Copyright footer boilerplate</footer></body></html>"""
