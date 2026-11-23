"""Source-quality checks (read-only): who published a document, is it valid, how old, which version, overlaps.

Pure functions over document metadata/text; they never modify a source. Missing metadata is reported as
``unknown`` - it is never interpreted as valid or official. Thresholds are configuration, not policy.

    report = assess_documents(docs, SourceQualityConfig(official_domains=settings.allowed_domains))

Each ``doc`` is a dict with any of: id, title, authority_type, source_url, valid_from, valid_until,
source_published_at, approved_at, verification_status, is_current, text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from app.core.constants import OFFICIAL_AUTHORITIES

_EDITION = re.compile(r"((?:19|20)\d{2})\s*(?:년\s*)?(?:개정판|개정|판|edition|ed\.|version|revised)", re.I)
_WORD = re.compile(r"[가-힣]+|[A-Za-z]{2,}|\d+")


@dataclass
class SourceQualityConfig:
    official_authorities: tuple[str, ...] = OFFICIAL_AUTHORITIES
    official_domains: list[str] = field(default_factory=list)   # e.g. Settings.allowed_domains
    max_age_days: int = 3 * 365                                 # older publication -> "review age" (not "invalid")
    overlap_containment: float = 0.5                            # share of a document's shingles found in another
    shingle_size: int = 5


def _date(v: Any) -> datetime | None:
    if not v:
        return None
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def _host_ok(url: str, domains: list[str]) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in domains)


def declared_edition_year(title: str | None, text: str | None) -> int | None:
    """Edition / revision year the document states about itself ("2021 개정판", "2019 edition"), from the title and
    the first 3000 characters. Text evidence only - never authoritative metadata."""
    m = _EDITION.search(f"{title or ''} {(text or '')[:3000]}")
    return int(m.group(1)) if m else None


def age_review_warning(published: datetime | None, title: str | None, text: str | None, max_age_days: int,
                       now: datetime | None = None) -> str | None:
    """Reviewer warning when a document's publication date or declared edition is older than ``max_age_days``.

    Generic (no document-specific rule): it asks the reviewer to verify time-sensitive guidance; it never changes
    metadata, validity or what is published.
    """
    now = now or datetime.now(UTC)
    year = declared_edition_year(title, text)
    pub = published if (published is None or published.tzinfo) else published.replace(tzinfo=UTC)
    old_pub = pub is not None and (now - pub).days > max_age_days
    old_ed = year is not None and now.year - year > max_age_days // 365
    if not (old_pub or old_ed):
        return None
    parts = ([f"published {pub.date().isoformat()}"] if old_pub and pub else []) + \
        ([f"declares a {year} edition"] if old_ed else [])
    return (f"Older source: {' and '.join(parts)}. Verify time-sensitive guidance (fees, amounts, deadlines, visa, "
            "work and insurance rules, contacts) against current official sources before approving, and set a "
            "validity date if parts are outdated.")


def assess_document(doc: dict[str, Any], cfg: SourceQualityConfig, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    out: dict[str, Any] = dict(id=doc.get("id"), title=doc.get("title"), flags=[])
    # --- official identity
    at = doc.get("authority_type")
    out["authority"] = "unknown" if not at else ("official" if at in cfg.official_authorities else at)
    url = doc.get("source_url")
    if not url:
        out["domain"] = "unknown"
        out["flags"].append("no_source_url")
    elif not cfg.official_domains:
        out["domain"] = "unknown"           # no allowlist configured: cannot verify
    else:
        out["domain"] = "listed" if _host_ok(url, cfg.official_domains) else "unlisted"
        if out["domain"] == "unlisted":
            out["flags"].append("unlisted_domain")
    if out["authority"] == "unknown":
        out["flags"].append("authority_unknown")
    # --- validity window
    vf, vu = _date(doc.get("valid_from")), _date(doc.get("valid_until"))
    if vu and vu <= now:
        out["validity"] = "expired"
        out["flags"].append("expired")
    elif vf and vf > now:
        out["validity"] = "not_yet_valid"
    elif vf or vu:
        out["validity"] = "valid"
    else:
        out["validity"] = "unknown"         # no validity period recorded: NOT assumed valid
    # --- publication date / age
    pub = _date(doc.get("source_published_at"))
    if pub:
        out["published"] = pub.date().isoformat()
        out["age_days"] = (now - pub).days
        if out["age_days"] > cfg.max_age_days:
            out["flags"].append("old_publication")
    else:
        out["published"] = "unknown"
        out["age_days"] = None
    out["declared_edition_year"] = declared_edition_year(doc.get("title"), doc.get("text"))  # text evidence only
    if out["declared_edition_year"] and now.year - out["declared_edition_year"] > cfg.max_age_days // 365:
        out["flags"].append("old_declared_edition")
    # --- version status
    st = doc.get("verification_status")
    if st is None:
        out["version_status"] = "unknown"
    elif st == "approved" and doc.get("is_current", True):
        out["version_status"] = "current_approved"
    else:
        out["version_status"] = st
        out["flags"].append(f"version_{st}")
    return out


def _shingles(text: str, k: int) -> set[tuple[str, ...]]:
    w = [x.lower() for x in _WORD.findall(text or "")]
    return {tuple(w[i:i + k]) for i in range(max(0, len(w) - k + 1))}


def overlaps(docs: list[dict[str, Any]], cfg: SourceQualityConfig) -> list[dict[str, Any]]:
    """Duplicated / overlapping content between documents: containment of A's word shingles in B."""
    sh = {d["id"]: _shingles(d.get("text") or "", cfg.shingle_size) for d in docs if d.get("text")}
    out = []
    for a, sa in sh.items():
        for b, sb in sh.items():
            if a == b or not sa:
                continue
            c = len(sa & sb) / len(sa)
            if c >= cfg.overlap_containment:
                out.append(dict(document=a, contained_in=b, containment=round(c, 3)))
    return out


def assess_documents(docs: list[dict[str, Any]], cfg: SourceQualityConfig | None = None,
                     now: datetime | None = None) -> dict[str, Any]:
    cfg = cfg or SourceQualityConfig()
    rows = [assess_document(d, cfg, now) for d in docs]
    ov = overlaps(docs, cfg)
    for r in rows:
        r["overlaps"] = [o for o in ov if o["document"] == r["id"]]
        if r["overlaps"]:
            r["flags"].append("overlapping_content")
    keys = ("authority", "domain", "validity", "published", "version_status")
    summary = {k: sum(1 for r in rows if r[k] == "unknown") for k in keys}
    return dict(documents=rows, overlaps=ov, unknown_counts=summary,
                flag_counts={f: sum(f in r["flags"] for r in rows) for f in sorted({f for r in rows for f in r["flags"]})})
