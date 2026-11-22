"""Phase 2: board connector, file/OCR intake, review workflow, persistent jobs, allowlist, search v2."""
from __future__ import annotations

import io
from datetime import UTC, datetime, timedelta

import pytest

from app.repositories.base import Query
from app.services.ingestion.errors import ExtractionError
from app.services.ingestion.extractors_files import extract_pdf, extract_text_file, validate_upload
from app.services.ingestion.sch_board import parse_listing
from app.services.ocr.providers import NoOCR, OCRLine, OCRResult, OCRUnavailable, _parse_tsv
from app.services.retrieval.service import exact_terms

BOARD = "https://sgee.sch.ac.kr/notice/notice01.php?page=1&make=&search=&type=&table_name=noti_fore&loc_mnu=3"


def notice_url(no: int) -> str:
    return f"https://sgee.sch.ac.kr/notice/notice01.php?admin_mode=read&no={no}&table_name=noti_fore"


def board_html(rows: list[tuple[int, str, str, bool]]) -> str:
    trs = "".join(
        f'<tr><td class="w_cell">{"<span class=ico>공지</span>" if pinned else no}</td>'
        f'<td class="subject"><a href="/notice/notice01.php?admin_mode=read&no={no}&make=&search=&type=&loc_mnu=3'
        f'&table_name=noti_fore&page=1"> {title}</a></td><td class="w_cell">국제교육교류처</td><td>{date}</td>'
        f'<td class="w_cell">10</td></tr>' for no, title, date, pinned in rows)
    return f"<html><body><table><thead><tr><th>번호</th></tr></thead><tbody>{trs}</tbody></table></body></html>"


def notice_html(title: str, date: str, body: str, attachment: str | None = None) -> str:
    att = (f"<tr><th>첨부파일</th><td colspan='3'><a href='../lib/download.php?file_name=x.pdf&save_file=a.pdf' "
           f"class='down_file'><span>{attachment}</span></a></td></tr>") if attachment else ""
    return (f"<html><body><div class='view_tit'><h3 class='v_tit'>{title}</h3></div><p class='click_count'>조회수 : 24</p>"
            f"<table class='board-view'><tbody><tr><th>작성일</th><td>{date}</td><th>작성자</th><td>국제교육교류처</td></tr>"
            f"{att}<tr><td class='view_td' colspan='4'>{body}"
            "<div id='hwpEditorBoardContent'><!--[data-hwpjson]{\"x\": 1}--></div></td></tr></tbody></table></body></html>")


def make_board_source(env, **kw):
    r = env.client.post("/api/v1/admin/sources", headers=env.auth("admin"), json=dict(
        title="SCH international notices", original_url=BOARD, organization="SCH 국제교육교류처", source_type="sch_board",
        authority_type="official_university", scope="university", category="university-announcements", language="ko",
        sync_frequency="daily", config={"max_items": 3, "max_pages": 1}, **kw))
    assert r.status_code == 201, r.text
    return r.json()


def ingest(env, source_id, role="admin"):
    r = env.client.post(f"/api/v1/admin/sources/{source_id}/ingest", headers=env.auth(role))
    assert r.status_code == 202, r.text
    return env.client.get(f"/api/v1/admin/ingestion-jobs/{r.json()['job_id']}", headers=env.auth("admin")).json()


def setup_board(env, notices: dict[int, tuple[str, str, str]]):
    env.page(BOARD, board_html([(no, t, d, i == 0) for i, (no, (t, d, _b)) in enumerate(notices.items())]))
    for no, (t, d, b) in notices.items():
        env.page(notice_url(no), notice_html(t, d.replace("-", "."), b, attachment="안내문.pdf"))


NOTICES = {
    6708: ("[생활관] 방학 중 짐 보관 안내", "2026-11-17", "<p>방학 중 교내에 개인 짐을 보관할 수 없습니다. 첨부 안내문을 참고하세요.</p>"),
    6707: ("[모집] 동계방학 생활관 입사생 모집", "2026-11-17", "<p>신청 기간: 2026. 11. 18.(화) ~ 11. 25.(화) 17:00까지</p>"
           "<p>장소: 글로벌빌리지 행정실</p>"),
    6706: ("[홍보] 독도 서포터즈 모집", "2026-11-16", "<p>대상: D-2 비자 소지 외국인 유학생 누구나 지원할 수 있습니다.</p>"),
}


