"""One notice page that official-source discovery found, read by the parser that found it: the notice's own title, text and
attachments, never the site's name, menus or buttons. The generic extractor is for pages an administrator adds by hand."""
from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup

from app.models.domain import ExtractedDocument
from app.services.ingestion.errors import ExtractionError
from app.services.ingestion.extractors_html import decode_html, extract_html
from app.services.ingestion.normalize import normalize_text
from app.services.ingestion.sch_board import NoticeRef, notice_document, parse_notice


def config_for(source_kind: str, source_config: dict[str, Any], item: dict[str, Any]) -> dict[str, Any] | None:
    """What a knowledge source made from a discovered item stores, so that every later import reads it the same way."""
    if source_kind == "sch_board":
        return {"reader": "sch_notice"}
    if source_kind == "listing" and source_config.get("content_selector"):
        return {"reader": "listing_item", "title": item["title"][:300], "published_on": item.get("published_on"),
                "content_selector": source_config["content_selector"],
                **({"attachment_selector": source_config["attachment_selector"]} if source_config.get("attachment_selector") else {})}
    if source_kind == "page" and source_config.get("content_selector"):
        return {"reader": "listing_item", "title": item["title"][:300], "content_selector": source_config["content_selector"]}
    return None


def read_notice(reader: str, content: bytes, source: dict[str, Any]) -> ExtractedDocument:
    cfg, url = source.get("config") or {}, source["original_url"]
    if reader == "sch_notice":
        q = parse_qs(urlsplit(url).query)
        ref = NoticeRef(q.get("no", [""])[0], q.get("table_name", ["notice"])[0], "", url, None, None, False)
        return notice_document(parse_notice(content, ref), source.get("organization") or "SCH")
    if reader == "listing_item":
        html = decode_html(content)
        soup = BeautifulSoup(html, "lxml")
        body = soup.select_one(str(cfg.get("content_selector") or ""))
        if body is None:
            raise ExtractionError("notice_structure_changed", "The notice text was not found; the page structure may have changed.")
        doc = extract_html(str(body), url, None, 1)
        title = str(cfg.get("title") or source["title"])
        text = doc.text
        if text.startswith("# "):           # a heading the extractor took from elsewhere is replaced by the notice's title
            text = text.split("\n", 1)[1] if "\n" in text else ""
        parts = [f"# {title}", text.strip()]
        box = soup.select_one(str(cfg["attachment_selector"])) if cfg.get("attachment_selector") else None
        files = [(a.get_text(" ", strip=True)[:300], urljoin(url, str(a["href"]))) for a in box.select("a[href]")][:10] if box is not None else []
        files = [(n, u) for n, u in files if n and u.startswith(("https://", "http://"))]
        if files:
            parts.append("## 첨부파일 (Attachments)\n" + "\n".join(f"- {n}: {u}" for n, u in files))
        facts = ([f"- 작성일 (Posted): {cfg['published_on']}"] if cfg.get("published_on") else []) + [f"- 원문 (Original): {url}"]
        parts.append("## 공지 정보 (Notice details)\n" + "\n".join(facts))
        published = doc.source_published_at
        if cfg.get("published_on"):
            from datetime import UTC, datetime

            published = datetime.fromisoformat(f"{cfg['published_on']}T00:00:00+09:00").astimezone(UTC)
        meta = dict(doc.metadata, extractor="listing_item", attachments=[{"name": n, "url": u} for n, u in files])
        return ExtractedDocument(title=title, text=normalize_text("\n\n".join(p for p in parts if p)), language="ko", source_published_at=published,
                                 links=doc.links, metadata=meta)
    raise ExtractionError("unknown_reader", "This source has an unknown reader.")
