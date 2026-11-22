"""Document translations against the REAL database (PostgREST + PostgreSQL + migration 0011): durable AI draft job,
language-scoped approval (API + trigger), public display, invalidation on a new original version.
Skipped unless the integration environment is configured (see test_postgres_integration.py)."""
from __future__ import annotations

import uuid

import pytest

from app.services.llm.base import ScriptedLLMProvider
from tests.conftest import ARTICLE_HTML, ARTICLE_URL
from tests.integration.test_postgres_integration import IT, PSQL, REST, sql
from tests.test_document_translations import fake_translate

pytestmark = pytest.mark.skipif(not (REST and PSQL), reason="set SCH_IT_REST_URL and SCH_IT_PSQL to run")


@pytest.fixture(scope="module")
def it() -> IT:
    return IT()


def test_document_translation_workflow_against_real_database(it: IT):
    c, a = it.client, it.auth("admin")
    svc = it.app.state.services
    svc.llm = svc.doc_translations.llm = svc.conversations.llm = ScriptedLLMProvider(fake_translate)
    sup = it.users["supporter"]
    sql(f"insert into public.supporter_languages (supporter_id, language_code, can_support, can_review_translations) "
        f"values ('{sup}', 'id', true, true) on conflict do nothing")
    url = f"{ARTICLE_URL}?tr={uuid.uuid4().hex[:8]}"
    it.pages[url] = ARTICLE_HTML.encode()
    src = c.post("/api/v1/admin/sources", headers=a, json=dict(
        title=f"IT translations {uuid.uuid4().hex[:6]}", original_url=url, organization="NIIED", source_type="website",
        authority_type="official_government", scope="national", category="visa-immigration", language="en")).json()
    jid = c.post(f"/api/v1/admin/sources/{src['id']}/ingest", headers=a).json()["job_id"]
    job = c.get(f"/api/v1/admin/ingestion-jobs/{jid}", headers=a).json()
    assert c.post(f"/api/v1/admin/versions/{job['version_id']}/approve", headers=a, json={}).status_code == 202
    doc = job["document_id"]
    assert sql(f"select count(*) from public.document_translations where document_id = '{doc}' "
               f"and translation_status = 'todo'") == "4"

    # durable AI draft job through the real queue tables
    r = c.post(f"/api/v1/admin/documents/{doc}/translations/drafts", headers=a, json={"languages": ["id"]})
    assert r.status_code == 202, r.text
    tj = c.get(f"/api/v1/admin/ingestion-jobs/{r.json()['items'][0]['job_id']}", headers=a).json()
    assert tj["status"] == "succeeded" and tj["job_type"] == "translate_document", tj
    row = sql(f"select translation_status || '|' || provider || '|' || jsonb_array_length(headings) "
              f"from public.document_translations where document_id = '{doc}' and language_code = 'id'")
    assert row.startswith("machine_draft|scripted|") and not row.endswith("|0")

    # the public API never shows the machine draft (anon RLS is covered by the SQL behaviour suite)
    assert c.get(f"/api/v1/knowledge/documents/{doc}", params={"lang": "id"}).json()["translation"] is None

    # supporter edits + approves Indonesian; Vietnamese is refused
    h = it.auth("supporter")
    assert c.put(f"/api/v1/admin/documents/{doc}/translations/id", headers=h,
                 json={"title": "Visa dan Izin Tinggal", "body": "# Visa dan Izin Tinggal\n\nIsi.", "submit": True}
                 ).status_code == 200
    r = c.post(f"/api/v1/admin/documents/{doc}/translations/id/approve", headers=h, json={"original_verified": True})
    assert r.status_code == 200, r.text
    assert c.post(f"/api/v1/admin/documents/{doc}/translations/vi/approve", headers=h,
                  json={"original_verified": True}).status_code == 403
    tr = c.get(f"/api/v1/knowledge/documents/{doc}", params={"lang": "id"}).json()["translation"]
    assert tr["status"] == "verified" and tr["title"] == "Visa dan Izin Tinggal"

    # new original version -> old translation outdated (kept), new task, no longer public
    it.pages[url] = ARTICLE_HTML.replace("Bring your passport", "Bring your passport and ARC form").encode()
    jid = c.post(f"/api/v1/admin/sources/{src['id']}/ingest", headers=a).json()["job_id"]
    j2 = c.get(f"/api/v1/admin/ingestion-jobs/{jid}", headers=a).json()
    assert j2["outcome"] == "new_version"
    assert c.post(f"/api/v1/admin/versions/{j2['version_id']}/approve", headers=a, json={}).status_code == 202
    assert sql(f"select count(*) from public.document_translations where document_id = '{doc}' "
               f"and language_code = 'id' and is_outdated and translation_status = 'human_approved'") == "1"
    assert sql(f"select count(*) from public.document_translations where version_id = '{j2['version_id']}'") == "4"
    assert c.get(f"/api/v1/knowledge/documents/{doc}", params={"lang": "id"}).json()["translation"] is None