# ------------------------------------------------------------------ board connector
def test_board_listing_parser_finds_notices_and_pinned_rows():
    refs = parse_listing(board_html([(1, "A 공지", "2026-09-08", True), (2, "B", "2026-11-17", False)]), BOARD)
    assert [r.notice_no for r in refs] == ["1", "2"]
    assert refs[0].pinned and not refs[1].pinned and refs[1].posted == "2026-11-17"
    assert refs[1].url == notice_url(2)  # canonical: no paging/search parameters


def test_board_sync_creates_one_document_per_notice_and_dedups(env):
    setup_board(env, NOTICES)
    src = make_board_source(env)
    job = ingest(env, src["id"])
    assert job["status"] == "succeeded" and job["outcome"] == "new_version", job
    st = job["statistics"]
    assert st["items_found"] == 3 and st["items_new"] == 3 and st["items_failed"] == 0
    docs, _ = env.store.select("source_documents", Query(eq={"source_id": src["id"]}))
    assert {d["external_id"] for d in docs} == {"noti_fore:6708", "noti_fore:6707", "noti_fore:6706"}
    assert all(d["document_type"] == "notice" and d["canonical_url"].startswith("https://sgee") for d in docs)
    assert all(d["metadata"]["attachments"][0]["name"] == "안내문.pdf" for d in docs)
    vs, _ = env.store.select("document_versions")
    text = next(v for v in vs if "짐 보관" in v["extracted_text"])["extracted_text"]
    assert "작성일 (Posted): 2026-11-17" in text and "hwpjson" not in text and notice_url(6708) in text
    assert text.splitlines()[2].startswith("방학 중")  # body comes right after the title (excerpt / first chunk)
    period = next(v for v in vs if "입사생" in v["extracted_text"])["structured_data"]["fields"]
    assert period["deadline"]["value"] == "2026-11-25" and period["location"]["value"].startswith("글로벌빌리지")
    # second sync: nothing changed -> no new versions
    job2 = ingest(env, src["id"])
    assert job2["outcome"] == "unchanged" and job2["statistics"]["items_unchanged"] == 3
    assert len(env.store.select("document_versions")[0]) == 3
    events = env.client.get(f"/api/v1/admin/ingestion-jobs/{job['id']}/events", headers=env.auth("admin")).json()["items"]
    assert any(e["step"] == "list" for e in events) and events[-1]["step"] == "finish"


def test_board_detects_updated_notice_and_partial_failures(env):
    setup_board(env, NOTICES)
    src = make_board_source(env)
    ingest(env, src["id"])
    env.page(notice_url(6706), notice_html(NOTICES[6706][0], "2026.11.16", "<p>대상: D-2, D-4 비자 소지자 (수정됨)</p>"))
    env.pages[notice_url(6707)] = lambda req: __import__("httpx").Response(500)
    job = ingest(env, src["id"])
    assert job["outcome"] == "partial" and job["statistics"]["items_new"] == 1 and job["statistics"]["items_failed"] == 1
    v6706 = [v for v in env.store.select("document_versions")[0] if "D-4" in v["extracted_text"]]
    assert len(v6706) == 1 and v6706[0]["version_number"] == 2


def test_board_blocked_by_robots_marks_source_blocked(env):
    env.page("https://sgee.sch.ac.kr/robots.txt", "User-agent: *\nDisallow: /notice/", "text/plain")
    src = make_board_source(env)
    job = ingest(env, src["id"])
    assert job["status"] == "failed" and job["error_code"] == "robots_disallowed"
    s = env.client.get(f"/api/v1/admin/sources/{src['id']}", headers=env.auth("admin")).json()
    assert s["status"] == "blocked"


def test_board_source_requires_sch_board_url(env):
    r = env.client.post("/api/v1/admin/sources", headers=env.auth("admin"), json=dict(
        title="x", original_url="https://www.hikorea.go.kr/", organization="x", source_type="sch_board",
        authority_type="official_university", scope="university", category="university-announcements"))
    assert r.status_code == 409


# ------------------------------------------------------------------ files
def make_pdf(pages: list[list[tuple[str, float]]]) -> bytes:
    import pymupdf

    doc = pymupdf.open()
    for lines in pages:
        page = doc.new_page()
        y = 72.0
        for text, size in lines:
            page.insert_text((72, y), text, fontsize=size)
            y += size * 2
    return doc.tobytes()


def test_pdf_headings_and_page_markers():
    data = make_pdf([[("Residence Permit Guide", 24), ("Bring your passport and the application form to the office.", 11),
                      ("Required documents", 16), ("Passport, photo, certificate of enrollment.", 11)],
                     [("Second page text about the extension of stay period.", 11)]])
    ex = extract_pdf(data, "guide.pdf")
    assert "[Page 1]" in ex.text and "[Page 2]" in ex.text
    assert "# Residence Permit Guide" in ex.text and "## Required documents" in ex.text
    assert ex.metadata["pages"] == 2 and ex.metadata["pages_with_text"] == 2


