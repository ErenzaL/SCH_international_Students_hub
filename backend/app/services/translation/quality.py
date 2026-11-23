"""Automated checks for machine translations and summaries, and the risk level of the original.

Every check only FLAGS; nothing is repaired. Any finding sets the translation to ``needs_review`` (never shown to
students until a reviewer approves it). On top of the preservation checks of ``translation_drafts`` (URLs, e-mail
addresses, phone numbers, visa codes, numbers, headings, table rows) this adds: wrong target language, truncation /
missing sections, leftover placeholders or prompt wrappers, and numbers, URLs or codes that the original does not
contain (an invented fee, date or requirement).
"""
from __future__ import annotations

import re
from typing import Any

from app.services.language_detect import detect_language
from app.services.translation_drafts import _EMAIL, _VISA, _numbers, _urls, preservation_warnings

# expected length of a translation relative to its original (characters), per direction; anything far below this is
# probably truncated. Korean is much denser than English.
_LENGTH_RATIO = {("ko", "en"): 1.6, ("en", "ko"): 0.45}
_PLACEHOLDER = re.compile(r"</?source_text>|\{\{|\}\}|\[(?:TODO|TBD|TRANSLATION|\.\.\.|…)\]|<\s*(?:placeholder|translation)\s*>"
                          r"|^\s*(?:here is|here's) the translation|^\s*번역(?:문|본)?\s*[:：]", re.I | re.M)
# immigration, employment, insurance, money, deadlines and legal consequences (in Korean and English): an
# unreviewed machine translation of such content is labelled more prominently or held for review (policy)
_HIGH_RISK = re.compile(
    r"\b(visa|immigration|residence (?:card|permit)|alien registration|sojourn|extension of stay|work permit|"
    r"part[- ]time (?:work|job|employment)|employment|insurance|tuition|fee|fine|penalt|deport|illegal|legal|"
    r"deadline|refund|scholarship)\w*|비자|체류|출입국|외국인등록|사증|시간제\s*취업|취업|아르바이트|보험|"
    r"등록금|수수료|벌금|과태료|강제\s*출국|불법|법률|마감|기한|환불|장학금", re.I)


def is_high_risk(*texts: str | None) -> bool:
    return bool(_HIGH_RISK.search(" ".join(t or "" for t in texts)))


def _blocks(text: str) -> int:
    return len([b for b in re.split(r"\n\s*\n", text or "") if b.strip()])


def _wrong_language(translated: str, target: str) -> str | None:
    sample = re.sub(r"https?://\S+|[\w.+-]+@[\w-]+(?:\.[\w-]+)+|\d+", " ", translated or "")
    letters = re.findall(r"[^\W\d_]", sample)
    if len(letters) < 40:
        return None                       # too short to judge reliably
    got = detect_language(sample)
    if target == "ko" and len(re.findall(r"[가-힣]", sample)) / len(letters) < 0.3:
        return got or "unknown"
    if target == "en" and len(re.findall(r"[A-Za-z]", sample)) / len(letters) < 0.6:
        return got or "unknown"
    return None


def validate_translation(original: str, translated: str, source: str, target: str) -> list[dict[str, Any]]:
    """Warnings for a FULL translation (title + body joined by a newline on both sides)."""
    out = preservation_warnings(original, translated)
    wrong = _wrong_language(translated, target)
    if wrong:
        out.append({"type": "language", "value": f"expected {target}, looks like {wrong}"})
    ratio = _LENGTH_RATIO.get((source, target), 1.0)
    if len(original) >= 200 and len(translated) < 0.5 * ratio * len(original):
        out.append({"type": "truncated", "value": f"{len(original)} → {len(translated)} characters"})
    ob, tb = _blocks(original), _blocks(translated)
    if ob >= 4 and tb < 0.75 * ob:
        out.append({"type": "missing_sections", "value": f"{ob} → {tb} paragraphs"})
    if _PLACEHOLDER.search(translated or ""):
        out.append({"type": "placeholder", "value": _PLACEHOLDER.search(translated).group(0)[:40]})  # type: ignore[union-attr]
    out += _invented(original, translated)
    return out


def validate_summary(original: str, summary: str, target: str) -> list[dict[str, Any]]:
    """A summary may leave things out but must not state anything the original does not contain."""
    out: list[dict[str, Any]] = []
    wrong = _wrong_language(summary, target)
    if wrong:
        out.append({"type": "language", "value": f"expected {target}, looks like {wrong}"})
    if _PLACEHOLDER.search(summary or ""):
        out.append({"type": "placeholder", "value": _PLACEHOLDER.search(summary).group(0)[:40]})  # type: ignore[union-attr]
    if len(re.sub(r"\s", "", summary or "")) < 40:
        out.append({"type": "truncated", "value": "summary is empty or too short"})
    return out + _invented(original, summary)


def _invented(original: str, translated: str) -> list[dict[str, Any]]:
    """Multi-digit numbers, URLs, e-mail addresses and visa codes that appear in the output but nowhere in the
    original (dates and amounts are copied, never computed or converted, under the translation rules)."""
    out: list[dict[str, Any]] = []
    o_nums = set(_numbers(original))
    for n in dict.fromkeys(_numbers(translated)):
        if n not in o_nums and n not in original:
            out.append({"type": "number_added", "value": n})
    o_urls = set(_urls(original))
    for u in dict.fromkeys(_urls(translated)):
        if u not in o_urls and u not in original:
            out.append({"type": "url_added", "value": u})
    o_mail = {e.lower() for e in _EMAIL.findall(original)}
    for e in dict.fromkeys(_EMAIL.findall(translated)):
        if e.lower() not in o_mail:
            out.append({"type": "email_added", "value": e})
    o_codes = set(_VISA.findall(original))
    for c in dict.fromkeys(_VISA.findall(translated)):
        if c not in o_codes:
            out.append({"type": "code_added", "value": c})
    return out[:20]
