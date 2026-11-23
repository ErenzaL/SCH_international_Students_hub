"""Original documents for the Knowledge Center: what the original is (PDF / Word file / web page / text entry) and a
faithful-as-possible preview of Word files.

* The original file is read from PRIVATE storage by the API after the same publication checks as the public document
  page; the bucket is never exposed and no storage URL leaves the server.
* RAG chunks are never used to show a document: PDFs are rendered from the original file in the browser, Word files
  get a formatted preview generated from the file's own structure (below), web sources link to the original page.
* The Word preview is built element by element from python-docx objects and every text is HTML-escaped, so no markup
  from the file reaches the page (no sanitizer needed); images are embedded as data URIs (raster formats only,
  bounded size). The frontend shows it in a sandboxed iframe without scripts.
"""
from __future__ import annotations

import base64
import html
import io
from typing import Any

PDF_MIME = "application/pdf"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
WEB_SOURCE_TYPES = ("website", "sch_board")
MAX_PREVIEW_IMAGE_BYTES = 6 * 1024 * 1024          # all embedded images together
_IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/bmp", "image/webp"}


def file_kind(original: dict[str, Any]) -> str | None:
    name = str(original.get("filename") or "").lower()
    mime = str(original.get("mime_type") or "").lower()
    if name.endswith(".pdf") or mime == PDF_MIME:
        return "pdf"
    if name.endswith(".docx") or mime == DOCX_MIME:
        return "docx"
    if name.endswith((".txt", ".md")) or mime.startswith("text/"):
        return "text"
    return None


def original_info(document: dict[str, Any], source: dict[str, Any], version: dict[str, Any]) -> dict[str, Any]:
    """How the Knowledge Center shows the original of this document version."""
    f = version.get("original_file") or {}
    kind = file_kind(f) if f.get("storage_path") else None
    url = document.get("canonical_url") or source.get("original_url")
    base = f"/api/v1/knowledge/documents/{document['id']}/original"
    if kind:
        return dict(kind=kind, has_file=True, filename=f.get("filename"), size=f.get("size"),
                    mime_type=f.get("mime_type") or (PDF_MIME if kind == "pdf" else DOCX_MIME if kind == "docx" else
                                                     "text/plain"),
                    file_url=base, download_url=f"{base}?download=1",
                    preview_url=f"{base}/preview" if kind == "docx" else None, source_url=url)
    if source.get("source_type") in WEB_SOURCE_TYPES and url:
        return dict(kind="web", has_file=False, source_url=url)
    # pasted / manually entered text: the approved text IS the original
    return dict(kind="text", has_file=False, source_url=url)


# ----------------------------------------------------------------------------------------- Word preview
_CSS = """body{font:15px/1.6 system-ui,-apple-system,"Segoe UI","Noto Sans KR",sans-serif;color:#1f2328;
margin:0;padding:24px;max-width:860px}h1{font-size:1.6em}h2{font-size:1.35em}h3{font-size:1.15em}
h1,h2,h3,h4{margin:1.2em 0 .5em;line-height:1.3}p{margin:.45em 0}ul,ol{padding-left:1.6em;margin:.4em 0}
table{border-collapse:collapse;margin:.8em 0;width:100%;font-size:.95em}td,th{border:1px solid #c9ced6;
padding:4px 8px;vertical-align:top;text-align:left}img{max-width:100%;height:auto}.omitted{color:#6b7280;
font-style:italic}@media (prefers-color-scheme:dark){body{background:#0d1117;color:#e6edf3}td,th{border-color:#3d444d}}"""


def docx_preview_html(data: bytes, title: str = "") -> dict[str, Any]:
    """Formatted HTML preview of a .docx file: headings, paragraphs (bold/italic/underline), bulleted and numbered
    lists, tables (merged cells collapsed), embedded raster images. Returns {html, omitted_images, blocks}."""
    from docx import Document
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = Document(io.BytesIO(data))
    budget = {"bytes": MAX_PREVIEW_IMAGE_BYTES, "omitted": 0}

    def images(p: Any) -> str:
        out = []
        for blip in p._p.iter(qn("a:blip")):
            rid = blip.get(qn("r:embed"))
            part = p.part.related_parts.get(rid) if rid else None
            ctype = getattr(part, "content_type", "")
            blob = getattr(part, "blob", b"") or b""
            if ctype in _IMAGE_TYPES and len(blob) <= budget["bytes"]:
                budget["bytes"] -= len(blob)
                out.append(f'<img alt="" src="data:{ctype};base64,{base64.b64encode(blob).decode()}">')
            else:
                budget["omitted"] += 1
                out.append('<span class="omitted">[image not shown in the preview]</span>')
        return "".join(out)

    def runs(p: Any) -> str:
        parts = []
        for r in p.runs:
            t = html.escape(r.text or "")
            if not t:
                continue
            if r.bold:
                t = f"<strong>{t}</strong>"
            if r.italic:
                t = f"<em>{t}</em>"
            if r.underline:
                t = f"<u>{t}</u>"
            parts.append(t)
        return "".join(parts).replace("\n", "<br>") + images(p)

    def list_kind(p: Any) -> str | None:
        style = (p.style.name if p.style is not None else "") or ""
        if p._p.pPr is not None and p._p.pPr.numPr is not None:
            return "ol" if "Number" in style else "ul"
        if style.startswith("List Number"):
            return "ol"
        if style.startswith("List") or style.startswith("List Bullet"):
            return "ul"
        return None

    def heading_level(p: Any) -> int | None:
        style = (p.style.name if p.style is not None else "") or ""
        if style == "Title":
            return 1
        if style.startswith("Heading"):
            try:
                return min(max(int(style.split()[-1]), 1), 4)
            except ValueError:
                return 2
        return None

    def table(t: Any) -> str:
        rows = []
        for row in t.rows:
            cells, seen = [], set()
            for cell in row.cells:
                if id(cell._tc) in seen:        # horizontally merged cells repeat the same element
                    continue
                seen.add(id(cell._tc))
                inner = "".join(f"<p>{runs(cp)}</p>" for cp in cell.paragraphs if runs(cp)) or "&nbsp;"
                cells.append(f"<td>{inner}</td>")
            rows.append(f"<tr>{''.join(cells)}</tr>")
        return f"<table>{''.join(rows)}</table>"

    body: list[str] = []
    open_list: str | None = None
    blocks = 0
    for child in doc.element.body.iterchildren():
        if child.tag == qn("w:p"):
            p = Paragraph(child, doc)
            content = runs(p)
            kind = list_kind(p)
            if open_list and kind != open_list:
                body.append(f"</{open_list}>")
                open_list = None
            if not content.strip():
                continue
            blocks += 1
            level = heading_level(p)
            if kind:
                if open_list is None:
                    body.append(f"<{kind}>")
                    open_list = kind
                body.append(f"<li>{content}</li>")
            elif level:
                body.append(f"<h{level}>{content}</h{level}>")
            else:
                body.append(f"<p>{content}</p>")
        elif child.tag == qn("w:tbl"):
            if open_list:
                body.append(f"</{open_list}>")
                open_list = None
            blocks += 1
            body.append(table(Table(child, doc)))
    if open_list:
        body.append(f"</{open_list}>")
    page = (f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,'
            f'initial-scale=1"><title>{html.escape(title)}</title><style>{_CSS}</style></head><body>'
            f"{''.join(body)}</body></html>")
    return dict(html=page, omitted_images=budget["omitted"], blocks=blocks)
