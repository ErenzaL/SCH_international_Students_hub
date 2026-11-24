"""Dates (with weekday), money and times of Korean announcements: exact renderings for the local model's prompt, and the
matching checks for its drafts. Only used for drafts of local models (never for other providers)."""
from __future__ import annotations

import re
from typing import Any

WEEK_KO = "월화수목금토일"
WEEK = {
    "en": ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"),
    "id": ("Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"),
    "vi": ("Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"),
    "zh-CN": ("周一", "周二", "周三", "周四", "周五", "周六", "周日"),
}
MONTHS = {
    "en": ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"),
    "id": ("Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober", "November", "Desember"),
}
_WD = r"(?:\s*\(\s*([월화수목금토일])\s*\))?"
_FULL = re.compile(r"(20\d\d)\s*(?:[.\-/]|년)\s*(\d{1,2})\s*(?:[.\-/]|월)\s*(\d{1,2})\s*(?:[.일])?" + _WD)
_SHORT = re.compile(r"(?<![\d.,/:-])(\d{1,2})\s*(?:월|[./])\s*(\d{1,2})\s*(?:일|\.)?" + _WD + r"(?![\d:])")
_MONEY = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(천만|백만|십만|만|천|억)?\s*원")
_UNIT = {"": 1, "천": 1e3, "만": 1e4, "십만": 1e5, "백만": 1e6, "천만": 1e7, "억": 1e8}
_LINK = re.compile(r"https?://[\x21-\x7e]+|[\w.+-]+@[\w-]+(?:\.[\w-]+)+|(?<!\d)0\d{1,2}[-.\s]\d{3,4}[-.\s]\d{4}(?!\d)", re.A)


def _plain(text: str) -> str:
    return _LINK.sub(" ", re.sub(r"\\([~_\[\]*])", r"\1", text or ""))


def _ok(m: int, d: int) -> bool:
    return 1 <= m <= 12 and 1 <= d <= 31


def ko_dates(text: str) -> list[dict[str, Any]]:
    """Dates in reading order: source text, year (or None), month, day, weekday index (or None)."""
    out, taken = [], []
    t = _plain(text)
    for m in _FULL.finditer(t):
        if _ok(int(m[2]), int(m[3])):
            out.append(dict(src=m[0].strip(), pos=m.start(), year=int(m[1]), month=int(m[2]), day=int(m[3]),
                            weekday=WEEK_KO.index(m[4]) if m[4] else None))
            taken.append(m.span())
    for m in _SHORT.finditer(t):
        if any(a <= m.start() < b for a, b in taken) or not _ok(int(m[1]), int(m[2])):
            continue
        if "월" not in m[0] and not m[3] and "/" not in m[0]:
            continue                # "2.5", "3.0": not a date without a weekday
        out.append(dict(src=m[0].strip(), pos=m.start(), year=None, month=int(m[1]), day=int(m[2]),
                        weekday=WEEK_KO.index(m[3]) if m[3] else None))
    return sorted(out, key=lambda x: x["pos"])


def render_date(d: dict[str, Any], lang: str) -> str:
    y, m, day = d["year"], d["month"], d["day"]
    if lang == "en":
        s = f"{MONTHS['en'][m - 1]} {day}" + (f", {y}" if y else "")
    elif lang == "id":
        s = f"{day} {MONTHS['id'][m - 1]}" + (f" {y}" if y else "")
    elif lang == "vi":
        s = f"{day}/{m}" + (f"/{y}" if y else "")
    else:
        s = (f"{y}年" if y else "") + f"{m}月{day}日"
    if d["weekday"] is not None:
        s += f"（{WEEK[lang][d['weekday']]}）" if lang == "zh-CN" else f" ({WEEK[lang][d['weekday']]})"
    return s


def ko_money(text: str) -> list[tuple[str, int]]:
    out = []
    for m in _MONEY.finditer(_plain(text)):
        v = int(round(float(m[1].replace(",", "")) * _UNIT[m[2] or ""]))
        if v >= 100:
            out.append((m[0].strip(), v))
    return out


