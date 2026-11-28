"""Official-source connectors: turn one configured source into a list of discovered entries.

Every request goes through the existing ``GuardedFetcher`` (domain allowlist incl. admin-managed domains, SSRF checks
on every redirect, robots.txt, response size and time limits, GET only). Connectors never execute page scripts,
never submit forms and never follow links to other hosts. Page content is untrusted data: it is reduced to plain
text, links are kept only when they are http(s), and nothing in it is ever interpreted as an instruction.

Kinds
  sch_board  SCH notice boards (notice01.php): the existing parser (listing -> each notice page).
  listing    any official list page; an admin gives CSS selectors for the items (and optionally title / date /
             link inside an item). Items with a real link can be followed (same host only); items whose page opens
             through JavaScript keep the list page as their citation and are flagged ``no_detail_page``.
  page       one official page watched as a whole (e.g. a scholarship overview): change detection + facts.
"""
from __future__ import annotations

import hashlib
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag

from app.core.errors import ValidationFailed
from app.services.ingestion.errors import ExtractionError, FetchError
from app.services.ingestion.extractors_html import decode_html, extract_html
from app.services.ingestion.normalize import normalize_text
from app.services.ingestion.sch_board import KST

KINDS = ("sch_board", "listing", "page", "saramin_api", "data_go_kr_jobs", "work24_api")
API_KINDS = ("saramin_api", "data_go_kr_jobs", "work24_api")
MAX_TEXT = 20000
_DATE = re.compile(r"(20\d{2})\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})")


@dataclass
class Entry:
    key: str                         # canonical URL: the dedupe identity
    url: str                         # the citation (the item page, or the list page when there is none)
    title: str
    published_on: str | None
    text: str
    links: list[dict[str, str]] = field(default_factory=list)
    attachments: list[dict[str, str]] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    error: str | None = None          # the item could not be read (code); kept so it is reported, not hidden

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(f"{self.title}\n{self.published_on}\n{self.text}".encode()).hexdigest()


@dataclass
class ConnectorResult:
    entries: list[Entry]
    listing_hash: str | None = None
    requests: int = 0


def canonical(url: str) -> str:
    """Scheme + host lower-cased, no fragment, no tracking parameters."""
    p = urlsplit(url.strip())
    # tracking and paging parameters never identify a notice (the same article is linked from page 1 and page 2)
    query = "&".join(q for q in p.query.split("&")
                     if q and not re.match(r"(utm_\w+|fbclid|gclid|pager\.offset|pageIndex|currentPage)=", q))
    return urlunsplit((p.scheme.lower(), (p.hostname or "").lower() + (f":{p.port}" if p.port else ""), p.path or "/",
                       query, ""))


def _date(text: str | None) -> str | None:
    m = _DATE.search(text or "")
    if not m:
        return None
    try:
        from datetime import date

        return date(int(m[1]), int(m[2]), int(m[3])).isoformat()
    except ValueError:
        return None


CONTENT_ROOTS = ("main, article, .board_contents, .board_view, #contents, #content, #sub_contents, .content, "
                 ".view_td")
#: site chrome around the content: links inside it (menus, quick links, banners, footers) are never the notice's links
CHROME_TAGS = {"nav", "header", "footer", "aside"}
CHROME_ROLES = {"navigation", "banner", "contentinfo", "menu", "menubar", "search"}
CHROME_NAMES = re.compile(r"(?:^|[-_])(?:gnb\d*|lnb|snb|tnb|nav|navi|navigation|menu|menu_depth\d*|quick|quickmenu|sitemap|"
                          r"breadcrumb|location|util|banner|popup|footer|header|skip|family|sns|share)(?:$|[-_\d])",
                          re.IGNORECASE)


def in_chrome(el: Any, root: Any) -> bool:
    """Whether a link sits in navigation / site chrome between itself and the content root."""
    for p in el.parents:
        if p is root or p is None or p.name in ("body", "html", "[document]"):
            return False
        if p.name in CHROME_TAGS or str(p.get("role") or "").lower() in CHROME_ROLES:
            return True
        names = [str(p.get("id") or ""), *(p.get("class") or [])]
        if any(CHROME_NAMES.search(n) for n in names if n):
            return True
    return False


