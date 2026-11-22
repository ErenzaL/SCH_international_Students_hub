import time

import jwt
import pytest

from tests.conftest import JWT_SECRET, make_token

ADMIN_ENDPOINTS = [
    ("get", "/api/v1/admin/sources"), ("get", "/api/v1/admin/documents"), ("get", "/api/v1/admin/overview"),
    ("get", "/api/v1/admin/users"), ("get", "/api/v1/admin/settings"), ("get", "/api/v1/admin/audit-log"),
    ("get", "/api/v1/admin/ingestion-jobs"),
]


@pytest.mark.parametrize("method,path", ADMIN_ENDPOINTS)
def test_admin_endpoints_require_authentication(env, method, path):
    r = getattr(env.client, method)(path)
    assert r.status_code == 401 and r.json()["error"]["code"] == "not_authenticated"


@pytest.mark.parametrize("method,path", ADMIN_ENDPOINTS)
@pytest.mark.parametrize("role,expected", [("student", 403), ("supporter", 403), ("admin", 200), ("super_admin", 200)])
def test_admin_endpoints_role_matrix(env, method, path, role, expected):
    if role == "supporter" and path == "/api/v1/admin/sources":
        expected = 200  # Phase 2: supporters list (only) the sources they created
    r = getattr(env.client, method)(path, headers=env.auth(role))
    assert r.status_code == expected, (path, role, r.text)


def test_supporter_sees_only_own_sources(env):
    body = dict(title="Admin site", original_url="https://www.hikorea.go.kr/info", organization="Hi Korea",
                source_type="website", authority_type="official_government", scope="national", category="visa-immigration")
    assert env.client.post("/api/v1/admin/sources", json=body, headers=env.auth("admin")).status_code == 201
    r = env.client.get("/api/v1/admin/sources", headers=env.auth("supporter"))
    assert r.status_code == 200 and r.json()["total"] == 0


