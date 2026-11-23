"""Original documents in the Knowledge Center: the stored original file (never RAG chunks) of the CURRENT approved
version of a PUBLIC document, a formatted Word preview built from the file's own structure, and clear errors for
unpublished documents and missing files."""
from __future__ import annotations

import io
import json
import struct
import zlib

from app.repositories.base import Query
from app.services.originals import docx_preview_html, original_info
from tests.test_pdf_ingestion import korean_pdf, upload
from tests.test_rag_sync import approve


def _png() -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    raw = b"\x00\xff\x00\x00"           # 1x1 red pixel
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)) + \
        chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def word_file() -> bytes:
    from docx import Document

    d = Document()
    d.add_heading("장학금 안내 <script>alert(1)</script>", level=1)
    p = d.add_paragraph("신청 기한은 ")
    p.add_run("3월 15일").bold = True
    p.add_run("까지입니다.")
    d.add_paragraph("여권 사본", style="List Bullet")
    d.add_paragraph("재학증명서", style="List Bullet")
    d.add_paragraph("첫째 단계", style="List Number")
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text, t.cell(0, 1).text, t.cell(1, 0).text, t.cell(1, 1).text = "항목", "금액", "수수료", "30,000원"
    d.add_picture(io.BytesIO(_png()))
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def upload_file(env, data: bytes, name: str, mime: str):  # type: ignore[no-untyped-def]
    return env.client.post("/api/v1/admin/intake/document", headers=env.auth("admin"),
                           files={"file": (name, io.BytesIO(data), mime)},
                           data={"metadata": json.dumps(dict(title="장학금 안내", organization="국제교육교류처",
                                                             category="scholarships", scope="university",
                                                             authority_type="official_university", language="ko"))})


def ingest(env, r, *, publish=True):  # type: ignore[no-untyped-def]
    assert r.status_code == 202, r.text
    job = env.client.get(f"/api/v1/admin/ingestion-jobs/{r.json()['job_id']}", headers=env.auth("admin")).json()
    assert job["status"] == "succeeded", job
    if publish:
        approve(env, job["version_id"])
    return job


# ------------------------------------------------------------------------------------------------- PDF
def test_pdf_original_is_served_from_storage_with_viewer_metadata(env):
    data = korean_pdf(3)
    job = ingest(env, upload(env, data))
    d = env.client.get(f"/api/v1/knowledge/documents/{job['document_id']}").json()
    o = d["original"]
    assert o["kind"] == "pdf" and o["has_file"] and o["filename"] == "notice.pdf"
    assert o["file_url"] == f"/api/v1/knowledge/documents/{job['document_id']}/original"
    assert "storage" not in json.dumps(o) and "sources/" not in json.dumps(o)     # no storage path leaves the server
    r = env.client.get(o["file_url"])
    assert r.status_code == 200 and r.content == data                          # the actual uploaded bytes
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"].startswith("inline;")
    assert r.headers["x-content-type-options"] == "nosniff"
    dl = env.client.get(o["download_url"])
    assert dl.status_code == 200 and dl.headers["content-disposition"].startswith("attachment;")


def test_unpublished_documents_have_no_public_original(env):
    job = ingest(env, upload(env, korean_pdf(2)), publish=False)            # pending review
    assert env.client.get(f"/api/v1/knowledge/documents/{job['document_id']}/original").status_code == 404
    approve(env, job["version_id"])
    assert env.client.get(f"/api/v1/knowledge/documents/{job['document_id']}/original").status_code == 200
    # withdrawn again: gone
    env.store.update("source_documents", {"is_canceled": True}, {"id": job["document_id"]})
    assert env.client.get(f"/api/v1/knowledge/documents/{job['document_id']}/original").status_code == 404


def test_missing_original_file_is_a_clear_404_not_a_crash(env):
    job = ingest(env, upload(env, korean_pdf(2)))
    v = env.store.select("document_versions", Query(eq={"id": job["version_id"]}))[0][0]
    env.storage.remove(v["original_file"]["storage_path"])
    r = env.client.get(f"/api/v1/knowledge/documents/{job['document_id']}/original")
    assert r.status_code == 404 and r.json()["error"]["code"] == "original_unavailable"
    # the document page itself still works (it shows the open/download fallback)
    assert env.client.get(f"/api/v1/knowledge/documents/{job['document_id']}").status_code == 200


def test_text_and_web_documents_have_no_file(env):
    from tests.test_retrieval import make_doc

    text = make_doc(env, "Dormitory rules", "Quiet hours start at 23:00 in every dormitory building.")
    o = env.client.get(f"/api/v1/knowledge/documents/{text['document_id']}").json()["original"]
    assert o == dict(kind="text", has_file=False, source_url=None)
    assert env.client.get(f"/api/v1/knowledge/documents/{text['document_id']}/original").status_code == 404
    web = original_info(dict(id="d", canonical_url="https://www.hikorea.go.kr/x"), dict(source_type="website"), {})
    assert web == dict(kind="web", has_file=False, source_url="https://www.hikorea.go.kr/x")


def test_announcement_documents_are_not_served_as_knowledge_originals(env):
    from tests.test_announcements import create

    a = create(env, submit=True)
    env.client.post(f"/api/v1/admin/announcements/{a['id']}/approve", headers=env.auth("admin"), json={})
    assert env.client.get(f"/api/v1/knowledge/documents/{a['document_id']}/original").status_code == 404


# ------------------------------------------------------------------------------------------------- Word
def test_word_preview_keeps_structure_and_escapes_everything():
    out = docx_preview_html(word_file(), "장학금")
    h = out["html"]
    assert "<h1>장학금 안내 &lt;script&gt;alert(1)&lt;/script&gt;</h1>" in h and "<script>" not in h
    assert "<strong>3월 15일</strong>" in h
    assert "<ul><li>여권 사본</li><li>재학증명서</li></ul>" in h and "<ol><li>첫째 단계</li></ol>" in h
    assert "<td><p>수수료</p></td><td><p>30,000원</p></td>" in h
    assert 'src="data:image/png;base64,' in h and out["omitted_images"] == 0


def test_word_original_preview_and_download(env):
    data = word_file()
    mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    job = ingest(env, upload_file(env, data, "guide.docx", mime))
    o = env.client.get(f"/api/v1/knowledge/documents/{job['document_id']}").json()["original"]
    assert o["kind"] == "docx" and o["preview_url"].endswith("/original/preview")
    p = env.client.get(o["preview_url"])
    assert p.status_code == 200 and "<table>" in p.json()["html"]
    f = env.client.get(o["file_url"])
    assert f.content == data and f.headers["content-disposition"].startswith("attachment;")   # never inline
    # a PDF has no Word preview
    pdf = ingest(env, upload(env, korean_pdf(2), name="other.pdf"))
    assert env.client.get(f"/api/v1/knowledge/documents/{pdf['document_id']}/original/preview").status_code == 404
