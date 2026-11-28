"""Announcement translation routing on the REAL database (PostgREST + PostgreSQL). Skipped unless configured.

* every schema from 0015 (production today): publication-time languages are stored without a migration, the
  translation list works without the 0016 columns, a request without the GPU worker is refused clearly, and a
  server job never reaches Gemini without TRANSLATION_FALLBACK_TO_GEMINI;
* with 0016: the request is queued for the GPU worker, claimed by the real claim_gpu_job with TranslateGemma only,
  stored as a private draft, recovered after a dead worker, bounded backfill without duplicates.
"""
from __future__ import annotations

import uuid

import pytest

from app.services.llm.base import ScriptedLLMProvider
from tests.integration.test_postgres_integration import IT, PSQL, REST, sql
from tests.test_gpu_worker import call

pytestmark = pytest.mark.skipif(not (REST and PSQL), reason="set SCH_IT_REST_URL and SCH_IT_PSQL to run")
MODEL = "translategemma:12b"


def has_0016() -> bool:
    return sql("select count(*) from information_schema.tables where table_name = 'gpu_workers'") != "0"


@pytest.fixture(scope="module")
def it() -> IT:
    it = IT()
    it.server_model = ScriptedLLMProvider(lambda s, x: "SHOULD NOT BE USED", model="gemini-3.5-flash-lite")  # type: ignore[attr-defined]
    it.app.state.services.announcement_translator.llm = it.server_model   # type: ignore[attr-defined]
    return it


def publish(it: IT, targets: list[str] | None = None, language: str = "ko") -> str:
    tag = uuid.uuid4().hex[:6]
    body = dict(title=f"기숙사 입사 안내 {tag}", body=f"2027년 2월 24일 10:00부터 입사합니다. 문의: dorm@sch.ac.kr {tag}",
                category="scholarships", source_type="manual_text", submit=True, evidence_note="integration test",
                original_language=language)
    if targets is not None:
        body["translation_targets"] = targets
    a = it.client.post("/api/v1/admin/announcements", headers=it.auth("admin"), json=body).json()
    assert it.client.post(f"/api/v1/admin/announcements/{a['id']}/approve", headers=it.auth("admin"), json={}).status_code == 200
    return a["id"]


def jobs_of(aid: str) -> list[str]:
    out = sql(f"select string_agg(payload->>'language', ',' order by payload->>'language') from public.ingestion_jobs "
              f"where job_type = 'translate_announcement' and payload->>'announcement_id' = '{aid}'")
    return [x for x in out.split(",") if x]


# ------------------------------------------------------------------------------------- any schema (0015+)
def test_languages_are_stored_with_the_announcement_without_a_migration(it: IT):
    it.settings.gpu_worker_enabled = False
    aid = publish(it, targets=["en", "id", "ko"])
    assert sql(f"select d.metadata->'translation_targets' from public.announcements a join public.source_documents d "
               f"on d.id = a.document_id where a.id = '{aid}'") == '["en", "id"]'
    view = it.client.get(f"/api/v1/admin/announcements/{aid}", headers=it.auth("admin")).json()
    assert view["translation_targets"] == ["en", "id"]
    assert jobs_of(aid) == []                                      # no GPU worker: nothing queued, nothing charged
    r = it.client.post(f"/api/v1/admin/announcements/{aid}/translations/en/machine-translate", headers=it.auth("admin"))
    assert r.status_code == 409 and r.json()["error"]["code"] == "translation_worker_disabled"
    items = it.client.get("/api/v1/admin/translations", headers=it.auth("super_admin"),
                          params={"page_size": 100}).json()["items"]
    mine = [i for i in items if i["announcement_id"] == aid]
    states = {i["language_code"]: i["machine"]["state"] for i in mine}
    assert states["en"] == states["id"] == "ready" and states["vi"] == states["zh-CN"] == "manual"
    assert it.server_model.calls == []                              # type: ignore[attr-defined]


def test_a_server_job_never_reaches_gemini_without_the_fallback(it: IT):
    it.settings.gpu_worker_enabled = False
    it.settings.translation_fallback_to_gemini = True
    svc = it.app.state.services
    aid = publish(it)
    runner, svc.announcement_translator.jobs = svc.announcement_translator.jobs, None
    try:
        r = it.client.post(f"/api/v1/admin/announcements/{aid}/translations/id/machine-translate", headers=it.auth("admin"))
        assert r.status_code == 202, r.text
    finally:
        svc.announcement_translator.jobs = runner
        it.settings.translation_fallback_to_gemini = False
    out = svc.ingestion.run_job(r.json()["job_id"])
    assert out["status"] == "failed" and out["error_code"] == "translation_fallback_disabled"
    assert it.server_model.calls == []                              # type: ignore[attr-defined]


# ------------------------------------------------------------------------------------- with migration 0016
@pytest.fixture
def gpu(it: IT):  # type: ignore[no-untyped-def]
    if not has_0016():
        pytest.skip("migration 0016 is not applied")
    it.settings.gpu_worker_enabled = True
    sql("update public.ingestion_jobs set status = 'failed' where executor = 'gpu' and status in ('queued', 'running')")
    if not hasattr(it, "worker"):
        it.worker = it.app.state.services.gpu.create_worker(f"it-{uuid.uuid4().hex[:8]}", it.users["admin"])  # type: ignore[attr-defined]
    call(it, "/claim", lease_token=str(uuid.uuid4()), model="qwen2.5:7b-instruct")   # contacted the API: online
    yield it
    it.settings.gpu_worker_enabled = False


