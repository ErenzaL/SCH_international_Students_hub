"""GPU worker endpoints against the REAL database (PostgREST + PostgreSQL + migration 0016). Skipped unless configured."""
from __future__ import annotations

import uuid

import pytest

from tests.integration.test_postgres_integration import IT, PSQL, REST, sql
from tests.test_gpu_worker import GOOD, call, claim, done

pytestmark = pytest.mark.skipif(not (REST and PSQL), reason="set SCH_IT_REST_URL and SCH_IT_PSQL to run")


@pytest.fixture(scope="module")
def it() -> IT:
    if sql("select count(*) from information_schema.tables where table_name = 'gpu_workers'") == "0":
        pytest.skip("migration 0016 is not applied")
    it = IT()
    it.settings.gpu_worker_enabled = it.settings.public_machine_translations = True
    sql("update public.ingestion_jobs set status = 'failed' where executor = 'gpu' and status in ('queued', 'running')")
    svc = it.app.state.services
    admin = it.users["admin"]
    it.worker = svc.gpu.create_worker(f"it-{uuid.uuid4().hex[:8]}", admin)  # type: ignore[attr-defined]
    call(it, "/claim", lease_token=str(uuid.uuid4()))            # a worker is available once it contacted the API
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
    jid = request(it, aid, "en")
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


def test_mixed_workload_in_worker_mode(it: IT):
    """The API's real worker threads keep ingesting, indexing, translating and running agent tasks while GPU jobs wait
    and run; nobody takes the other's jobs."""
    import time

    from app.services.llm.base import ScriptedLLMProvider
    from tests.test_auto_translation import FakeTranslator

    sql("update public.ingestion_jobs set status = 'failed' where executor = 'gpu' and status in ('queued', 'running')")
    svc = it.app.state.services
    worker = svc.gpu.create_worker(f"mix-{uuid.uuid4().hex[:8]}", it.users["admin"])
    it.worker = worker  # type: ignore[attr-defined]
    call(it, "/claim", lease_token=str(uuid.uuid4()))
    aid, aid2 = publish(it), publish(it)
    # Release 1: from Korean only en / id drafts, so the third GPU job comes from a second announcement
    gpu_jobs = [request(it, aid, "en"), request(it, aid, "id"), request(it, aid2, "en")]   # older than everything below
    running = claim(it)
    it.settings.job_execution, it.settings.job_poll_seconds = "worker", 0.2
    svc.doc_translations.llm = svc.announcement_translator.llm = ScriptedLLMProvider(FakeTranslator(), model="own-1")
    a = it.auth("admin")
    try:
        svc.jobs.start()
        src = it.client.post("/api/v1/admin/sources", headers=a, json=dict(
            title=f"mix {uuid.uuid4().hex[:6]}", organization="SCH", source_type="manual_text",
            authority_type="official_university", scope="university", category="academic-life", language="ko")).json()
        job = it.client.post(f"/api/v1/admin/sources/{src['id']}/submit-text", headers=a, json=dict(
            title="기숙사 안내", text=f"입사일은 2027-02-24입니다. 학생증을 가져오세요. {uuid.uuid4().hex}", authorized_by_supporter=True)).json()
        assert it.client.post(f"/api/v1/admin/versions/{job['version_id']}/approve", headers=a, json={}).status_code == 202
        it.settings.gpu_worker_job_types = "translate_announcement"      # documents stay with the API's own model
        task = it.client.post("/api/v1/agents/announcement/tasks", headers=it.auth("student"), json=dict(
            task_type="announcement_digest", params={}))
        assert task.status_code == 201, task.text

        def finished(query: str) -> bool:
            return sql(query) == "0"

        end = time.time() + 30
        local_open = (f"select count(*) from public.ingestion_jobs where source_id = '{src['id']}' "
                      "and status in ('queued', 'running')")
        while time.time() < end and not finished(local_open):
            time.sleep(0.2)
        assert finished(local_open)
        r = it.client.post(f"/api/v1/admin/documents/{job['document_id']}/translations/drafts", headers=it.auth("super_admin")
                           if "super_admin" in it.users else a, json=dict(languages=["en"]))
        assert r.status_code == 202, r.text
        end = time.time() + 30
        while time.time() < end and not (finished(local_open) and finished(
                f"select count(*) from public.agent_tasks where id = '{task.json()['id']}' and status not in ('completed')")):
            time.sleep(0.2)
        assert sql(f"select status from public.agent_tasks where id = '{task.json()['id']}'") == "completed"
        assert sql(f"select string_agg(distinct job_type || ':' || status, ',' order by job_type || ':' || status) from public.ingestion_jobs "
                   f"where source_id = '{src['id']}'") == "index_version:succeeded,ingest:succeeded,translate_document:succeeded"
        assert sql(f"select provider || ':' || model from public.document_translations where document_id = '{job['document_id']}' "
                   f"and language_code = 'en'") == "scripted:own-1"
        states = sql("select string_agg(status || ':' || coalesce(split_part(locked_by, ':', 1), '-'), ',' order by created_at) "
                     f"from public.ingestion_jobs where id in ({','.join(repr(j) for j in gpu_jobs)})")
        assert states == "running:gpu,queued:-,queued:-"
        assert done(it, running).json()["status"] == "succeeded"
        svc.gpu.sweep()
    finally:
        svc.jobs.stop()
        it.settings.job_execution = "inline"
        it.settings.gpu_worker_job_types = "translate_announcement,translate_document"


