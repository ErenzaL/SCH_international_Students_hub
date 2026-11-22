"""PDF and DOCX extractors (+ upload validation) and the manual-text processor."""
from __future__ import annotations

import io
import re
import zipfile
from datetime import UTC, datetime

from app.models.domain import ExtractedDocument
from app.services.ingestion.errors import ExtractionError
from app.services.ingestion.normalize import normalize_text

PDF_MAGIC = b"%PDF-"
MIN_CHARS_PER_TEXT_PAGE = 20
MAX_DOCX_UNCOMPRESSED = 60 * 1024 * 1024  # zip-bomb guard
CONTENT_TYPES = {
    "pdf": {"application/pdf", "application/x-pdf"},
    "docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/octet-stream"},
}


def validate_upload(kind: str, filename: str, content_type: str | None, data: bytes, max_bytes: int) -> None:
    """Validate size, extension and magic bytes. Raises ExtractionError with a clear code."""
    if not data:
        raise ExtractionError("empty_file", "The uploaded file is empty.")
    if len(data) > max_bytes:
        raise ExtractionError("file_too_large", f"File exceeds the {max_bytes // (1024 * 1024)} MB limit.")
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext != kind:
        raise ExtractionError("unsupported_file_type", f"Expected a .{kind} file but got '.{ext or '?'}'.")
    if content_type and content_type.split(";")[0].strip().lower() not in CONTENT_TYPES[kind]:
        raise ExtractionError("unsupported_file_type", f"Unexpected content type '{content_type}' for a {kind} upload.")
    if kind == "pdf" and not data.startswith(PDF_MAGIC):
        raise ExtractionError("unsupported_file_type", "File does not look like a PDF (bad header).")
    if kind == "docx":
        if not data.startswith(b"PK"):
            raise ExtractionError("unsupported_file_type", "File does not look like a DOCX (not a zip container).")
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                names = set(z.namelist())
                if "word/document.xml" not in names or "[Content_Types].xml" not in names:
                    raise ExtractionError("unsupported_file_type", "ZIP file is not a Word document.")
                if sum(i.file_size for i in z.infolist()) > MAX_DOCX_UNCOMPRESSED:
                    raise ExtractionError("file_too_large", "DOCX expands to an unreasonable size.")
        except zipfile.BadZipFile as exc:
            raise ExtractionError("corrupt_file", "The DOCX file is corrupt.") from exc


def extract_pdf(data: bytes, filename: str = "document.pdf") -> ExtractedDocument:
    try:
        import pymupdf as fitz
    except ImportError as exc:  # pragma: no cover
        raise ExtractionError("dependency_missing", "PyMuPDF is not installed.") from exc
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:  # noqa: BLE001
        raise ExtractionError("corrupt_file", f"The PDF could not be opened: {exc}") from exc
    with doc:
        if doc.needs_pass:
            raise ExtractionError("encrypted_file", "The PDF is password protected and cannot be read.")
        total_pages = doc.page_count
        if total_pages == 0:
            raise ExtractionError("empty_extraction", "The PDF has no pages.")
        parts: list[str] = []
        pages_with_text = 0
        for i, page in enumerate(doc, start=1):
            text = normalize_text(page.get_text("text"))
            if len(text) >= MIN_CHARS_PER_TEXT_PAGE:
                pages_with_text += 1
                parts.append(f"[Page {i}]\n{text}")
        meta_title = (doc.metadata or {}).get("title") or ""
        created = (doc.metadata or {}).get("creationDate") or ""
    if pages_with_text == 0:
        raise ExtractionError(
            "needs_ocr",
            f"No selectable text found in {total_pages} page(s): this looks like an image-only scan. "
            "OCR is not part of Phase 1; flagged for the later OCR workflow.",
        )
    body = "\n\n".join(parts)
    title = meta_title.strip() or filename.rsplit(".", 1)[0]
    published = None
    m = re.match(r"D:(\d{4})(\d{2})(\d{2})", created)
    if m:
        try:
            published = datetime(int(m[1]), int(m[2]), int(m[3]), tzinfo=UTC)
        except ValueError:
            published = None
    return ExtractedDocument(
        title=title, text=f"# {title}\n\n{body}", source_published_at=published,
        metadata={
            "extractor": "pymupdf", "pages": total_pages, "pages_with_text": pages_with_text,
            "pages_without_text": total_pages - pages_with_text,
            "warnings": ([f"{total_pages - pages_with_text} page(s) had no selectable text (possible scans; OCR pending)"]
                         if pages_with_text < total_pages else []),
        },
    )


def extract_docx(data: bytes, filename: str = "document.docx") -> ExtractedDocument:
    try:
        from docx import Document
        from docx.table import Table
        from docx.text.paragraph import Paragraph
    except ImportError as exc:  # pragma: no cover
        raise ExtractionError("dependency_missing", "python-docx is not installed.") from exc
    try:
        doc = Document(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        raise ExtractionError("corrupt_file", f"The DOCX could not be opened: {exc}") from exc

    lines: list[str] = []
    for child in doc.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p = Paragraph(child, doc)
            text = p.text.strip()
            if not text:
                lines.append("")
                continue
            style = (p.style.name if p.style is not None else "") or ""
            m = re.match(r"Heading (\d)", style, re.I)
            if m:
                lines.append("\n" + "#" * min(int(m.group(1)), 6) + " " + text + "\n")
            elif style.lower() == "title":
                lines.append("\n# " + text + "\n")
            elif "list" in style.lower():
                lines.append("- " + text)
            else:
                lines.append(text + "\n")
        elif tag == "tbl":
            table = Table(child, doc)
            for row in table.rows:
                cells = [re.sub(r"\s+", " ", c.text).strip().replace("|", "/") for c in row.cells]
                if any(cells):
                    lines.append("| " + " | ".join(cells) + " |")
            lines.append("")
    text = normalize_text("\n".join(lines))
    if len(text) < 20:
        raise ExtractionError("empty_extraction", "The DOCX contains no readable text.")
    title = (doc.core_properties.title or "").strip() or filename.rsplit(".", 1)[0]
    created = doc.core_properties.created
    published = created.replace(tzinfo=created.tzinfo or UTC) if created else None
    if not text.lstrip().startswith("#"):
        text = f"# {title}\n\n{text}"
    return ExtractedDocument(title=title, text=text, source_published_at=published, metadata={"extractor": "python-docx"})


def process_manual_text(title: str, text: str, source_published_at: datetime | None = None) -> ExtractedDocument:
    cleaned = normalize_text(text)
    if len(cleaned) < 10:
        raise ExtractionError("empty_extraction", "The submitted text is empty or too short.")
    return ExtractedDocument(title=title.strip(), text=cleaned, source_published_at=source_published_at,
                             metadata={"extractor": "manual"})
