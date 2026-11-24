"""The configuration check: GET only, no secret in the report, honest states."""
from __future__ import annotations

import json

import httpx
import jwt

from app.doctor import FAIL, OWNER, PASS, SKIP, Doctor, main
from tests.conftest import make_settings

KEY = jwt.encode({"role": "service_role"}, "k" * 40, algorithm="HS256")
ANON = jwt.encode({"role": "anon"}, "k" * 40, algorithm="HS256")
URL = "https://abcdefghijklmnopqrst.supabase.co"


def run(handler, env=None, **kw):  # type: ignore[no-untyped-def]
    seen: list[httpx.Request] = []

    def h(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return handler(req)

    s = make_settings(supabase_url=URL, supabase_service_role_key=KEY, llm_api_key="SECRET-LLM-KEY", llm_provider="gemini", cron_secret="SECRET-CRON-VALUE-1234567890", **kw.pop("settings", {}))
    d = Doctor(s, env=env or {}, http=httpx.Client(transport=httpx.MockTransport(h)), **kw)
    checks = d.run()
    return {c.name: c for c in checks}, seen, json.dumps([c.__dict__ for c in checks], ensure_ascii=False)


def healthy(req: httpx.Request) -> httpx.Response:
    p = req.url.path
    if p == "/rest/v1/":
        return httpx.Response(200, json={"paths": {f"/rpc/{f}": {} for f in ("search_knowledge_v2", "claim_ingestion_job", "claim_agent_task", "replace_version_chunks", "rollback_document_version")}})
    if p.startswith("/storage"):
        return httpx.Response(200, json={"public": False})
    if req.headers.get("apikey") == ANON:
        return httpx.Response(200, json=[])
    if p == "/rest/v1/categories":
        return httpx.Response(200, json=[{"slug": i} for i in range(11)])
    return httpx.Response(200, json=[])


def test_only_get_requests_and_no_secret_in_the_report():
    by, seen, text = run(healthy, env={"SUPABASE_ANON_KEY": ANON})
    assert seen and {r.method for r in seen} == {"GET"}
    for secret in (KEY, ANON, "SECRET-LLM-KEY", "SECRET-CRON", "unit-test-secret"):
        assert secret not in text
    assert by["connection"].state == PASS and by["migration 0017"].state == PASS and by["public key sees no private rows"].state == PASS
    assert by["super administrator"].state == OWNER and by["translation reviewer per language"].state == OWNER
    assert by["official sources of Yuna"].state == OWNER and by["gemini models answer"].state == SKIP


def test_open_tables_public_buckets_and_missing_migrations_fail():
    def h(req):  # type: ignore[no-untyped-def]
        if req.url.path == "/rest/v1/support_tickets" and req.headers.get("apikey") == ANON:
            return httpx.Response(200, json=[{"id": 1}])
        if req.url.path.startswith("/storage"):
            return httpx.Response(200, json={"public": True})
        if req.url.path in ("/rest/v1/discovered_items", "/rest/v1/gpu_workers"):
            return httpx.Response(404, json={})
        return healthy(req)

    by, _seen, _t = run(h, env={"SUPABASE_ANON_KEY": ANON}, settings=dict(gpu_worker_enabled=True))
    assert by["public key sees no private rows"].state == FAIL and "support_tickets" in by["public key sees no private rows"].detail
    assert by["storage bucket source-files"].state == FAIL and by["migration 0015"].state == FAIL
    assert by["migration 0016"].state == SKIP and by["GPU_WORKER_ENABLED needs migration 0016"].state == FAIL


def test_a_secret_key_in_a_public_variable_fails_without_being_shown():
    by, _s, text = run(healthy, env={"NEXT_PUBLIC_SUPABASE_ANON_KEY": KEY})
    assert by["no secret key in NEXT_PUBLIC_*"].state == FAIL and KEY not in text


def test_unreachable_database_and_live_service_are_reported_not_raised():
    def down(req):  # type: ignore[no-untyped-def]
        raise httpx.ConnectError("refused")

    by, _s, _t = run(down, api="https://api.example", web="https://web.example")
    assert by["connection"].state == FAIL and any(c.state == FAIL for c in by.values())


def test_live_service_checks():
    def h(req):  # type: ignore[no-untyped-def]
        if req.url.host == "api.example":
            if req.url.path == "/health":
                return httpx.Response(200, json={"supabase": "configured", "embedding_model": "m"})
            if req.url.path in ("/api/v1/categories", "/api/v1/agents"):
                hdr = {"access-control-allow-origin": "https://web.example"} if req.headers.get("origin") == "https://web.example" else {}
                return httpx.Response(200, json=[], headers=hdr)
            return httpx.Response(401, json={})
        return httpx.Response(200) if req.url.host == "web.example" else healthy(req)

    by, _s, _t = run(h, api="https://api.example/", web="https://web.example")
    assert by["API /health"].state == PASS and by["GET /api/v1/admin/overview without sign-in"].state == PASS
    assert by["CORS refuses unknown websites"].state == PASS and by["CORS allows the website"].state == PASS


def test_command_line(capsys):  # type: ignore[no-untyped-def]
    assert main(make_settings(), api=None, web=None, as_json=True) in (0, 1)
    assert isinstance(json.loads(capsys.readouterr().out), list)