def test_parallel_claims_never_share_a_job(it: IT):
    from collections import Counter
    from concurrent.futures import ThreadPoolExecutor

    svc = it.app.state.services
    sql("update public.ingestion_jobs set status = 'failed' where status in ('queued', 'running')")
    sid = sql("select id from public.knowledge_sources limit 1")
    for executor, kind in (("local", "ocr_intake"), ("gpu", "translate_document")):
        sql(f"insert into public.ingestion_jobs (source_id, job_type, executor, payload) select '{sid}', '{kind}', '{executor}', "
            f"jsonb_build_object('translation_id', 'p-{executor}-' || g) from generate_series(1, 40) g")

    def local(_n: int) -> str | None:
        rows = svc.store.rpc("claim_ingestion_job", dict(p_worker="w", p_stale_seconds=600))
        rows = [rows] if isinstance(rows, dict) else rows or []
        return rows[0]["id"] + "|" + rows[0]["executor"] if rows and rows[0].get("id") else None

    def gpu(_n: int) -> str | None:
        rows = svc.store.rpc("claim_gpu_job", dict(p_worker=it.worker["id"], p_lease_token=str(uuid.uuid4()), p_lease_seconds=60,  # type: ignore[attr-defined]
                                                   p_job_types=["translate_document"], p_max_running=1000))
        rows = [rows] if isinstance(rows, dict) else rows or []
        return rows[0]["id"] + "|" + rows[0]["executor"] if rows and rows[0].get("id") else None

    with ThreadPoolExecutor(12) as pool:
        got = [f.result() for pair in [(pool.submit(local, i), pool.submit(gpu, i)) for i in range(60)] for f in pair]
    got = [g for g in got if g]
    assert max(Counter(got).values()) == 1 and Counter(g.split("|")[1] for g in got) == {"local": 40, "gpu": 40}
    sql("update public.ingestion_jobs set status = 'failed' where status in ('queued', 'running')")


def test_sweep_and_routing_on_the_real_database(it: IT):
    svc = it.app.state.services
    aid = publish(it)
    jid = request(it, aid, "id")
    sql(f"update public.ingestion_jobs set created_at = now() - interval '3 days' where id = '{jid}'")
    assert svc.gpu.sweep()["failed"] == 1
    assert sql(f"select status || ':' || error_code from public.ingestion_jobs where id = '{jid}'") == "failed:gpu_worker_unavailable"
    sql("update public.gpu_workers set last_seen_at = now() - interval '2 days'")
    jid = request(it, aid, "id")
    assert sql(f"select executor from public.ingestion_jobs where id = '{jid}'") == "local"
