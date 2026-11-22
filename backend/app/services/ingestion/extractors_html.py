"""HTML extractor: Trafilatura first (boilerplate removal), BeautifulSoup fallback.

Preserves page title, headings, tables (as pipe rows), lists and links (as markdown).
Raises ExtractionError('empty_extraction') instead of returning empty content.
"""
from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup, NavigableString, Tag, UnicodeDammit

from app.models.domain import ExtractedDocument
from app.services.ingestion.errors import ExtractionError
from app.services.ingestion.normalize import normalize_text

log = logging.getLogger("app.extract.html")

_DROP_TAGS = ["script", "style", "noscript", "template", "iframe", "svg", "form", "nav", "header", "footer", "aside", "button"]
_BOILERPLATE_HINT = re.compile(r"(^|[-_ ])(nav|menu|gnb|lnb|snb|breadcrumb|footer|sidebar|banner|popup|sns|share|skip)([-_ ]|$)", re.I)
_MAIN_SELECTORS = ["main", "article", "[role=main]", "#content", "#contents", "#container", ".contents", ".content", ".sub_content", "#bo_v", ".board"]


def decode_html(content: bytes, declared_encoding: str | None = None) -> str:
    """Decode bytes robustly (many Korean sites still serve EUC-KR/CP949)."""
    hints = [declared_encoding] if declared_encoding else []
    dammit = UnicodeDammit(content, known_definite_encodings=hints, is_html=True)
    if dammit.unicode_markup is None:
        raise ExtractionError("decode_error", "Could not decode the page text.")
    return dammit.unicode_markup


def _page_title(soup: BeautifulSoup) -> str:
    for sel in ("meta[property='og:title']", "meta[name='twitter:title']"):
        tag = soup.select_one(sel)
        if tag and tag.get("content"):
            return str(tag["content"]).strip()
    if soup.title and soup.title.get_text(strip=True):
        return soup.title.get_text(" ", strip=True)
    h1 = soup.find("h1")
    return h1.get_text(" ", strip=True) if h1 else ""


def _cell_text(cell: Tag) -> str:
    return re.sub(r"\s+", " ", cell.get_text(" ", strip=True)).replace("|", "/")


def _table_md(table: Tag) -> str:
    rows = []
    for tr in table.find_all("tr"):
        cells = [_cell_text(c) for c in tr.find_all(["th", "td"], recursive=False) or tr.find_all(["th", "td"])]
        if any(cells):
            rows.append("| " + " | ".join(cells) + " |")
    return "\n".join(rows)


def _inline(node: Tag, base_url: str, links: list[dict[str, str]]) -> str:
    out: list[str] = []
    for child in node.children:
        if isinstance(child, NavigableString):
            out.append(str(child))
        elif isinstance(child, Tag):
            if child.name == "br":
                out.append("\n")
            elif child.name == "a" and child.get("href"):
                text = re.sub(r"\s+", " ", child.get_text(" ", strip=True))
                href = str(child["href"]).strip()
                if text and href and not href.lower().startswith(("javascript:", "#", "mailto:", "tel:")):
                    absolute = urljoin(base_url, href)
                    links.append({"text": text, "href": absolute})
                    out.append(f"[{text}]({absolute})")
                else:
                    out.append(text)
            else:
                out.append(_inline(child, base_url, links))
    return "".join(out)


_INLINE = {"a", "strong", "b", "em", "i", "u", "small", "label", "mark", "sup", "sub", "abbr", "time", "code", "span"}
_BLOCKISH = ["p", "h1", "h2", "h3", "h4", "h5", "h6", "table", "ul", "ol", "div", "section", "pre", "blockquote"]


def _blocks(node: Tag, base_url: str, links: list[dict[str, str]], out: list[str]) -> None:
    pending: list[Tag | NavigableString] = []  # inline run (text + inline tags) between block elements

    def flush_inline() -> None:
        if not pending:
            return
        holder = BeautifulSoup("<p></p>", "lxml").p
        assert holder is not None
        for n in pending:
            holder.append(n.extract() if hasattr(n, "extract") else n)
        text = re.sub(r"[ \t]+", " ", _inline(holder, base_url, links)).strip()
        if text:
            out.append("\n" + text + "\n")
        pending.clear()

    for child in list(node.children):
        if isinstance(child, NavigableString):
            if str(child).strip():
                pending.append(child)
            continue
        if not isinstance(child, Tag):
            continue
        name = child.name
        if name in _INLINE and not child.find(_BLOCKISH):
            pending.append(child)
            continue
        flush_inline()
        if name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            text = re.sub(r"\s+", " ", _inline(child, base_url, links)).strip()
            if text:
                out.append("\n" + "#" * int(name[1]) + " " + text + "\n")
        elif name == "table":
            md = _table_md(child)
            if md:
                out.append("\n" + md + "\n")
        elif name in ("ul", "ol"):
            for i, li in enumerate(child.find_all("li", recursive=False), 1):
                text = re.sub(r"[ \t]+", " ", _inline(li, base_url, links)).strip()
                if text:
                    out.append(("- " if name == "ul" else f"{i}. ") + text.replace("\n", " "))
            out.append("")
        elif name in ("p", "pre", "blockquote", "dd", "dt", "figcaption", "caption"):
            text = re.sub(r"[ \t]+", " ", _inline(child, base_url, links)).strip()
            if text:
                out.append("\n" + text + "\n")
        elif name == "br":
            out.append("")
        elif child.find(_BLOCKISH):
            _blocks(child, base_url, links, out)
        else:
            text = re.sub(r"[ \t]+", " ", _inline(child, base_url, links)).strip()
            if text:
                out.append("\n" + text + "\n")
    flush_inline()


