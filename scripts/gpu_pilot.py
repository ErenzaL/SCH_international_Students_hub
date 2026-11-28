"""ONE manual production translation with the GPU worker (docs/release/gpu-worker-readiness.md, section 9).

    export HUB_URL=https://<api host>                   # no token on the command line; it is asked for (or HUB_TOKEN)
    python scripts/gpu_pilot.py preflight ANNOUNCEMENT_ID vi      # read-only
    python scripts/gpu_pilot.py queue ANNOUNCEMENT_ID vi --authorized "name, date, where the approval is recorded"
    # on the GPU server: python -m app.gpu_worker --once
    python scripts/gpu_pilot.py verify ANNOUNCEMENT_ID vi         # read-only

Run it on an administrator's own computer, not on the GPU server: it needs an administrator's login token. ``queue`` does
every preflight check again, changes exactly one thing (it queues one job) and refuses when anything else is waiting.
The token is never printed or stored.
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys
from typing import Any
from urllib.parse import urlsplit

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))
from app.services.translation.quality import is_high_risk  # noqa: E402


class Stop(Exception):
    pass


class Pilot:
    def __init__(self, url: str, token: str, transport: httpx.BaseTransport | None = None):
        p = urlsplit(url)
        if p.scheme != "https" and p.hostname not in ("127.0.0.1", "localhost"):
            raise Stop("HUB_URL must use https")
        self.http = httpx.Client(base_url=url.rstrip("/"), timeout=90, follow_redirects=False, transport=transport,
                                 headers={"Authorization": f"Bearer {token}"})

    def get(self, path: str, **params: Any) -> dict[str, Any]:
        r = self.http.get("/api/v1" + path, params=params)
        if r.status_code != 200:
            raise Stop(f"GET {path}: {r.status_code} {_code(r)}")
        return r.json()

    def preflight(self, aid: str, lang: str) -> list[str]:
        """Problems (empty = ready). Read-only."""
        bad = []
        st = self.get("/admin/gpu/status")
        if not st["available"]:
            bad.append("no GPU worker contacted the API recently (run it once with --once)")
        if len([w for w in st["workers"] if w["status"] == "active" and not w["expired"]]) != 1:
            bad.append("there must be exactly one active worker")
        if st["queue"]["queued"] or st["queue"]["running"]:
            bad.append(f"other GPU jobs are open: {st['queue']}")
        a = self.get(f"/announcements/{aid}", lang=lang)
        text = f"{a['title']}\n{a['body']}"
        if is_high_risk(text):
            bad.append("high-risk content (visa, work, money, deadlines, insurance, law): choose another announcement")
        if len(a["body"]) > 2000:
            bad.append("longer than 2000 characters: choose a short announcement")
        if lang == a["original_language"]:
            bad.append("the target is the original language")
        if a.get("translation"):
            bad.append("students already see a translation in this language")
        d = self.get(f"/admin/announcements/{aid}/translations/{lang}")
        t = d.get("translation")
        if t and t["translation_status"] != "todo":
            bad.append(f"there is already a translation ({t['translation_status']})")
        if d["original"]["body"] != a["body"]:
            bad.append("the announcement has an unapproved change")
        if not d["permissions"]["can_review"]:
            bad.append("this account cannot review this language (nobody could check the draft with it)")
        return bad

    def queue(self, aid: str, lang: str) -> str:
        bad = self.preflight(aid, lang)
        if bad:
            raise Stop("not queued: " + "; ".join(bad))
        r = self.http.post(f"/api/v1/admin/announcements/{aid}/translations/{lang}/machine-translate")
        if r.status_code != 202:
            raise Stop(f"not queued: {r.status_code} {_code(r)}")
        jobs = [j for j in self.get("/admin/gpu/status")["jobs"] if j["id"] == r.json()["job_id"]]
        if not jobs:
            raise Stop("the job was not given to the GPU worker; check it in the admin pages")
        return r.json()["job_id"]

    def verify(self, aid: str, lang: str) -> list[str]:
        bad = []
        if self.get(f"/announcements/{aid}", lang=lang).get("translation"):
            bad.append("STOP: students can see the translation")
        t = self.get(f"/admin/announcements/{aid}/translations/{lang}").get("translation") or {}
        if t.get("translation_status") != "needs_review":
            bad.append(f"status is {t.get('translation_status')}, expected needs_review")
        st = self.get("/admin/gpu/status")
        if st["queue"]["queued"] or st["queue"]["running"]:
            bad.append(f"GPU jobs are still open: {st['queue']}")
        return bad


def _code(r: httpx.Response) -> str:
    try:
        return str(r.json()["error"]["code"])
    except (ValueError, KeyError, TypeError):
        return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["preflight", "queue", "verify"])
    ap.add_argument("announcement")
    ap.add_argument("language", choices=["en", "id", "ko"])   # Release 1: announcement drafts only ko / en / id
    ap.add_argument("--authorized", default="", help="queue: who approved the pilot, when, and where it is recorded")
    a = ap.parse_args()
    if a.step == "queue" and len(a.authorized) < 10:
        print("queue changes production data: state the approval with --authorized", file=sys.stderr)
        return 2
    try:
        p = Pilot(os.environ.get("HUB_URL", ""), os.environ.get("HUB_TOKEN") or getpass.getpass("Admin token: "))
        if a.step == "queue":
            print(f"queued job {p.queue(a.announcement, a.language)} (approval: {a.authorized})")
            return 0
        bad = p.preflight(a.announcement, a.language) if a.step == "preflight" else p.verify(a.announcement, a.language)
    except (Stop, httpx.HTTPError) as exc:
        print(exc if isinstance(exc, Stop) else type(exc).__name__, file=sys.stderr)
        return 1
    print("\n".join(f"- {b}" for b in bad) or f"{a.step}: ok")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
