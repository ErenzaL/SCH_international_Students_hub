"""PDF ingestion robustness: isolated extraction, timeouts/crashes -> Failed with actionable errors, Korean text,
scan detection, duplicate prevention, worker interruption + recovery, idempotent retries, job liveness."""
from __future__ import annotations

import io
import json
import sys
from datetime import UTC, datetime, timedelta

import pytest

from app.core.errors import Conflict, DuplicateError
from app.repositories.base import Query
from app.services.ingestion import pdf_isolation
from app.services.ingestion.errors import ExtractionError
from app.services.ingestion.extractors_files import extract_pdf
from app.services.jobs import JobRunner
from tests.conftest import make_settings

KOREAN = "국제교육교류처 외국인 유학생 비자 연장 안내. 신청 기간은 2026년 3월 1일부터 3월 15일까지이며 수수료는 30,000원입니다."


def korean_pdf(pages: int = 2, lines_per_page: int = 0) -> bytes:
    import pymupdf

    doc = pymupdf.open()
    for p in range(pages):
        page = doc.new_page(width=595, height=842)
        if lines_per_page:
            shape = page.new_shape()
            n, y = 0, 60
            while n < lines_per_page:
                x = 40
                while x < 555 and n < lines_per_page:
                    shape.draw_line((x, y), (x + 4, y))
                    n += 1
                    x += 5
                y = 60 if y > 800 else y + 6
            shape.finish(width=0.3)
            shape.commit()
        page.insert_textbox(pymupdf.Rect(50, 80, 545, 780), f"{p + 1}쪽. " + KOREAN * 3, fontname="korea", fontsize=11)
    return doc.tobytes()


def scanned_pdf() -> bytes:
    import pymupdf

    img = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 200, 280), 0)
    img.clear_with(200)
    doc = pymupdf.open()
    for _ in range(2):
        page = doc.new_page(width=595, height=842)
        page.insert_image(page.rect, pixmap=img)
    return doc.tobytes()


def upload(env, data: bytes, name: str = "notice.pdf"):  # type: ignore[no-untyped-def]
    r = env.client.post("/api/v1/admin/intake/document", headers=env.auth("admin"),
                        files={"file": (name, io.BytesIO(data), "application/pdf")},
                        data={"metadata": json.dumps(dict(title="비자 연장 안내", organization="국제교육교류처",
                                                          category="visa-immigration", scope="university",
                                                          authority_type="official_university", language="ko"))})
    return r


def job_of(env, r):  # type: ignore[no-untyped-def]
    assert r.status_code == 202, r.text
    return env.client.get(f"/api/v1/admin/ingestion-jobs/{r.json()['job_id']}", headers=env.auth("admin")).json()


def events(env, job_id: str) -> list[dict]:  # type: ignore[type-arg]
    return env.client.get(f"/api/v1/admin/ingestion-jobs/{job_id}/events", headers=env.auth("admin")).json()["items"]


# ------------------------------------------------------------------------ extraction
def test_korean_pdf_is_extracted_in_an_isolated_process_and_not_published(env):
    job = job_of(env, upload(env, korean_pdf(3)))
    assert job["status"] == "succeeded" and job["outcome"] == "new_version", job
    assert [s["stage"] for s in job["stages"]][:3] == ["download", "validate", "extract"]
    assert all(s["ok"] and s["ms"] >= 0 for s in job["stages"])
    ex = next(s for s in job["stages"] if s["stage"] == "extract")
    assert ex["pages"] == 3 and ex["chars"] > 100 and ex["hangul_ratio"] > 0.3 and ex["needs_ocr_pages"] == 0
    assert job["pdf"]["pages_with_text"] == 3
    v = env.store.select("document_versions", Query(eq={"id": job["version_id"]}))[0][0]
    assert "국제교육교류처" in v["extracted_text"] and "[Page 3]" in v["extracted_text"]
    # never published automatically, never in the student-facing index
    assert v["verification_status"] == "pending_review"
    doc = env.store.select("source_documents", Query(eq={"id": job["document_id"]}))[0][0]
    assert doc["current_version_id"] is None
    assert env.client.post("/api/v1/knowledge/search", json={"query": "국제교육교류처 비자 연장"}).json()["results"] == []
    assert any(e["step"] == "extract" and "isolated process" in e["message"] for e in events(env, job["id"]))


