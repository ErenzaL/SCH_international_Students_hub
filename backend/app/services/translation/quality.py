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


_HAN = re.compile(r"[\u4e00-\u9fff]")
# instructions of the prompts that a small model may repeat as if they were part of the notice
_LEAK = re.compile(r"source_?text|exactly as (?:it is )?written|copied? exactly|D-2, D-4-1|output only|直接翻译|不会添加|以下是翻译|"
                   r"use exactly these forms|previous translation", re.I)
_ITEM = re.compile(r"^\s*(?:#{1,4}\s|\*{1,2}\S|>|[-*•■▣▶▸○◦∘ㅇ※·⇓|①-⑳Ⅰ-Ⅹ]|\d{1,2}\s*[.)]|[가-하A-Za-z]\s*[.)])", re.M)
_ASCII_URL = re.compile(r"https?://[\x21-\x7e]+")


def local_translation_warnings(original: str, translated: str, source: str, target: str) -> list[dict[str, Any]]:
    """All checks for a FULL translation made by a local model: the shared checks, minus flags for dates, amounts and
    times that are there in another form ("December 1"), plus what small local models get wrong: weekdays, missing list
    items, instructions repeated in the text. Their drafts are always reviewed, so this decides what a reviewer sees."""
    from app.services.translation.facts import explained_numbers, wrong_weekdays

    # a URL directly followed by Chinese or Korean text is not a new URL
    spaced = lambda t: _ASCII_URL.sub(lambda m: m[0].rstrip(".,;:)]") + " ", t)  # noqa: E731
    out = validate_translation(spaced(original), spaced(translated), source, target)
    if source == "ko" and target in ("en", "id", "vi", "zh-CN"):
        ok_src, ok_new, missing = explained_numbers(original, translated, target)
        out = [w for w in out if not (w["type"] == "number" and w["value"] in ok_src)
               and not (w["type"] == "number_added" and w["value"] in ok_new)]
        out += [{"type": "number", "value": m} for m in missing]
        out += [{"type": "number", "value": w} for w in wrong_weekdays(original, translated, target)]
        # added headings and merged line breaks change the look, not the content: lost list items do
        out = [w for w in out if w["type"] not in ("headings", "missing_sections")]
        o, t = len(_ITEM.findall(original)), len(_ITEM.findall(translated))
        if t < o - 1:
            out.append({"type": "missing_sections", "value": f"{o} → {t} list items"})
        if target == "zh-CN":       # Chinese needs about 0.55 characters per Korean character
            out = [w for w in out if w["type"] != "truncated" or len(translated) < 0.4 * len(original)]
    if _LEAK.search(translated) and not _LEAK.search(original):
        out.append({"type": "placeholder", "value": _LEAK.search(translated).group(0)[:40]})  # type: ignore[union-attr]
    return out + local_model_warnings(original, translated, source, target)
_HANGUL = re.compile(r"[가-힣]")


def local_model_warnings(original: str, translated: str, source: str, target: str) -> list[dict[str, Any]]:
    """Extra checks for small local models (Qwen), which tend to slip into Chinese or to return the source text
    unchanged. Only applied to their output: other providers' checks are unchanged."""
    out: list[dict[str, Any]] = []
    if target != "zh-CN":
        allowed = set(_HAN.findall(original))
        stray = [c for c in _HAN.findall(translated) if c not in allowed]
        # official Chinese names may stay (translation rules), whole sentences may not
        if source == "zh-CN" and len(_HAN.findall(translated)) > 0.1 * len(translated):
            stray = _HAN.findall(translated)
        if stray:
            out.append({"type": "language", "value": f"{len(stray)} Chinese character(s)"})
    if target != "ko":
        letters = re.findall(r"[^\W\d_]", translated)
        # official Korean names may stay (translation rules), whole sentences may not
        if len(letters) >= 40 and len(_HANGUL.findall(translated)) / len(letters) > 0.25:
            out.append({"type": "language", "value": "mostly Korean text left"})
    if target in ("id", "vi", "zh-CN"):           # ko / en are covered by _wrong_language
        got = detect_language(re.sub(r"https?://\S+|[\w.+-]+@[\w-]+(?:\.[\w-]+)+", " ", translated))
        if got and got != target:
            out.append({"type": "language", "value": f"expected {target}, looks like {got}"})
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
