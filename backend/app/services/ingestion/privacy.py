"""Privacy redaction for KakaoTalk-derived text (applied by default; Phase 1 is manual paste only).

Removes sender names/timestamps from chat-export lines and masks phone numbers,
e-mail addresses, resident-registration-like numbers and bank-account-like numbers,
so personal information is not stored or indexed.
"""
from __future__ import annotations

import re

# PC export: "2024. 3. 5. 오후 3:21, 홍길동 : message"   /  mobile: "[홍길동] [오후 3:21] message"
_PC_LINE = re.compile(r"^\s*\d{4}[.\-/]\s*\d{1,2}[.\-/]\s*\d{1,2}\.?\s*(?:오전|오후|AM|PM)?\s*\d{1,2}:\d{2}\s*,\s*[^:\n]{1,40}?\s:\s*", re.M)
_MOBILE_LINE = re.compile(r"^\s*\[[^\]\n]{1,40}\]\s*\[(?:오전|오후|AM|PM)?\s*\d{1,2}:\d{2}\]\s*", re.M)
_DATE_SEPARATOR = re.compile(r"^\s*-{3,}\s*\d{4}년.*?-{3,}\s*$", re.M)
_PHONE = re.compile(r"(?<!\d)(?:\+?82[-\s]?)?0?1[016789][-.\s]?\d{3,4}[-.\s]?\d{4}(?!\d)")
_LANDLINE = re.compile(r"(?<!\d)0(?:2|[3-6]\d)[-.\s]\d{3,4}[-.\s]\d{4}(?!\d)")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_RRN = re.compile(r"(?<!\d)\d{6}[-\s]?[1-8]\d{6}(?!\d)")
_ACCOUNT = re.compile(r"(?<!\d)\d{2,6}-\d{2,6}-\d{2,8}(?:-\d{1,4})?(?!\d)")


def redact_personal_info(text: str) -> tuple[str, dict[str, int]]:
    stats = {"sender_lines": 0, "phones": 0, "emails": 0, "id_numbers": 0, "account_numbers": 0}

    def sub(pattern: re.Pattern[str], repl: str, key: str, s: str) -> str:
        s, n = pattern.subn(repl, s)
        stats[key] += n
        return s

    text = sub(_PC_LINE, "", "sender_lines", text)
    text = sub(_MOBILE_LINE, "", "sender_lines", text)
    text, _ = _DATE_SEPARATOR.subn("", text)
    text = sub(_RRN, "[redacted id number]", "id_numbers", text)
    text = sub(_EMAIL, "[redacted email]", "emails", text)
    text = sub(_PHONE, "[redacted phone]", "phones", text)
    text = sub(_LANDLINE, "[redacted phone]", "phones", text)
    def _account(m: re.Match[str]) -> str:
        if re.fullmatch(r"(?:19|20)\d{2}-\d{1,2}-\d{1,2}", m.group(0)):  # an ISO-style date, not an account
            return m.group(0)
        stats["account_numbers"] += 1
        return "[redacted account number]"

    text = _ACCOUNT.sub(_account, text)
    return text, stats
