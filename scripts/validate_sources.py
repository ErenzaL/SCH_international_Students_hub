"""Check a file of official-source proposals against the LIVE websites, without a database: allowlist, robots.txt, parser, dates,
links. Uses the Hub's own guarded fetcher and connectors (GET, robots.txt, at least one second between requests).

    cd backend && .venv/bin/python ../scripts/validate_sources.py app/services/discovery/catalog.json [--items 3] [--write]

--write stores the result (status, counts, date) next to every entry. Nothing is sent to the Hub.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.core.config import Settings  # noqa: E402
from app.services.agents.tasks import DISCOVERY_AGENTS  # noqa: E402
from app.services.discovery.connectors import API_KINDS, Connectors, validate_config  # noqa: E402
from app.services.discovery.extract import analyse  # noqa: E402
from app.services.ingestion.fetcher import GuardedFetcher  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("file", type=Path)
    p.add_argument("--items", type=int, default=3)
    p.add_argument("--only")
    p.add_argument("--write", action="store_true")
    p.add_argument("--show", action="store_true", help="print titles")
    a = p.parse_args()
    data = json.loads(a.file.read_text())
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    con = Connectors(GuardedFetcher(s), delay_seconds=1.0)
    bad = 0
    for e in data["sources"]:
        if a.only and a.only not in e["url"] and a.only != e["agent_id"]:
            continue
        if e["kind"] in API_KINDS:
            print(f"skipped  {e['agent_id']:13} {e['name'][:40]:42} needs {e.get('needs')}")
            continue
        t0, out = time.time(), {}
        try:
            assert e["agent_id"] in DISCOVERY_AGENTS, "unknown desk"
            cfg = validate_config(e["kind"], e["url"], e.get("config") or {})
            res = con.run(dict(e, config=cfg, id="x"), max_items=a.items)
            facts = [analyse(x.title, x.text, published_on=x.published_on, links=x.links, attachments=x.attachments, today=date.today(),
                             watched="watched_page" in x.flags, list_only="no_detail_page" in x.flags) for x in res.entries]
            out = dict(status="ok" if res.entries and not any(x.error for x in res.entries) else "partial" if res.entries else "empty",
                       items_read=len(res.entries), with_text=sum(len(x.text) > 80 for x in res.entries), with_date=sum(bool(x.published_on) for x in res.entries),
                       with_deadline=sum(bool(f["deadlines"]) for f in facts), newest=max((x.published_on for x in res.entries if x.published_on), default=None))
            if a.show:
                for x, f in zip(res.entries, facts, strict=True):
                    print("     ", x.published_on, f["opportunity_kind"], f["open_status"], x.title[:80], x.flags, len(x.text))
        except Exception as exc:  # noqa: BLE001
            out = dict(status="failed", error=getattr(exc, "code", None) or f"{type(exc).__name__}: {exc}"[:160])
            bad += 1
        out.update(seconds=round(time.time() - t0, 1), checked=date.today().isoformat())
        print(f"{out['status']:8} {e['agent_id']:13} {e['name'][:40]:42} {json.dumps({k: v for k, v in out.items() if k not in ('status', 'checked')}, ensure_ascii=False)}", flush=True)
        if a.write:
            e["validated"] = out
    if a.write:
        a.file.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