def test_corrupt_pdf_fails_with_actionable_error(env):
    job = job_of(env, upload(env, b"%PDF-1.7\n" + b"\x00garbage" * 50, "broken.pdf"))
    assert job["status"] == "failed" and job["error_code"] == "corrupt_file"
    assert "could not be opened" in job["error_message"]
    assert job["stages"][-1] == {"stage": "extract", "ms": job["stages"][-1]["ms"], "ok": False, "error": "corrupt_file"}
    src = env.store.select("knowledge_sources", Query(eq={"id": job["source_id"]}))[0][0]
    assert src["status"] == "failed"


def test_scanned_pdf_is_diagnosed_as_needing_ocr(env):
    with pytest.raises(ExtractionError) as e:
        extract_pdf(scanned_pdf(), "scan.pdf")
    assert e.value.code == "needs_ocr" and "scanned PDF (2 of 2 page(s) are images" in e.value.message
    job = job_of(env, upload(env, scanned_pdf(), "scan.pdf"))
    assert job["status"] == "failed" and job["error_code"] == "needs_ocr" and "OCR_PROVIDER" in job["error_message"]


def test_vector_heavy_pdf_skips_table_detection_and_stays_fast():
    data = korean_pdf(2, lines_per_page=20000)
    ex = extract_pdf(data, "hwp.pdf", table_mode="auto", max_table_items=1500)
    assert "국제교육교류처" in ex.text and ex.metadata["table_mode"] == "auto"
    assert any("Table layout detection was skipped on 2 page(s)" in w for w in ex.metadata["warnings"])


def test_extraction_timeout_fails_the_job_and_the_service_keeps_working(env):
    env.app.state.services.settings.pdf_extract_timeout_seconds = 2
    env.app.state.services.settings.pdf_table_detection = "auto"
    env.app.state.services.settings.pdf_max_table_items = 10**9          # force the expensive path
    job = job_of(env, upload(env, korean_pdf(4, lines_per_page=20000), "huge.pdf"))
    assert job["status"] == "failed" and job["error_code"] == "extraction_timeout", job
    assert "did not finish within 2 s" in job["error_message"] and "Split the PDF" in job["error_message"]
    env.app.state.services.settings.pdf_table_detection = "off"
    assert job_of(env, upload(env, korean_pdf(1), "small.pdf"))["status"] == "succeeded"   # still serving jobs


def test_killed_extraction_process_is_reported_not_left_running(monkeypatch):
    monkeypatch.setattr(pdf_isolation, "_child_command", lambda path, opts: [
        sys.executable, "-c", "import os, signal; os.kill(os.getpid(), signal.SIGKILL)"])
    with pytest.raises(ExtractionError) as e:
        pdf_isolation.extract_pdf_isolated(korean_pdf(1), "x.pdf", timeout_seconds=20)
    assert e.value.code == "extraction_crashed" and "out of memory" in e.value.message


# ------------------------------------------------------------------------ duplicates
def test_duplicate_upload_of_a_file_already_being_processed(env):
    svc = env.app.state.services
    from app.security.auth import AuthUser

    admin = AuthUser(id=env.users["admin"], email=None, role="admin")
    data = korean_pdf(1)
    meta = dict(title="비자", organization="SCH", category="visa-immigration", scope="university",
                authority_type="official_university", language="ko")
    first = svc.intake.upload_document(data=data, filename="a.pdf", content_type="application/pdf", actor=admin, meta=meta)
    assert first["job"]["status"] == "queued"            # not processed yet (no version exists)
    with pytest.raises(Conflict) as e:
        svc.intake.upload_document(data=data, filename="a-again.pdf", content_type="application/pdf", actor=admin,
                                   meta=meta)
    assert e.value.code == "already_processing" and e.value.details["job_id"] == first["job"]["id"]
    # a different file for the same source while its job is active
    with pytest.raises(Conflict):
        svc.intake.upload_document(data=korean_pdf(2), filename="b.pdf", content_type="application/pdf", actor=admin,
                                   source_id=first["source"]["id"])
    # the database guarantees it even if two requests race past the check
    with pytest.raises(DuplicateError):
        env.store.insert("ingestion_jobs", dict(source_id=None, status="queued", job_type="ingest",
                                                payload={"sha256": first["job"]["payload"]["sha256"]}))
    # API: the same file uploaded again through the endpoint -> 409 with the existing job
    r = upload(env, data, "again.pdf")
    assert r.status_code == 409 and r.json()["error"]["details"]["job_id"] == first["job"]["id"]
    # once finished, the exact same file is recognised as an existing version (no second document)
    svc.ingestion.run_job(first["job"]["id"])
    r = upload(env, data, "third.pdf")
    assert r.status_code == 409 and r.json()["error"]["details"]["version_number"] == 1


