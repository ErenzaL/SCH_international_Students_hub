"""OCR providers for screenshots and image-only PDFs.

Chosen for Render's 512 MB free instances, which already hold the E5 embedding model:
  * ``none``       - no OCR; the supporter transcribes the text (always works, the default)
  * ``tesseract``  - open-source Tesseract via its CLI binary (separate process, no model kept in the
                     API's memory). Needs the binary + language data (kor, eng, vie, ind, chi_sim);
                     available locally / in Docker, NOT on Render's native Python runtime.
  * ``ocr_space``  - OCR.space hosted API (free tier, Korean supported). Images leave our servers, so the
                     supporter must confirm the content is authorized for processing (enforced upstream).
OCR output is never trusted: it is stored as raw evidence and must be corrected/confirmed by a human.
"""
from __future__ import annotations

import base64
import logging
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import httpx

from app.core.config import Settings

log = logging.getLogger("app.ocr")
LOW_CONFIDENCE = 60.0  # tesseract word confidence (0-100) below which a line is flagged as uncertain


class OCRUnavailable(Exception):
    """OCR is not configured or the provider cannot run right now (caller falls back to manual text)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class OCRLine:
    text: str
    confidence: float | None = None


@dataclass
class OCRResult:
    text: str
    provider: str
    model: str
    mean_confidence: float | None = None
    lines: list[OCRLine] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    raw_text: str | None = None  # exact provider output (evidence); ``text`` is the cleaned suggestion

    def __post_init__(self) -> None:
        if self.raw_text is None:
            self.raw_text = self.text
            self.text = clean_ocr_text(self.text)

    def uncertain_lines(self) -> list[dict[str, Any]]:
        return [{"text": ln.text, "confidence": ln.confidence} for ln in self.lines
                if ln.confidence is not None and ln.confidence < LOW_CONFIDENCE][:50]


_HANGUL_SYLLABLE = re.compile(r"^[가-힣]$")


def _join_spaced_hangul(line: str) -> str:
    """Tesseract's Korean model often emits '국 제 교 육' for '국제교육'; join runs of single syllables."""
    tokens = line.split(" ")
    out: list[str] = []
    run: list[str] = []
    for t in tokens:
        if _HANGUL_SYLLABLE.match(t):
            run.append(t)
            continue
        if run:
            out.append("".join(run) if len(run) >= 2 else run[0])
            run = []
        out.append(t)
    if run:
        out.append("".join(run) if len(run) >= 2 else run[0])
    return " ".join(x for x in out if x != "")


def clean_ocr_text(text: str) -> str:
    lines = []
    for ln in text.splitlines():
        ln = _join_spaced_hangul(re.sub(r"[ \t]+", " ", ln).strip())
        ln = re.sub(r"\(\s+", "(", re.sub(r"\s+\)", ")", ln))
        lines.append(ln)
    return "\n".join(lines).strip()


class OCRProvider(Protocol):
    name: str

    def available(self) -> tuple[bool, str | None]: ...

    def extract(self, image: bytes, mime_type: str) -> OCRResult: ...


class NoOCR:
    name = "none"

    def available(self) -> tuple[bool, str | None]:
        return False, "OCR is not configured (OCR_PROVIDER=none). Type or paste the text from the image."

    def extract(self, image: bytes, mime_type: str) -> OCRResult:
        raise OCRUnavailable("ocr_not_configured", self.available()[1] or "")


class TesseractOCR:
    name = "tesseract"

    def __init__(self, settings: Settings, binary: str | None = None):
        self.languages = settings.ocr_languages
        self.timeout = settings.ocr_timeout_seconds
        self.binary = binary or shutil.which("tesseract")

    def available(self) -> tuple[bool, str | None]:
        if not self.binary:
            return False, "The tesseract binary is not installed on this server."
        return True, None

    def extract(self, image: bytes, mime_type: str) -> OCRResult:
        ok, why = self.available()
        if not ok:
            raise OCRUnavailable("ocr_unavailable", why or "")
        suffix = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}.get(mime_type, ".png")
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / f"in{suffix}"
            src.write_bytes(image)
            try:  # TSV gives per-word confidences; psm 6 = uniform block (chat bubbles / notices).
                # "-c tessedit_create_tsv=1" works without the 'configs/tsv' file some tessdata folders lack.
                proc = subprocess.run(  # noqa: S603 - fixed binary, no shell, file path we created
                    [self.binary, str(src), "stdout", "-l", self.languages, "--psm", "6", "-c", "tessedit_create_tsv=1"],
                    capture_output=True, timeout=self.timeout, check=False)
            except subprocess.TimeoutExpired as exc:
                raise OCRUnavailable("ocr_timeout", f"OCR took longer than {self.timeout:.0f}s.") from exc
        if proc.returncode != 0:
            msg = proc.stderr.decode("utf-8", "replace").strip().splitlines()[-1:] or ["unknown error"]
            raise OCRUnavailable("ocr_failed", f"Tesseract failed: {msg[0][:300]}")
        out = proc.stdout.decode("utf-8", "replace")
        if not out.startswith("level\t"):  # plain text (no TSV): keep the text, report no confidence
            text = out.strip()
            return OCRResult(text=text, provider="tesseract", model=f"tesseract:{self.languages}",
                             lines=[OCRLine(t) for t in text.splitlines() if t.strip()],
                             warnings=["OCR confidence is unavailable for this result; verify every line."])
        return _parse_tsv(out, self.languages)