def test_image_only_pdf_needs_ocr():
    import pymupdf

    doc = pymupdf.open()
    doc.new_page()
    with pytest.raises(ExtractionError) as e:
        extract_pdf(doc.tobytes(), "scan.pdf")
    assert e.value.code == "needs_ocr"


def test_text_and_markdown_files_decode_korean_and_keep_headings():
    md = "##등록 안내\n\n외국인 등록은 입국 후 90일 이내에 해야 합니다.".encode("cp949")
    ex = extract_text_file(md, "guide.md")
    assert "## 등록 안내" in ex.text and "90일" in ex.text and ex.metadata["encoding"] == "cp949"
    with pytest.raises(ExtractionError):
        validate_upload("text_file", "x.txt", "text/plain", b"\x00\x01binary", 10_000)


def test_image_validation_checks_magic_bytes():
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 20
    assert validate_upload("screenshot", "a.png", "image/png", png, 10_000) == "image/png"
    with pytest.raises(ExtractionError):
        validate_upload("screenshot", "a.jpg", "image/jpeg", png, 10_000)  # PNG bytes named .jpg
    with pytest.raises(ExtractionError):
        validate_upload("screenshot", "a.png", "image/png", b"GIF89a....", 10_000)


def meta(**kw):
    import json

    base = dict(title="Residence guide", organization="Korea Immigration Service", category="visa-immigration",
                scope="national", authority_type="official_government", language="en")
    base.update(kw)
    return json.dumps(base)


def test_document_upload_intake_creates_source_and_versions_and_blocks_duplicates(env):
    data = make_pdf([[("Alien registration guide", 22), ("Register within 90 days of entry at the immigration office.", 11)]])
    files = {"file": ("guide.pdf", io.BytesIO(data), "application/pdf")}
    r = env.client.post("/api/v1/admin/intake/document", headers=env.auth("admin"), files=files, data={"metadata": meta()})
    assert r.status_code == 202, r.text
    job = env.client.get(f"/api/v1/admin/ingestion-jobs/{r.json()['job_id']}", headers=env.auth("admin")).json()
    assert job["status"] == "succeeded" and job["outcome"] == "new_version", job
    v = env.client.get(f"/api/v1/admin/versions/{job['version_id']}", headers=env.auth("admin")).json()
    assert v["original_file"]["filename"] == "guide.pdf" and v["original_file"]["sha256"]
    assert "[Page 1]" in v["extracted_text"] and v["indexing_status"] == "indexed"
    doc = env.store.select("source_documents", Query(eq={"id": job["document_id"]}))[0][0]
    assert doc["title"] == "Residence guide"  # submitter's title, not the file name
    orig = env.client.get(f"/api/v1/admin/versions/{job['version_id']}/original", headers=env.auth("admin"))
    assert orig.status_code == 200 and orig.content == data and orig.headers["content-type"] == "application/pdf"
    again = env.client.post("/api/v1/admin/intake/document", headers=env.auth("admin"),
                            files={"file": ("copy.pdf", io.BytesIO(data), "application/pdf")}, data={"metadata": meta()})
    assert again.status_code == 409 and again.json()["error"]["details"]["version_id"] == job["version_id"]
    assert env.client.get(f"/api/v1/admin/versions/{job['version_id']}/original").status_code == 401


def test_upload_rejects_wrong_type_and_oversize(env):
    r = env.client.post("/api/v1/admin/intake/document", headers=env.auth("admin"),
                        files={"file": ("x.exe", io.BytesIO(b"MZ..."), "application/octet-stream")}, data={"metadata": meta()})
    assert r.status_code == 415
    big = b"%PDF-" + b"0" * (env.settings.max_upload_bytes + 10)
    r = env.client.post("/api/v1/admin/intake/document", headers=env.auth("admin"),
                        files={"file": ("big.pdf", io.BytesIO(big), "application/pdf")}, data={"metadata": meta()})
    assert r.status_code == 413
    assert env.store.select("knowledge_sources")[0] == []  # failed intake leaves nothing behind


# ------------------------------------------------------------------ OCR / screenshots
class FakeOCR:
    name = "fake"

    def __init__(self, text: str, conf: float = 91.0):
        self.text, self.conf = text, conf

    def available(self):
        return True, None

    def extract(self, image, mime_type):
        return OCRResult(text=self.text, provider="fake", model="fake-1", mean_confidence=self.conf,
                         lines=[OCRLine(t, self.conf if i else 41.0) for i, t in enumerate(self.text.splitlines())])


