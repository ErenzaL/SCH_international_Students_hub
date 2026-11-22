"""Rule-based structured field detection (no LLM required).

Each detected value carries the evidence snippet it came from and ``confirmed: false``; reviewers
confirm or correct values in the admin. Nothing is inferred: a date written without a year keeps
``year: null`` and is flagged, and fields that are not found are simply absent (never guessed).
Structured data is stored separately from the extracted text and never replaces it.
"""
from __future__ import annotations

import re
from typing import Any

KEY_FIELDS = ("deadline", "event_date", "application_period", "time", "location", "fee", "contact",
              "eligibility", "required_documents", "application_method")

_Y = r"(20\d{2})"
_DATE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(_Y + r"\s*[.\-/]\s*(\d{1,2})\s*[.\-/]\s*(\d{1,2})\.?"), "ymd"),
    (re.compile(_Y + r"\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일"), "ymd"),
    (re.compile(r"(?<![\d.])(\d{1,2})\s*월\s*(\d{1,2})\s*일"), "md"),
    (re.compile(r"(?<![\d./-])(\d{1,2})\s*/\s*(\d{1,2})(?![\d/])(?=\s*\(|\s*[~\-]|\s*까지|\s*$)", re.M), "md"),
]
_DATE_A = r"(?:(?P<y1>20\d{2})\s*[.\-/년]\s*(?P<m1>\d{1,2})\s*[.\-/월]\s*(?P<d1>\d{1,2})|(?P<m1b>\d{1,2})\s*[./월]\s*(?P<d1b>\d{1,2}))\s*일?\.?"
_DATE_B = r"(?:(?P<y2>20\d{2})\s*[.\-/년]\s*(?P<m2>\d{1,2})\s*[.\-/월]\s*(?P<d2>\d{1,2})|(?P<m2b>\d{1,2})\s*[./월]\s*(?P<d2b>\d{1,2}))\s*일?\.?"
_PAREN = r"(?:\s*\([^)]{1,6}\))?"
_HHMM = r"(?:\s*\d{1,2}:\d{2})?"
_RANGE = re.compile(_DATE_A + _PAREN + _HHMM + r"\s*(?:~|∼|～|–|—|부터|-)\s*(?P<end>" + _DATE_B + r")" + _PAREN)
_TIME = re.compile(r"(오전|오후|AM|PM|am|pm)?\s*(\d{1,2})\s*[:시]\s*(\d{2})?\s*(분)?(?:\s*(AM|PM|am|pm))?")
_RANGE_SEP = re.compile(r"\s*(?:~|∼|～|–|—|-|부터)\s*")
_DEADLINE_WORDS = re.compile(r"(마감|까지|기한|deadline|due|until|no later than|batas waktu|hạn|截止)", re.I)
_PERIOD_WORDS = re.compile(r"(신청\s*기간|접수\s*기간|모집\s*기간|application period|registration period|기간)", re.I)
_EVENT_WORDS = re.compile(r"(일시|일정|행사일|시험일|date of event|event date|exam date)", re.I)
_URL = re.compile(r"https?://[^\s<>\"')\]]+")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE = re.compile(r"(?<!\d)(?:0\d{1,2}[-.\s]?\d{3,4}[-.\s]?\d{4}|1[0-9]{3}-\d{4})(?!\d)")
_FEE = re.compile(r"(무료|free of charge|\bfree\b|gratis|miễn phí|免费|(?:₩|KRW)[ \t]?\d[\d,]*|"
                  r"\d[\d,]*[ \t]*(?:만[ \t]*)?원(?!문|본|래|칙|장|인|서|어|격|룸))", re.I)
_IDENTIFIER = re.compile(r"\b(?:[A-Z]-\d{1,2}(?:-\d{1,2})?|TOPIK\s?(?:I{1,2}|[12])|ARC|E-\d|F-\d(?:-\d)?|D-\d{1,2})\b")