def anchors(html: str, base: str, limit: int = 200, root_selector: str | None = None) -> list[dict[str, str]]:
    """http(s) links of the page's main content (the admin's content selector, else a known content region, else
    the body), as plain data. Links in navigation, menus, banners or footers are never included."""
    soup = BeautifulSoup(html, "lxml")
    root = (soup.select_one(root_selector) if root_selector else None) or soup.select_one(CONTENT_ROOTS) or soup.body or soup
    out: list[dict[str, str]] = []
    for a in root.select("a[href]"):
        if in_chrome(a, root):
            continue
        url = urljoin(base, str(a["href"]))
        if url.startswith(("https://", "http://")):
            out.append({"text": re.sub(r"\s+", " ", a.get_text(" ", strip=True))[:200], "href": url[:1000]})
        if len(out) >= limit:
            break
    return out


def validate_config(kind: str, url: str, config: dict[str, Any]) -> dict[str, Any]:
    """Admin input: only known keys, bounded sizes, selectors that parse."""
    if kind not in KINDS:
        raise ValidationFailed(f"Unknown connector kind '{kind}'.")
    if kind in API_KINDS:
        from app.services.discovery.job_apis import check_config

        return check_config(kind, config)
    allowed = {"max_items", "max_pages", "item_selector", "title_selector", "date_selector", "link_selector",
               "include_url", "follow_items", "skip_selector", "delay_seconds", "content_selector",
               "attachment_selector"}
    unknown = set(config) - allowed
    if unknown:
        raise ValidationFailed(f"Unknown connector settings: {', '.join(sorted(unknown))}.")
    out: dict[str, Any] = {}
    if "max_items" in config:
        out["max_items"] = max(1, min(int(config["max_items"]), 30))
    if "max_pages" in config:
        out["max_pages"] = max(1, min(int(config["max_pages"]), 3))
    if "delay_seconds" in config:     # a slower pace for a sensitive site (never faster than the global delay)
        out["delay_seconds"] = max(1.0, min(float(config["delay_seconds"]), 10.0))
    for k in ("item_selector", "title_selector", "date_selector", "link_selector", "skip_selector", "content_selector",
              "attachment_selector"):
        if config.get(k):
            v = str(config[k])
            if len(v) > 200:
                raise ValidationFailed(f"{k} is too long.")
            try:
                BeautifulSoup("<div></div>", "lxml").select(v)
            except Exception as exc:  # noqa: BLE001 - soupsieve raises several types
                raise ValidationFailed(f"{k} is not a valid CSS selector.") from exc
            out[k] = v
    if config.get("include_url"):
        v = str(config["include_url"])
        if len(v) > 200:
            raise ValidationFailed("include_url is too long.")
        try:
            re.compile(v)
        except re.error as exc:
            raise ValidationFailed("include_url is not a valid pattern.") from exc
        out["include_url"] = v
    if "follow_items" in config:
        out["follow_items"] = bool(config["follow_items"])
    if kind == "listing" and not out.get("item_selector"):
        raise ValidationFailed("A listing source needs item_selector (the CSS selector of one item in the list).")
    if kind == "sch_board":
        from app.services.ingestion.sch_board import is_sch_board_url

        if not is_sch_board_url(url):
            raise ValidationFailed("sch_board sources must be SCH notice01.php board pages.")
    return out