def use_ocr(env, provider):
    svc = env.app.state.services
    svc.ocr = svc.intake.ocr = svc.ingestion.ocr = provider


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
OCR_TEXT = "[국제교육교류처] TOPIK 설명회 안내\n일시: 2026년 12월 3일(수) 오후 2시\n장소: 인문과학관 101호\n참가비: 무료\n문의: 041-530-0000"


def shot(env, role="supporter", authorized=True, data=PNG):
    return env.client.post("/api/v1/admin/intake/screenshot", headers=env.auth(role),
                           files={"file": ("notice.png", io.BytesIO(data), "image/png")},
                           data={"metadata": meta(title="TOPIK 설명회", category="topik-korean", scope="university",
                                                  authority_type="staff_communication", language="ko"),
                                 "authorized_for_distribution": str(authorized).lower()})


def test_screenshot_requires_authorization_confirmation(env):
    use_ocr(env, FakeOCR(OCR_TEXT))
    assert shot(env, authorized=False).status_code == 422


def test_screenshot_ocr_flow_needs_human_confirmation_before_approval(env):
    use_ocr(env, FakeOCR(OCR_TEXT))
    r = shot(env)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["ocr"]["available"] and "TOPIK" in body["ocr"]["text"] and body["ocr"]["uncertain_lines"]
    assert body["detected"]["fields"]["location"]["value"] == "인문과학관 101호"
    img = env.client.get(f"/api/v1/admin/intake/screenshot/{body['job']['id']}/image", headers=env.auth("supporter"))
    assert img.status_code == 200 and img.content == PNG
    assert not env.store.select("document_versions")[0]  # nothing created before the human submits

    corrected = OCR_TEXT.replace("101호", "102호")
    sub = env.client.post(f"/api/v1/admin/intake/screenshot/{body['job']['id']}/submit", headers=env.auth("supporter"),
                          json=dict(title="TOPIK 설명회 안내", text=corrected, submit=True, fields={"location": "인문과학관 102호"}))
    assert sub.status_code == 201 and sub.json()["status"] == "succeeded", sub.text
    vid = sub.json()["version_id"]
    v = env.client.get(f"/api/v1/admin/versions/{vid}", headers=env.auth("admin")).json()
    assert v["raw_text"] == OCR_TEXT and "102호" in v["extracted_text"]  # evidence kept, correction stored separately
    assert v["requires_field_confirmation"] and v["original_file"]["mime_type"] == "image/png"
    assert v["structured_data"]["fields"]["location"]["confirmed"] is True
    assert "[redacted phone]" in v["extracted_text"]  # personal-detail redaction is on by default

    blocked = env.client.post(f"/api/v1/admin/versions/{vid}/approve", headers=env.auth("admin"), json={})
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "fields_not_confirmed"
    sup = env.client.patch(f"/api/v1/admin/versions/{vid}", headers=env.auth("supporter"), json={"fields_confirmed": True})
    assert sup.status_code in (403, 409)
    ok = env.client.patch(f"/api/v1/admin/versions/{vid}", headers=env.auth("admin"), json={"fields_confirmed": True})
    assert ok.status_code == 200
    appr = env.client.post(f"/api/v1/admin/versions/{vid}/approve", headers=env.auth("admin"), json={})
    assert appr.status_code == 200 and appr.json()["verification_status"] == "approved"
    hits = env.client.post("/api/v1/knowledge/search", json={"query": "TOPIK 설명회 장소"}).json()["results"]
    assert hits and hits[0]["authority_type"] == "staff_communication"
    again = env.client.post(f"/api/v1/admin/intake/screenshot/{body['job']['id']}/submit", headers=env.auth("supporter"),
                            json=dict(title="dup", text=corrected, submit=True))
    assert again.status_code == 409


def test_screenshot_without_ocr_provider_allows_manual_transcription(env):
    use_ocr(env, NoOCR())
    body = shot(env).json()
    assert body["ocr"]["available"] is False and body["ocr"]["text"] == "" and body["detected"] is None
    sub = env.client.post(f"/api/v1/admin/intake/screenshot/{body['job']['id']}/submit", headers=env.auth("supporter"),
                          json=dict(title="Typed from image", text="장학금 신청은 2026년 12월 1일까지입니다.", submit=False))
    assert sub.status_code == 201
    v = env.client.get(f"/api/v1/admin/versions/{sub.json()['version_id']}", headers=env.auth("supporter")).json()
    assert v["verification_status"] == "draft" and v["raw_text"] is None
    assert v["structured_data"]["fields"]["deadline"]["value"] == "2026-12-01"