def render_money(v: int, lang: str) -> str:
    n = f"{v:,}"
    return f"{n.replace(',', '.')} won" if lang in ("id", "vi") else f"{n}韩元" if lang == "zh-CN" else f"{n} won"


def renderings(text: str, lang: str, limit: int = 30) -> list[tuple[str, str]]:
    """(as written in the source, exactly how to write it) for the dates and amounts of a Korean text."""
    if lang not in WEEK:
        return []
    pairs = [(d["src"], render_date(d, lang)) for d in ko_dates(text)]
    pairs += [(s, render_money(v, lang)) for s, v in ko_money(text)]
    return list(dict.fromkeys(pairs))[:limit]


# -------------------------------------------------------------------------------- checks
def target_dates(text: str, lang: str) -> list[tuple[int, int, int, int]]:
    """(month, day, start, end) of every reading of a date in a draft (d/m and m/d are both accepted)."""
    t = _plain(text)
    out: list[tuple[int, int, int, int]] = []

    def add(m: str, d: str, x: re.Match[str]) -> None:
        if _ok(int(m), int(d)):
            out.append((int(m), int(d), x.start(), x.end()))

    for x in re.finditer(r"20\d\d\s*[.\-/年]\s*(\d{1,2})\s*[.\-/月]\s*(\d{1,2})\s*日?", t):
        add(x[1], x[2], x)
    for x in re.finditer(r"(?<![\d.,:])(\d{1,2})\s*[./-]\s*(\d{1,2})(?:\s*[./-]\s*20\d\d)?(?![\d:])", t):
        add(x[1], x[2], x)
        add(x[2], x[1], x)
    for x in re.finditer(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日?", t):
        add(x[1], x[2], x)
    for x in re.finditer(r"(\d{1,2})\s*tháng\s*(\d{1,2})(?:\s*năm\s*20\d\d)?", t, re.I):
        add(x[2], x[1], x)
    for i, name in enumerate(MONTHS.get(lang, ()), 1):
        n = rf"{name[:3]}(?:{name[3:]}|\.)?" if len(name) > 4 else name
        for x in re.finditer(rf"\b{n}\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?!:)(?:,?\s*20\d\d)?", t, re.I):
            add(str(i), x[1], x)
        for x in re.finditer(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?{n}\b(?:,?\s*20\d\d)?", t, re.I):
            add(str(i), x[1], x)
    return out


def _weekday_after(text: str, lang: str) -> int | None:
    """Index of the weekday written right after a date, e.g. '(Friday)', ', Thứ Sáu', '（周五）'."""
    head = text[:24].lower()
    if lang == "vi":
        m = re.match(r"[\s,(（]*(?:thứ\s*)?(hai|ba|tư|năm|sáu|bảy|chủ nhật|[2-7])\b(?!\s*20)", head)
        names = ["hai", "ba", "tư", "năm", "sáu", "bảy", "chủ nhật"]
        if not m or not re.match(r"[\s,]*[(（]|[\s,]*thứ|[\s,]*chủ", head):
            return None
        return int(m[1]) - 2 if m[1].isdigit() else names.index(m[1])
    if lang == "zh-CN":
        m = re.match(r"\s*[(（]?\s*(?:周|星期|礼拜)\s*([一二三四五六日天])", head)
        return "一二三四五六日".index(m[1].replace("天", "日")) if m else None
    m = re.match(r"[\s,(（]*([a-z]+)", head)
    if not m:
        return None
    for i, n in enumerate(WEEK[lang]):
        if len(m[1]) >= 3 and (n.lower().startswith(m[1]) or (lang == "id" and m[1] in ("jum'at", "jumaat") and i == 4)):
            return i
    return None


def wrong_weekdays(source: str, draft: str, lang: str) -> list[str]:
    """Dates whose weekday in the draft differs from the source."""
    want = {(d["month"], d["day"]): d["weekday"] for d in ko_dates(source) if d["weekday"] is not None}
    t = _plain(draft)
    out, right = [], set()
    for m, d, _s, e in target_dates(draft, lang):
        got = _weekday_after(t[e:], lang)
        if got is None or (m, d) not in want:
            continue
        if want[m, d] == got:
            right.add((m, d))
        else:
            out.append((m, d, got))
    return list(dict.fromkeys(f"{m}/{d}: {WEEK[lang][want[m, d]]}, not {WEEK[lang][g]}" for m, d, g in out if (m, d) not in right))


def _amounts(text: str) -> set[int]:
    unit = {"thousand": 1e3, "million": 1e6, "ribu": 1e3, "juta": 1e6, "nghìn": 1e3, "ngàn": 1e3, "triệu": 1e6, "千": 1e3,
            "万": 1e4, "百万": 1e6, "千万": 1e7, "": 1}
    out = set()
    for m in re.finditer(r"(\d[\d.,]*)\s*(thousand|million|ribu|juta|nghìn|ngàn|triệu|千万|百万|万|千)?", text.lower()):
        raw = m[1].rstrip(".,")
        for v in (re.sub(r"[.,]", "", raw), raw.replace(",", ".") if re.fullmatch(r"\d+[.,]\d", raw) else ""):
            if v:
                out.add(int(round(float(v) * unit[m[2] or ""])))
    return out


def explained_numbers(source: str, draft: str, lang: str) -> tuple[set[str], set[str], list[str]]:
    """(digits of the source that the draft expresses in another form, digits the draft may add for that reason,
    facts that are really missing). Digits as in ``translation_drafts._numbers`` (no separators)."""
    ok_src: set[str] = set()
    ok_new: set[str] = set()
    missing: list[str] = []
    have = {(m, d) for m, d, _a, _b in target_dates(draft, lang)}
    for d in ko_dates(source):
        m, day = d["month"], d["day"]
        forms = {f"{m}", f"{m:02d}", f"{day}", f"{day:02d}"}
        years = {str(d["year"])} if d["year"] else set()
        if (m, day) in have:
            ok_src |= forms | {f"{d['year']}{a}{b}" for a in (f"{m}", f"{m:02d}") for b in (f"{day}", f"{day:02d}")} \
                | {f"{a}{b}" for a in (f"{m}", f"{m:02d}") for b in (f"{day}", f"{day:02d}")}
            ok_new |= forms | years | {f"{a}{b}{y}" for a in (f"{day}", f"{day:02d}") for b in (f"{m}", f"{m:02d}")
                                       for y in ("", *years)} | {f"{y}{b}{a}" for a in (f"{day}", f"{day:02d}")
                                                                 for b in (f"{m}", f"{m:02d}") for y in ("", *years)}
        else:
            missing.append(d["src"])
    amounts = _amounts(_plain(draft))
    for src, v in ko_money(source):
        if v in amounts:
            ok_src |= {re.sub(r"\D", "", src)}
            ok_new |= {str(v), *(str(v // k) for k in (1000, 10000, 1000000) if v % k == 0)}
        else:
            missing.append(src)
    for h, mi in re.findall(r"(?<!\d)(\d{1,2})\s*(?::|시)\s*([0-5]\d)?", _plain(source)):
        mi = mi or "00"
        hh = int(h)
        new = {f"{hh:02d}{mi}", f"{hh}{mi}", f"{hh % 12 or 12}", f"{hh:02d}", mi, f"{hh + 12}{mi}" if hh < 12 else ""} - {""}
        if re.search(rf"(?<!\d)0?{hh}\s*[:.h時时点]\s*{mi}|(?<!\d){hh % 12 or 12}(?::{mi})?\s*[ap]\.?m|(?<!\d)0?{hh}\s*(?:giờ|点|时)", draft, re.I):
            ok_src |= {h, f"{hh:02d}", mi}
            ok_new |= new
    return ok_src, ok_new, list(dict.fromkeys(missing))
