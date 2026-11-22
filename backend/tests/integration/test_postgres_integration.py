"""Integration test: real SupabaseStore (supabase-py) -> PostgREST -> PostgreSQL + pgvector + the real migrations.

Skipped unless these are set (see docs/setup.md "Running the integration test"):
  SCH_IT_REST_URL  base URL that serves /rest/v1 (e.g. http://127.0.0.1:54331 via scripts/dev_rest_proxy.py)
  SCH_IT_PSQL      psql command line for the scratch DB, e.g. "psql -h localhost -p 54329 -U postgres -d hub -q -t -A"
  SCH_IT_JWT_SECRET  the PostgREST JWT secret
"""
from __future__ import annotations

import os
import shlex
import subprocess
import time
import uuid
from datetime import date, timedelta

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.errors import Forbidden
from app.core.rate_limit import limiter
from app.main import create_app
from app.repositories.memory_store import MemoryFileStorage
from app.repositories.supabase_store import SupabaseStore
from app.services.embeddings.hash_provider import HashEmbeddingProvider
from app.services.ingestion.fetcher import GuardedFetcher
from tests.conftest import ARTICLE_HTML, ARTICLE_URL, PUBLIC_IP

REST = os.environ.get("SCH_IT_REST_URL")
PSQL = os.environ.get("SCH_IT_PSQL")
SECRET = os.environ.get("SCH_IT_JWT_SECRET", "unit-test-secret-unit-test-secret-1234")
pytestmark = pytest.mark.skipif(not (REST and PSQL), reason="set SCH_IT_REST_URL and SCH_IT_PSQL to run")


def sql(statement: str) -> str:
    out = subprocess.run(shlex.split(PSQL or "") + ["-v", "ON_ERROR_STOP=1", "-c", statement], capture_output=True,
                         text=True)
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


class IT:
    def __init__(self) -> None:
        limiter.reset()
        service_key = jwt.encode({"role": "service_role", "exp": int(time.time()) + 3600}, SECRET, algorithm="HS256")
        self.settings = Settings(_env_file=None, supabase_url=REST, supabase_service_role_key=service_key,
                                 supabase_jwt_secret=SECRET, embedding_provider="hash",
                                 rate_limit_search_per_minute=1000, rate_limit_ingest_per_minute=1000,
                                 rate_limit_public_per_minute=1000, job_execution="inline")
        self.pages: dict[str, bytes] = {}

        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path == "/robots.txt":
                return httpx.Response(404)
            body = self.pages.get(str(req.url))
            return httpx.Response(200, content=body, headers={"content-type": "text/html"}) if body else httpx.Response(404)

        fetcher = GuardedFetcher(self.settings, transport=httpx.MockTransport(handler), resolver=lambda h: [PUBLIC_IP])
        self.store = SupabaseStore(self.settings)
        self.embedder = HashEmbeddingProvider()
        self.app = create_app(self.settings, store=self.store, storage=MemoryFileStorage(), embedder=self.embedder,
                              fetcher=fetcher)
        self.client = TestClient(self.app)
        self.users: dict[str, str] = {}
        tag = uuid.uuid4().hex[:6]
        for role in ("super_admin", "admin", "supporter", "student"):
            uid = str(uuid.uuid4())
            sql(f"insert into auth.users (id, email) values ('{uid}', '{role}-{tag}@example.test')")
            if role != "student":  # manual bootstrap, exactly like docs/setup.md
                sql(f"update public.profiles set role = '{role}' where id = '{uid}'")
            self.users[role] = uid

    def auth(self, role: str) -> dict[str, str]:
        tok = jwt.encode({"sub": self.users[role], "aud": "authenticated", "exp": int(time.time()) + 3600}, SECRET,
                         algorithm="HS256")
        return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def it() -> IT:
    return IT()


