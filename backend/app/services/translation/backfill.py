"""Controlled backfill of machine translations for content that is already published.

* ``plan``: read-only. Lists every (item, language) pair that needs a machine translation, the mode (full
  translation, or title + summary for long documents), and an estimate of model requests and tokens.
* ``apply``: creates at most ``limit`` durable jobs (oldest first) and returns. It never runs them: the API's worker
  claims queued jobs (one at a time) and respects the daily translation budget and provider quota (deferral).
  Re-running is safe: pairs with an open job, a current machine translation or human work are skipped, so an
  interrupted backfill resumes where it stopped. Originals are never modified.
"""
from __future__ import annotations

import math
from typing import Any

from app.repositories.base import Query, get_many
from app.services.translation.auto import auto_languages, machine_languages
from app.services.translation_drafts import chunk_text

# rough model tokenizer densities (characters per token) for the estimate; system prompt per request
_CHARS_PER_TOKEN = {"ko": 1.6, "zh-CN": 1.4, "en": 4.0, "id": 4.0, "vi": 3.2}
_SYSTEM_TOKENS = 380
_SUMMARY_OUTPUT_TOKENS = 700


def _tokens(chars: int, lang: str) -> int:
    return math.ceil(chars / _CHARS_PER_TOKEN.get(lang, 3.0))


def plan(svc: Any, languages: list[str] | None = None) -> dict[str, Any]:
    s = svc.settings
    langs = languages or auto_languages(s)
    ann_langs = [x for x in langs if x in machine_languages(s)]    # Release 1: announcement drafts only ko, en, id
    items: list[dict[str, Any]] = []
    tr = svc.announcement_translator

    anns, _ = svc.store.select("announcements", Query(eq={"publication_status": "published"}))
    for a in anns:
        orig = svc.translations.original(a["id"])
        chars = len(orig["title"]) + len(orig["body"])
        parts = len(chunk_text(orig["body"], s.translation_chunk_chars))
        for lang in ann_langs:
            if lang == a["original_language"]:
                continue
            row = tr._row(a["id"], lang)
            if not tr.needs_translation(row, orig["content_hash"]):
                continue
            items.append(dict(kind="announcement", id=a["id"], title=a["title"][:80], language=lang,
                              source_language=a["original_language"], chars=chars, mode="full",
                              requests=parts + 1, too_long=parts + 1 > s.translation_max_requests_per_job,
                              queued=bool(row and tr.open_job(row["id"]))))

    dt = svc.doc_translations
    docs = svc.public._public_documents_all()
    versions = get_many(svc.store, "document_versions", [d["current_version_id"] for d in docs])
    for d in docs:
        v = versions.get(d["current_version_id"])
        if not v or v.get("verification_status") != "approved":
            continue
        body = v.get("extracted_text") or ""
        parts = len(chunk_text(body, s.translation_chunk_chars))
        summary = len(body) > s.translation_full_max_chars or parts + 1 > s.translation_max_requests_per_job
        src = d.get("language") or "ko"
        for lang in langs:
            if lang == src:
                continue
            row = dt._current(d["id"], v["id"], lang)
            st = (row or {}).get("translation_status", "todo")
            if row is not None and (st not in ("todo",) and not (st in ("machine_draft", "needs_review") and
                                                                  row.get("source_content_hash") != v["content_hash"])):
                continue      # done, or a person's work
            items.append(dict(kind="document", id=d["id"], title=d["title"][:80], language=lang, source_language=src,
                              chars=len(d["title"]) + len(body), mode="summary" if summary else "full",
                              requests=2 if summary else parts + 1, too_long=False,
                              queued=bool(row and dt._open_job(row["id"]))))

    for it in items:
        if it["mode"] == "summary":
            src_chars = min(it["chars"], s.translation_summary_source_chars)
            it["input_tokens"] = 2 * _SYSTEM_TOKENS + _tokens(src_chars, it["source_language"]) + 60
            it["output_tokens"] = _SUMMARY_OUTPUT_TOKENS + 40
        else:
            src_tokens = _tokens(it["chars"], it["source_language"])
            it["input_tokens"] = it["requests"] * _SYSTEM_TOKENS + src_tokens
            # the translation carries the same content in the target language's density
            it["output_tokens"] = _tokens(int(it["chars"] * _length_ratio(it["source_language"], it["language"])),
                                          it["language"])
    todo = [i for i in items if not i["queued"] and not i["too_long"]]
    return dict(
        languages=langs, pairs=len(items), already_queued=sum(i["queued"] for i in items),
        too_long_for_automatic=[i for i in items if i["too_long"]],
        announcements=sum(i["kind"] == "announcement" for i in items),
        documents=sum(i["kind"] == "document" for i in items),
        long_documents_summary_only=sorted({(i["id"], i["title"], i["chars"]) for i in items if i["mode"] == "summary"}),
        requests=sum(i["requests"] for i in todo), input_tokens=sum(i["input_tokens"] for i in todo),
        output_tokens=sum(i["output_tokens"] for i in todo),
        days_at_daily_job_limit=math.ceil(len(todo) / max(1, s.translation_daily_job_limit)),
        items=items)


def _length_ratio(src: str, tgt: str) -> float:
    return {("ko", "en"): 1.6, ("en", "ko"): 0.45}.get((src, tgt), 1.0)


def apply(svc: Any, limit: int, languages: list[str] | None = None, *, kinds: list[str] | None = None) -> list[dict[str, Any]]:
    """Queue up to ``limit`` jobs from the plan (announcements first, then documents); returns what was queued."""
    out: list[dict[str, Any]] = []
    for it in plan(svc, languages)["items"]:
        if len(out) >= limit:
            break
        if it["queued"] or it["too_long"] or (kinds and it["kind"] not in kinds):
            continue
        if it["kind"] == "announcement":
            job = svc.announcement_translator.queue(it["id"], it["language"], None, enqueue=False)
        else:
            dt = svc.doc_translations
            dt.sync(it["id"])
            d, s, v = dt._context(it["id"])
            job = dt._queue(d, s, v, it["language"], None, force=False)
        out.append(dict(kind=it["kind"], id=it["id"], language=it["language"], job_id=job["id"], mode=it["mode"]))
    return out
