"""Document families: editions of the same notice ("2025 동계방학 입사생 모집" / "2026 동계방학 입사생 모집"), exact copies of one
notice that arrived through two sources, and dates that have passed. Pure functions over search hits: nothing is deleted or
merged in the database, every document keeps its own provenance.

* Same family = same organization and the same title once year and semester are removed. Seasons, building names and every
  other word stay: a summer notice is not an edition of the winter notice, and "향설 2관" is not "향설 1관".
* An edition is *older* only when both periods are known (year / semester in the title, else the publication date).
* A question that names the older year gets the older edition.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from app.services.retrieval.query_analysis import token_set

_YEAR = re.compile(r"(?<!\d)(20\d{2})(?!\d)\s*(?:년도|학년도|년|년도\s*)?")
_SEM = re.compile(r"제?\s*([12])\s*학기|\b(spring|fall|autumn|1st|2nd)\s+semester\b|\bsemester\s+([12])\b", re.I)
_PERIOD = re.compile(r"제?\s*\d{1,3}\s*(?:회|차)(?![가-힣])")          # 제105회, 2차: editions of a series
_SEM_NUM = {"spring": 1, "1st": 1, "fall": 2, "autumn": 2, "2nd": 2}
MIN_KEY = 6
COPY_OVERLAP = 0.8


@dataclass(frozen=True)
class Period:
    year: int
    part: int = 0          # semester / series number, 0 = unknown

    def older_than(self, other: Period) -> bool:
        if self.year != other.year:
            return self.year < other.year
        return bool(self.part and other.part and self.part < other.part)


def family_key(title: str, organization: str | None) -> str | None:
    t = _PERIOD.sub(" ", _SEM.sub(" ", _YEAR.sub(" ", title or "")))
    key = re.sub(r"[\W_]+", "", t.lower())
    if len(key) < MIN_KEY:
        return None
    return f"{re.sub(r'[^a-z0-9가-힣]+', '', (organization or '').lower())}|{key}"


def _day(v: Any) -> date | None:
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def period_of(title: str, published: Any) -> Period | None:
    y = [int(x) for x in _YEAR.findall(title or "")]
    m = _SEM.search(title or "")
    part = 0
    if m:
        part = int(m[1] or m[3] or 0) or _SEM_NUM.get((m[2] or "").lower(), 0)
    else:
        n = re.search(r"제?\s*(\d{1,3})\s*(?:회|차)(?![가-힣])", title or "")
        part = int(n[1]) if n else 0
    if y:
        return Period(max(y), part)
    d = _day(published)
    if d is None:
        return None
    return Period(d.year, part or d.month * 100 + d.day)


def asked_years(question: str) -> set[int]:
    return {int(x) for x in re.findall(r"(?<!\d)(20\d{2})(?!\d)", question or "")}


def annotate(hits: list[dict[str, Any]], question: str = "") -> list[dict[str, Any]]:
    """The same hits, in order, with ``superseded_by`` (a newer edition is among the hits) and ``copy_of`` (the same
    notice from another source; the newest verified copy is kept as the original)."""
    years = asked_years(question)
    docs: dict[str, dict[str, Any]] = {}
    for h in hits:
        d = docs.setdefault(h["document_id"], dict(
            id=h["document_id"], title=h.get("document_title") or "", key=family_key(h.get("document_title") or "", h.get("organization")),
            period=period_of(h.get("document_title") or "", h.get("source_published_at")),
            verified=str(h.get("verified_at") or ""), tokens=set()))
        d["tokens"] |= token_set(h.get("passage") or "")
    marks: dict[str, dict[str, str]] = {}
    families: dict[str, list[dict[str, Any]]] = {}
    for d in docs.values():
        if d["key"]:
            families.setdefault(d["key"], []).append(d)
    for members in families.values():
        if len(members) < 2:
            continue
        for d in members:
            newer = [o for o in members if o is not d and d["period"] and o["period"] and d["period"].older_than(o["period"])]
            if newer and d["period"].year not in years:
                best = max(newer, key=lambda o: (o["period"].year, o["period"].part))
                marks[d["id"]] = {"superseded_by": best["id"], "superseded_by_title": best["title"]}
    # copies: identical normalized titles (including the year) and nearly the same text, any organization
    by_title: dict[str, list[dict[str, Any]]] = {}
    for d in docs.values():
        t = re.sub(r"[\W_]+", "", d["title"].lower())
        if len(t) >= MIN_KEY:
            by_title.setdefault(t, []).append(d)
    for same in by_title.values():
        same.sort(key=lambda d: (d["verified"], d["id"]), reverse=True)
        for d in same[1:]:
            keep = same[0]
            if d["id"] in marks or keep["id"] in marks:
                continue
            a, b = d["tokens"], keep["tokens"]
            if a and b and len(a & b) / len(a | b) >= COPY_OVERLAP:
                marks[d["id"]] = {"copy_of": keep["id"]}
    return [dict(h, **marks[h["document_id"]]) if h["document_id"] in marks else h for h in hits]


def reorder(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Superseded editions and copies after everything else (stable); nothing is dropped."""
    return [h for h in hits if not (h.get("superseded_by") or h.get("copy_of"))] + \
        [h for h in hits if h.get("superseded_by") or h.get("copy_of")]


def deadline_status(title: str, passages: list[str], published: Any, today: date) -> dict[str, Any] | None:
    """The last deadline a notice states and whether it has passed (quoted dates only; a date without a year uses the
    publication year and is only trusted when that is known)."""
    from app.services.agents.tools import extract_dates

    pub = _day(published)
    years = [int(y) for y in _YEAR.findall(title)]
    year = pub.year if pub else max(years) if years else None
    found = [d for d in extract_dates("\n".join([title, *passages]), default_year=year or today.year, limit=30)
             if d["kind"] == "deadline" and (year or not d["year_assumed"])]
    if not found:
        return None
    last = max(d["date"] for d in found)
    return dict(date=last, passed=last < today.isoformat())