def test_end_to_end_against_real_database(it: IT):
    c, a = it.client, it.auth("admin")
    suffix = uuid.uuid4().hex[:8]

    # seeded reference data + sample test data are visible through the real DB
    cats = c.get("/api/v1/categories").json()["items"]
    assert len(cats) == 11 and cats[0]["document_count"] is not None
    sample = [x for x in c.get("/api/v1/announcements").json()["items"] if x["is_test_data"]]
    assert sample and sample[0]["title"].startswith("[SAMPLE - TEST DATA]")

    # roles come from public.profiles
    assert c.get("/api/v1/me", headers=it.auth("student")).json()["role"] == "student"
    assert c.get("/api/v1/admin/sources", headers=it.auth("student")).status_code == 403
    assert c.get("/api/v1/admin/overview", headers=it.auth("supporter")).status_code == 403
    assert c.get("/api/v1/admin/sources", headers=it.auth("supporter")).json()["total"] == 0  # only own sources
    assert c.get("/api/v1/admin/sources", headers=a).status_code == 200

    # register a source (unique url) -> duplicate maps to 409 through the unique index
    url = f"{ARTICLE_URL}?it={suffix}"
    html = ARTICLE_HTML.replace("Visa and Stay", f"Visa and Stay {suffix}")
    it.pages[url] = html.encode()
    body = dict(title=f"IT source {suffix}", original_url=url, organization="Study in Korea (IT)", source_type="website",
                authority_type="official_government", scope="national", category="visa-immigration", language="en")
    r = c.post("/api/v1/admin/sources", headers=a, json=body)
    assert r.status_code == 201, r.text
    src = r.json()
    assert c.post("/api/v1/admin/sources", headers=a, json=body).status_code == 409

    # ingest -> chunks stored for review, but NOT embedded before approval
    jid = c.post(f"/api/v1/admin/sources/{src['id']}/ingest", headers=a).json()["job_id"]
    job = c.get(f"/api/v1/admin/ingestion-jobs/{jid}", headers=a).json()
    assert job["status"] == "succeeded" and job["outcome"] == "new_version", job
    embedded_sql = (f"select count(*) from public.document_chunks where version_id = '{job['version_id']}' "
                    f"and embedding is not null and embedding_model = 'hash-dev-384' "
                    f"and extensions.vector_dims(embedding) = 384")
    assert job["statistics"]["chunk_count"] >= 1 and int(sql(embedded_sql)) == 0
    assert c.get("/api/v1/knowledge/documents", params={"q": f"Visa and Stay {suffix}"}).json()["total"] == 0  # pending => private
    first = c.post("/api/v1/knowledge/search", json=dict(query="alien registration immigration"))
    assert [r for r in first.json()["results"] if r["version_id"] == job["version_id"]] == []

    # DB-level authorization: a student actor id is refused inside the SQL function itself
    with pytest.raises(Forbidden):
        it.store.rpc("approve_document_version", dict(p_version_id=job["version_id"], p_actor=it.users["student"]))

    # approve -> searchable with accurate citation (hybrid + vector + keyword)
    ok = c.post(f"/api/v1/admin/versions/{job['version_id']}/approve", headers=a, json={})
    assert ok.status_code == 202 and ok.json()["verification_status"] == "approved", ok.text
    assert int(sql(embedded_sql)) == job["statistics"]["chunk_count"]  # vector(384) rows written by the index job
    for mode in ("hybrid", "vector", "keyword"):
        res = c.post("/api/v1/knowledge/search", json=dict(query="alien registration immigration office", mode=mode, top_k=20)).json()
        hit = [r for r in res["results"] if r["version_id"] == job["version_id"]]
        assert hit, (mode, res)
        assert hit[0]["source_url"] == url and hit[0]["organization"] == "Study in Korea (IT)"
    assert c.get("/api/v1/knowledge/documents", params={"q": f"Visa and Stay {suffix}"}).json()["total"] == 1

    # new content -> v2 pending; approved v1 still served; second approve supersedes atomically
    it.pages[url] = html.replace("Passport", "Passport and certificate").encode()
    jid2 = c.post(f"/api/v1/admin/sources/{src['id']}/ingest", headers=a).json()["job_id"]
    job2 = c.get(f"/api/v1/admin/ingestion-jobs/{jid2}", headers=a).json()
    assert job2["outcome"] == "new_version"
    detail = c.get(f"/api/v1/admin/documents/{job['document_id']}", headers=a).json()
    assert detail["current_version"]["version_number"] == 1 and detail["pending_version"]["version_number"] == 2
    assert detail["diff"]["added_count"] >= 1
    pub = c.get(f"/api/v1/knowledge/documents/{job['document_id']}").json()
    assert pub["version_number"] == 1
    # same content again: no new version (unique (document_id, content_hash))
    jid3 = c.post(f"/api/v1/admin/sources/{src['id']}/ingest", headers=a).json()["job_id"]
    assert c.get(f"/api/v1/admin/ingestion-jobs/{jid3}", headers=a).json()["outcome"] == "unchanged"
    assert c.post(f"/api/v1/admin/versions/{job2['version_id']}/approve", headers=a, json={}).status_code == 202
    statuses = sql(f"select string_agg(version_number || ':' || verification_status, ',' order by version_number) "
                   f"from public.document_versions where document_id = '{job['document_id']}'")
    assert statuses == "1:superseded,2:approved"
    r = c.post(f"/api/v1/admin/documents/{job['document_id']}/rollback", headers=a, json={"version_id": job["version_id"]})
    assert r.status_code == 200 and r.json()["current_version"]["version_number"] == 1
    with pytest.raises(AssertionError, match="immutable"):  # approved/superseded text is immutable in the DB
        sql(f"update public.document_versions set extracted_text = 'tampered' where id = '{job['version_id']}'")

    # job failure is persisted; the approved version survives
    del it.pages[url]
    jid4 = c.post(f"/api/v1/admin/sources/{src['id']}/ingest", headers=a).json()["job_id"]
    j4 = c.get(f"/api/v1/admin/ingestion-jobs/{jid4}", headers=a).json()
    assert j4["status"] == "failed" and j4["error_code"] == "http_404"
    assert c.get(f"/api/v1/knowledge/documents/{job['document_id']}").status_code == 200
    assert c.get(f"/api/v1/admin/sources/{src['id']}", headers=a).json()["status"] == "failed"

    # announcements: draft -> submit -> approve -> public + searchable; translations; cancel
    today = date.today()
    pa = dict(title=f"IT 공지 {suffix}", body="통합 테스트 공지 본문입니다. 실제 공지가 아닙니다 (test data).",
              category="scholarships", target_audience="test", deadline=str(today + timedelta(days=5)),
              source_type="manual_text")
    ann = c.post("/api/v1/admin/announcements", headers=it.auth("supporter"), json=pa)
    assert ann.status_code == 201, ann.text
    aid = ann.json()["id"]
    assert c.post(f"/api/v1/admin/announcements/{aid}/submit", headers=it.auth("supporter")).status_code == 200
    assert c.post(f"/api/v1/admin/announcements/{aid}/approve", headers=it.auth("supporter"), json={}).status_code == 403
    assert c.get(f"/api/v1/announcements/{aid}").status_code == 404
    assert c.post(f"/api/v1/admin/announcements/{aid}/approve", headers=a, json={"note": "ok"}).json()["publication_status"] == "published"
    pubd = c.get(f"/api/v1/announcements/{aid}").json()
    assert pubd["status"] == "active" and "통합 테스트" in pubd["body"]
    hits = c.post("/api/v1/knowledge/search", json=dict(query="통합 테스트 공지")).json()["results"]
    assert any(h["document_title"] == pa["title"] for h in hits)
    sql(f"insert into public.supporter_languages (supporter_id, language_code, can_review_translations) "
        f"values ('{it.users['supporter']}', 'id', true)")
    tr = c.put(f"/api/v1/admin/announcements/{aid}/translations/id", headers=it.auth("supporter"),
               json=dict(title="Pengumuman IT", body="Isi", translation_status="in_review"))
    assert tr.status_code == 200, tr.text
    assert c.get(f"/api/v1/announcements/{aid}").json()["translations"] == []
    assert c.post(f"/api/v1/admin/announcements/{aid}/translations/id/approve", headers=it.auth("supporter"),
                  json={"original_verified": True}).status_code == 200
    assert c.get(f"/api/v1/announcements/{aid}").json()["translations"][0]["language"] == "id"
    assert c.post(f"/api/v1/admin/announcements/{aid}/cancel", headers=a, json={"reason": "test"}).json()["publication_status"] == "canceled"
    assert c.get(f"/api/v1/announcements/{aid}").status_code == 404
    hist = c.get(f"/api/v1/admin/announcements/{aid}/history", headers=a).json()["items"]
    assert {"announcement.create", "announcement.submit", "announcement.approve", "announcement.cancel"} <= {h["action"] for h in hist}

    # sample pending doc from seed can't be approved until embedded; reprocess then approve works
    docs = c.get("/api/v1/admin/documents", headers=a, params={"has_pending": "true"}).json()["items"]
    pending = [d for d in docs if d["title"].startswith("[SAMPLE - TEST DATA] Pending")]
    if pending:  # (the seed's sample pending document; consumed by the first run against a given database)
        # not approvable until embedded: the DB function and API both refuse
        r = c.post(f"/api/v1/admin/versions/{pending[0]['pending_version_id']}/approve", headers=a, json={})
        assert r.status_code == 202  # approval queues the index job, which embeds and activates
        assert r.json()["verification_status"] == "approved"  # inline mode: indexed + activated before responding

    # overview, users, settings
    ov = c.get("/api/v1/admin/overview", headers=a).json()
    assert ov["sources_total"] >= 8 and ov["recent_jobs"] and ov["recent_audit"]
    users = c.get("/api/v1/admin/users", headers=a).json()
    assert users["total"] >= 4
    assert c.patch(f"/api/v1/admin/users/{it.users['student']}/role", headers=a, json={"role": "admin"}).status_code == 403
    assert c.patch(f"/api/v1/admin/users/{it.users['student']}/role", headers=it.auth("super_admin"), json={"role": "supporter"}).json()["role"] == "supporter"

    # unknown id formats are 404, not 500
    assert c.get("/api/v1/announcements/not-a-uuid").status_code == 404
    assert c.get("/api/v1/admin/documents/not-a-uuid", headers=a).status_code == 404
