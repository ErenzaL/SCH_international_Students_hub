"""Lightweight detection of a document's ORIGINAL language (ko / en / id / vi / zh-CN).

Used when a document is first created, because HTML ``lang`` attributes and source defaults are often site-wide
("ko" on the English pages of Korean government sites). Returns None unless the evidence is clear; callers then
keep the declared language.
"""
from __future__ import annotations

import re

_HANGUL = re.compile(r"[가-힣ᄀ-ᇿ㄰-㆏]")
_HAN = re.compile(r"[一-鿿]")
_LATIN = re.compile(r"[A-Za-zÀ-ɏḀ-ỿ]")
_VI = re.compile(r"[ăâđêôơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]", re.I)
_WORD = re.compile(r"[a-z]+")
_EN = {"the", "and", "of", "to", "in", "for", "is", "are", "with", "be", "you", "your", "must", "will", "this"}
_ID = {"yang", "dan", "untuk", "dengan", "tidak", "dalam", "ini", "itu", "dari", "atau", "akan", "pada", "anda",
       "harus", "mahasiswa"}


def detect_language(text: str, *, min_letters: int = 80) -> str | None:
    sample = (text or "")[:20000]
    hangul = len(_HANGUL.findall(sample))
    han = len(_HAN.findall(sample))
    latin = len(_LATIN.findall(sample))
    letters = hangul + han + latin
    if letters < min_letters:
        return None
    if hangul / letters >= 0.15:
        return "ko"
    if han / letters >= 0.3 and hangul == 0:
        return "zh-CN"
    if latin / letters < 0.8:
        return None
    if len(_VI.findall(sample)) / max(latin, 1) >= 0.02:
        return "vi"
    words = _WORD.findall(sample.lower())
    en = sum(1 for w in words if w in _EN)
    ind = sum(1 for w in words if w in _ID)
    if max(en, ind) < 8:
        return None
    if en >= 2 * ind:
        return "en"
    if ind >= 2 * en:
        return "id"
    return None