def test_ocr_unavailable_error_is_reported(env):
    class Broken(FakeOCR):
        def extract(self, image, mime_type):
            raise OCRUnavailable("ocr_failed", "service down")

    use_ocr(env, Broken(""))
    body = shot(env).json()
    assert body["ocr"]["available"] is False and "service down" in body["ocr"]["warnings"][0]


def test_tesseract_tsv_parsing_keeps_confidence():
    tsv = ("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
           "5\t1\t1\t1\t1\t1\t0\t0\t1\t1\t95.5\t외국인\n5\t1\t1\t1\t1\t2\t0\t0\t1\t1\t30.0\t등록\n"
           "5\t1\t2\t1\t1\t1\t0\t0\t1\t1\t88\tARC\n")
    r = _parse_tsv(tsv, "kor+eng")
    assert r.text == "외국인 등록\n\nARC" and r.lines[0].confidence == 62.8 and r.mean_confidence == 71.2


# ------------------------------------------------------------------ pasted announcements + review workflow
def paste(env, role="supporter", **kw):
    body = dict(original_text="[국제교육교류처] 겨울방학 기숙사 신청 안내\n신청 기간: 2026.12.01 ~ 12.10\n홍길동 010-1234-5678로 문의",
                title="겨울방학 기숙사 신청", organization="국제교육교류처", category="dormitory-housing",
                authorized_by_supporter=True, location="글로벌빌리지", deadline="2026-12-10", submit=True)
    body.update(kw)
    return env.client.post("/api/v1/admin/intake/announcement", headers=env.auth(role), json=body)


def test_paste_requires_authorization_and_keeps_original_evidence(env):
    assert paste(env, authorized_by_supporter=False).status_code == 422
    r = paste(env)
    assert r.status_code == 201 and r.json()["status"] == "succeeded", r.text
    v = env.client.get(f"/api/v1/admin/versions/{r.json()['version_id']}", headers=env.auth("admin")).json()
    assert "010-1234-5678" in v["raw_text"] and "010-1234-5678" not in v["extracted_text"]
    assert v["structured_data"]["fields"]["deadline"] == {"value": "2026-12-10", "evidence": None, "confirmed": True,
                                                         "source": "submitter"}
    src = env.store.select("knowledge_sources")[0][0]
    assert src["source_type"] == "kakao_message" and src["authority_type"] == "staff_communication"


def test_request_changes_edit_resubmit_approve_and_audit(env):
    vid = paste(env).json()["version_id"]
    # pending content is never public
    assert env.client.post("/api/v1/knowledge/search", json={"query": "기숙사 신청"}).json()["results"] == []
    rc = env.client.post(f"/api/v1/admin/versions/{vid}/request-changes", headers=env.auth("admin"),
                         json={"note": "Add the application link"})
    assert rc.status_code == 200 and rc.json()["verification_status"] == "draft"
    assert env.client.post(f"/api/v1/admin/versions/{vid}/request-changes", headers=env.auth("supporter"),
                           json={"note": "x" * 5}).status_code == 403
    new_text = "겨울방학 기숙사 신청 안내\n신청 기간: 2026.12.01 ~ 12.10\n신청: https://sgee.sch.ac.kr/apply"
    ed = env.client.patch(f"/api/v1/admin/versions/{vid}", headers=env.auth("supporter"), json={"extracted_text": new_text})
    assert ed.status_code == 200 and ed.json()["edited_at"] and ed.json()["indexing_status"] == "indexed"
    chunks, _ = env.store.select("document_chunks", Query(eq={"version_id": vid}))
    assert any("sgee.sch.ac.kr/apply" in c["content"] for c in chunks)  # re-chunked after the edit
    assert env.client.post(f"/api/v1/admin/versions/{vid}/submit", headers=env.auth("supporter")).status_code == 200
    assert env.client.post(f"/api/v1/admin/versions/{vid}/approve", headers=env.auth("supporter"), json={}).status_code == 403
    assert env.client.post(f"/api/v1/admin/versions/{vid}/approve", headers=env.auth("admin"), json={}).status_code == 200
    # approved versions cannot be edited in place
    assert env.client.patch(f"/api/v1/admin/versions/{vid}", headers=env.auth("admin"),
                            json={"extracted_text": "changed text after approval"}).status_code == 409
    doc_id = env.store.select("document_versions", Query(eq={"id": vid}))[0][0]["document_id"]
    hist = env.client.get(f"/api/v1/admin/documents/{doc_id}/history", headers=env.auth("admin")).json()["items"]
    actions = [h["action"] for h in hist]
    assert {"version.request_changes", "version.edit", "version.submit", "version.approve"} <= set(actions)
    appr = next(h for h in hist if h["action"] == "version.approve")
    assert appr["details"]["previous_status"] == "pending_review" and appr["details"]["new_status"] == "approved"
    detail = env.client.get(f"/api/v1/knowledge/documents/{doc_id}").json()
    assert detail["key_facts"]["deadline"] == "2026-12-10" and detail["authority_type"] == "staff_communication"


