"""Text normalization and content hashing (hash is the version-dedup key)."""
from __future__ import annotations

import hashlib
import re
import unicodedata

_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍⁠﻿"), None)
_MULTISPACE = re.compile(r"[ \t ]+")
_MANY_NEWLINES = re.compile(r"\n{3,}")


def normalize_text(text: str) -> str:
    """NFC-normalize, unify newlines, drop zero-width chars, collapse whitespace.

    Structure (blank-line paragraph breaks, markdown headings, list markers) is preserved.
    """
    text = unicodedata.normalize("NFC", text).translate(_ZERO_WIDTH)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [_MULTISPACE.sub(" ", ln).strip() for ln in text.split("\n")]
    return _MANY_NEWLINES.sub("\n\n", "\n".join(lines)).strip()


def content_hash(text: str) -> str:
    """SHA-256 of the normalized text (so cosmetic whitespace changes do not create versions)."""
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def text_fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