_LABELS: dict[str, re.Pattern[str]] = {
    "location": re.compile(r"^\s*(?:[-*•·○]\s*)?(?:장소|위치|location|venue|place|tempat|địa điểm|地点)\s*[:：]\s*(.+)$", re.I | re.M),
    "eligibility": re.compile(r"^\s*(?:[-*•·○]\s*)?(?:대상|지원\s*자격|신청\s*자격|자격|eligibility|who can apply|target|sasaran|đối tượng|对象)\s*[:：]\s*(.+)$", re.I | re.M),
    "required_documents": re.compile(r"^\s*(?:[-*•·○]\s*)?(?:제출\s*서류|구비\s*서류|준비물|required documents|documents|dokumen|hồ sơ|所需材料)\s*[:：]\s*(.+)$", re.I | re.M),
    "application_method": re.compile(r"^\s*(?:[-*•·○]\s*)?(?:신청\s*방법|접수\s*방법|지원\s*방법|how to apply|application method|cara mendaftar|cách đăng ký|申请方法)\s*[:：]\s*(.+)$", re.I | re.M),
    "contact": re.compile(r"^\s*(?:[-*•·○]\s*)?(?:문의(?:처)?|연락처|담당|contact|inquiries|kontak|liên hệ|咨询)\s*[:：]\s*(.+)$", re.I | re.M),
    "fee_label": re.compile(r"^\s*(?:[-*•·○]\s*)?(?:비용|참가비|수수료|응시료|fee|cost|biaya|phí|费用)\s*[:：]\s*(.+)$", re.I | re.M),
}


def _snippet(text: str, start: int, end: int, pad: int = 40) -> str:
    s = max(0, start - pad)
    e = min(len(text), end + pad)
    return re.sub(r"\s+", " ", text[s:e]).strip()


def _line_at(text: str, pos: int) -> str:
    s = text.rfind("\n", 0, pos) + 1
    e = text.find("\n", pos)
    return text[s: e if e != -1 else len(text)]


def _valid(y: int | None, m: int, d: int) -> bool:
    return 1 <= m <= 12 and 1 <= d <= 31 and (y is None or 2000 <= y <= 2100)


def find_dates(text: str) -> list[dict[str, Any]]:
    """All explicit dates with position. Year is null when the text does not state it."""
    found: list[dict[str, Any]] = []
    taken: list[tuple[int, int]] = []
    for pat, kind in _DATE_PATTERNS:
        for m in pat.finditer(text):
            if any(a <= m.start() < b for a, b in taken):
                continue
            if kind == "ymd":
                y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            else:
                y, mo, d = None, int(m.group(1)), int(m.group(2))
            if not _valid(y, mo, d):
                continue
            taken.append((m.start(), m.end()))
            found.append(dict(year=y, month=mo, day=d, start=m.start(), end=m.end(),
                              iso=f"{y:04d}-{mo:02d}-{d:02d}" if y else None, text=m.group(0).strip()))
    found.sort(key=lambda x: x["start"])
    return found


def _field(value: Any, evidence: str, **extra: Any) -> dict[str, Any]:
    return {"value": value, "evidence": evidence[:300], "confirmed": False, "source": "rule", **extra}


