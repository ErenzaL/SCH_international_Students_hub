"""Official-source discovery: admin-managed sources, checks with change detection and deduplication, review
candidates, and the admin actions on them.

What this never does
  * publish anything or add anything to RAG knowledge. A discovered item is a candidate. "Send to review" creates a
    normal knowledge source + ingestion job, so the item becomes a pending_review version that an admin approves in
    the existing review screen (the same path as any other new content);
  * fetch outside the domain allowlist, bypass robots.txt or access restrictions, run page scripts or submit forms;
  * treat page text as instructions (it is stored as plain text and shown escaped).
"""
from __future__ import annotations

import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from app.core.config import Settings
from app.core.errors import AppError, Conflict, InvalidState, NotFound, ValidationFailed
from app.repositories.base import Query, Store, get_one
from app.services.announcements import today_kst
from app.services.discovery.connectors import API_KINDS, Connectors, Entry, canonical, validate_config
from app.services.discovery.extract import analyse, effective_open_status
from app.services.discovery.job_apis import HOME
from app.services.ingestion.errors import ExtractionError, FetchError
from app.services.ingestion.notice_reader import config_for

log = logging.getLogger("app.discovery")
BLOCKED = {"api_key_missing", "api_key_invalid", "robots_disallowed", "http_401", "http_403", "http_406", "http_429"}
MAX_FAILURES = 5          # a source failing this many times in a row is skipped by scheduled checks
EXCERPT = 6000


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _norm_title(t: str) -> str:
    t = re.sub(r"^\s*(\[[^\]]{1,20}\]\s*)+", "", t)          # [홍보] [공모전] prefixes differ between boards
    return re.sub(r"[\W_]+", "", t.lower())


def _desk(agent_id: str) -> str:
    from app.services.agents.registry import AGENTS

    return AGENTS[agent_id].character_id if agent_id in AGENTS else "guide-bot"


def authority_for(url: str) -> tuple[str, str]:
    host = (urlsplit(url).hostname or "").lower()
    if host.endswith("sch.ac.kr"):
        return "official_university", "university"
    if host.endswith(".go.kr") or host.endswith(".or.kr"):
        return "official_government", "national"
    return "other", "national"


