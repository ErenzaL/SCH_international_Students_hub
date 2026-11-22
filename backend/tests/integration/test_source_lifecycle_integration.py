"""Source deletion against the REAL database (PostgREST + PostgreSQL + migration 0010): role enforcement,
retrieval exclusion, cleanup, and concurrency (parallel deletes, a worker claiming jobs during a delete).
Skipped unless the integration environment is configured (see test_postgres_integration.py)."""
from __future__ import annotations

import shlex
import subprocess
import threading
import time
import uuid

import pytest

from app.core.errors import AppError, NotFound
from app.security.auth import AuthUser
from tests.conftest import ARTICLE_HTML, ARTICLE_URL
from tests.integration.test_postgres_integration import IT, PSQL, REST, sql

pytestmark = pytest.mark.skipif(not (REST and PSQL), reason="set SCH_IT_REST_URL and SCH_IT_PSQL to run")


@pytest.fixture(scope="module")
def it() -> IT:
    return IT()


def hits(it: IT, q: str) -> list:  # type: ignore[type-arg]
    return it.client.post("/api/v1/knowledge/search", json={"query": q, "top_k": 10}).json()["results"]


def make_source(it: IT, title: str, url: str | None = None) -> dict:  # type: ignore[type-arg]
    body = dict(title=title, organization="NIIED", authority_type="official_government", scope="national",
                category="visa-immigration", language="en")
    body.update(dict(source_type="website", original_url=url) if url else dict(source_type="text_file"))
    r = it.client.post("/api/v1/admin/sources", headers=it.auth("admin"), json=body)
    assert r.status_code == 201, r.text
    return r.json()


def delete(it: IT, sid: str, title: str, role: str = "super_admin", destructive: bool = False):  # type: ignore[no-untyped-def]
    return it.client.post(f"/api/v1/admin/sources/{sid}/delete", headers=it.auth(role),
                          json={"reason": "integration cleanup", "confirm_title": title,
                                "confirm_destructive": destructive})


def test_source_delete_lifecycle_against_real_database(it: IT):
    c, a = it.client, it.auth("admin")
    url = f"{ARTICLE_URL}?it={uuid.uuid4().hex[:8]}"
    it.pages[url] = ARTICLE_HTML.encode() if isinstance(ARTICLE_HTML, str) else ARTICLE_HTML
    title = f"IT source {uuid.uuid4().hex[:6]}"
    src = make_source(it, title, url)
    sid = src["id"]
    job_id = c.post(f"/api/v1/admin/sources/{sid}/ingest", headers=a).json()["job_id"]
    job = c.get(f"/api/v1/admin/ingestion-jobs/{job_id}", headers=a).json()
    assert job["status"] == "succeeded", job
    assert c.post(f"/api/v1/admin/versions/{job['version_id']}/approve", headers=a, json={}).status_code == 202
    q = "alien registration immigration office"
    assert any(h["document_id"] == job["document_id"] for h in hits(it, q))

    chk = c.get(f"/api/v1/admin/sources/{src['id']}/deletion-check", headers=a).json()
    assert chk["is_searchable"] and chk["approved_versions"] == 1 and chk["indexed_chunks"] >= 1
    assert chk["recommended_action"] == "archive" and not chk["eligible"]
    for role in ("admin", "supporter", "student"):
        assert delete(it, src["id"], title, role=role, destructive=True).status_code == 403
    assert delete(it, src["id"], title, destructive=True).status_code == 409   # published

    assert c.post(f"/api/v1/admin/sources/{src['id']}/archive", headers=a, json={"reason": "IT archive"}).status_code == 200
    assert all(h["document_id"] != job["document_id"] for h in hits(it, q))
    assert delete(it, src["id"], title).status_code == 422                     # second confirmation missing
    r = delete(it, src["id"], title, destructive=True)
    assert r.status_code == 200, r.text
    assert r.json()["documents"] == 1 and r.json()["chunks"] >= 1
    assert sql(f"select count(*) from public.document_chunks where version_id = '{job['version_id']}'") == "0"
    assert sql(f"select count(*) from public.knowledge_sources where id = '{src['id']}'") == "0"
    assert sql(f"select count(*) from public.ingestion_jobs where id = '{job['id']}' and source_id is null") == "1"
    assert sql(f"select count(*) from public.audit_log where action = 'source.delete' and entity_id = '{src['id']}'") == "1"
    assert sql(f"select count(*) from public.audit_log where action = 'version.approve' "
               f"and entity_id = '{job['version_id']}'") == "1"
    assert delete(it, src["id"], title, destructive=True).status_code == 404   # repeated request
    view = c.get(f"/api/v1/admin/ingestion-jobs/{job['id']}", headers=a).json()
    assert view["source_deleted"] and view["source_title"] == title


def test_parallel_deletes_remove_once(it: IT):
    title = f"IT parallel {uuid.uuid4().hex[:6]}"
    src = make_source(it, title)
    svc = it.app.state.services
    actor = AuthUser(id=it.users["super_admin"], email=None, role="super_admin")
    results: list[str] = []

    def run() -> None:
        try:
            svc.source_lifecycle.delete(src["id"], actor, "parallel cleanup", title, False)
            results.append("ok")
        except NotFound:
            results.append("404")
        except AppError as exc:
            results.append(f"{exc.code}")

    threads = [threading.Thread(target=run) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count("ok") == 1 and set(results) <= {"ok", "404"}, results
    assert sql(f"select count(*) from public.audit_log where action = 'source.delete' and entity_id = '{src['id']}'") == "1"


def test_worker_cannot_claim_a_job_while_its_source_is_being_deleted(it: IT):
    title = f"IT worker {uuid.uuid4().hex[:6]}"
    src = make_source(it, title)
    jid = sql(f"insert into public.ingestion_jobs (source_id, status, run_after, created_at) values "
              f"('{src['id']}', 'queued', now() - interval '1 hour', now() - interval '10 years') returning id")
    jid = jid.splitlines()[0].strip()
    # a delete that holds its locks for a few seconds (as a slow transaction would)
    stmt = (f"begin; select public.delete_source('{src['id']}', '{it.users['super_admin']}', 'slow cleanup', "
            f"'{title}', true); select pg_sleep(3); commit;")
    proc = subprocess.Popen(shlex.split(PSQL or "") + ["-v", "ON_ERROR_STOP=1", "-c", stmt],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        time.sleep(1.0)
        # the oldest queued job is ours, but it is locked: SKIP LOCKED passes over it
        claimed = it.store.rpc("claim_ingestion_job", {"p_worker": "it-worker", "p_stale_seconds": 900}) or []
        claimed = claimed if isinstance(claimed, list) else [claimed]
        assert all(j["id"] != jid for j in claimed)
        for j in claimed:   # put back anything unrelated we picked up
            sql(f"update public.ingestion_jobs set status = 'queued', locked_by = null where id = '{j['id']}'")
    finally:
        out, err = proc.communicate(timeout=30)
    assert proc.returncode == 0, err
    row = sql(f"select status || ',' || coalesce(error_code, '') || ',' || coalesce(source_id::text, 'null') "
              f"from public.ingestion_jobs where id = '{jid}'")
    assert row == "failed,source_deleted,null", row
    # and after the delete, the worker never picks it up
    claimed = it.store.rpc("claim_ingestion_job", {"p_worker": "it-worker", "p_stale_seconds": 900}) or []
    claimed = claimed if isinstance(claimed, list) else [claimed]
    assert all(j["id"] != jid for j in claimed)
    for j in claimed:
        sql(f"update public.ingestion_jobs set status = 'queued', locked_by = null where id = '{j['id']}'")
