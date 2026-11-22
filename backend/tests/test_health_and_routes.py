"""Root/health endpoints and the route contract the frontend depends on."""
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def test_root_identifies_api(env):
    r = env.client.get("/")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "SCH International Student Hub API"
    assert body["status"] == "ok"
    assert body["docs"] == "/docs" and body["health"] == "/health" and body["api"] == "/api/v1"


def test_health_ok(env):
    r = env.client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_root_and_health_work_without_supabase():
    """Render's health check must pass even before Supabase is configured (no DB or model access)."""
    client = TestClient(create_app(Settings(_env_file=None, embedding_provider="hash")))
    assert client.get("/").status_code == 200
    h = client.get("/health")
    assert h.status_code == 200 and h.json()["supabase"] == "not_configured"


def test_unknown_path_is_structured_404(env):
    r = env.client.get("/definitely-not-a-route")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


# Paths the Next.js frontend calls (apps/web/src). A prefix or rename mismatch breaks the site silently.
FRONTEND_ROUTES = [
    ("get", "/api/v1/categories"), ("get", "/api/v1/announcements"), ("get", "/api/v1/announcements/{announcement_id}"),
    ("get", "/api/v1/assistant/status"), ("post", "/api/v1/knowledge/search"), ("get", "/api/v1/knowledge/documents"),
    ("get", "/api/v1/knowledge/documents/{document_id}"), ("get", "/api/v1/me"),
    ("get", "/api/v1/admin/overview"), ("get", "/api/v1/admin/settings"), ("get", "/api/v1/admin/sources"),
    ("post", "/api/v1/admin/sources"), ("post", "/api/v1/admin/sources/{source_id}/ingest"),
    ("post", "/api/v1/admin/sources/{source_id}/upload"), ("post", "/api/v1/admin/sources/{source_id}/submit-text"),
    ("post", "/api/v1/admin/sources/{source_id}/disable"), ("post", "/api/v1/admin/sources/{source_id}/enable"),
    ("get", "/api/v1/admin/documents"), ("get", "/api/v1/admin/documents/{document_id}"),
    ("post", "/api/v1/admin/versions/{version_id}/approve"), ("post", "/api/v1/admin/versions/{version_id}/reject"),
    ("post", "/api/v1/admin/announcements/{announcement_id}/approve"), ("get", "/api/v1/admin/users"),
]


@pytest.fixture(scope="module")
def spec_paths():
    return create_app(Settings(_env_file=None, embedding_provider="hash")).openapi()["paths"]


@pytest.mark.parametrize("method,path", FRONTEND_ROUTES)
def test_frontend_routes_exist(spec_paths, method, path):
    # parameter names can differ; compare the path shape
    import re

    shape = re.sub(r"\{[^}]+\}", "{}", path)
    matches = [p for p in spec_paths if re.sub(r"\{[^}]+\}", "{}", p) == shape]
    assert matches, f"no backend route for {path}"
    assert any(method in spec_paths[p] for p in matches), f"{method.upper()} not allowed on {path}"


def test_public_endpoints_respond(env):
    assert env.client.get("/api/v1/categories").status_code == 200
    assert env.client.get("/api/v1/announcements").status_code == 200
    assert env.client.get("/api/v1/knowledge/documents").status_code == 200
    r = env.client.post("/api/v1/knowledge/search", json={"query": "D-2 visa"})
    assert r.status_code == 200 and r.json()["results"] == []  # no approved content in a fresh store


def test_admin_requires_auth_and_me_works(env):
    assert env.client.get("/api/v1/admin/sources").status_code == 401
    me = env.client.get("/api/v1/me", headers=env.auth("admin"))
    assert me.status_code == 200 and me.json()["role"] == "admin"