class Connectors:
    def __init__(self, fetcher: Any, *, delay_seconds: float = 1.0, default_items: int = 10,
                 sleep: Callable[[float], None] = time.sleep):
        self.fetcher = fetcher
        self.delay = delay_seconds
        self.default_items = default_items
        self.sleep = sleep
        self._pace = delay_seconds
        self.settings: Any = None            # keys of the official APIs
        self.api_http: Any = None            # tests

    def run(self, source: dict[str, Any], *, max_items: int | None = None,
            on_item: Callable[[], None] | None = None) -> ConnectorResult:
        cfg = source.get("config") or {}
        limit = max(1, min(int(max_items or cfg.get("max_items") or self.default_items), 30))
        tick = on_item or (lambda: None)
        if source["kind"] in API_KINDS:
            from app.services.discovery import job_apis

            return job_apis.run(source, self.settings, limit, self.api_http)
        self._pace = max(self.delay, float(cfg.get("delay_seconds") or 0))
        if source["kind"] == "sch_board":
            return self._sch_board(source, limit, tick)
        if source["kind"] == "listing":
            return self._listing(source, cfg, limit, tick)
        if source["kind"] == "page":
            return self._page(source)
        raise ValidationFailed(f"Unknown connector kind '{source['kind']}'.")

    def _get(self, url: str, language: str | None) -> Any:
        return self.fetcher.fetch(url, language)

    # ---------------------------------------------------------------------------------- SCH boards
    def _sch_board(self, source: dict[str, Any], limit: int, tick: Callable[[], None]) -> ConnectorResult:
        from app.services.ingestion.sch_board import parse_listing, parse_notice

        res = self._get(source["url"], "ko")
        refs = parse_listing(res.content, source["url"])[:limit]
        listing_hash = hashlib.sha256("|".join(f"{r.notice_no}:{r.title}" for r in refs).encode()).hexdigest()
        entries: list[Entry] = []
        requests = 1
        for ref in refs:
            self.sleep(self._pace)
            tick()
            try:
                page = self._get(ref.url, "ko")
                requests += 1
                n = parse_notice(page.content, ref)
            except (FetchError, ExtractionError) as exc:
                entries.append(Entry(key=canonical(ref.url), url=ref.url, title=ref.title, published_on=ref.posted,
                                     text="", flags=["detail_failed"], error=exc.code))
                if exc.code in ("robots_disallowed", "http_401", "http_403", "http_429"):
                    raise
                continue
            # posted_at is midnight KST stored as UTC: the notice's date is the KST date
            posted = n.posted_at.astimezone(KST).date().isoformat() if n.posted_at else ref.posted
            entries.append(Entry(key=canonical(ref.url), url=ref.url, title=n.title, published_on=posted,
                                 text=n.body_text[:MAX_TEXT], attachments=n.attachments,
                                 links=[{"text": x.get("text", ""), "href": x.get("href", "")} for x in n.links]))
        return ConnectorResult(entries, listing_hash, requests)

    # --------------------------------------------------------------------------- generic listings
    def _listing(self, source: dict[str, Any], cfg: dict[str, Any], limit: int,
                 tick: Callable[[], None]) -> ConnectorResult:
        res = self._get(source["url"], source.get("language"))
        soup = BeautifulSoup(decode_html(res.content), "lxml")
        items = soup.select(cfg["item_selector"])
        if not items:
            raise ExtractionError("listing_structure_changed",
                                  "No items matched the configured selector; the page structure may have changed.")
        host = urlsplit(res.url).hostname
        include = re.compile(cfg["include_url"]) if cfg.get("include_url") else None
        entries: list[Entry] = []
        seen: set[str] = set()
        requests = 1
        for el in items:
            if len(entries) >= limit:
                break
            if cfg.get("skip_selector") and el.select_one(cfg["skip_selector"]):
                continue          # e.g. rows pinned to the top of a board (often years old)
            if cfg.get("title_selector"):
                title_el = el.select_one(cfg["title_selector"])
            else:   # without a title selector the link text is the title (not the whole row with its date)
                title_el = el if el.name == "a" else (el.select_one(cfg["link_selector"]) if cfg.get("link_selector")
                                                       else el.select_one("a")) or el
            title = re.sub(r"\s+", " ", (title_el or el).get_text(" ", strip=True))[:500]
            if not title:
                continue
            date_el = el.select_one(cfg["date_selector"]) if cfg.get("date_selector") else None
            published = _date(date_el.get_text(" ", strip=True) if date_el else el.get_text(" ", strip=True))
            link = self._item_link(el, cfg, res.url)
            flags: list[str] = []
            if link and (urlsplit(link).hostname != host or (include and not include.search(link))):
                link = None
            if link is None:
                # the item opens through JavaScript (or leaves the site): cite the list page, identified by title
                key = canonical(res.url) + "#item-" + hashlib.sha256(f"{title}|{published}".encode()).hexdigest()[:16]
                flags.append("no_detail_page")
                # the row itself only repeats title, date, author and view count: no text of its own
                entry = Entry(key=key, url=res.url, title=title, published_on=published, text="", flags=flags)
            else:
                entry = Entry(key=canonical(link), url=link, title=title, published_on=published, text="", flags=flags)
                if cfg.get("follow_items", True):
                    self.sleep(self._pace)
                    tick()
                    entry = self._follow(entry, source.get("language"), cfg)
                    requests += 1
                else:
                    entry.text = el.get_text("\n", strip=True)[:2000]
            if entry.key in seen:
                continue
            seen.add(entry.key)
            entries.append(entry)
        listing_hash = hashlib.sha256("|".join(f"{e.key}:{e.title}" for e in entries).encode()).hexdigest()
        return ConnectorResult(entries, listing_hash, requests)

    @staticmethod
    def _item_link(el: Tag, cfg: dict[str, Any], base: str) -> str | None:
        a = el.select_one(cfg["link_selector"]) if cfg.get("link_selector") else (el if el.name == "a" else el.select_one("a[href]"))
        href = str(a.get("href") or "") if isinstance(a, Tag) else ""
        if not href or href.startswith(("javascript:", "#", "mailto:", "tel:")):
            return None
        url = urljoin(base, href)
        return url if url.startswith(("https://", "http://")) else None

    def _follow(self, entry: Entry, language: str | None, cfg: dict[str, Any] | None = None) -> Entry:
        cfg = cfg or {}
        try:
            res = self._get(entry.url, language)
        except FetchError as exc:
            entry.flags.append("detail_failed")
            entry.error = exc.code
            if exc.code in ("robots_disallowed", "http_401", "http_403", "http_429"):
                raise
            return entry
        if res.content_type == "application/pdf":
            entry.text = self._pdf_text(res.content, entry.url)
            return entry
        html = decode_html(res.content)
        soup = BeautifulSoup(html, "lxml")
        body = soup.select_one(cfg["content_selector"]) if cfg.get("content_selector") else None
        try:   # only the article when the admin named it (no menus, author / view-count lines or site buttons)
            doc = extract_html(str(body) if body is not None else res.content, res.url,
                               None if body is not None else res.encoding, 1)
        except ExtractionError as exc:
            entry.flags.append("detail_failed")
            entry.error = exc.code
            return entry
        entry.text = doc.text[:MAX_TEXT]
        entry.links = anchors(html, res.url, root_selector=cfg.get("content_selector"))
        if cfg.get("attachment_selector"):
            box = soup.select_one(cfg["attachment_selector"])
            if box is not None:
                entry.attachments = [{"name": a.get_text(" ", strip=True)[:300], "url": urljoin(res.url, str(a["href"]))}
                                     for a in box.select("a[href]") if a.get_text(strip=True)
                                     and urljoin(res.url, str(a["href"])).startswith(("https://", "http://"))][:10]
        if not entry.published_on and doc.source_published_at:
            entry.published_on = doc.source_published_at.date().isoformat()
        return entry

    @staticmethod
    def _pdf_text(data: bytes, url: str) -> str:
        from app.services.ingestion.pdf_isolation import extract_pdf_isolated

        try:
            doc = extract_pdf_isolated(data, url.rsplit("/", 1)[-1] or "document.pdf", timeout_seconds=60, max_pages=20)
        except Exception:  # noqa: BLE001 - an unreadable PDF is reported by the empty text flag
            return ""
        return doc.text[:MAX_TEXT]

    # ------------------------------------------------------------------------------- single page
    def _page(self, source: dict[str, Any]) -> ConnectorResult:
        cfg = source.get("config") or {}
        res = self._get(source["url"], source.get("language"))
        if res.content_type == "application/pdf":
            text = self._pdf_text(res.content, res.url)
            entry = Entry(key=canonical(source["url"]), url=res.url, title=source["name"], published_on=None, text=text)
        else:
            html = decode_html(res.content)
            soup = BeautifulSoup(html, "lxml")
            body = soup.select_one(cfg["content_selector"]) if cfg.get("content_selector") else None
            # only the part the admin named (a calendar, a program description), never menus or site buttons
            doc = extract_html(str(body) if body is not None else res.content, res.url,
                               None if body is not None else res.encoding, 1)
            # buttons that only show a message ("접수 기간이 아닙니다") are part of what the page says
            notes = re.findall(r"showNotificationModal\('([^']{1,200})'\)", str(body) if body is not None else html)
            text = normalize_text(doc.text + ("\n\n" + "\n".join(dict.fromkeys(notes)) if notes else ""))
            # a watched page is named by the admin (page <title>s are site chrome) and has no reliable publication
            # date: what matters is whether its content changed
            entry = Entry(key=canonical(source["url"]), url=res.url, title=source["name"], published_on=None,
                          text=text[:MAX_TEXT], links=anchors(html, res.url, root_selector=cfg.get("content_selector")),
                          flags=["watched_page"])
            if cfg.get("attachment_selector"):
                box = soup.select_one(cfg["attachment_selector"])
                if box is not None:
                    entry.attachments = [{"name": a.get_text(" ", strip=True)[:300], "url": urljoin(res.url, str(a["href"]))}
                                         for a in box.select("a[href]") if a.get_text(strip=True)
                                         and urljoin(res.url, str(a["href"])).startswith(("https://", "http://"))][:10]
        return ConnectorResult([entry], entry.content_hash, 1)