# --------------------------------------------------------------- restart resilience
def _worker(env) -> JobRunner:  # type: ignore[no-untyped-def]
    s = make_settings(job_execution="worker")
    return JobRunner(env.store, env.app.state.services.ingestion, s)


def test_interrupted_job_is_recovered_after_restart_without_duplicates(env):
    svc = env.app.state.services
    from app.security.auth import AuthUser

    admin = AuthUser(id=env.users["admin"], email=None, role="admin")
    out = svc.intake.upload_document(data=korean_pdf(2), filename="r.pdf", content_type="application/pdf", actor=admin,
                                     meta=dict(title="재시작", organization="SCH", category="visa-immigration",
                                               scope="university", authority_type="official_university", language="ko"))
    jid = out["job"]["id"]
    # the previous process claimed it, reached 'extract' and died (OOM / redeploy): running, stale heartbeat
    old = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    env.store.update("ingestion_jobs", dict(status="running", attempts=1, started_at=old, heartbeat_at=old,
                                            locked_by="old-host:1:dead", statistics={"stage": "extract"}), {"id": jid})
    view = env.client.get(f"/api/v1/admin/ingestion-jobs/{jid}", headers=env.auth("admin")).json()
    assert view["stale"] and view["stage"] == "extract" and view["heartbeat_age_seconds"] >= 290
    # the new process starts: its first claim uses the short startup threshold, re-queues and runs the job
    assert _worker(env).run_once(stale_seconds=90)
    job = env.client.get(f"/api/v1/admin/ingestion-jobs/{jid}", headers=env.auth("admin")).json()
    assert job["status"] == "succeeded" and job["attempts"] == 2 and job["resumed_from_stage"] == "extract"
    assert any(e["step"] == "resume" and "stopped during extract" in e["message"] for e in events(env, jid))
    versions = env.store.select("document_versions", Query(eq={"document_id": job["document_id"]}))[0]
    assert len(versions) == 1
    chunks = env.store.select("document_chunks", Query(eq={"version_id": job["version_id"]}))[0]
    # the same job interrupted AFTER it created the version (e.g. died before saving its result) and run again
    env.store.update("ingestion_jobs", dict(status="running", heartbeat_at=old, statistics={"stage": "process"}),
                     {"id": jid})
    assert _worker(env).run_once(stale_seconds=90)
    again = env.client.get(f"/api/v1/admin/ingestion-jobs/{jid}", headers=env.auth("admin")).json()
    assert again["status"] == "succeeded" and again["outcome"] == "unchanged"
    assert len(env.store.select("document_versions", Query(eq={"document_id": job["document_id"]}))[0]) == 1
    assert len(env.store.select("document_chunks", Query(eq={"version_id": job["version_id"]}))[0]) == len(chunks)


def test_job_that_keeps_dying_ends_failed_not_running(env):
    svc = env.app.state.services
    src = env.store.insert("knowledge_sources", dict(title="x", organization="SCH", source_type="pdf",
                                                     authority_type="official_university", scope="university",
                                                     category="visa-immigration"))
    job = svc.ingestion.create_job(src, payload={"storage_path": "sources/x/missing.pdf", "filename": "m.pdf"})
    old = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
    env.store.update("ingestion_jobs", dict(status="running", attempts=3, max_attempts=3, heartbeat_at=old,
                                            started_at=old), {"id": job["id"]})
    _worker(env).run_once(stale_seconds=90)
    row = env.store.select("ingestion_jobs", Query(eq={"id": job["id"]}))[0][0]
    assert row["status"] == "failed" and row["error_code"] == "interrupted"


def test_late_result_of_a_taken_over_attempt_is_discarded(env):
    svc = env.app.state.services
    src = env.store.insert("knowledge_sources", dict(title="y", organization="SCH", source_type="pdf",
                                                     authority_type="official_university", scope="university",
                                                     category="visa-immigration"))
    job = svc.ingestion.create_job(src, payload={"filename": "y.pdf"})
    stale_attempt = env.store.update("ingestion_jobs", dict(status="running", attempts=1), {"id": job["id"]})[0]
    env.store.update("ingestion_jobs", dict(status="running", attempts=2), {"id": job["id"]})   # newer attempt owns it
    out = svc.ingestion._update_owned(stale_attempt, dict(status="failed", error_code="late"))
    assert out["attempts"] == 2 and out["status"] == "running"