class DiscoveryService:
    def __init__(self, store: Store, settings: Settings, fetcher: Any, domains: Any, notifications: Any = None):
        self.store = store
        self.settings = settings
        self.domains = domains
        self.notifications = notifications
        self.connectors = Connectors(fetcher, delay_seconds=settings.board_request_delay_seconds,
                                     default_items=settings.discovery_max_items)
        self.connectors.settings = settings
        self.sources_service: Any = None     # SourceService (send to review)
        self.ingestion: Any = None
        self.jobs: Any = None
        self.llm: Any = None                 # shared model slot, only for optional summaries

    # ===================================================================== sources (admin)
    def list_sources(self, agent_id: str | None = None) -> list[dict[str, Any]]:
        rows, _ = self.store.select("discovery_sources", Query(eq={"agent_id": agent_id} if agent_id else {},
                                                               order=[("created_at", False)]))
        return rows

    def catalog(self) -> list[dict[str, Any]]:
        import json
        from pathlib import Path

        entries = json.loads((Path(__file__).parent / "catalog.json").read_text(encoding="utf-8"))["sources"]
        have = {(s["agent_id"], s["url"]) for s in self.list_sources()}
        out = []
        for e in entries:
            need = e.get("needs")
            out.append(dict({k: e[k] for k in ("agent_id", "name", "kind", "url", "category", "language", "config")},
                            recommended_interval_minutes=e["recommended_interval_minutes"], validated=e.get("validated") or {},
                            added=(e["agent_id"], e["url"]) in have, needs=need,
                            ready=not need or bool(getattr(self.settings, need.lower(), ""))))
        return out

    def get_source(self, source_id: str) -> dict[str, Any]:
        s = get_one(self.store, "discovery_sources", id=source_id)
        if s is None:
            raise NotFound("Source not found.")
        return s

    def _validate_url(self, url: str) -> str:
        from app.security.url_guard import validate_url_syntax

        return validate_url_syntax(url, self.domains.domains())    # allowlist (env + admin-managed) + syntax rules

    def create_source(self, admin_id: str, data: dict[str, Any]) -> dict[str, Any]:
        # the two official APIs have fixed addresses; everything else must be on the allowlist
        url = HOME[data["kind"]] if data["kind"] in API_KINDS else self._validate_url(data["url"])
        if data["kind"] in API_KINDS and data["agent_id"] != "career":
            raise ValidationFailed("Recruitment APIs belong to the career desk.")
        config = validate_config(data["kind"], url, data.get("config") or {})
        row = dict(agent_id=data["agent_id"], name=data["name"].strip(), kind=data["kind"], url=url, config=config,
                   category=data.get("category"), language=data.get("language") or "ko",
                   enabled=data.get("enabled", True), created_by=admin_id, updated_by=admin_id)
        try:
            s = self.store.insert("discovery_sources", row)
        except Exception as exc:
            if "duplicate" in str(exc).lower():
                raise Conflict("This agent already monitors that URL.") from exc
            raise
        self._audit(admin_id, "discovery_source.create", s["id"], dict(url=url, kind=s["kind"], agent=s["agent_id"]))
        return s

    def update_source(self, admin_id: str, source_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        s = self.get_source(source_id)
        fields: dict[str, Any] = {k: v for k, v in patch.items() if v is not None and k in
                                  ("name", "config", "category", "language", "enabled")}
        if "config" in fields:
            fields["config"] = validate_config(s["kind"], s["url"], fields["config"])
        if patch.get("reset_failures"):
            fields.update(consecutive_failures=0, last_error=None)
        fields["updated_by"] = admin_id
        row = self.store.update("discovery_sources", fields, {"id": source_id})[0]
        self._audit(admin_id, "discovery_source.update", source_id, {k: v for k, v in fields.items() if k != "updated_by"})
        return row

    def delete_source(self, admin_id: str, source_id: str) -> None:
        s = self.get_source(source_id)
        items, _ = self.store.select("discovered_items", Query(eq={"source_id": source_id}, cols="id"))
        for it in items:   # the database cascades; explicit for every store
            self.store.delete("discovered_items", {"id": it["id"]})
        self.store.delete("discovery_sources", {"id": source_id})
        self._audit(admin_id, "discovery_source.delete", source_id, dict(url=s["url"], items=len(items)))

    def _audit(self, actor: str | None, action: str, entity_id: str, details: dict[str, Any]) -> None:
        self.store.insert("audit_log", dict(action=action, entity_type="discovery", entity_id=entity_id,
                                            actor_id=actor, details=details))

    # ===================================================================== checks
    def check_sources(self, agent_id: str, *, source_ids: list[str] | None = None, max_sources: int = 5,
                      max_items: int | None = None, scheduled: bool = False, summarize: bool = False,
                      progress: Callable[[dict[str, Any]], None] = lambda p: None,
                      checkpoint: Callable[[str], None] = lambda stage: None,
                      log_step: Callable[..., None] = lambda *a, **k: None) -> dict[str, Any]:
        sources = [s for s in self.list_sources(agent_id) if s["enabled"]]
        if source_ids:
            sources = [s for s in sources if s["id"] in set(source_ids)]
        if scheduled:      # failing sources back off (1 h, 2 h, 4 h ... 24 h) and stop after MAX_FAILURES
            sources = [s for s in sources if s["consecutive_failures"] < MAX_FAILURES and not self._backing_off(s)]
        sources = sources[: max(1, min(max_sources, self.settings.discovery_max_sources))]
        state: dict[str, Any] = dict(sources_total=len(sources), sources_done=0, items_found=0, new=0, updated=0,
                                     sources=[dict(id=s["id"], name=s["name"], url=s["url"], status="pending")
                                              for s in sources])
        progress(state)
        results = []
        for i, s in enumerate(sources):
            checkpoint(f"checking {s['name'][:60]}")
            state["current"] = s["name"]
            state["sources"][i]["status"] = "checking"
            progress(state)
            log_step(agent_id, "tool", "official_source_check", f"Checking {s['name']}", dict(url=s["url"]))
            r = self.check_source(s, max_items=max_items, scheduled=scheduled, summarize=summarize,
                                  tick=lambda: checkpoint("reading notices"))
            results.append(r)
            state["sources"][i].update(status=r["status"], new=r["new"], updated=r["updated"], found=r["found"],
                                       error=r.get("error"), checked_at=r.get("checked_at"))
            state.update(sources_done=i + 1, items_found=state["items_found"] + r["found"],
                         new=state["new"] + r["new"], updated=state["updated"] + r["updated"])
            progress(state)
        state.pop("current", None)
        progress(state)
        return dict(sources=results, **{k: state[k] for k in ("sources_total", "sources_done", "items_found", "new",
                                                               "updated")})

    @staticmethod
    def _backing_off(s: dict[str, Any], now: datetime | None = None) -> bool:
        n = s["consecutive_failures"]
        if not n or not s.get("last_checked_at"):
            return False
        wait = timedelta(hours=min(2 ** (n - 1), 24))
        return (now or datetime.now(UTC)) - datetime.fromisoformat(s["last_checked_at"]) < wait

    def _failed(self, s: dict[str, Any], status: str, code: str, message: str, checked: str, scheduled: bool) -> None:
        failures = s["consecutive_failures"] + 1
        self.store.update("discovery_sources", dict(last_checked_at=checked, last_status=status,
                                                    last_error=f"{code}: {message}"[:500],
                                                    consecutive_failures=failures), {"id": s["id"]})
        log.warning("discovery source %s %s (%s), %d failure(s) in a row", s["id"], status, code, failures)
        # alert admins once when a source starts failing repeatedly, and once when it is paused
        if self.notifications is not None and (status == "blocked" or failures in (3, MAX_FAILURES)):
            paused = failures >= MAX_FAILURES
            self.notifications.notify(
                "discovery_source_failing",
                f"Official source {'paused' if paused else 'failing'}: {s['name'][:120]}",
                f"{status} ({code}) {failures} time(s) in a row."
                + (" Scheduled checks skip it until an admin resets it." if paused else
                   " The site refused automated access; it is not retried automatically." if status == "blocked" else
                   " Scheduled checks back off between attempts."),
                severity="error" if paused or status == "blocked" else "warning",
                entity_type="discovery_source", entity_id=s["id"])

    def check_source(self, s: dict[str, Any], *, max_items: int | None = None, scheduled: bool = False,
                     summarize: bool = False, tick: Callable[[], None] = lambda: None) -> dict[str, Any]:
        out: dict[str, Any] = dict(source_id=s["id"], name=s["name"], url=s["url"], status="ok", found=0, new=0,
                                   updated=0, unchanged=0, failed=0, item_ids=[], checked_at=None)
        last = s.get("last_checked_at")
        min_gap = self.settings.discovery_min_check_interval_seconds
        if last and not scheduled and (datetime.now(UTC) - datetime.fromisoformat(last)).total_seconds() < min_gap:
            # polite to the site: a manual re-check within minutes returns what we already know
            out.update(status="recently_checked", checked_at=last, item_ids=self._recent_ids(s))
            out["found"] = len(out["item_ids"])
            return out
        checked = now_iso()
        try:
            res = self.connectors.run(s, max_items=max_items, on_item=tick)
        except (FetchError, ExtractionError) as exc:
            status = "blocked" if exc.code in BLOCKED else "failed"
            self._failed(s, status, exc.code, exc.message, checked, scheduled)
            out.update(status=status, error=exc.code, checked_at=checked)
            return out
        except AppError as exc:     # e.g. the URL is no longer on the allowlist
            self._failed(s, "failed", exc.code, exc.message, checked, scheduled)
            out.update(status="failed", error=exc.code, checked_at=checked)
            return out
        summaries = 0
        for e in res.entries:
            if e.error:
                out["failed"] += 1
            item, change = self._upsert(s, e)
            out["found"] += 1
            out[change] += 1
            out["item_ids"].append(item["id"])
            if summarize and change in ("new", "updated") and summaries < 3 and len(e.text) > 1500:
                if self._summarize(item, e):
                    summaries += 1
        status = "partial" if out["failed"] else "ok"
        self.store.update("discovery_sources", dict(last_checked_at=checked, last_success_at=checked, last_status=status,
                                                    last_error=None, consecutive_failures=0,
                                                    last_listing_hash=res.listing_hash), {"id": s["id"]})
        out.update(status=status, checked_at=checked)
        return out

    def _recent_ids(self, s: dict[str, Any]) -> list[str]:
        rows, _ = self.store.select("discovered_items", Query(eq={"source_id": s["id"]}, order=[("last_seen_at", True)],
                                                              limit=30, cols="id"))
        return [r["id"] for r in rows]

    def _upsert(self, s: dict[str, Any], e: Entry) -> tuple[dict[str, Any], str]:
        facts = analyse(e.title, e.text, published_on=e.published_on, links=e.links, attachments=e.attachments,
                        today=today_kst(), watched="watched_page" in e.flags, list_only="no_detail_page" in e.flags)
        facts["flags"] = sorted(set(facts["flags"]) | set(e.flags))
        facts["attachments"] = [dict(name=a.get("name", "")[:200], url=a.get("url", "")) for a in e.attachments
                                if str(a.get("url", "")).startswith(("https://", "http://"))][:10]
        if e.error:
            facts["error"] = e.error
        h = e.content_hash
        now = now_iso()
        cur = get_one(self.store, "discovered_items", item_key=e.key)
        base = dict(url=e.url, title=e.title[:500], published_on=e.published_on, language=s.get("language"),
                    text_excerpt=e.text[:EXCERPT] or None, extracted=facts, category=facts["category"],
                    opportunity_kind=facts["opportunity_kind"], open_status=facts["open_status"], last_seen_at=now)
        if cur is None:
            dup = self._duplicate_of(e)
            row = self.store.insert("discovered_items", dict(base, source_id=s["id"], item_key=e.key, content_hash=h,
                                                             change="new", first_seen_at=now, last_changed_at=now,
                                                             duplicate_of=dup))
            return row, "new"
        if cur["content_hash"] == h:
            row = self.store.update("discovered_items", dict(change="unchanged", last_seen_at=now,
                                                             open_status=facts["open_status"], extracted=facts),
                                    {"id": cur["id"]})[0]
            return row, "unchanged"
        patch = dict(base, content_hash=h, previous_hash=cur["content_hash"], change="updated", last_changed_at=now)
        if cur["status"] == "dismissed":     # the notice changed after it was dismissed: it needs a new look
            patch["status"] = "candidate"
        row = self.store.update("discovered_items", patch, {"id": cur["id"]})[0]
        return row, "updated"

    def _duplicate_of(self, e: Entry) -> str | None:
        """The same notice under another URL (another board, a copy): same title and publication date."""
        key = _norm_title(e.title)
        if len(key) < 6:
            return None
        rows, _ = self.store.select("discovered_items", Query(
            eq={"published_on": e.published_on} if e.published_on else {}, is_null={"duplicate_of": True},
            cols="id,title,published_on", limit=500))
        for r in rows:
            if _norm_title(r["title"]) == key:
                return r["id"]
        return None

    def _summarize(self, item: dict[str, Any], e: Entry) -> bool:
        llm = self.llm
        if llm is None or not getattr(llm, "enabled", False):
            return False
        from app.services.translation_drafts import SUMMARY_PROMPT, SUMMARY_SYSTEM, _strip_wrappers

        try:
            r = llm.complete(SUMMARY_SYSTEM.format(source="Korean", target="English"),
                             SUMMARY_PROMPT.format(title=e.title[:300], target="English", outline="", text=e.text[:8000]),
                             max_tokens=800)
        except Exception:  # noqa: BLE001 - a summary is optional; the item stays without one
            log.warning("discovery summary failed for %s", item["id"])
            return False
        facts = dict(item.get("extracted") or {}, summary=dict(text=_strip_wrappers(r.text)[:2000], model=r.model,
                                                                 label="ai_generated"))
        self.store.update("discovered_items", dict(extracted=facts), {"id": item["id"]})
        return True

    # ===================================================================== reading
    def view(self, it: dict[str, Any], sources: dict[str, dict[str, Any]] | None = None, *,
             admin: bool = False) -> dict[str, Any]:
        f = it.get("extracted") or {}
        src = (sources or {}).get(it["source_id"]) or get_one(self.store, "discovery_sources", id=it["source_id"]) or {}
        status, reason = effective_open_status(it["open_status"], f, today_kst())
        out = dict(kind="discovered", id=it["id"], title=it["title"], href=it["url"], url=it["url"],
                   published_on=it.get("published_on"), category=it.get("category"),
                   opportunity_kind=it.get("opportunity_kind"), open_status=status,
                   open_reason=reason, next_deadline=f.get("next_deadline"),
                   deadline=f.get("next_deadline"), event_date=f.get("event_date"), deadlines=f.get("deadlines") or [],
                   eligibility=f.get("eligibility") or [], application_links=f.get("application_links") or [],
                   flags=f.get("flags") or [], change=it["change"], first_seen_at=it["first_seen_at"],
                   last_seen_at=it["last_seen_at"], last_checked_at=src.get("last_checked_at"),
                   source_name=src.get("name"), excerpt=(it.get("text_excerpt") or "")[:400],
                   reliability="external_unverified", review_status=it["status"],
                   summary=(f.get("summary") or {}).get("text"))
        if f.get("summary"):
            out["summary_label"] = "ai_generated"
        if admin:
            out.update(open_status_when_checked=it["open_status"])
            out.update(duplicate_of=it.get("duplicate_of"), imported_source_id=it.get("imported_source_id"),
                       reviewed_at=it.get("reviewed_at"), review_note=it.get("review_note"),
                       error=f.get("error"), category_reason=f.get("category_reason"))
        return out

    def _sources_map(self) -> dict[str, dict[str, Any]]:
        return {s["id"]: s for s in self.list_sources()}

    def opportunities(self, *, q: str | None = None, kinds: list[str] | None = None, include_closed: bool = False,
                      limit: int = 20, approved_documents: Callable[[list[str]], dict[str, str]] | None = None,
                      reviewed_only: bool = True, agent_id: str | None = None) -> list[dict[str, Any]]:
        """Official items classified as opportunities, never dismissed ones or duplicates.

        An item an admin sent to review whose Knowledge Center version has since been approved is shown as verified,
        linked to that document (``approved_documents`` maps knowledge source -> public document). With
        ``reviewed_only`` (everyone but admins) ONLY such items are returned; admins also get the unreviewed
        candidates, labelled unverified (official site, not reviewed by staff)."""
        statuses = ["imported"] if reviewed_only else ["candidate", "imported"]
        in_: dict[str, list[Any]] = {"status": statuses}
        if kinds:
            in_["opportunity_kind"] = kinds
        if agent_id:
            in_["source_id"] = [s["id"] for s in self.list_sources(agent_id)]
            if not in_["source_id"]:
                return []
        rows, _ = self.store.select("discovered_items", Query(
            in_=in_, is_null={"duplicate_of": True}, order=[("last_changed_at", True)], limit=200))
        imported = sorted({r["imported_source_id"] for r in rows if r.get("imported_source_id")})
        approved = approved_documents(imported) if approved_documents and imported else {}
        if reviewed_only:
            rows = [r for r in rows if r.get("imported_source_id") in approved]
        today = today_kst()
        status = {r["id"]: effective_open_status(r["open_status"], r.get("extracted"), today)[0] for r in rows}
        if not include_closed:                    # a passed deadline hides the item at once, without a new crawl
            rows = [r for r in rows if status[r["id"]] != "closed"]
        if q:
            ql = q.lower()
            rows = [r for r in rows if ql in (r["title"] + " " + (r.get("text_excerpt") or "")).lower()]
        rows.sort(key=lambda r: ({"open": 0, "unknown": 1, "closed": 2}[status[r["id"]]],
                                 (r.get("extracted") or {}).get("next_deadline") or "9999"))
        smap = self._sources_map()
        out = []
        for r in rows[:limit]:
            v = self.view(r, smap, admin=not reviewed_only)
            doc = approved.get(r.get("imported_source_id") or "")
            if doc:
                v.update(reliability="verified", href=f"/knowledge/{doc}", document_id=doc, official_url=r["url"])
            if reviewed_only:
                v.pop("review_status", None)
            out.append(v)
        return out

    def candidates(self, *, agent_id: str | None = None, status: str = "candidate", changed_only: bool = False,
                   limit: int = 50) -> list[dict[str, Any]]:
        smap = self._sources_map()
        ids = [k for k, v in smap.items() if not agent_id or v["agent_id"] == agent_id]
        if not ids:
            return []
        eq: dict[str, Any] = {"status": status} if status != "all" else {}
        rows, _ = self.store.select("discovered_items", Query(in_={"source_id": ids}, eq=eq,
                                                              order=[("last_changed_at", True)], limit=limit))
        if changed_only:
            rows = [r for r in rows if r["change"] in ("new", "updated")]
        return [self.view(r, smap, admin=True) for r in rows]

    def items_by_id(self, ids: list[str], *, admin: bool) -> list[dict[str, Any]]:
        if not ids:
            return []
        rows, _ = self.store.select("discovered_items", Query(in_={"id": ids}))
        order = {i: n for n, i in enumerate(ids)}
        rows.sort(key=lambda r: order.get(r["id"], 0))
        smap = self._sources_map()
        return [self.view(r, smap, admin=admin) for r in rows]

    # ===================================================================== review actions (admin)
    def _item(self, item_id: str) -> dict[str, Any]:
        it = get_one(self.store, "discovered_items", id=item_id)
        if it is None:
            raise NotFound("Item not found.")
        return it

    def dismiss(self, admin_id: str, item_id: str, note: str | None) -> dict[str, Any]:
        it = self._item(item_id)
        row = self.store.update("discovered_items", dict(status="dismissed", reviewed_by=admin_id, reviewed_at=now_iso(),
                                                         review_note=(note or None) and note[:1000]), {"id": it["id"]})[0]
        self._audit(admin_id, "discovered_item.dismiss", item_id, dict(title=it["title"][:200]))
        return self.view(row, admin=True)

    def send_to_review(self, admin_id: str, item_id: str, background: Any = None) -> dict[str, Any]:
        """Register the official page as a knowledge source and queue its normal ingestion job: the result is a
        pending_review version in the existing review screen. Nothing is approved or published here."""
        it = self._item(item_id)
        if it["status"] == "imported" and it.get("imported_source_id"):
            raise InvalidState("This item was already sent to review.")
        if "no_detail_page" in ((it.get("extracted") or {}).get("flags") or []):
            raise InvalidState("This item has no page of its own on the official site (it opens through a script). "
                               "Add it manually from the original notice.")
        src = get_one(self.store, "discovery_sources", id=it["source_id"]) or {}
        if "api_item" in ((it.get("extracted") or {}).get("flags") or []):
            return self._api_item_to_review(admin_id, it, src)
        authority, scope = authority_for(it["url"])
        category = it.get("category") or src.get("category") or "university-announcements"
        existing = get_one(self.store, "knowledge_sources", original_url=self._validate_url(it["url"]))
        if existing is not None:
            ks = existing
        else:
            ks = self.sources_service.create(dict(
                title=it["title"][:200], original_url=it["url"], organization=(src.get("name") or "Official source")[:200],
                source_type="website", authority_type=authority, scope=scope, category=category,
                language=it.get("language") or "ko", sync_frequency="manual", is_active=True,
                config=config_for(src.get("kind") or "", src.get("config") or {}, it)), admin_id)
        job = None
        if not self.ingestion.has_open_job(ks["id"]):
            job = self.ingestion.create_job(ks, "manual", admin_id)
            self.jobs.enqueue(job, background)
        row = self.store.update("discovered_items", dict(status="imported", imported_source_id=ks["id"],
                                                         reviewed_by=admin_id, reviewed_at=now_iso()),
                                {"id": it["id"]})[0]
        self._audit(admin_id, "discovered_item.send_to_review", item_id,
                    dict(knowledge_source_id=ks["id"], job_id=job["id"] if job else None))
        return dict(item=self.view(row, admin=True), knowledge_source_id=ks["id"], job_id=job["id"] if job else None)

    def _api_item_to_review(self, admin_id: str, it: dict[str, Any], src: dict[str, Any]) -> dict[str, Any]:
        """A posting from an official API: its few facts and the link become a pending_review text (the page itself is never
        fetched). It leaves search on its deadline."""
        facts = it.get("extracted") or {}
        ks = self.sources_service.create(dict(
            title=it["title"][:200], original_url=None, organization=(src.get("name") or "Official API")[:200], source_type="manual_text",
            authority_type="other", scope="national", category="employment-internships", language="ko", sync_frequency="manual", is_active=True), admin_id)
        job = self.ingestion.ingest_text(ks, title=it["title"][:200], text=it.get("text_excerpt") or it["title"], requested_by=admin_id, external_id=it["item_key"][:200])
        if job.get("version_id") and facts.get("next_deadline"):
            end = datetime.fromisoformat(f"{facts['next_deadline']}T23:59:59+09:00").astimezone(UTC).isoformat()
            self.store.update("document_versions", {"valid_until": end}, {"id": job["version_id"], "verification_status": "pending_review"})
        row = self.store.update("discovered_items", dict(status="imported", imported_source_id=ks["id"], reviewed_by=admin_id, reviewed_at=now_iso()),
                                {"id": it["id"]})[0]
        self._audit(admin_id, "discovered_item.send_to_review", it["id"], dict(knowledge_source_id=ks["id"], job_id=job["id"], api_item=True))
        return dict(item=self.view(row, admin=True), knowledge_source_id=ks["id"], job_id=job["id"])

    def notify_new(self, agent_id: str, new: int, updated: int) -> None:
        if self.notifications is None or not (new or updated):
            return
        self.notifications.notify(
            "discovery_candidates", f"{new} new and {updated} changed official notices to review ({agent_id})",
            "Found by the AI Office monitoring. Nothing is published until an admin reviews it.",
            link="/ai-office?desk=" + _desk(agent_id))

    def purge(self) -> int:
        """Dismissed candidates that have not been seen for 90 days are removed."""
        cutoff = (datetime.now(UTC) - timedelta(days=90)).isoformat()
        rows, _ = self.store.select("discovered_items", Query(eq={"status": "dismissed"}, lt={"last_seen_at": cutoff},
                                                              cols="id"))
        for r in rows:
            self.store.delete("discovered_items", {"id": r["id"]})
        return len(rows)


_ = (ValidationFailed, canonical)