def test_supporter_cannot_touch_other_peoples_versions(env):
    vid = paste(env, role="admin", submit=False).json()["version_id"]
    assert env.client.get(f"/api/v1/admin/versions/{vid}", headers=env.auth("supporter")).status_code == 403
    assert env.client.patch(f"/api/v1/admin/versions/{vid}", headers=env.auth("supporter"),
                            json={"extracted_text": "x" * 20}).status_code == 403
    assert env.client.post(f"/api/v1/admin/versions/{vid}/submit", headers=env.auth("supporter")).status_code == 403
    mine = env.client.get("/api/v1/admin/intake/mine", headers=env.auth("admin")).json()
    assert mine["total"] == 1 and mine["items"][0]["document_title"] == "겨울방학 기숙사 신청"


def test_review_warnings_flag_changed_deadline_and_non_official_immigration(env):
    r = paste(env, role="admin", category="visa-immigration", authority_type="supporter_submitted",
              original_text="체류기간 연장 신청은 2026.12.10까지 하세요.", deadline=None)
    vid = r.json()["version_id"]
    env.client.post(f"/api/v1/admin/versions/{vid}/approve", headers=env.auth("admin"), json={})
    doc_id = r.json()["document_id"]
    src_id = env.store.select("source_documents", Query(eq={"id": doc_id}))[0][0]["source_id"]
    r2 = env.client.post("/api/v1/admin/intake/announcement", headers=env.auth("admin"), json=dict(
        source_id=src_id, original_text="체류기간 연장 신청은 2026.12.20까지 하세요.", title="겨울방학 기숙사 신청",
        organization="x", category="visa-immigration", authorized_by_supporter=True, submit=True))
    assert r2.status_code == 201, r2.text
    detail = env.client.get(f"/api/v1/admin/documents/{doc_id}", headers=env.auth("admin")).json()
    codes = {w["code"] for w in detail["review_warnings"]}
    assert {"non_official_immigration", "deadline_changed"} <= codes
    assert detail["current_version"]["verification_status"] == "approved"  # old one stays live until review


# ------------------------------------------------------------------ indexing / approval safety
def test_embedding_failure_on_approval_keeps_previous_version_live(env):
    from app.services.embeddings.base import EmbeddingError

    vid = paste(env, role="admin").json()["version_id"]
    env.client.post(f"/api/v1/admin/versions/{vid}/approve", headers=env.auth("admin"), json={})
    src_id = env.store.select("knowledge_sources")[0][0]["id"]
    embedder = env.app.state.services.embedder

    def boom(texts):
        raise EmbeddingError("model failed to load (out of memory)")

    orig = embedder.embed_passages
    embedder.embed_passages = boom
    try:
        r = env.client.post("/api/v1/admin/intake/announcement", headers=env.auth("admin"), json=dict(
            source_id=src_id, original_text="겨울방학 기숙사 신청 기간이 연장되었습니다: 2026.12.15까지", title="겨울방학 기숙사 신청",
            organization="x", category="dormitory-housing", authorized_by_supporter=True, submit=True))
        new_vid = r.json()["version_id"]
        v = env.client.get(f"/api/v1/admin/versions/{new_vid}", headers=env.auth("admin")).json()
        assert v["indexing_status"] == "failed" and "out of memory" in v["indexing_error"]
        a = env.client.post(f"/api/v1/admin/versions/{new_vid}/approve", headers=env.auth("admin"), json={})
        assert a.status_code == 503
    finally:
        embedder.embed_passages = orig
    live = env.client.post("/api/v1/knowledge/search", json={"query": "기숙사 신청"}).json()["results"]
    assert live and all(x["version_id"] == vid for x in live)


