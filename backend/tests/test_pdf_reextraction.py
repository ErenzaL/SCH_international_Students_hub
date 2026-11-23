"""Korean PDF body-size fix, control-character cleanup, older-source review warning and re-extraction of a stored
original into a new version that waits for review (the live version is never changed)."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.repositories.base import Query
from app.services.chunking import chunk_text
from app.services.ingestion import extractors_files as ef
from app.services.source_quality import age_review_warning, declared_edition_year
from tests.test_pdf_ingestion import korean_pdf, upload
from tests.test_rag_sync import approve, search

BODY = "외국인 유학생은 체류기간 연장을 신청할 때 재학증명서와 성적증명서를 제출해야 하며"


def front_matter_heavy_pdf() -> bytes:
    """20 pages of dense 6 pt contact tables, then 40 pages of 10 pt Korean body text under 16 pt section headings:
    the layout of the 2021 NIIED guidebook that made the first-20-pages estimate pick the table size."""
    import pymupdf

    doc = pymupdf.open()
    for p in range(20):
        page = doc.new_page(width=595, height=842)
        for i in range(40):
            page.insert_text((40, 60 + i * 9.6), f"Embassy {p}-{i}  Tel 02-000-{i:04d}  Fax 02-000-{i + 1:04d}  consular office",
                             fontsize=6)
    for p in range(21, 61):
        page = doc.new_page(width=595, height=842)
        page.insert_text((40, 60), f"제{p}장 체류 안내", fontname="korea", fontsize=16)
        for i in range(30):
            line = f"수수료는 {p}0,000원이며 신청 기간은 {p}일 이내이고" if i == 0 else BODY
            page.insert_text((40, 100 + i * 16), line, fontname="korea", fontsize=10)
    return doc.tobytes()


def chunk_content(text: str) -> str:
    return "\n".join(c.content for c in chunk_text(text))


# ------------------------------------------------------------------------------------------- body-size estimate
def test_body_size_is_estimated_over_all_pages_not_front_matter():
    data = front_matter_heavy_pdf()
    doc = ef.open_pdf(data)
    with doc:
        assert ef._body_font_size(doc, max_pages=20) == 6.0      # the old estimate: front-matter tables
        assert ef._body_font_size(doc) == 10.0                   # the fix: the real body size
    text = ef.extract_pdf(data, "guide.pdf").text
    assert "## 제21장 체류 안내" in text                        # real section headings stay headings
    assert f"## {BODY}" not in text and BODY in text              # body lines are no longer headings
    content = chunk_content(text)
    # every page's specific figures reach chunk content, with the right page reference
    assert all(f"수수료는 {p}0,000원" in content for p in range(21, 61))
    fee_chunk = next(c for c in chunk_text(text) if "수수료는 350,000원" in c.content)
    assert fee_chunk.page_start <= 35 <= fee_chunk.page_end and fee_chunk.heading == "제35장 체류 안내"


def test_first_pages_estimate_loses_body_text_regression_guard(monkeypatch):
    """Documents the defect: with the old estimate the body text becomes headings and never reaches chunk text."""
    original = ef._body_font_size
    monkeypatch.setattr(ef, "_body_font_size", lambda doc, max_pages=None: original(doc, max_pages=20))
    content = chunk_content(ef.extract_pdf(front_matter_heavy_pdf(), "guide.pdf").text)
    assert sum(f"수수료는 {p}0,000원" in content for p in range(21, 61)) < 5


def test_short_documents_are_unchanged_by_the_fix():
    data = korean_pdf(3)
    doc = ef.open_pdf(data)
    with doc:
        assert ef._body_font_size(doc) == ef._body_font_size(doc, max_pages=20)


def test_control_characters_are_removed_from_pdf_text():
    assert ef._strip_controls("- \x07운영시간: 주중 11:00~20:00\n※ \x07출입국\tA") == "- 운영시간: 주중 11:00~20:00\n※ 출입국\tA"


# ------------------------------------------------------------------------------------------- older-source warning
def test_age_review_warning_is_generic_and_configurable():
    now = datetime(2026, 11, 23, tzinfo=UTC)
    old = age_review_warning(datetime(2021, 3, 5, tzinfo=UTC), "가이드북", "외국인 유학생 가이드북 2021 개정판", 1095, now)
    assert old and "published 2021-03-05" in old and "declares a 2021 edition" in old and "Verify" in old
    assert age_review_warning(datetime(2026, 1, 27, tzinfo=UTC), "Guide", "2026 edition", 1095, now) is None
    assert age_review_warning(None, "Guide", "no dates here", 1095, now) is None            # unknown is not "old"
    assert age_review_warning(datetime(2021, 3, 5, tzinfo=UTC), None, None, 10 * 365, now) is None   # threshold
    assert declared_edition_year("x", "2019 edition of the handbook") == 2019


def test_old_pdf_gets_a_reviewer_warning_on_its_new_version(env):
    import pymupdf

    doc = pymupdf.open(stream=korean_pdf(2), filetype="pdf")
    doc.set_metadata({"creationDate": "D:20190305094724+09'00'"})
    job = env.client.get(f"/api/v1/admin/ingestion-jobs/{upload(env, doc.tobytes()).json()['job_id']}",
                         headers=env.auth("admin")).json()
    v = env.store.select("document_versions", Query(eq={"id": job["version_id"]}))[0][0]
    assert v["source_published_at"].startswith("2019-03-05")
    assert any(w.startswith("Older source: published 2019-03-05") for w in v["extraction_meta"]["warnings"])
    assert v["verification_status"] == "pending_review"          # a warning only: nothing published or hidden


# ------------------------------------------------------------------------------------------- re-extraction
@pytest.fixture
def changed_extractor(env, monkeypatch):
    """Call it AFTER the live version exists: from then on extraction is inline and its output differs from the
    stored text (stands in for an improved extractor)."""
    from app.services.ingestion import pipeline

    def enable() -> None:
        monkeypatch.setattr(env.app.state.services.ingestion.settings, "pdf_extraction_isolation", "inline")
        real = pipeline.extract_pdf

        def improved(*a, **kw):  # type: ignore[no-untyped-def]
            ex = real(*a, **kw)
            ex.text += "\n\n[Page 4]\n새로 복구된 본문: 등록금 납부 기한은 개강 2주 전입니다."
            return ex
        monkeypatch.setattr(pipeline, "extract_pdf", improved)
        monkeypatch.setattr(ef, "extract_pdf", improved)          # the CLI preview imports it from the module
    return enable


def live_pdf(env):
    r = upload(env, korean_pdf(3))
    job = env.client.get(f"/api/v1/admin/ingestion-jobs/{r.json()['job_id']}", headers=env.auth("admin")).json()
    approve(env, job["version_id"])
    return job["document_id"], job["version_id"]


def versions(env, doc_id):
    return env.store.select("document_versions", Query(eq={"document_id": doc_id}, order=[("version_number", False)]))[0]


def test_reextraction_creates_a_pending_version_and_keeps_the_live_one(env, changed_extractor):
    doc_id, v1 = live_pdf(env)
    changed_extractor()
    live_chunks = {c["id"] for c in env.store.select("document_chunks", Query(eq={"version_id": v1}))[0]}
    r = env.client.post(f"/api/v1/admin/versions/{v1}/re-extract?apply=true", headers=env.auth("admin"))
    assert r.status_code == 202, r.text
    job = env.client.get(f"/api/v1/admin/ingestion-jobs/{r.json()['job_id']}", headers=env.auth("admin")).json()
    assert job["status"] == "succeeded" and job["outcome"] == "new_version", job
    vs = versions(env, doc_id)
    assert [v["version_number"] for v in vs] == [1, 2]
    v2 = vs[1]
    assert v2["id"] == job["version_id"] and v2["verification_status"] == "pending_review"
    assert "새로 복구된 본문" in v2["extracted_text"]
    assert v2["original_file"]["storage_path"] == vs[0]["original_file"]["storage_path"]   # the same stored file
    # the live version is untouched and the new text is not searchable before approval
    doc = env.store.select("source_documents", Query(eq={"id": doc_id}))[0][0]
    assert doc["current_version_id"] == v1 and vs[0]["verification_status"] == "approved"
    assert {c["id"] for c in env.store.select("document_chunks", Query(eq={"version_id": v1}))[0]} == live_chunks
    assert not any("새로 복구된" in (x.get("content") or x.get("passage") or "") for x in search(env, "등록금 납부 기한 개강"))
    jobrow = env.store.select("ingestion_jobs", Query(eq={"id": job["id"]}))[0][0]
    assert jobrow["payload"]["reextract_of"] == v1 and jobrow["requested_by"] == env.users["admin"]
    assert any(a["action"] == "version.reextract_requested" and a["entity_id"] == v1
               for a in env.store.select("audit_log", Query())[0])
    # approving the new version goes through the normal activation path
    approve(env, v2["id"])
    doc = env.store.select("source_documents", Query(eq={"id": doc_id}))[0][0]
    assert doc["current_version_id"] == v2["id"]


def test_reextraction_with_identical_output_creates_nothing(env):
    doc_id, v1 = live_pdf(env)
    r = env.client.post(f"/api/v1/admin/versions/{v1}/re-extract?apply=true", headers=env.auth("admin"))
    job = env.client.get(f"/api/v1/admin/ingestion-jobs/{r.json()['job_id']}", headers=env.auth("admin")).json()
    assert job["status"] == "succeeded" and job["outcome"] == "unchanged"
    assert len(versions(env, doc_id)) == 1


def test_reextraction_guards(env):
    _, v1 = live_pdf(env)
    for q in ("", "?apply=true"):    # admin only, dry run included
        assert env.client.post(f"/api/v1/admin/versions/{v1}/re-extract{q}", headers=env.auth("supporter")).status_code == 403
        assert env.client.post(f"/api/v1/admin/versions/{v1}/re-extract{q}").status_code == 401
        assert env.client.post(f"/api/v1/admin/versions/00000000-0000-0000-0000-000000000000/re-extract{q}",
                               headers=env.auth("admin")).status_code == 404
    from tests.test_phase2 import paste

    pasted = paste(env, role="admin").json()["version_id"]     # pasted text has no stored original file
    for q in ("", "?apply=true"):
        r = env.client.post(f"/api/v1/admin/versions/{pasted}/re-extract{q}", headers=env.auth("admin"))
        assert r.status_code in (400, 409) and "original file" in r.text


def snapshot(env) -> tuple[int, ...]:
    return tuple(len(env.store.select(t, Query())[0]) for t in
                 ("ingestion_jobs", "document_versions", "document_chunks", "audit_log", "ingestion_events"))


def test_api_dry_run_is_the_default_and_writes_nothing(env, changed_extractor):
    doc_id, v1 = live_pdf(env)
    changed_extractor()
    before = snapshot(env)
    r = env.client.post(f"/api/v1/admin/versions/{v1}/re-extract", headers=env.auth("admin"))
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["dry_run"] is True and p["unchanged"] is False and p["can_apply"] is True
    assert p["new_chars"] > p["stored_chars"] and p["new"]["chunks"] >= 1 and p["pdf"]["pages"] == 3
    assert 0 < p["new"]["word_coverage"] <= 1 and p["new"]["pages_without_chunks"] == []
    assert snapshot(env) == before and len(versions(env, doc_id)) == 1
    doc = env.store.select("source_documents", Query(eq={"id": doc_id}))[0][0]
    assert doc["current_version_id"] == v1


def test_cli_preview_is_read_only(env, changed_extractor):
    from app.cli import reextract, reextract_preview

    services = env.app.state.services
    doc_id, v1 = live_pdf(env)
    changed_extractor()
    jobs_before = len(env.store.select("ingestion_jobs", Query())[0])
    p = reextract_preview(services, v1)
    assert p["unchanged"] is False and p["new_chars"] > p["stored_chars"] and p["new"]["chunks"] >= 1
    assert reextract(services, v1, apply=False) == 0
    assert len(versions(env, doc_id)) == 1 and len(env.store.select("ingestion_jobs", Query())[0]) == jobs_before
