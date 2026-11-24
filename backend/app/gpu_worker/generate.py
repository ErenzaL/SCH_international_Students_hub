"""Turn one job into a draft with the local model, using the Hub's own prompts and checks."""
from __future__ import annotations

import logging
import re
import threading
from typing import Any

from app.gpu_worker.glossary import terms_in
from app.services.llm.base import LLMError, LLMResult
from app.services.translation.facts import renderings
from app.services.translation.quality import local_translation_warnings
from app.services.translation_drafts import LANGUAGE_NAMES, summarize_document, translate_document

log = logging.getLogger("gpu_worker")
LANGS = {"ko", "en", "id", "vi", "zh-CN"}
_SOURCE = re.compile(r"<source_text>\n(.*)\n</source_text>", re.S)
MAX_REPAIRS = 2
_FACTS = ("url", "email", "phone", "code", "number")
# the shared prompt's examples turned up in drafts: a small model repeats them as if they were part of the notice
_EXAMPLES = re.compile(r" \(for example D-2, D-4-1, F-2-7\)")
HINTS = """

Use exactly these forms wherever the source text contains the item on the left (do not copy this list):
{pairs}"""
REPAIR = """

Your previous translation had these problems: {missing}
Translate the source text again, completely, into {target} only. Keep every line, list item, URL, e-mail address, phone \
number, code, amount, date and weekday. Do not add anything."""


class Cancelled(Exception):
    pass


class CheckedModel:
    """The model plus help and control per call. Help: the exact form of every date (with weekday) and amount, and the
    terms of the glossary that occur in the text. Control: when the result lost something, got a weekday wrong, repeated
    instructions or slipped into another language, it is translated again with the problems named (at most twice) and the
    best version is kept. A version that is still in the wrong language is refused (llm_malformed: the job is retried)."""

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
        return [f"{w['value']}" if w["type"] in _FACTS else f"{w['type']}: {w['value']}"
                for w in local_translation_warnings(src, out, self.source, self.target)]

    def _wrong_language(self, src: str, out: str) -> bool:
        letters = len(re.findall(r"[^\W\d_]", out)) or 1
        han, hangul = len(re.findall(r"[\u4e00-\u9fff]", out)), len(re.findall(r"[가-힣]", out))
        if self.target != "zh-CN" and han / letters > 0.03 and han > 2 * len(re.findall(r"[\u4e00-\u9fff]", src)):
            return True
        return self.target != "ko" and hangul / letters > 0.3 and letters > 12

    def complete(self, system: str, prompt: str, **kw: Any) -> LLMResult:
        m = _SOURCE.search(prompt)
        if not self.repair or m is None:
            return self._call(system, prompt, **kw)
        src = m.group(1)
        system = _EXAMPLES.sub("", system)
        # a line like "<title>" looks like a tag to the model (a whole section was dropped after one)
        clean = re.sub(r"<([^<>\n]{2,80})>", r"[\1]", src)
        base = prompt.replace(src, clean, 1)
        if self.source == "ko":
            pairs = renderings(src, self.target) + terms_in(src, self.target)
            if pairs:
                base += HINTS.format(pairs="\n".join(f"- {a} → {b}" for a, b in pairs))
        best = self._call(system, base, **kw)
        problems = self._problems(clean, best.text)
        for _ in range(MAX_REPAIRS):
            if not problems:
                break
            self.repairs += 1
            try:
                again = self._call(system, base + REPAIR.format(missing="; ".join(problems[:20]),
                                                                target=LANGUAGE_NAMES[self.target]), **kw)
            except LLMError:
                break
            found = self._problems(clean, again.text)
            if len(found) >= len(problems) and not (self._wrong_language(clean, best.text)
                                                    and not self._wrong_language(clean, again.text)):
                break
            best, problems = again, found
        if self._wrong_language(clean, best.text):
            raise LLMError("llm_malformed", "The model answered in the wrong language.", transient=True)
        return best


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
