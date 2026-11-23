"""File extractors (PDF / DOCX / TXT / Markdown), upload validation and the manual-text processor.

Every extractor returns normalized, markdown-ish text that keeps structure the chunker understands:
``#`` headings, ``[Page N]`` markers, list lines and ``| a | b |`` table rows.
"""
from __future__ import annotations

import hashlib
import io
import re
import zipfile
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from app.models.domain import ExtractedDocument
from app.services.ingestion.errors import ExtractionError
from app.services.ingestion.normalize import normalize_text

PDF_MAGIC = b"%PDF-"
MIN_CHARS_PER_TEXT_PAGE = 20
# PyMuPDF's find_tables() costs ~230 MB on its first call and its CPU time grows steeply with the number of vector
# line segments on a page (HWP-exported Korean PDFs draw tables/underlines as thousands of tiny lines). On a 512 MB
# / 0.1 CPU instance that crashed or stalled ingestion, so table detection is opt-in and budgeted per page.
TABLE_MODES = ("off", "auto")
DEFAULT_MAX_TABLE_ITEMS = 1500   # drawing items per page above which find_tables() is skipped (auto mode)
_HANGUL_RE = re.compile(r"[\uac00-\ud7a3]")
# C0 control characters other than \t \n. InDesign exports put an invisible "indent to here" mark (\x07) after list
# markers ("- \x07text"); it carries no content.
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
MAX_DOCX_UNCOMPRESSED = 60 * 1024 * 1024  # zip-bomb guard