# ------------------------------------------------------------------ jobs
def test_worker_claims_queued_jobs_and_requeues_stale_ones(env):
    svc = env.app.state.services
    setup_board(env, {6708: NOTICES[6708]})
    src = make_board_source(env)
    job = svc.ingestion.create_job(env.store.select("knowledge_sources", Query(eq={"id": src["id"]}))[0][0], "schedule")
    assert svc.jobs.run_once() is True
    done = env.store.select("ingestion_jobs", Query(eq={"id": job["id"]}))[0][0]
    assert done["status"] == "succeeded" and done["attempts"] == 1 and done["locked_by"] is None
    assert svc.jobs.run_once() is False
    # a job left running by a dead worker is re-queued, then fails after max_attempts
    stale = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    j2 = svc.ingestion.create_job(env.store.select("knowledge_sources", Query(eq={"id": src["id"]}))[0][0], "schedule")
    env.store.update("ingestion_jobs", dict(status="running", attempts=3, max_attempts=3, heartbeat_at=stale,
                                            started_at=stale), {"id": j2["id"]})
    env.store.rpc("claim_ingestion_job", dict(p_worker="w", p_stale_seconds=900))
    j2 = env.store.select("ingestion_jobs", Query(eq={"id": j2["id"]}))[0][0]
    assert j2["status"] == "failed" and j2["error_code"] == "interrupted"


def test_cron_endpoint_requires_secret_and_queues_due_sources(env):
    assert env.client.post("/api/v1/internal/sync/run-due").status_code == 404  # disabled without CRON_SECRET
    env.settings.cron_secret = "s3cret-value"
    setup_board(env, {6708: NOTICES[6708]})
    make_board_source(env)
    assert env.client.post("/api/v1/internal/sync/run-due", headers={"X-Cron-Secret": "wrong"}).status_code == 403
    r = env.client.post("/api/v1/internal/sync/run-due", headers={"X-Cron-Secret": "s3cret-value"})
    assert r.status_code == 202 and r.json()["queued"] == 1
    r2 = env.client.post("/api/v1/internal/sync/run-due", headers={"X-Cron-Secret": "s3cret-value"})
    assert r2.json()["queued"] == 0  # just checked: not due again


# ------------------------------------------------------------------ allowlist + url tools
def test_domain_allowlist_admin_managed(env):
    url = "https://www.immigration.example.kr/guide"
    assert env.client.post("/api/v1/admin/sources/validate-url", headers=env.auth("admin"),
                           json={"url": url}).json()["checks"][0]["ok"] is False
    assert env.client.post("/api/v1/admin/allowed-domains", headers=env.auth("admin"),
                           json={"domain": "immigration.example.kr"}).status_code == 403
    r = env.client.post("/api/v1/admin/allowed-domains", headers=env.auth("super_admin"),
                        json={"domain": "https://www.immigration.example.kr/x"})
    assert r.status_code == 201 and r.json()["domain"] == "immigration.example.kr"
    listed = env.client.get("/api/v1/admin/allowed-domains", headers=env.auth("admin")).json()["items"]
    assert any(d["domain"] == "visa.go.kr" and d["origin"] == "environment" for d in listed)
    env.page(url, "<html><head><title>Guide</title></head><body><article><h1>Guide</h1><p>"
                  + "Extension of stay applications are filed online or at the office. " * 4 + "</p></article></body></html>")
    pv = env.client.post("/api/v1/admin/sources/preview", headers=env.auth("admin"), json={"url": url})
    assert pv.status_code == 200 and pv.json()["kind"] == "page" and pv.json()["estimated_chunks"] >= 1
    assert env.store.select("knowledge_sources")[0] == []  # preview stores nothing
    assert env.client.delete("/api/v1/admin/allowed-domains/visa.go.kr", headers=env.auth("super_admin")).status_code == 409
    assert env.client.delete("/api/v1/admin/allowed-domains/immigration.example.kr",
                             headers=env.auth("super_admin")).status_code == 204


def test_validate_url_reports_robots_and_ssrf(env):
    env.page("https://www.topik.go.kr/robots.txt", "User-agent: *\nDisallow: /", "text/plain")
    r = env.client.post("/api/v1/admin/sources/validate-url", headers=env.auth("admin"),
                        json={"url": "https://www.topik.go.kr/TWMAIN/TWMAIN0010.do"}).json()
    assert r["ok"] is False and next(c for c in r["checks"] if c["name"] == "robots")["ok"] is False
    bad = env.client.post("/api/v1/admin/sources/validate-url", headers=env.auth("admin"),
                          json={"url": "http://169.254.169.254/latest/meta-data"}).json()
    assert bad["ok"] is False