def _soup_fallback(html: str, base_url: str) -> tuple[str, list[dict[str, str]]]:
    soup = BeautifulSoup(html, "lxml")
    for t in soup(_DROP_TAGS):
        t.decompose()
    for t in soup.find_all(True):
        if t.attrs is None:  # already decomposed
            continue
        ident = " ".join([str(t.get("id", ""))] + list(t.get("class", []) or []))
        if ident and _BOILERPLATE_HINT.search(ident) and t.name not in ("html", "body"):
            t.decompose()
    root: Tag | None = None
    for sel in _MAIN_SELECTORS:
        cand = soup.select_one(sel)
        if cand and len(cand.get_text(" ", strip=True)) > 80:
            root = cand
            break
    root = root or soup.body or soup
    links: list[dict[str, str]] = []
    out: list[str] = []
    _blocks(root if root is not soup else soup, base_url, links, out)
    return "\n".join(out), links


def _published_at(html: str, url: str) -> datetime | None:
    try:
        import trafilatura

        meta = trafilatura.extract_metadata(html, default_url=url)
        if meta and meta.date:
            return datetime.fromisoformat(meta.date).replace(tzinfo=UTC)
    except Exception:  # noqa: BLE001 - metadata is best-effort only
        return None
    return None


_TAG_LEFTOVER = re.compile(r"<[^>\n]{1,300}>")


def _clean_leftovers(text: str) -> str:
    """Remove raw HTML tags that leaked into text (malformed markup) and tidy the result."""
    return normalize_text(_TAG_LEFTOVER.sub(" ", text))


def _body_chars(text: str, title: str) -> int:
    """Readable characters excluding the page title and markdown markers (guards against title-only 'content')."""
    body = re.sub(r"[#*|\-\s]+", " ", text).strip()
    if title:
        body = body.replace(title, " ", 1)
    return len(body.strip())


def extract_html(content: bytes | str, url: str, declared_encoding: str | None = None, min_chars: int = 40) -> ExtractedDocument:
    html = content if isinstance(content, str) else decode_html(content, declared_encoding)
    if not html.strip():
        raise ExtractionError("empty_extraction", "The page body was empty.")
    soup = BeautifulSoup(html, "lxml")
    title = _page_title(soup)

    text = ""
    links: list[dict[str, str]] = []
    method = "trafilatura"
    try:
        import trafilatura

        extracted = trafilatura.extract(
            html, url=url, output_format="markdown", include_tables=True, include_links=True,
            include_comments=False, favor_recall=True, deduplicate=False,
        )
        text = extracted or ""
    except Exception as exc:  # noqa: BLE001
        log.warning("trafilatura failed (%s); using fallback", type(exc).__name__)
    text = _clean_leftovers(normalize_text(text))
    if _body_chars(text, title) < min_chars:
        method = "beautifulsoup"
        fb, links = _soup_fallback(html, url)
        fb = _clean_leftovers(normalize_text(fb))
        if _body_chars(fb, title) > _body_chars(text, title):
            text = fb
    body_chars = _body_chars(text, title)
    if body_chars < min_chars:
        raise ExtractionError(
            "empty_extraction",
            f"No readable main content could be extracted ({body_chars} characters; minimum {min_chars}). "
            "The page may be rendered by JavaScript or blocked. Use manual official-content import instead.",
        )
    if title and not text.lstrip().startswith("#"):
        text = f"# {title}\n\n{text}"
    if not links:
        links = [{"text": m.group(1), "href": m.group(2)} for m in re.finditer(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", text)][:200]
    return ExtractedDocument(
        title=title or url, text=text, links=links[:200], source_published_at=_published_at(html, url),
        metadata={"extractor": method, "html_chars": len(html)},
    )
