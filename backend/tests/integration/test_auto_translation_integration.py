"""Automatic machine translation against the REAL database (PostgREST + PostgreSQL + migration 0013): publication
queues a durable job, the machine translation lands with provenance, the unique open-job index works through the
real store, quota exhaustion defers (not fails) the job, long documents get a summary, students see labelled
machine translations only when enabled. Skipped unless the integration environment is configured."""
from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from app.services.llm.base import LLMError, ScriptedLLMProvider
from tests.integration.test_postgres_integration import IT, PSQL, REST, sql
from tests.test_auto_translation import FakeTranslator

pytestmark = pytest.mark.skipif(not (REST and PSQL), reason="set SCH_IT_REST_URL and SCH_IT_PSQL to run")


@pytest.fixture(scope="module")
def it() -> IT:
    it = IT()
    s = it.settings
    s.auto_translate_announcements = s.auto_translate_documents = s.public_machine_translations = True
    s.auto_translate_languages = "ko,en"
    return it


def use(it: IT, fake: FakeTranslator) -> None:
    svc = it.app.state.services
    svc.doc_translations.llm = svc.announcement_translator.llm = ScriptedLLMProvider(fake, model="translate-1")


def publish(it: IT, title: str, body: str) -> dict:  # type: ignore[type-arg]
    a = it.auth("admin")
    ann = it.client.post("/api/v1/admin/announcements", headers=a, json=dict(
        title=title, body=body, category="scholarships", source_type="manual_text", submit=True,
        evidence_note="integration test", deadline=str(date.today() + timedelta(days=10)))).json()
    r = it.client.post(f"/api/v1/admin/announcements/{ann['id']}/approve", headers=a, json={})
    assert r.status_code == 200, r.text
    return ann


def test_publication_creates_a_machine_translation_in_the_real_database(it: IT):
    use(it, FakeTranslator())
    tag = uuid.uuid4().hex[:6]
    ann = publish(it, f"장학금 신청 안내 {tag}", "장학금 신청 기간은 2026년 12월 1일부터 15일까지입니다. 문의: intl@sch.ac.kr")
    row = sql(f"select translation_status || '|' || provider || '|' || model || '|' || jsonb_array_length(warnings) "
              f"from public.announcement_translations where announcement_id = '{ann['id']}' and language_code = 'en'")
    assert row == "machine_draft|scripted|translate-1|0", row
    assert sql(f"select count(*) from public.ingestion_jobs where job_type = 'translate_announcement' "
               f"and payload->>'announcement_id' = '{ann['id']}' and status = 'succeeded'") == "1"
    # Release 1: unreviewed machine drafts of announcements are never public (PUBLIC_MACHINE_TRANSLATIONS is ignored for them)
    assert it.client.get(f"/api/v1/announcements/{ann['id']}", params={"lang": "en"}).json()["translation"] is None
    # the original is untouched
    assert sql(f"select count(*) from public.document_versions where document_id = '{ann['document_id']}' "
               f"and extracted_text like '장학금 신청 기간은%'") == "1"


def test_unique_open_job_index_and_quota_deferral_through_the_real_store(it: IT):
    svc = it.app.state.services
    it.settings.auto_translate_announcements = False
    ann = publish(it, f"기숙사 안내 {uuid.uuid4().hex[:6]}", "기숙사 입사는 3월 2일 10시부터입니다.")
    it.settings.auto_translate_announcements = True
    tr = svc.announcement_translator
    first = tr.queue(ann["id"], "en", None, enqueue=False)
    real_open = tr.open_job
    calls = {"n": 0}

    def stale_once(tid):  # type: ignore[no-untyped-def]
        calls["n"] += 1                                      # a concurrent request that did not see the first job
        return None if calls["n"] == 1 else real_open(tid)
    tr.open_job = stale_once
    try:   # the unique index rejects the second insert (23505 -> DuplicateError); the existing job is returned
        assert tr.queue(ann["id"], "en", None, enqueue=False)["id"] == first["id"]
    finally:
        tr.open_job = real_open
    assert sql(f"select count(*) from public.ingestion_jobs where payload->>'announcement_id' = '{ann['id']}'") == "1"
    # the provider's daily quota is exhausted: the job waits (queued, attempt not counted) instead of failing
    use(it, FakeTranslator(fail=LLMError("llm_quota", "The Gemini API quota is exhausted.", transient=True)))
    done = svc.ingestion.run_job(first["id"])
    assert done["status"] == "queued" and done["attempts"] == 0 and done["statistics"]["deferrals"] == 1
    assert sql(f"select run_after > now() + interval '50 minutes' from public.ingestion_jobs where id = '{first['id']}'") == "t"


def test_long_document_summary_and_daily_budget_query(it: IT):
    from app.services.translation.auto import daily_budget_exceeded

    use(it, FakeTranslator())
    it.settings.translation_full_max_chars = 300
    a = it.auth("admin")
    src = it.client.post("/api/v1/admin/sources", headers=a, json=dict(
        title=f"IT guide {uuid.uuid4().hex[:6]}", organization="NIIED", source_type="manual_text",
        authority_type="official_government", scope="national", category="visa-immigration", language="ko")).json()
    body = "\n\n".join(f"## 제{i}장\n\n외국인 유학생은 체류 규정을 지켜야 합니다. 신고 기한은 {i}0일입니다." for i in range(1, 12))
    job = it.client.post(f"/api/v1/admin/sources/{src['id']}/submit-text", headers=a,
                         json=dict(title="유학생 가이드", text=body, authorized_by_supporter=True)).json()
    assert it.client.post(f"/api/v1/admin/versions/{job['version_id']}/approve", headers=a, json={}).status_code == 202
    svc = it.app.state.services
    for jid in sql(f"select id from public.ingestion_jobs where job_type = 'translate_document' and status = 'queued' "
                   f"and payload->>'document_id' = '{job['document_id']}'").split():
        svc.ingestion.run_job(jid)
    assert sql(f"select translation_status || '|' || scope from public.document_translations "
               f"where document_id = '{job['document_id']}' and language_code = 'en' and not is_outdated") \
        == "machine_draft|summary"
    tr = it.client.get(f"/api/v1/knowledge/documents/{job['document_id']}", params={"lang": "en"}).json()["translation"]
    assert tr["scope"] == "summary" and tr["status"] == "machine"
    # the budget query (in_ + gte + neq + count) runs against PostgREST
    it.settings.translation_daily_job_limit = 10_000
    assert daily_budget_exceeded(svc.store, it.settings, str(uuid.uuid4())) is False
    it.settings.translation_daily_job_limit = 0
    assert daily_budget_exceeded(svc.store, it.settings, str(uuid.uuid4())) is True
    it.settings.translation_daily_job_limit = 60
