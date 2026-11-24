"""Approved-source rule and document titles on the REAL database (no migration needed). Skipped unless configured."""
from __future__ import annotations

import uuid

import pytest

from app.services.ingestion.normalize import content_hash
from app.services.llm.base import ScriptedLLMProvider
from tests.integration.test_postgres_integration import IT, PSQL, REST, sql

pytestmark = pytest.mark.skipif(not (REST and PSQL), reason="set SCH_IT_REST_URL and SCH_IT_PSQL to run")


@pytest.fixture(scope="module")
def it() -> IT:
    return IT()


def test_title_follows_the_approved_version_and_the_rollback(it: IT):
    a, tag = it.auth("admin"), uuid.uuid4().hex[:8]
    src = it.client.post("/api/v1/admin/sources", headers=a, json=dict(
        title=f"titles {tag}", organization="SCH", source_type="manual_text", authority_type="official_university",
        scope="university", category="academic-life", language="en")).json()
    row = it.app.state.services.store.select("knowledge_sources")[0]
    row = next(r for r in row if r["id"] == src["id"])
    ingest = lambda title, text: it.app.state.services.ingestion.ingest_text(  # noqa: E731
        row, title=title, text=text, requested_by=it.users["admin"], external_id=f"t-{tag}")
    one = ingest("Old title", f"The library opens at nine in the morning. {tag}")
    assert it.client.post(f"/api/v1/admin/versions/{one['version_id']}/approve", headers=a, json={}).status_code == 202
    two = ingest("New UNAPPROVED title", f"The library opens at ten in the morning from now on. {tag}")
    title = lambda: sql(f"select title from public.source_documents where id = '{one['document_id']}'")  # noqa: E731
    assert two["document_id"] == one["document_id"] and title() == "Old title"
    assert it.client.get(f"/api/v1/knowledge/documents/{one['document_id']}").json()["title"] == "Old title"
    d = it.client.get(f"/api/v1/admin/documents/{one['document_id']}", headers=a).json()
    assert d["title"] == "Old title" and d["proposed_title"] == "New UNAPPROVED title"
    assert it.client.post(f"/api/v1/admin/versions/{two['version_id']}/approve", headers=a, json={}).status_code == 202
    assert title() == "New UNAPPROVED title"
    assert sql(f"select distinct document_title from public.searchable_chunks where document_id = '{one['document_id']}'") == title()
    r = it.client.post(f"/api/v1/admin/documents/{one['document_id']}/rollback", headers=a, json=dict(version_id=one["version_id"]))
    assert r.status_code == 200 and title() == "Old title"


def test_published_announcement_is_translated_from_the_approved_text(it: IT):
    a, svc, tag = it.auth("admin"), it.app.state.services, uuid.uuid4().hex[:8]
    p = ScriptedLLMProvider(lambda s, x: f"Scholarship guide 2026-12-01 {tag}")
    svc.announcement_translator.llm = p
    ann = it.client.post("/api/v1/admin/announcements", headers=a, json=dict(
        title=f"장학금 안내 {tag}", body=f"신청 기간은 2026-12-01부터입니다. {tag}", category="scholarships",
        source_type="manual_text", submit=True, evidence_note="integration test")).json()
    assert it.client.post(f"/api/v1/admin/announcements/{ann['id']}/approve", headers=a, json={}).status_code == 200
    doc = sql(f"select document_id from public.announcements where id = '{ann['id']}'")
    edit = f"SECRET-EDIT 신청 기간은 2026-12-20부터입니다. {tag}"
    sql("insert into public.document_versions (document_id, version_number, extracted_text, content_hash) "
        f"values ('{doc}', 2, '{edit}', '{content_hash(edit)}')")
    r = it.client.post(f"/api/v1/admin/announcements/{ann['id']}/translations/en/machine-translate", headers=a)
    assert r.status_code == 202 and p.calls and all("SECRET-EDIT" not in x for _s, x in p.calls)
    d = it.client.get(f"/api/v1/admin/documents/{doc}", headers=a).json()
    assert d["pending_version"]["extracted_text"] == edit and d["diff"]["added_count"] >= 1
    vid = d["pending_version"]["id"]
    assert it.client.post(f"/api/v1/admin/versions/{vid}/approve", headers=a, json={}).status_code == 202
    assert it.client.get(f"/api/v1/announcements/{ann['id']}", params={"lang": "en"}).json()["body"] == edit
    assert sql("select is_outdated from public.announcement_translations "
               f"where announcement_id = '{ann['id']}' and language_code = 'en'") == "t"
