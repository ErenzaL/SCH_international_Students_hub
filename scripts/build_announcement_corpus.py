"""Corpus of real, public SCH announcements for the translation benchmark.

    cd backend
    .venv/bin/python ../scripts/build_announcement_corpus.py --candidates   # fetch public notices into .eval-cache
    .venv/bin/python ../scripts/build_announcement_corpus.py --select A,B   # write the manifest for reviewed notices
    .venv/bin/python ../scripts/build_announcement_corpus.py                # re-fetch exactly the manifest, check hashes

The notices belong to the university: their text is cached in backend/.eval-cache (git-ignored, never committed). Only
the manifest (URL, date, SHA-256, length) is in the repository, so anybody can rebuild the same corpus; a notice that
was edited since is reported as changed. Uses the application's guarded fetcher (allowlist, robots.txt, 1.5 s between
requests) with a neutral client name. No login, no database.

Non-sensitive only: notices with mobile numbers, identity / student / account numbers, private mail addresses or
lists of people are dropped automatically; every remaining notice must be read by a person before it is selected.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.core.config import Settings  # noqa: E402
from app.services.discovery.connectors import Connectors  # noqa: E402
from app.services.ingestion.fetcher import GuardedFetcher  # noqa: E402
from app.services.ingestion.normalize import normalize_text  # noqa: E402
from app.services.ingestion.sch_board import page_url, parse_listing, parse_notice  # noqa: E402

CACHE = ROOT / "backend" / ".eval-cache"
CANDIDATES, CORPUS = CACHE / "announcement_candidates.json", CACHE / "announcement_corpus.json"
MANIFEST = ROOT / "scripts" / "benchmarks" / "announcement_corpus_manifest.json"
BOARD = "https://sgee.sch.ac.kr/notice/notice01.php?table_name=noti_fore&loc_mnu=3"
LISTING = dict(item_selector="table tbody tr", title_selector="td.subject a", date_selector="td.date",
               link_selector="td.subject a", skip_selector="span.notice", content_selector="div.board_contents",
               attachment_selector="div.board_file", max_items=10, delay_seconds=1.5)
LISTINGS = {"academic": "https://home.sch.ac.kr/sch/06/010200.jsp", "scholarship": "https://home.sch.ac.kr/sch/06/010300.jsp"}
SENSITIVE = {
    "mobile number": r"(?<!\d)01[016789][-.\s]?\d{3,4}[-.\s]?\d{4}(?!\d)",
    "identity number": r"(?<!\d)\d{6}[-\s]?[1-8]\d{6}(?!\d)",
    "student number": r"(?<!\d)20[12]\d{5}(?!\d)|학번\s*[:：]?\s*\d{5,}",
    "account number": r"계좌\s*(?:번호)?\s*[:：]?\s*[\w가-힣\s]{0,12}\d{2,6}-\d{2,6}-\d{2,}",
    "private mail": r"[\w.+-]+@(?:gmail|naver|daum|hanmail|kakao|outlook|hotmail|qq|163)\.",
    "list of people": r"(?:합격자|선발자|수상자|당첨자|대상자)\s*(?:명단|발표)",
}


def digest(title: str, text: str) -> str:
    return hashlib.sha256(f"{title}\n\n{text}".encode()).hexdigest()


def reasons(text: str) -> list[str]:
    return [k for k, rx in SENSITIVE.items() if re.search(rx, text)]


def item(group: str, title: str, url: str, posted: str | None, text: str) -> dict:  # type: ignore[type-arg]
    text = normalize_text(text).strip()
    return dict(group=group, title=title.strip(), url=url, posted=posted, text=text, chars=len(text),
                sha256=digest(title.strip(), text))


def fetcher() -> GuardedFetcher:
    return GuardedFetcher(Settings(_env_file=None, fetch_user_agent="research-client/1.0"))


def candidates(pages: int) -> list[dict]:  # type: ignore[type-arg]
    f, out = fetcher(), []
    for p in range(1, pages + 1):
        refs = parse_listing(f.fetch(page_url(BOARD, p), "ko").content, BOARD)
        for ref in refs:
            time.sleep(1.5)
            if any(ref.url == x["url"] for x in out):
                continue
            try:
                n = parse_notice(f.fetch(ref.url, "ko").content, ref)
                out.append(item("international", n.title, ref.url, ref.posted, n.body_text))
            except Exception as exc:  # noqa: BLE001 - a notice without text is simply not a candidate
                print(f"skipped {ref.notice_no}: {getattr(exc, 'code', type(exc).__name__)}")
        time.sleep(1.5)
    c = Connectors(f, delay_seconds=1.5)
    for group, url in LISTINGS.items():
        for e in c.run(dict(kind="listing", url=url, language="ko", config=LISTING)).entries:
            out.append(item(group, e.title, e.url, e.published_on, e.text))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", action="store_true")
    ap.add_argument("--pages", type=int, default=4)
    ap.add_argument("--select", default="", help="comma-separated sha256 prefixes of notices a person has read")
    ap.add_argument("--set", default="", help="another set of notices, e.g. heldout")
    a = ap.parse_args()
    global CORPUS, MANIFEST
    if a.set:
        CORPUS = CACHE / f"announcement_corpus_{a.set}.json"
        MANIFEST = MANIFEST.with_name(f"announcement_corpus_manifest_{a.set}.json")
    CACHE.mkdir(exist_ok=True)
    if a.candidates:
        rows = candidates(a.pages)
        for r in rows:
            r["sensitive"] = reasons(r["title"] + "\n" + r["text"])
            r["usable"] = not r["sensitive"] and 120 <= r["chars"] <= 8000
        CANDIDATES.write_text(json.dumps(rows, ensure_ascii=False, indent=1))
        print(f"{len(rows)} notices, {sum(r['usable'] for r in rows)} usable -> {CANDIDATES}")
        return 0
    if a.select:
        rows = json.loads(CANDIDATES.read_text())
        chosen = []
        for prefix in a.select.split(","):
            m = [r for r in rows if r["sha256"].startswith(prefix.strip())]
            if len(m) != 1 or not m[0]["usable"]:
                print(f"{prefix}: not exactly one usable notice", file=sys.stderr)
                return 1
            chosen += m
        MANIFEST.write_text(json.dumps(dict(
            note="Public SCH notices used by scripts/bench_announcements.py. Texts are not stored in the repository.",
            notices=[dict(id=f"{'H' if a.set else 'N'}{i:02d}", **{k: r[k] for k in ("group", "url", "posted", "chars", "sha256")})
                     for i, r in enumerate(chosen, 1)]), indent=1) + "\n")
        CORPUS.write_text(json.dumps([dict(r, id=f"{'H' if a.set else 'N'}{i:02d}") for i, r in enumerate(chosen, 1)], ensure_ascii=False, indent=1))
        print(f"{len(chosen)} notices -> {MANIFEST}")
        return 0
    old = {r["sha256"]: r for r in (json.loads(CORPUS.read_text()) if CORPUS.exists() else [])}
    want, f, out, changed = json.loads(MANIFEST.read_text())["notices"], None, [], 0
    for w in want:
        if w["sha256"] in old:
            out.append(old[w["sha256"]])
            continue
        f = f or fetcher()
        time.sleep(1.5)
        page = f.fetch(w["url"], "ko")
        if w["group"] == "international":
            from app.services.ingestion.sch_board import NoticeRef

            n = parse_notice(page.content, NoticeRef("", "", "", w["url"], w["posted"], None, False))
            r = item(w["group"], n.title, w["url"], w["posted"], n.body_text)
        else:
            print(f"{w['id']}: rebuild the {w['group']} notices with --candidates and --select")
            changed += 1
            continue
        if r["sha256"] != w["sha256"]:
            print(f"{w['id']}: the notice was edited since the manifest was made")
            changed += 1
        out.append(dict(r, id=w["id"]))
    CORPUS.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"{len(out)}/{len(want)} notices, {changed} changed -> {CORPUS}")
    return 1 if changed else 0


if __name__ == "__main__":
    raise SystemExit(main())
