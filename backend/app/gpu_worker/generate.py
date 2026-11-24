"""Turn one job into a draft with the local model, using the Hub's own prompts and checks."""
from __future__ import annotations

import logging
import re
import threading
from typing import Any

from app.services.llm.base import LLMError, LLMResult
from app.services.translation.quality import local_model_warnings
from app.services.translation_drafts import preservation_warnings, summarize_document, translate_document

log = logging.getLogger("gpu_worker")
LANGS = {"ko", "en", "id", "vi", "zh-CN"}
_SOURCE = re.compile(r"<source_text>\n(.*)\n</source_text>", re.S)
_FACTS = ("url", "email", "phone", "code", "number")
REPAIR = """

Your previous translation lost or changed these parts of the source: {missing}
Translate again, completely, into {target} only. Every URL, e-mail address, phone number, code, amount, date and \
deadline of the source must appear exactly as it is written there."""


class Cancelled(Exception):
    pass


class CheckedModel:
    """The model plus one repair attempt per call: when a translated part lost a fact (URL, amount, date, code ...) or
    slipped into another language, it is translated once more with the lost parts named, and the better version is
    kept. What still differs is flagged by the server's checks; a person reviews every draft."""

    def __init__(self, llm: Any, source: str, target: str, cancelled: threading.Event, *, repair: bool):
        self.llm, self.source, self.target, self.cancelled, self.repair = llm, source, target, cancelled, repair
        self.max_source_chars = llm.max_source_chars
        self.calls = self.repairs = self.input_tokens = self.output_tokens = 0

    def _call(self, system: str, prompt: str, **kw: Any) -> LLMResult:
        if self.cancelled.is_set():
            raise Cancelled
        self.calls += 1
        try:
            r = self.llm.complete(system, prompt, **kw)
        except LLMError:
            if self.cancelled.is_set():
                raise Cancelled from None
            raise
        self.input_tokens += r.input_tokens
        self.output_tokens += r.output_tokens
        return r

    def _problems(self, src: str, out: str) -> list[str]:
        lost = [w["value"] for w in preservation_warnings(src, out) if w["type"] in _FACTS]
        return lost + [w["value"] for w in local_model_warnings(src, out, self.source, self.target)]

    def complete(self, system: str, prompt: str, **kw: Any) -> LLMResult:
        first = self._call(system, prompt, **kw)
        m = _SOURCE.search(prompt)
        if not self.repair or m is None:
            return first
        before = self._problems(m.group(1), first.text)
        if not before:
            return first
        self.repairs += 1
        from app.services.translation_drafts import LANGUAGE_NAMES

        try:
            second = self._call(system, prompt + REPAIR.format(missing="; ".join(before[:20]),
                                                               target=LANGUAGE_NAMES[self.target]), **kw)
        except LLMError:
            return first
        return second if len(self._problems(m.group(1), second.text)) < len(before) else first


def check_job(job: Any) -> dict[str, Any]:
    """The server is trusted, but a malformed job must fail cleanly."""
    if not isinstance(job, dict) or job.get("mode") not in ("translate", "summarize") \
            or job.get("source_language") not in LANGS or job.get("target_language") not in LANGS \
            or not all(isinstance(job.get(k), str) and job[k].strip() for k in ("id", "lease_token", "title", "body")) \
            or not all(isinstance(job.get(k), int) and job[k] > 0 for k in ("chunk_chars", "max_source_chars",
                                                                           "lease_seconds", "max_seconds")):
        raise ValueError("invalid job")
    return job


def generate(llm: Any, job: dict[str, Any], cancelled: threading.Event) -> tuple[dict[str, Any], CheckedModel]:
    summarize = job["mode"] == "summarize"
    model = CheckedModel(llm, job["source_language"], job["target_language"], cancelled, repair=not summarize)
    common = dict(title=job["title"], body=job["body"], source_lang=job["source_language"],
                  target_lang=job["target_language"])
    if summarize:
        model.max_source_chars = min(llm.max_source_chars, job["max_source_chars"])
        return summarize_document(model, max_source_chars=job["max_source_chars"], **common), model
    return translate_document(model, chunk_chars=job["chunk_chars"], **common), model
