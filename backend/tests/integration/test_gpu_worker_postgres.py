"""GPU worker endpoints against the REAL database (PostgREST + PostgreSQL + migration 0016). Skipped unless configured."""
from __future__ import annotations

import uuid

import pytest

from tests.integration.test_postgres_integration import IT, PSQL, REST, sql
from tests.test_gpu_worker import GOOD, call, claim, done

pytestmark = pytest.mark.skipif(not (REST and PSQL), reason="set SCH_IT_REST_URL and SCH_IT_PSQL to run")


@pytest.fixture(scope="module")
def it() -> IT:
    it = IT()
    it.settings.gpu_worker_enabled = it.settings.public_machine_translations = True
    sql("update public.ingestion_jobs set status = 'failed' where executor = 'gpu' and status in ('queued', 'running')")
    svc = it.app.state.services
    admin = it.users["admin"]
    it.worker = svc.gpu.create_worker(f"it-{uuid.uuid4().hex[:8]}", admin)  # type: ignore[attr-defined]
    return it


def publish(it: IT) -> str:
    a = it.auth("admin")
    ann = it.client.post("/api/v1/admin/announcements", headers=a, json=dict(
        title=f"장학금 신청 안내 {uuid.uuid4().hex[:6]}", body="신청 기간은 2026-12-01부터입니다. 문의: intl@example.ac.kr",
        category="scholarships", source_type="manual_text", submit=True, evidence_note="integration test")).json()
    assert it.client.post(f"/api/v1/admin/announcements/{ann['id']}/approve", headers=a, json={}).status_code == 200
    return ann["id"]


def request(it: IT, aid: str, lang: str = "en") -> str:
    r = it.client.post(f"/api/v1/admin/announcements/{aid}/translations/{lang}/machine-translate", headers=it.auth("admin"))
    assert r.status_code == 202, r.text
    return r.json()["job_id"]


def test_lease_complete_and_idempotency(it: IT):
    aid = publish(it)
    jid = request(it, aid)
    lease = str(uuid.uuid4())
    job = claim(it, lease)
    assert job["id"] == jid and claim(it, lease)["id"] == jid and claim(it) is None
    assert call(it, f"/jobs/{jid}/heartbeat", lease_token=lease).json()["cancel"] is False
    tag = job["title"].split()[-1]
    digits = {"title": f"Scholarship guide {tag}"}
    assert done(it, job, **digits).json() == dict(status="succeeded", duplicate=False)
    assert done(it, job, **digits).json() == dict(status="succeeded", duplicate=True)
    assert sql(f"select translation_status || '|' || provider || '|' || (reviewed_by is null) from public.announcement_translations "
               f"where announcement_id = '{aid}' and language_code = 'en'") == "needs_review|ollama|true"
    assert sql(f"select status || '|' || attempts || '|' || (statistics -> 'gpu' ->> 'model') from public.ingestion_jobs "
               f"where id = '{jid}'") == f"succeeded|1|{GOOD['model']}"
    assert it.client.get(f"/api/v1/announcements/{aid}", params={"lang": "en"}).json()["translation"] is None


def test_lease_expiry_release_cancel_and_revocation(it: IT):
    aid = publish(it)
    jid = request(it, aid, "vi")
    job = claim(it)
    sql(f"update public.ingestion_jobs set lease_expires_at = now() - interval '1 second' where id = '{jid}'")
    second = claim(it)
    assert second["id"] == jid and done(it, job).json()["error"]["code"] == "lease_lost"
    assert call(it, f"/jobs/{jid}/fail", lease_token=second["lease_token"], code="worker_shutdown").json()["status"] == "queued"
    third = claim(it)
    assert third["id"] == jid
    r = it.client.post(f"/api/v1/admin/gpu/jobs/{jid}/cancel", headers=it.auth("admin"))
    assert r.json()["status"] == "cancelling"
    assert done(it, third).json()["status"] == "cancelled"
    jid = request(it, aid, "id")
    assert claim(it)["id"] == jid
    st = it.client.get("/api/v1/admin/gpu/status", headers=it.auth("admin"))
    assert st.status_code == 200 and st.json()["queue"]["running"] == 1, st.text
    it.app.state.services.gpu.rotate(it.worker["id"], it.users["admin"], 5)  # type: ignore[attr-defined]
    assert call(it, "/claim", lease_token=str(uuid.uuid4())).status_code == 200      # overlap
    it.app.state.services.gpu.set_status(it.worker["id"], "revoked", it.users["admin"])  # type: ignore[attr-defined]
    assert call(it, "/claim", lease_token=str(uuid.uuid4())).status_code == 401
    assert sql(f"select status from public.ingestion_jobs where id = '{jid}'") == "queued"
