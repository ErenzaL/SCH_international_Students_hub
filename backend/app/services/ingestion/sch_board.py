"""Connector for the SCH Global Education & Exchange (sgee.sch.ac.kr) notice boards.

The board is a list page (``notice01.php?table_name=...``) linking to individual notices
(``notice01.php?admin_mode=read&no=<id>&table_name=...``). Each notice becomes its own
source_document (identity = ``<table_name>:<no>``); the listing page itself is never indexed.

Structure observed on 2026-11-22:
  list   : <td class="subject"><a href="...admin_mode=read&no=6708...">title</a></td>, then author / date cells;
           pinned rows show <span class="ico">공지</span> in the number cell
  notice : <h3 class="v_tit">title</h3>; table.board-view with 작성일 / 작성자 / 첨부파일 rows;
           body in <td class="view_td">
If the markup changes, parsing fails loudly with ``board_structure_changed`` (never silently empty).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag

from app.models.domain import ExtractedDocument
from app.services.ingestion.errors import ExtractionError
from app.services.ingestion.extractors_html import _blocks, decode_html
from app.services.ingestion.normalize import normalize_text

KST = timezone(timedelta(hours=9))
_DATE = re.compile(r"(20\d{2})\s*[.\-/]\s*(\d{1,2})\s*[.\-/]\s*(\d{1,2})")
MIN_BODY_CHARS = 30


@dataclass
class NoticeRef:
    notice_no: str
    table: str
    title: str
    url: str            # canonical notice URL
    posted: str | None  # YYYY-MM-DD as shown in the list
    author: str | None
    pinned: bool


@dataclass
class Notice:
    ref: NoticeRef
    title: str
    posted_at: datetime | None
    author: str | None
    body_text: str
    attachments: list[dict[str, str]] = field(default_factory=list)
    images: list[str] = field(default_factory=list)
    links: list[dict[str, str]] = field(default_factory=list)
    view_count: int | None = None


def is_sch_board_url(url: str) -> bool:
    p = urlsplit(url)
    return (p.hostname or "").endswith("sch.ac.kr") and p.path.endswith("notice01.php")


def board_table(url: str) -> str:
    return (parse_qs(urlsplit(url).query).get("table_name") or ["notice"])[0]


def notice_url(base: str, table: str, no: str) -> str:
    """Canonical notice URL: only the parameters that identify the notice (no paging/search state)."""
    p = urlsplit(base)
    q = urlencode({"admin_mode": "read", "no": no, "table_name": table})
    return urlunsplit((p.scheme, p.netloc, p.path, q, ""))


def page_url(list_url: str, page: int) -> str:
    p = urlsplit(list_url)
    q = parse_qs(p.query, keep_blank_values=True)
    q["page"] = [str(page)]
    return urlunsplit((p.scheme, p.netloc, p.path, urlencode(q, doseq=True), ""))


def _date(text: str | None) -> str | None:
    m = _DATE.search(text or "")
    if not m:
        return None
    try:
        return datetime(int(m[1]), int(m[2]), int(m[3])).date().isoformat()
    except ValueError:
        return None


def parse_listing(html: bytes | str, list_url: str) -> list[NoticeRef]:
    text = html if isinstance(html, str) else decode_html(html)
    soup = BeautifulSoup(text, "lxml")
    table = board_table(list_url)
    refs: list[NoticeRef] = []
    seen: set[str] = set()
    for a in soup.select("td.subject a[href]"):
        href = urljoin(list_url, str(a["href"]))
        q = parse_qs(urlsplit(href).query)
        if (q.get("admin_mode") or [""])[0] != "read" or not q.get("no"):
            continue
        no = q["no"][0]
        if not no.isdigit() or no in seen:
            continue
        seen.add(no)
        tr = a.find_parent("tr")
        cells = tr.find_all("td") if isinstance(tr, Tag) else []
        first = cells[0] if cells else None
        pinned = bool(first and first.select_one("span.ico"))
        author = cells[2].get_text(" ", strip=True) if len(cells) > 2 else None
        posted = _date(cells[3].get_text(" ", strip=True)) if len(cells) > 3 else None
        refs.append(NoticeRef(notice_no=no, table=(q.get("table_name") or [table])[0], title=a.get_text(" ", strip=True),
                              url=notice_url(list_url, (q.get("table_name") or [table])[0], no), posted=posted,
                              author=author or None, pinned=pinned))
    if not refs and soup.select_one("table") is not None and "admin_mode=read" not in text:
        raise ExtractionError("board_structure_changed",
                              "No notice links were found on the board page; the page structure may have changed.")
    return refs


def _row_value(table: Tag, label: str) -> Tag | None:
    for th in table.find_all("th"):
        if th.get_text(strip=True).replace(" ", "") == label:
            td = th.find_next_sibling("td")
            if isinstance(td, Tag):
                return td
    return None


def parse_notice(html: bytes | str, ref: NoticeRef) -> Notice:
    text = html if isinstance(html, str) else decode_html(html)
    soup = BeautifulSoup(text, "lxml")
    title_el = soup.select_one(".view_tit .v_tit") or soup.select_one("h3.v_tit")
    meta = soup.select_one("table.board-view")
    body_el = soup.select_one("td.view_td")
    if title_el is None or body_el is None or meta is None:
        raise ExtractionError("board_structure_changed",
                              "The notice page does not have the expected title/body layout; structure may have changed.")
    title = re.sub(r"\s+", " ", title_el.get_text(" ", strip=True)) or ref.title
    date_td = _row_value(meta, "작성일")
    posted = _date(date_td.get_text(" ", strip=True) if date_td else None) or ref.posted
    author_td = _row_value(meta, "작성자")
    author = author_td.get_text(" ", strip=True) if author_td else ref.author

    attachments: list[dict[str, str]] = []
    files_td = _row_value(meta, "첨부파일")
    if files_td is not None:
        for a in files_td.select("a[href]"):
            name = a.get_text(" ", strip=True)
            if name:
                attachments.append({"name": name[:300], "url": urljoin(ref.url, str(a["href"]))})

    # editor artifacts (Hancom "hwpjson" comments/containers), scripts and styles are not content
    for junk in body_el.select("script, style, noscript, #hwpEditorBoardContent, .hwp_editor_board_content"):
        junk.decompose()
    images = [urljoin(ref.url, str(i["src"])) for i in body_el.select("img[src]")][:30]
    links: list[dict[str, str]] = []
    out: list[str] = []
    _blocks(body_el, ref.url, links, out)
    body = normalize_text("\n".join(out))
    views = None
    vc = soup.select_one("p.click_count")
    if vc:
        m = re.search(r"(\d[\d,]*)", vc.get_text())
        views = int(m.group(1).replace(",", "")) if m else None
    posted_at = None
    if posted:
        y, mo, d = map(int, posted.split("-"))
        posted_at = datetime(y, mo, d, tzinfo=KST).astimezone(UTC)
    return Notice(ref=ref, title=title, posted_at=posted_at, author=author, body_text=body,
                  attachments=attachments, images=images, links=links, view_count=views)


def notice_document(n: Notice, organization: str) -> ExtractedDocument:
    """Render one notice as stored text: body first (best first chunk / excerpt), then attachments, then the
    notice facts (date, author, number, original URL) so they stay searchable and citable."""
    parts = [f"# {n.title}"]
    warnings: list[str] = []
    if n.body_text:
        parts.append(n.body_text)  # never drop text, however short
    if len(n.body_text) < MIN_BODY_CHARS:
        warnings.append("The notice body has little or no text (it is probably an image or relies on the "
                        "attachment). Review the attachments/images and add the content manually if needed.")
    if n.attachments:
        parts.append("## 첨부파일 (Attachments)\n" + "\n".join(f"- {a['name']}: {a['url']}" for a in n.attachments))
    if n.images and len(n.body_text) < MIN_BODY_CHARS:
        parts.append("## 이미지 (Images in the notice)\n" + "\n".join(f"- {u}" for u in n.images[:10]))
    facts = []
    if n.posted_at:
        facts.append(f"- 작성일 (Posted): {n.posted_at.astimezone(KST).date().isoformat()}")
    if n.author:
        facts.append(f"- 작성자 (Author): {n.author}")
    facts.append(f"- 공지 번호 (Notice no.): {n.ref.notice_no}")
    facts.append(f"- 원문 (Original): {n.ref.url}")
    parts.append("## 공지 정보 (Notice details)\n" + "\n".join(facts))
    meta: dict[str, Any] = {
        "extractor": "sch_board", "notice_no": n.ref.notice_no, "board_table": n.ref.table, "author": n.author,
        "pinned": n.ref.pinned, "attachments": n.attachments, "images": n.images, "view_count": n.view_count,
        "organization": organization, "warnings": warnings, "body_chars": len(n.body_text),
    }
    return ExtractedDocument(title=n.title, text=normalize_text("\n\n".join(parts)), language="ko",
                             source_published_at=n.posted_at, links=n.links, metadata=meta)