# ------------------------------------------------------------------ retrieval v2
def test_exact_identifiers_and_scope_filters(env):
    for title, text in (("D-2 student visa", "The D-2 visa is for degree students. Bring the certificate of admission."),
                        ("D-4 language trainee visa", "The D-4 visa is for Korean language trainees at a language institute.")):
        vid = paste(env, role="admin", title=title, original_text=text, category="visa-immigration", deadline=None,
                    location=None, authority_type="official_university").json()["version_id"]
        assert env.client.post(f"/api/v1/admin/versions/{vid}/approve", headers=env.auth("admin"), json={}).status_code == 200
    res = env.client.post("/api/v1/knowledge/search", json={"query": "D-2 비자는 무엇인가요?", "mode": "keyword"}).json()
    assert res["retrieval"]["exact_terms"] == ["D-2"]
    assert res["results"][0]["document_title"] == "D-2 student visa" and res["results"][0]["exact_match"]
    assert all(r["document_title"] != "D-4 language trainee visa" or not r["exact_match"] for r in res["results"])
    nat = env.client.post("/api/v1/knowledge/search", json={"query": "D-2 visa", "scope": "national"}).json()
    assert nat["results"] == []
    assert "is_stale" in res["results"][0] and res["results"][0]["is_stale"] is False
    assert exact_terms("TOPIK II and ARC") == ["TOPIK II", "ARC"]


def test_stale_flag_and_knowledge_stats(env):
    vid = paste(env, role="admin").json()["version_id"]
    env.client.post(f"/api/v1/admin/versions/{vid}/approve", headers=env.auth("admin"), json={})
    old = (datetime.now(UTC) - timedelta(days=400)).isoformat()
    env.store.t["document_versions"][0]["approved_at"] = old
    docs = env.client.get("/api/v1/knowledge/documents").json()["items"]
    assert docs[0]["is_stale"] is True and docs[0]["verification_age_days"] >= 399
    stats = env.client.get("/api/v1/admin/knowledge/stats", headers=env.auth("admin")).json()
    assert stats["sources_total"] == 1 and stats["documents_approved"] == 1 and stats["searchable_chunks"] >= 1
    assert stats["versions_pending"] == 0 and "ocr_available" in stats


def test_identifiers_glued_to_cjk_text_are_detected():
    assert exact_terms("D-2签证是什么？") == ["D-2"] and exact_terms("D-2비자 연장") == ["D-2"]
    assert exact_terms("visa D-20 info") == ["D-20"]  # D-20 is not D-2


def test_pdf_served_as_octet_stream_is_accepted_only_with_pdf_magic(env):
    pdf = make_pdf([[("Official notice attachment", 18), ("Luggage storage service guide for the vacation.", 11)]])
    url = "https://sgee.sch.ac.kr/lib/download.php?file_name=a.pdf&save_file=a.pdf"
    env.page(url, pdf, content_type="application/octet-stream")
    res = env.app.state.services.ingestion.fetcher.fetch(url, "ko")
    assert res.content_type == "application/pdf"
    env.page(url, b"MZ\x90\x00 not a pdf", content_type="application/octet-stream")
    with pytest.raises(Exception) as e:
        env.app.state.services.ingestion.fetcher.fetch(url, "ko")
    assert getattr(e.value, "code", "") == "unsupported_content_type"


def test_ocr_cleanup_joins_spaced_hangul_but_keeps_raw_evidence():
    from app.services.ocr.providers import clean_ocr_text

    raw = "작성자 (Author): 국 제 교 육 교 류 처\n( 재 ) 독 도 재 단 에서 유 학 생 을 모집"
    r = OCRResult(text=raw, provider="t", model="m")
    assert r.raw_text == raw
    assert r.text.splitlines()[0] == "작성자 (Author): 국제교육교류처"
    assert clean_ocr_text("D-2 비자 안내") == "D-2 비자 안내"  # normal text untouched


def test_e5_onnx_tokenization_matches_xlmr_ids_and_model_id_is_distinct():
    from app.core.config import Settings
    from app.services.embeddings.e5_onnx import MAX_LENGTH, E5OnnxEmbeddingProvider
    from app.services.embeddings.factory import build_embedding_provider

    class FakeSP:
        def encode(self, text):
            return [0, 5, 9] * 400  # spm ids; 0 = unknown

    ids = E5OnnxEmbeddingProvider._ids(FakeSP(), "x")
    assert ids[0] == 0 and ids[-1] == 2 and len(ids) == MAX_LENGTH  # <s> ... </s>, truncated to 512
    assert ids[1:4] == [3, 6, 10]  # unk -> 3, others shifted by the fairseq offset (+1)
    emb = build_embedding_provider(Settings(_env_file=None, embedding_provider="e5_onnx"))
    assert emb.model_id == "intfloat/multilingual-e5-small#qint8"  # never mixed with fp32 vectors