def test_invalid_expired_wrong_audience_and_unsigned_tokens_rejected(env):
    uid = env.users["admin"]
    bad = {
        "garbage": "not-a-jwt",
        "wrong-secret": make_token(uid, secret="x" * 40),
        "expired": make_token(uid, exp_in=-10),
        "wrong-aud": make_token(uid, aud="other"),
        "unsigned": jwt.encode({"sub": uid, "aud": "authenticated", "exp": int(time.time()) + 100}, key=None, algorithm="none"),
    }
    for name, tok in bad.items():
        r = env.client.get("/api/v1/admin/sources", headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 401, name
        assert r.json()["error"]["code"] in ("invalid_token", "not_authenticated"), name


def test_role_is_read_from_database_not_from_token_claims(env):
    tok = make_token(env.users["student"], role="super_admin", app_metadata={"role": "admin"}, user_role="admin")
    r = env.client.get("/api/v1/admin/sources", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 403


def test_valid_token_without_profile_is_forbidden(env):
    r = env.client.get("/api/v1/me", headers={"Authorization": f"Bearer {make_token('00000000-0000-0000-0000-000000000099')}"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "no_profile"


def test_me_endpoint(env):
    r = env.client.get("/api/v1/me", headers=env.auth("supporter"))
    assert r.status_code == 200 and r.json()["role"] == "supporter" and r.json()["is_staff"] is True
    r = env.client.get("/api/v1/me", headers=env.auth("student"))
    assert r.json()["is_staff"] is False


def test_only_super_admin_changes_roles_and_last_super_admin_is_protected(env):
    target = env.users["student"]
    assert env.client.patch(f"/api/v1/admin/users/{target}/role", headers=env.auth("admin"), json={"role": "admin"}).status_code == 403
    r = env.client.patch(f"/api/v1/admin/users/{target}/role", headers=env.auth("super_admin"), json={"role": "supporter"})
    assert r.status_code == 200 and r.json()["role"] == "supporter"
    r = env.client.patch(f"/api/v1/admin/users/{env.users['super_admin']}/role", headers=env.auth("super_admin"),
                         json={"role": "admin"})
    assert r.status_code == 409  # last super_admin
    assert env.client.patch(f"/api/v1/admin/users/{target}/role", headers=env.auth("super_admin"), json={"role": "root"}).status_code == 422


def test_supporter_language_assignment(env):
    sup = env.users["supporter"]
    r = env.client.put(f"/api/v1/admin/users/{sup}/languages", headers=env.auth("admin"), json={"languages": ["id", "vi", "id"]})
    assert r.status_code == 200 and r.json()["languages"] == ["id", "vi"]
    assert env.client.put(f"/api/v1/admin/users/{sup}/languages", headers=env.auth("supporter"), json={"languages": ["id"]}).status_code == 403
    assert env.client.get("/api/v1/me", headers=env.auth("supporter")).json()["languages"] == ["id", "vi"]


def test_students_and_anonymous_cannot_use_staff_endpoints(env):
    assert env.client.post("/api/v1/admin/announcements", json={}).status_code == 401
    r = env.client.post("/api/v1/admin/announcements", headers=env.auth("student"), json=dict(
        title="x", body="0123456789", category="scholarships"))
    assert r.status_code == 403


def test_supabase_not_configured_returns_503_not_fake_data():
    from fastapi.testclient import TestClient

    from app.main import create_app
    from tests.conftest import make_settings

    client = TestClient(create_app(make_settings()))  # no store injected, no supabase env
    assert client.get("/health").json()["supabase"] == "not_configured"
    cats = client.get("/api/v1/categories").json()["items"]
    assert len(cats) == 11 and cats[0]["document_count"] is None
    for method, path in [("get", "/api/v1/announcements"), ("get", "/api/v1/knowledge/documents"),
                         ("post", "/api/v1/knowledge/search")]:
        kw = {"json": {"query": "visa"}} if method == "post" else {}
        r = getattr(client, method)(path, **kw)
        assert r.status_code == 503 and r.json()["error"]["code"] == "supabase_not_configured", path
    assert client.get("/api/v1/assistant/status").json()["retrieval"] == "unavailable"
    assert client.get("/api/v1/me", headers={"Authorization": f"Bearer {make_token('u')}"}).status_code == 503


def test_error_shape_and_request_id(env):
    r = env.client.get("/api/v1/admin/sources", headers={"x-request-id": "abc123"})
    body = r.json()
    assert set(body) == {"error", "request_id"} and body["request_id"] == "abc123"
    assert r.headers["x-request-id"] == "abc123"
    assert env.client.get("/api/v1/nope").json()["error"]["code"] == "not_found"


def test_request_body_limit(env):
    big = "x" * (13 * 1024 * 1024)
    r = env.client.post("/api/v1/knowledge/search", content=big, headers={"content-type": "application/json"})
    assert r.status_code == 413 and r.json()["error"]["code"] == "request_too_large"


def test_logs_do_not_contain_tokens(env, caplog):
    import logging

    caplog.set_level(logging.INFO)
    env.client.get("/api/v1/admin/sources", headers=env.auth("admin"))
    joined = "\n".join(r.getMessage() for r in caplog.records)
    assert "Bearer" not in joined and JWT_SECRET not in joined and "eyJ" not in joined


def test_cors_allows_configured_origin_only(env):
    ok = env.client.options("/api/v1/categories", headers={"Origin": "http://localhost:3000",
                                                           "Access-Control-Request-Method": "GET"})
    bad = env.client.options("/api/v1/categories", headers={"Origin": "https://evil.example.com",
                                                            "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert "access-control-allow-origin" not in bad.headers


PROD_WEB = "https://sch-international-students-hub.onrender.com"


@pytest.mark.parametrize("var", ["CORS_ORIGINS", "CORS_ALLOWED_ORIGINS"])
def test_cors_origins_read_from_either_env_var(monkeypatch, var):
    from fastapi.testclient import TestClient

    from app.core.config import Settings
    from app.main import create_app
    from app.repositories.memory_store import MemoryStore

    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)
    monkeypatch.setenv(var, f" {PROD_WEB}/ ")  # stray whitespace and trailing slash must not break matching
    settings = Settings(_env_file=None, embedding_provider="hash")
    assert settings.cors_origins == [PROD_WEB]
    client = TestClient(create_app(settings, store=MemoryStore()))
    r = client.options("/api/v1/categories", headers={"Origin": PROD_WEB, "Access-Control-Request-Method": "GET"})
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == PROD_WEB