def claim(it: IT, model: str | None = MODEL, lease: str | None = None) -> dict | None:  # type: ignore[type-arg]
    body = {"lease_token": lease or str(uuid.uuid4())} | ({"model": model} if model else {})
    r = call(it, "/claim", **body)
    assert r.status_code == 200, r.text
    return r.json()["job"]


def complete(it: IT, job: dict, title: str, body: str, model: str = MODEL):  # type: ignore[no-untyped-def,type-arg]
    return call(it, f"/jobs/{job['id']}/complete", lease_token=job["lease_token"], title=title, body=body, model=model,
                metrics=dict(duration_ms=8800, input_tokens=420, output_tokens=180, model_calls=2, parts=1))


def test_publication_queues_the_chosen_languages_once_for_the_gpu_worker(gpu: IT):
    aid = publish(gpu, targets=["en", "id"])
    assert jobs_of(aid) == ["en", "id"]
    assert sql(f"select string_agg(distinct executor, ',') from public.ingestion_jobs where job_type = "
               f"'translate_announcement' and payload->>'announcement_id' = '{aid}'") == "gpu"
    svc = gpu.app.state.services
    svc.translations.on_original_published(aid, None)               # a repeated publication event
    r = gpu.client.post(f"/api/v1/admin/announcements/{aid}/translations/en/machine-translate", headers=gpu.auth("admin"))
    assert r.status_code == 202
    assert jobs_of(aid) == ["en", "id"]                             # still one job per language
    assert claim(gpu, model="qwen2.5:7b-instruct") is None          # a Qwen worker gets no announcement job
    seen: dict[str, dict] = {}  # type: ignore[type-arg]
    while (job := claim(gpu)) is not None:
        seen[job["target_language"]] = job
        assert "dorm@sch.ac.kr" in job["body"] and "requested_by" not in job
        title, body = (("Dormitory move-in guide", "Move-in starts on 24 February 2027 at 10:00. Questions: dorm@sch.ac.kr")
                       if job["target_language"] == "en" else
                       ("Panduan masuk asrama", "Masuk asrama mulai 24 Februari 2027 pukul 10:00. Pertanyaan: dorm@sch.ac.kr"))
        assert complete(gpu, job, f"{title} {job['title'].split()[-1]}", f"{body} {job['title'].split()[-1]}").json()["status"] == "succeeded"
    assert set(seen) == {"en", "id"}
    assert sql(f"select string_agg(language_code || ':' || translation_status || ':' || model, ',' order by language_code) "
               f"from public.announcement_translations where announcement_id = '{aid}' and provider = 'ollama'") == \
        f"en:needs_review:{MODEL},id:needs_review:{MODEL}"
    assert gpu.client.get(f"/api/v1/announcements/{aid}", params={"lang": "id"}).json()["translation"] is None
    items = gpu.client.get("/api/v1/admin/translations", headers=gpu.auth("super_admin"), params={"page_size": 100}).json()["items"]
    states = {i["language_code"]: i["machine"]["state"] for i in items if i["announcement_id"] == aid}
    assert states["en"] == states["id"] == "needs_review"           # list through PostgREST with a JSON-path filter
    assert gpu.server_model.calls == []                             # type: ignore[attr-defined]


def test_a_dead_worker_hands_the_job_back_and_the_draft_is_stored_once(gpu: IT):
    aid = publish(gpu, targets=["en"])
    first = claim(gpu)
    assert first is not None
    sql(f"update public.ingestion_jobs set lease_expires_at = now() - interval '1 second' where id = '{first['id']}'")
    d = gpu.client.get(f"/api/v1/admin/announcements/{aid}/translations/en", headers=gpu.auth("super_admin")).json()
    assert d["machine"]["state"] == "stalled"
    r = gpu.client.post(f"/api/v1/admin/announcements/{aid}/translations/en/machine-translate", headers=gpu.auth("admin"))
    assert r.json()["job_id"] == first["id"]                        # the same job, handed back to the queue
    again = claim(gpu)
    assert again and again["id"] == first["id"]
    assert complete(gpu, first, "late", "late text").status_code == 409
    tag = again["title"].split()[-1]
    assert complete(gpu, again, f"Dormitory move-in guide {tag}",
                    f"Move-in starts on 24 February 2027 at 10:00. dorm@sch.ac.kr {tag}").json()["status"] == "succeeded"
    assert sql(f"select count(*) from public.ingestion_jobs where job_type = 'translate_announcement' and "
               f"payload->>'announcement_id' = '{aid}'") == "1"


def test_backfill_is_bounded_and_never_queues_twice(gpu: IT):
    for _ in range(2):
        publish(gpu)
    url, h = "/api/v1/admin/translations/backfill", gpu.auth("admin")
    plan = gpu.client.post(url, headers=h, json=dict(languages=["en"], dry_run=True)).json()
    assert plan["missing"] >= 2
    first = gpu.client.post(url, headers=h, json=dict(languages=["en"], limit=1, dry_run=False)).json()
    assert len(first["queued"]) == 1
    left = gpu.client.post(url, headers=h, json=dict(languages=["en"], dry_run=True)).json()
    assert left["missing"] == plan["missing"] - 1 and left["already_queued"] >= 1
