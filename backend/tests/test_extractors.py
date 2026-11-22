import io

import pytest

from app.services.ingestion.errors import ExtractionError
from app.services.ingestion.extractors_files import (
    extract_docx,
    extract_pdf,
    process_manual_text,
    validate_upload,
)
from app.services.ingestion.extractors_html import extract_html
from app.services.ingestion.privacy import redact_personal_info
from tests.conftest import ARTICLE_HTML, ARTICLE_URL


def test_html_extraction_keeps_structure_and_drops_boilerplate():
    doc = extract_html(ARTICLE_HTML, ARTICLE_URL)
    assert doc.title.startswith("Visa and Stay")
    assert "Alien registration" in doc.text
    assert "Registration happens at the immigration office" in doc.text
    assert "Copyright footer boilerplate" not in doc.text
    assert doc.text.lstrip().startswith("#")
    assert doc.metadata["extractor"] in ("trafilatura", "beautifulsoup")


def test_html_fallback_preserves_tables_lists_links_and_absolutizes():
    html = ("<html><head><title>T</title></head><body><div id='content'><h2>Heading</h2>"
            "<p>" + "Some paragraph text for the fallback extractor. " * 3 + "</p>"
            "<ul><li>One</li><li>Two</li></ul>"
            "<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>"
            "<a href='/rel/page.do'>Rel link</a></div></body></html>")
    from app.services.ingestion import extractors_html as m

    text, links = m._soup_fallback(html, "https://www.hikorea.go.kr/x/y")
    assert "## Heading" in text and "- One" in text and "| A | B |" in text
    assert {"text": "Rel link", "href": "https://www.hikorea.go.kr/rel/page.do"} in links


@pytest.mark.parametrize("html", ["", "   ", "<html><body></body></html>",
                                  "<html><body><script>var x=1;</script><nav>menu</nav></body></html>"])
def test_empty_extraction_is_an_error_not_empty_content(html):
    with pytest.raises(ExtractionError) as exc:
        extract_html(html, ARTICLE_URL)
    assert exc.value.code == "empty_extraction"


def test_euc_kr_pages_decode_correctly():
    body = ("<html><head><meta charset='euc-kr'><title>공지사항</title></head><body><div id='content'>"
            "<h1>외국인 유학생 공지</h1><p>" + "유학생은 외국인등록증을 신청해야 합니다. " * 5 + "</p></div></body></html>")
    doc = extract_html(body.encode("euc-kr"), "https://sgee.sch.ac.kr/notice")
    assert "외국인등록증" in doc.text


def _pdf(pages: list[str]) -> bytes:
    import pymupdf as fitz

    d = fitz.open()
    for t in pages:
        p = d.new_page()
        if t:
            p.insert_text((72, 100), t)
    data = d.tobytes()
    d.close()
    return data


def test_pdf_text_extraction_with_page_references():
    data = _pdf(["First page has enough readable text for extraction.", "Second page also has readable text here."])
    doc = extract_pdf(data, "guide.pdf")
    assert "[Page 1]" in doc.text and "[Page 2]" in doc.text
    assert doc.metadata["pages"] == 2 and doc.metadata["pages_without_text"] == 0


def test_image_only_pdf_is_flagged_for_ocr_not_success():
    import pymupdf as fitz

    d = fitz.open()
    p = d.new_page()
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 50, 50))
    pix.clear_with(200)
    p.insert_image(fitz.Rect(50, 50, 300, 300), pixmap=pix)
    data = d.tobytes()
    with pytest.raises(ExtractionError) as exc:
        extract_pdf(data, "scan.pdf")
    assert exc.value.code == "needs_ocr"


def test_partially_scanned_pdf_succeeds_with_warning():
    doc = extract_pdf(_pdf(["Readable text on the first page of this file.", ""]), "mixed.pdf")
    assert doc.metadata["pages_without_text"] == 1 and doc.metadata["warnings"]


def test_corrupt_pdf():
    with pytest.raises(ExtractionError) as exc:
        extract_pdf(b"%PDF-1.4 not really a pdf", "bad.pdf")
    assert exc.value.code in ("corrupt_file", "empty_extraction", "needs_ocr")


def _docx() -> bytes:
    from docx import Document

    d = Document()
    d.core_properties.title = "Scholarship Guide"
    d.add_heading("Eligibility", level=1)
    d.add_paragraph("Students must be enrolled full time to apply for this sample scholarship.")
    d.add_paragraph("Bring documents", style="List Bullet")
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text, t.cell(0, 1).text, t.cell(1, 0).text, t.cell(1, 1).text = "Item", "Value", "GPA", "3.0"
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def test_docx_extraction_headings_lists_tables():
    doc = extract_docx(_docx(), "guide.docx")
    assert doc.title == "Scholarship Guide"
    assert "# Eligibility" in doc.text and "- Bring documents" in doc.text and "| GPA | 3.0 |" in doc.text


def test_empty_docx_rejected():
    from docx import Document

    buf = io.BytesIO()
    Document().save(buf)
    with pytest.raises(ExtractionError) as exc:
        extract_docx(buf.getvalue(), "empty.docx")
    assert exc.value.code == "empty_extraction"


def test_upload_validation():
    pdf, docx = _pdf(["Hello readable content for validation."]), _docx()
    validate_upload("pdf", "a.pdf", "application/pdf", pdf, 10_000_000)
    validate_upload("docx", "a.docx", None, docx, 10_000_000)
    for kind, name, ctype, data, code in [
        ("pdf", "a.pdf", "application/pdf", b"", "empty_file"),
        ("pdf", "a.pdf", "application/pdf", pdf, "file_too_large"),
        ("pdf", "a.exe", "application/pdf", pdf, "unsupported_file_type"),
        ("pdf", "a.pdf", "text/html", pdf, "unsupported_file_type"),
        ("pdf", "a.pdf", "application/pdf", b"<html>not a pdf</html>", "unsupported_file_type"),
        ("docx", "a.docx", None, b"PK\x03\x04garbage", "corrupt_file"),
        ("docx", "a.docx", None, b"%PDF-1.4", "unsupported_file_type"),
    ]:
        limit = 100 if code == "file_too_large" else 10_000_000
        with pytest.raises(ExtractionError) as exc:
            validate_upload(kind, name, ctype, data, limit)
        assert exc.value.code == code, (name, code, exc.value.code)


def test_manual_text_processor():
    doc = process_manual_text("제목", "  첫 줄입니다.\r\n\r\n\r\n둘째 줄입니다.  ")
    assert doc.text == "첫 줄입니다.\n\n둘째 줄입니다."
    with pytest.raises(ExtractionError):
        process_manual_text("t", "   ")


def test_kakao_redaction_removes_senders_and_pii_but_keeps_dates():
    raw = ("2025. 3. 5. 오후 3:21, 홍길동 : 장학금 신청 안내입니다.\n"
           "[김철수] [오전 9:05] 문의: 010-1234-5678 또는 foo.bar@example.com\n"
           "계좌 110-123-456789 / 주민번호 900101-1234567 / 마감 2025-03-15까지")
    clean, stats = redact_personal_info(raw)
    assert "홍길동" not in clean and "김철수" not in clean
    assert "010-1234-5678" not in clean and "foo.bar@example.com" not in clean
    assert "110-123-456789" not in clean and "900101-1234567" not in clean
    assert "장학금 신청 안내입니다." in clean and "2025-03-15" in clean
    assert stats["sender_lines"] == 2 and stats["phones"] == 1 and stats["emails"] == 1 and stats["account_numbers"] == 1