def _parse_tsv(tsv: str, languages: str) -> OCRResult:
    rows = [r.split("\t") for r in tsv.splitlines()[1:]]
    lines: dict[tuple[str, str, str], list[tuple[str, float]]] = {}
    order: list[tuple[str, str, str]] = []
    for r in rows:
        if len(r) < 12 or r[0] != "5":
            continue
        word, conf = r[11].strip(), float(r[10]) if r[10] not in ("", "-1") else -1.0
        if not word:
            continue
        key = (r[2], r[3], r[4])  # block, paragraph, line
        if key not in lines:
            lines[key] = []
            order.append(key)
        lines[key].append((word, conf))
    out_lines: list[OCRLine] = []
    prev_block = None
    text_parts: list[str] = []
    confs: list[float] = []
    for key in order:
        words = lines[key]
        joined = " ".join(w for w, _ in words)
        c = [cf for _, cf in words if cf >= 0]
        conf = sum(c) / len(c) if c else None
        confs.extend(c)
        out_lines.append(OCRLine(joined, round(conf, 1) if conf is not None else None))
        if prev_block is not None and key[0] != prev_block:
            text_parts.append("")
        text_parts.append(joined)
        prev_block = key[0]
    mean = round(sum(confs) / len(confs), 1) if confs else None
    warnings = []
    if mean is not None and mean < LOW_CONFIDENCE:
        warnings.append(f"Low OCR confidence ({mean:.0f}/100): check every line against the image.")
    return OCRResult(text="\n".join(text_parts).strip(), provider="tesseract", model=f"tesseract:{languages}",
                     mean_confidence=mean, lines=out_lines, warnings=warnings)


class OCRSpace:
    name = "ocr_space"
    URL = "https://api.ocr.space/parse/image"

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self.key = settings.ocr_space_api_key
        self.language = settings.ocr_space_language
        self.engine = settings.ocr_space_engine
        self.timeout = settings.ocr_timeout_seconds
        self._transport = transport

    def available(self) -> tuple[bool, str | None]:
        if not self.key:
            return False, "OCR_SPACE_API_KEY is not set."
        return True, None

    def extract(self, image: bytes, mime_type: str) -> OCRResult:
        ok, why = self.available()
        if not ok:
            raise OCRUnavailable("ocr_unavailable", why or "")
        payload = {
            "base64Image": f"data:{mime_type};base64," + base64.b64encode(image).decode(),
            "language": self.language, "OCREngine": str(self.engine), "scale": "true",
            "isOverlayRequired": "false", "detectOrientation": "true",
        }
        try:
            with httpx.Client(timeout=self.timeout, transport=self._transport) as c:
                r = c.post(self.URL, data=payload, headers={"apikey": self.key})
        except httpx.HTTPError as exc:
            raise OCRUnavailable("ocr_failed", f"OCR service unreachable ({type(exc).__name__}).") from exc
        if r.status_code != 200:
            raise OCRUnavailable("ocr_failed", f"OCR service returned HTTP {r.status_code}.")
        try:
            body = r.json()
        except ValueError as exc:
            raise OCRUnavailable("ocr_failed", "OCR service returned an unreadable response.") from exc
        if body.get("IsErroredOnProcessing"):
            msg = body.get("ErrorMessage") or body.get("ErrorDetails") or "processing error"
            raise OCRUnavailable("ocr_failed", f"OCR service error: {msg if isinstance(msg, str) else '; '.join(msg)}")
        text = "\n".join((p.get("ParsedText") or "").strip() for p in body.get("ParsedResults") or []).strip()
        return OCRResult(text=text, provider="ocr_space", model=f"ocr.space-engine{self.engine}:{self.language}",
                         lines=[OCRLine(t) for t in text.splitlines() if t.strip()],
                         warnings=["This OCR service does not report confidence; verify every line."])


def build_ocr_provider(settings: Settings) -> OCRProvider:
    name = (settings.ocr_provider or "none").lower()
    if name == "tesseract":
        return TesseractOCR(settings)
    if name in ("ocr_space", "ocrspace"):
        return OCRSpace(settings)
    return NoOCR()