# kind -> (allowed extensions, allowed declared content types)
FILE_KINDS: dict[str, tuple[tuple[str, ...], set[str]]] = {
    "pdf": (("pdf",), {"application/pdf", "application/x-pdf", "application/octet-stream"}),
    "docx": (("docx",), {"application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                         "application/octet-stream", "application/zip"}),
    "text_file": (("txt", "md", "markdown"), {"text/plain", "text/markdown", "text/x-markdown",
                                              "application/octet-stream"}),
    "screenshot": (("png", "jpg", "jpeg", "webp"), {"image/png", "image/jpeg", "image/jpg", "image/webp",
                                                    "application/octet-stream"}),
}
IMAGE_MIME = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_extension(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def sniff_image(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def validate_upload(kind: str, filename: str, content_type: str | None, data: bytes, max_bytes: int) -> str:
    """Validate size, extension, declared type and magic bytes. Returns the verified MIME type."""
    if kind not in FILE_KINDS:
        raise ExtractionError("unsupported_file_type", f"Uploads are not accepted for '{kind}' sources.")
    if not data:
        raise ExtractionError("empty_file", "The uploaded file is empty.")
    if len(data) > max_bytes:
        raise ExtractionError("file_too_large", f"File exceeds the {max_bytes // (1024 * 1024)} MB limit.")
    exts, ctypes = FILE_KINDS[kind]
    ext = file_extension(filename)
    if ext not in exts:
        raise ExtractionError("unsupported_file_type",
                              f"Expected a {' / '.join('.' + e for e in exts)} file but got '.{ext or '?'}'.")
    declared = (content_type or "").split(";")[0].strip().lower()
    if declared and declared not in ctypes:
        raise ExtractionError("unsupported_file_type", f"Unexpected content type '{content_type}' for this upload.")
    if kind == "pdf":
        if not data.startswith(PDF_MAGIC):
            raise ExtractionError("unsupported_file_type", "File does not look like a PDF (bad header).")
        return "application/pdf"
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
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if kind == "text_file":
        if b"\x00" in data[:8192]:
            raise ExtractionError("unsupported_file_type", "File contains binary data; only plain text is accepted.")
        return "text/markdown" if ext in ("md", "markdown") else "text/plain"
    # screenshot
    sniffed = sniff_image(data)
    if sniffed is None:
        raise ExtractionError("unsupported_file_type", "File is not a PNG, JPEG or WEBP image.")
    if IMAGE_MIME[ext] != sniffed:
        raise ExtractionError("unsupported_file_type", f"File content is {sniffed} but the name ends in .{ext}.")
    return sniffed


# ---------------------------------------------------------------------------- PDF
def _md_table(rows: list[list[Any]]) -> str:
    out = []
    for row in rows:
        cells = [re.sub(r"\s+", " ", str(c or "")).strip().replace("|", "/") for c in row]
        if any(cells):
            out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


def _inside(bbox: tuple[float, float, float, float], area: tuple[float, float, float, float]) -> bool:
    x0, y0, x1, y1 = bbox
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    return area[0] <= cx <= area[2] and area[1] <= cy <= area[3]


def _drawing_items(page: Any) -> int:
    """Number of vector drawing operations on a page (cheap: ~0.15 s / 200k segments, no table analysis)."""
    try:
        return sum(len(d.get("items") or ()) for d in page.get_cdrawings())
    except Exception:  # noqa: BLE001 - older PyMuPDF
        return 0


def _image_coverage(page: Any) -> float:
    """Fraction of the page area covered by images (1.0 = a full-page scan)."""
    try:
        area = abs(page.rect)
        if not area:
            return 0.0
        covered = 0.0
        for info in page.get_image_info():
            x0, y0, x1, y1 = info.get("bbox") or (0, 0, 0, 0)
            covered += max(0.0, x1 - x0) * max(0.0, y1 - y0)
        return min(1.0, covered / area)
    except Exception:  # noqa: BLE001
        return 0.0


def _pdf_page_text(page: Any, body_size: float, *, tables_enabled: bool = False) -> tuple[str, int]:
    """Text of one page with detected headings (# / ##) and - only when enabled - tables (| a | b |)."""
    tables: list[tuple[tuple[float, float, float, float], str]] = []
    if tables_enabled:
        try:
            found = page.find_tables()
            for t in found.tables:
                md = _md_table(t.extract())
                if md.count("\n") >= 1:  # at least two rows: a real table, not a framed paragraph
                    tables.append((tuple(t.bbox), md))
        except Exception:  # noqa: BLE001 - table detection is best effort (older PyMuPDF / odd layouts)
            tables = []

    items: list[tuple[float, str]] = [(bbox[1], md) for bbox, md in tables]
    data = page.get_text("dict")
    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        bbox = tuple(block["bbox"])
        if any(_inside(bbox, area) for area, _ in tables):
            continue
        lines: list[str] = []
        for line in block.get("lines", []):
            spans = [s for s in line.get("spans", []) if s.get("text", "").strip()]
            if not spans:
                continue
            text = "".join(s["text"] for s in line.get("spans", [])).strip()
            size = max(s.get("size", 0) for s in spans)
            bold = all((s.get("flags", 0) & 16) for s in spans)
            short = len(text) <= 120 and not text.endswith((".", ",", "다.", "요."))
            if body_size and short and size >= body_size * 1.7:
                lines.append(f"\n# {text}\n")
            elif body_size and short and (size >= body_size * 1.2 or (bold and size >= body_size * 1.05 and len(text) <= 80)):
                lines.append(f"\n## {text}\n")
            else:
                lines.append(text)
        if lines:
            items.append((bbox[1], "\n".join(lines)))
    items.sort(key=lambda x: x[0])
    return normalize_text("\n\n".join(t for _, t in items)), len(tables)


def _strip_controls(text: str) -> str:
    return _CONTROL_RE.sub("", text)


def _body_font_size(doc: Any, max_pages: int | None = None) -> float:
    """Body text size = the character-weighted most common span size over ALL pages (``max_pages`` only for tests).

    Estimating it from the first pages alone is wrong for documents whose front matter is set in small type: the
    2021 NIIED guidebook's pages 14-18 (embassy contact tables, 6.2 pt) dominated the first 20 pages, so the real 9.4 pt
    body text was >= 1.2x the estimate and 82 % of it was tagged as '##' headings (then lost by the chunker).
    """
    sizes: Counter[float] = Counter()
    for i, page in enumerate(doc):
        if max_pages is not None and i >= max_pages:
            break
        for block in page.get_text("dict").get("blocks", []):
            for line in block.get("lines", []):
                for s in line.get("spans", []):
                    if s.get("text", "").strip():
                        sizes[round(float(s.get("size", 0)), 1)] += len(s["text"])
    return sizes.most_common(1)[0][0] if sizes else 0.0


def open_pdf(data: bytes) -> Any:
    try:
        import pymupdf as fitz
    except ImportError as exc:  # pragma: no cover
        raise ExtractionError("dependency_missing", "PyMuPDF is not installed.") from exc
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:  # noqa: BLE001
        raise ExtractionError("corrupt_file", f"The PDF could not be opened: {exc}") from exc
    if doc.needs_pass:
        doc.close()
        raise ExtractionError("encrypted_file", "The PDF is password protected and cannot be read.")
    if doc.page_count == 0:
        doc.close()
        raise ExtractionError("empty_extraction", "The PDF has no pages.")
    return doc


def extract_pdf(data: bytes, filename: str = "document.pdf", *, table_mode: str = "off",
                max_table_items: int = DEFAULT_MAX_TABLE_ITEMS, max_pages: int | None = None,
                on_page: Any = None) -> ExtractedDocument:
    """Text layer of a PDF (Korean included), page by page. ``on_page(done, total)`` reports progress.

    Pages are classified so a document without usable text gets an actionable diagnosis: scanned (images), text
    drawn as vector outlines (common in HWP exports), or genuinely empty.
    """
    if table_mode not in TABLE_MODES:
        table_mode = "off"
    doc = open_pdf(data)
    with doc:
        total_pages = doc.page_count
        if max_pages and total_pages > max_pages:
            raise ExtractionError("too_many_pages", f"The PDF has {total_pages} pages; the limit is {max_pages}. "
                                                    "Split it into smaller files and upload them separately.")
        body = _body_font_size(doc)
        parts: list[str] = []
        pages_with_text = 0
        table_count = 0
        tables_skipped = 0
        empty_pages: list[int] = []
        scanned_pages: list[int] = []
        vector_pages: list[int] = []
        hangul = chars = 0
        for i, page in enumerate(doc, start=1):
            items = _drawing_items(page)
            use_tables = table_mode == "auto" and items <= max_table_items
            if table_mode == "auto" and not use_tables:
                tables_skipped += 1
            text, n_tables = _pdf_page_text(page, body, tables_enabled=use_tables)
            if len(text) < MIN_CHARS_PER_TEXT_PAGE:  # fall back to the plain text layer
                text = normalize_text(page.get_text("text"))
            text = _strip_controls(text)
            if len(text) >= MIN_CHARS_PER_TEXT_PAGE:
                pages_with_text += 1
                table_count += n_tables
                chars += len(text)
                hangul += len(_HANGUL_RE.findall(text))
                parts.append(f"[Page {i}]\n{text}")
            else:
                empty_pages.append(i)
                if _image_coverage(page) >= 0.5:
                    scanned_pages.append(i)
                elif items >= 500:
                    vector_pages.append(i)
            if on_page:
                on_page(i, total_pages)
        meta = doc.metadata or {}
    if pages_with_text == 0:
        if scanned_pages and len(scanned_pages) >= len(vector_pages):
            why = (f"this is a scanned PDF ({len(scanned_pages)} of {total_pages} page(s) are images without a text "
                   "layer)")
        elif vector_pages:
            why = (f"the text is drawn as vector shapes on {len(vector_pages)} of {total_pages} page(s) (common for "
                   "HWP/PDF exports), so there is no selectable text")
        else:
            why = f"no selectable text was found in {total_pages} page(s)"
        raise ExtractionError(
            "needs_ocr",
            f"OCR needed: {why}. Configure OCR (OCR_PROVIDER), upload screenshots of the pages, or paste the text "
            "for review.",
        )
    title = (meta.get("title") or "").strip() or filename.rsplit(".", 1)[0]
    published = None
    m = re.match(r"D:(\d{4})(\d{2})(\d{2})", meta.get("creationDate") or "")
    if m:
        try:
            published = datetime(int(m[1]), int(m[2]), int(m[3]), tzinfo=UTC)
        except ValueError:
            published = None
    warnings = []
    if empty_pages:
        kind = ("scanned images" if scanned_pages else "vector-drawn text" if vector_pages else "no selectable text")
        warnings.append(f"{len(empty_pages)} page(s) had no selectable text ({kind}; pages "
                        f"{', '.join(map(str, empty_pages[:20]))}); they were not extracted - OCR or manual text is "
                        "needed for them.")
    if tables_skipped:
        warnings.append(f"Table layout detection was skipped on {tables_skipped} page(s) with very many drawn lines; "
                        "table text is kept as plain lines.")
    return ExtractedDocument(
        title=title, text=f"# {title}\n\n" + "\n\n".join(parts), source_published_at=published,
        metadata={
            "extractor": "pymupdf", "pages": total_pages, "pages_with_text": pages_with_text,
            "pages_without_text": total_pages - pages_with_text, "empty_pages": empty_pages[:200],
            "scanned_pages": scanned_pages[:200], "vector_text_pages": vector_pages[:200],
            "needs_ocr_pages": len(empty_pages), "chars": chars,
            "hangul_ratio": round(hangul / chars, 3) if chars else 0.0, "table_mode": table_mode,
            "tables": table_count, "pdf_author": (meta.get("author") or "")[:200] or None, "warnings": warnings,
        },
    )


def iter_pdf_pages_png(data: bytes, max_pages: int, dpi: int = 200) -> Any:
    """PNG renderings of the first pages, ONE AT A TIME (an A4 page at 200 dpi is ~11 MB raw; holding all pages
    of a scan in memory at once is what a 512 MB instance cannot afford)."""
    doc = open_pdf(data)
    with doc:
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            pix = page.get_pixmap(dpi=dpi)
            png = pix.tobytes("png")
            del pix
            yield png


def render_pdf_pages(data: bytes, max_pages: int, dpi: int = 200) -> list[bytes]:
    """PNG renderings of the first pages (kept for callers that need a list; prefer ``iter_pdf_pages_png``)."""
    return list(iter_pdf_pages_png(data, max_pages, dpi))


# --------------------------------------------------------------------------- DOCX
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
    tables = 0
    for child in doc.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p = Paragraph(child, doc)
            text = p.text.strip()
            if not text:
                lines.append("")
                continue
            style = (p.style.name if p.style is not None else "") or ""
            numbered = child.find(".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}numPr") is not None
            m = re.match(r"Heading (\d)", style, re.I)
            if m:
                lines.append("\n" + "#" * min(int(m.group(1)), 6) + " " + text + "\n")
            elif style.lower() == "title":
                lines.append("\n# " + text + "\n")
            elif "list" in style.lower() or numbered:
                lines.append(("1. " if "number" in style.lower() else "- ") + text)
            else:
                lines.append(text + "\n")
        elif tag == "tbl":
            table = Table(child, doc)
            tables += 1
            for row in table.rows:
                cells = [re.sub(r"\s+", " ", c.text).strip().replace("|", "/") for c in row.cells]
                if any(cells):
                    lines.append("| " + " | ".join(cells) + " |")
            lines.append("")
    text = normalize_text("\n".join(lines))
    if len(text) < 20:
        raise ExtractionError("empty_extraction", "The DOCX contains no readable text.")
    props = doc.core_properties
    title = (props.title or "").strip() or filename.rsplit(".", 1)[0]
    created = props.created
    published = created.replace(tzinfo=created.tzinfo or UTC) if created else None
    if not text.lstrip().startswith("#"):
        text = f"# {title}\n\n{text}"
    return ExtractedDocument(title=title, text=text, source_published_at=published, metadata={
        "extractor": "python-docx", "tables": tables, "docx_author": (props.author or "")[:200] or None,
        "warnings": []})


# --------------------------------------------------------------------- TXT / MD
def decode_text_file(data: bytes) -> tuple[str, str]:
    """Decode UTF-8 (with/without BOM), UTF-16 (BOM) or Korean legacy encodings. Returns (text, encoding)."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16"), "utf-16"
    for enc in ("utf-8-sig", "cp949", "euc-kr"):
        try:
            return data.decode(enc), "utf-8" if enc == "utf-8-sig" else enc
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace"), "utf-8 (with replacements)"


def extract_text_file(data: bytes, filename: str = "document.txt") -> ExtractedDocument:
    raw, encoding = decode_text_file(data)
    is_md = file_extension(filename) in ("md", "markdown")
    text = raw
    if is_md:
        text = re.sub(r"^(#{1,6})([^#\s])", r"\1 \2", text, flags=re.M)  # "##Title" -> "## Title"
        text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)           # images -> alt text
    text = normalize_text(text)
    if len(text) < 10:
        raise ExtractionError("empty_extraction", "The text file is empty or too short.")
    m = re.search(r"^#\s+(.+)$", text, re.M)
    title = (m.group(1).strip() if m else "") or filename.rsplit(".", 1)[0]
    if not text.lstrip().startswith("#"):
        text = f"# {title}\n\n{text}"
    warnings = [f"Decoded as {encoding}; check Korean characters."] if encoding not in ("utf-8", "utf-16") else []
    return ExtractedDocument(title=title, text=text, metadata={
        "extractor": "markdown" if is_md else "plain-text", "encoding": encoding, "warnings": warnings})


# ----------------------------------------------------------------- manual text
def process_manual_text(title: str, text: str, source_published_at: datetime | None = None) -> ExtractedDocument:
    cleaned = normalize_text(text)
    if len(cleaned) < 10:
        raise ExtractionError("empty_extraction", "The submitted text is empty or too short.")
    return ExtractedDocument(title=title.strip(), text=cleaned, source_published_at=source_published_at,
                             metadata={"extractor": "manual", "warnings": []})