def extract_structured_fields(text: str) -> dict[str, Any]:
    """Detect candidate fields. Returns {"fields": {...}, "dates": [...], "links": [...], ...}."""
    fields: dict[str, Any] = {}
    dates = find_dates(text)

    # explicit ranges: "2026. 10. 27.(월) ~ 11. 6.(목) 18:00까지", "2026.11.03~2026.11.14", "11월 3일 ~ 11월 14일"
    range_spans: list[tuple[int, int]] = []
    for m in _RANGE.finditer(text):
        y1 = int(m.group("y1")) if m.group("y1") else None
        m1, d1 = int(m.group("m1") or m.group("m1b")), int(m.group("d1") or m.group("d1b"))
        y2 = int(m.group("y2")) if m.group("y2") else None
        m2, d2 = int(m.group("m2") or m.group("m2b")), int(m.group("d2") or m.group("d2b"))
        if y1 is None and y2 is None and not re.search(r"[월일]", m.group(0)):
            continue  # "3.5 ~ 4.1" without a year or 월/일 is too ambiguous (could be numbers/versions)
        if not (_valid(y1, m1, d1) and _valid(y2, m2, d2)):
            continue
        inherited = False
        if y2 is None and y1 is not None and (m2, d2) >= (m1, d1):
            y2, inherited = y1, True  # the end date inherits the year written on the start date
        start_iso = f"{y1:04d}-{m1:02d}-{d1:02d}" if y1 else None
        end_iso = f"{y2:04d}-{m2:02d}-{d2:02d}" if y2 else None
        line = _line_at(text, m.start())
        ev = _snippet(text, m.start(), m.end())
        range_spans.append((m.start(), m.end()))
        if _PERIOD_WORDS.search(line) or _DEADLINE_WORDS.search(line) or _DEADLINE_WORDS.search(text[m.end(): m.end() + 12]):
            fields.setdefault("application_period", _field({"start": start_iso, "end": end_iso}, ev,
                                                           needs_year=start_iso is None or end_iso is None))
            fields.setdefault("deadline", _field(end_iso, ev, needs_year=end_iso is None, year_from_range=inherited,
                                                 date_text=m.group("end").strip()))
        elif _EVENT_WORDS.search(line):
            fields.setdefault("event_date", _field({"start": start_iso, "end": end_iso}, ev,
                                                   needs_year=start_iso is None or end_iso is None))

    for d in dates:
        if any(a <= d["start"] < b for a, b in range_spans):
            continue  # already interpreted as part of a range
        line = _line_at(text, d["start"])
        after = text[d["end"]: d["end"] + 12]
        if "deadline" not in fields and (_DEADLINE_WORDS.search(line) or re.match(r"\s*(\([^)]*\)\s*)?까지", after)):
            fields["deadline"] = _field(d["iso"], _snippet(text, d["start"], d["end"]), needs_year=d["iso"] is None,
                                        date_text=d["text"])
        elif "event_date" not in fields and _EVENT_WORDS.search(line):
            fields["event_date"] = _field(d["iso"], _snippet(text, d["start"], d["end"]), needs_year=d["iso"] is None,
                                          date_text=d["text"])

    for m in _TIME.finditer(text):
        if m.group(1) or m.group(4) or m.group(5) or ":" in m.group(0):
            h = int(m.group(2))
            if h > 24:
                continue
            fields.setdefault("time", _field(m.group(0).strip(), _snippet(text, m.start(), m.end())))
            break

    for key, pat in _LABELS.items():
        m = pat.search(text)
        if m:
            name = "fee" if key == "fee_label" else key
            fields.setdefault(name, _field(m.group(1).strip()[:300], _snippet(text, m.start(), m.end(), 0)))
    if "fee" not in fields:
        m = _FEE.search(text)
        if m:
            fields["fee"] = _field(m.group(0).strip(), _snippet(text, m.start(), m.end()))
    if "contact" not in fields:
        m = _EMAIL.search(text) or _PHONE.search(text)
        if m:
            fields["contact"] = _field(m.group(0).strip(), _snippet(text, m.start(), m.end()))

    links = list(dict.fromkeys(u.rstrip(".,;") for u in _URL.findall(text)))[:30]
    identifiers = list(dict.fromkeys(i.strip() for i in _IDENTIFIER.findall(text)))[:30]
    year_missing = [d["text"] for d in dates if d["year"] is None][:10]
    return {
        "fields": fields,
        "dates": [{k: d[k] for k in ("iso", "text", "year")} for d in dates][:40],
        "links": links,
        "identifiers": identifiers,
        "warnings": ([f"{len(year_missing)} date(s) have no year in the text ({', '.join(year_missing)}); "
                      "confirm the year before approval."] if year_missing else []),
        "fields_confirmed": False,
        "detector": "rules-v1",
    }


def merge_manual_fields(detected: dict[str, Any], manual: dict[str, Any]) -> dict[str, Any]:
    """Human-entered values (from the intake form) override detected ones and count as confirmed."""
    out = {**detected, "fields": dict(detected.get("fields", {}))}
    for k, v in manual.items():
        if v in (None, "", []):
            continue
        out["fields"][k] = {"value": v, "evidence": None, "confirmed": True, "source": "submitter"}
    return out
