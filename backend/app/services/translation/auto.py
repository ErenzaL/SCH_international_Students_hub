"""Automatic machine translation (Korean <-> English first) for announcements and Knowledge Center documents.

Design (reuses the existing translation tables, review workflow and durable job queue):

* Trigger: an announcement is published (or re-published after an edit) / a document version becomes active.
  Missing target languages from ``AUTO_TRANSLATE_LANGUAGES`` get a durable ``ingestion_jobs`` row
  (``translate_announcement`` / ``translate_document``), claimed by the worker with ``FOR UPDATE SKIP LOCKED``; a
  restart re-queues it (heartbeat). Publication never waits for a translation.
* Idempotent: a job whose row already holds a machine translation of exactly the current original (same content
  hash) does nothing; an identical original translated before (same hash, same language) is copied, not re-sent to
  the model. One open job per translation row.
* Budget: at most ``TRANSLATION_DAILY_JOB_LIMIT`` translation jobs start per UTC day, a bounded number of model
  calls per job (long documents: title + summary only); an exhausted provider quota defers the job by
  ``TRANSLATION_QUOTA_RETRY_SECONDS`` instead of failing it (bounded number of deferrals).
* Quality: automated checks (``quality.py``); any finding -> ``needs_review`` (never shown to students).
* Display: a clean machine translation is shown to students only when ``PUBLIC_MACHINE_TRANSLATIONS`` is on, always
  labelled as machine translation, with the original one click away; for immigration / employment / insurance / fee
  / legal content it is labelled unverified, or held for review when ``MACHINE_TRANSLATION_HIGH_RISK=review``.
  Human-approved translations always win; a person's edit is never overwritten by the machine.
* Originals, RAG chunks and embeddings are never touched: translations are display-only.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.config import Settings
from app.core.errors import DuplicateError, Forbidden, InvalidState, NotFound
from app.repositories.base import Query, Store, get_one
from app.services.ingestion.errors import IngestionError
from app.services.llm.base import LLMError, LLMProvider
from app.services.translation.quality import is_high_risk, validate_translation
from app.services.translation_drafts import chunk_text, translate_document

log = logging.getLogger("app.translation")

TRANSLATION_JOB_TYPES = ("translate_document", "translate_announcement")
SUPPORTED = ("ko", "en", "id", "vi", "zh-CN")
HUMAN_WORK = ("in_review", "changes_requested", "human_approved", "rejected", "draft")


def now() -> str:
    return datetime.now(UTC).isoformat()


def auto_languages(settings: Settings) -> list[str]:
    return [x for x in (s.strip() for s in settings.auto_translate_languages.split(",")) if x in SUPPORTED]


def daily_budget_exceeded(store: Store, settings: Settings, job_id: str) -> bool:
    """True when today's (UTC) translation job budget is used up (this job excluded)."""
    start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    _rows, n = store.select("ingestion_jobs", Query(
        in_={"job_type": list(TRANSLATION_JOB_TYPES), "status": ["running", "succeeded", "failed"]},
        gte={"started_at": start}, neq={"id": job_id}, cols="id", limit=1), count=True)
    return (n or 0) >= settings.translation_daily_job_limit


def seconds_until_tomorrow() -> int:
    t = datetime.now(UTC)
    nxt = (t + timedelta(days=1)).replace(hour=0, minute=5, second=0, microsecond=0)
    return int((nxt - t).total_seconds())


def public_machine_allowed(settings: Settings, high_risk: bool) -> bool:
    return settings.public_machine_translations and not (high_risk and settings.machine_translation_high_risk == "review")


def automation_state(row: dict[str, Any] | None, job: dict[str, Any] | None) -> str:
    """One status for admins: pending | processing | completed | needs_review | failed | outdated | approved |
    human_draft | missing."""
    if row is None:
        return "missing"
    if row.get("is_outdated"):
        return "outdated"
    if job and job.get("status") == "running":
        return "processing"
    if job and job.get("status") == "queued":
        return "pending"
    st = row.get("translation_status")
    if st == "human_approved":
        return "approved"
    if st == "needs_review":
        return "needs_review"
    if st == "machine_draft":
        return "completed" if row.get("provider") and not row.get("last_edited_by") else "human_draft"
    if st == "todo":
        return "failed" if job and job.get("status") == "failed" else "pending"
    return "human_draft"


class AnnouncementAutoTranslator:
    """Machine translations of published announcements (title + full body; announcements are never summarized)."""

    def __init__(self, store: Store, llm: LLMProvider, settings: Settings, notes: Any):
        self.store = store
        self.llm = llm
        self.settings = settings
        self.notes = notes
        self.ingestion: Any = None    # IngestionService (creates the durable jobs, logs events)
        self.jobs: Any = None         # JobRunner
        self.reviews: Any = None      # TranslationReviewService (original text + hash, reviewer lists)

    # ------------------------------------------------------------------ rows
    @staticmethod
    def machine_made(row: dict[str, Any]) -> bool:
        return bool(row.get("provider")) and not row.get("last_edited_by")

    def human_touched(self, row: dict[str, Any]) -> bool:
        st = row.get("translation_status")
        return st in HUMAN_WORK or (st in ("machine_draft", "needs_review") and not self.machine_made(row))

    def _row(self, announcement_id: str, language: str) -> dict[str, Any] | None:
        return get_one(self.store, "announcement_translations", announcement_id=announcement_id, language_code=language)

    def open_job(self, translation_id: str) -> dict[str, Any] | None:
        rows, _ = self.store.select("ingestion_jobs", Query(
            eq={"job_type": "translate_announcement", "payload->>translation_id": translation_id},
            in_={"status": ["queued", "running"]}, limit=1))
        return rows[0] if rows else None

    def last_job(self, translation_id: str) -> dict[str, Any] | None:
        rows, _ = self.store.select("ingestion_jobs", Query(
            eq={"job_type": "translate_announcement", "payload->>translation_id": translation_id},
            order=[("created_at", True)], limit=1))
        return rows[0] if rows else None

    def _source(self, announcement: dict[str, Any]) -> dict[str, Any]:
        d = get_one(self.store, "source_documents", id=announcement["document_id"])
        s = get_one(self.store, "knowledge_sources", id=d["source_id"]) if d else None
        if s is None:
            raise NotFound("The announcement's source was not found.")
        return s

    # ----------------------------------------------------------------- queue
    def needs_translation(self, row: dict[str, Any] | None, content_hash: str) -> bool:
        if row is None or row["translation_status"] == "todo":
            return True
        if self.human_touched(row):
            return False                      # reviewers own it (they are notified when the original changes)
        return row.get("source_content_hash") != content_hash or bool(row.get("is_outdated"))

    def queue(self, announcement_id: str, language: str, actor_id: str | None, *, force: bool = False,
              background: Any = None, enqueue: bool = True) -> dict[str, Any]:
        a = get_one(self.store, "announcements", id=announcement_id)
        if a is None:
            raise NotFound("Announcement not found.")
        if a["publication_status"] != "published":
            raise InvalidState("Only published announcements are translated automatically.")
        if language == a["original_language"] or language not in SUPPORTED:
            raise InvalidState("The original language does not need a translation.")
        if not self.llm.enabled:
            raise InvalidState("Machine translation needs an LLM provider (LLM_PROVIDER and an API key).",
                               code="llm_disabled")
        row = self._row(announcement_id, language) or self.store.insert("announcement_translations", dict(
            announcement_id=announcement_id, language_code=language, title="", body="", translation_status="todo"))
        if self.human_touched(row) and not force:
            raise InvalidState("A person is working on this translation; a machine translation would replace it.",
                               code="human_draft_exists")
        existing = self.open_job(row["id"])
        if existing:
            return existing
        try:
            job = self.ingestion.create_job(self._source(a), "manual", actor_id, job_type="translate_announcement",
                                            payload=dict(announcement_id=announcement_id, translation_id=row["id"],
                                                         language=language, force=force))
        except DuplicateError:          # queued concurrently (unique index): use that job
            existing = self.open_job(row["id"])
            if existing is None:
                raise
            return existing
        self.ingestion.event(job["id"], "queued", f"Machine translation into {language} queued for the announcement.")
        self.store.insert("audit_log", dict(action="translation.machine_requested", entity_type="announcement",
                                            entity_id=announcement_id, actor_id=actor_id,
                                            details={"language": language, "job_id": job["id"]}))
        if enqueue and self.jobs is not None:     # backfill: leave it to the API worker (enqueue=False)
            self.jobs.enqueue(job, background)
        return job

    def on_published(self, announcement_id: str, actor_id: str | None, background: Any = None) -> list[dict[str, Any]]:
        """Publication hook: queue the missing / outdated machine translations (never blocks publication)."""
        if not (self.settings.auto_translate_announcements and self.llm.enabled and self.ingestion):
            return []
        a = get_one(self.store, "announcements", id=announcement_id)
        if a is None or a["publication_status"] != "published":
            return []
        h = self.reviews.original(announcement_id)["content_hash"]
        out = []
        for lang in auto_languages(self.settings):
            if lang == a["original_language"] or not self.needs_translation(self._row(announcement_id, lang), h):
                continue
            try:
                out.append(self.queue(announcement_id, lang, actor_id, background=background))
            except Exception:  # noqa: BLE001 - a translation must never break publication
                log.exception("could not queue the %s translation of announcement %s", lang, announcement_id)
        return out

    # ------------------------------------------------------------------- run
    def _cached(self, content_hash: str, language: str, exclude: str) -> dict[str, Any] | None:
        rows, _ = self.store.select("announcement_translations", Query(
            eq={"source_content_hash": content_hash, "language_code": language, "translation_status": "machine_draft"},
            neq={"id": exclude}, limit=5))
        return next((r for r in rows if self.machine_made(r)), None)

    def run_job(self, job: dict[str, Any], heartbeat: Any, event: Any) -> dict[str, Any]:
        p = job.get("payload") or {}
        row = get_one(self.store, "announcement_translations", id=p.get("translation_id"))
        if row is None:
            raise IngestionError("translation_missing", "The translation task no longer exists.")
        a = get_one(self.store, "announcements", id=row["announcement_id"])
        if a is None or a["publication_status"] != "published":
            raise IngestionError("source_changed", "The announcement is no longer published; nothing was translated.")
        orig = self.reviews.original(a["id"])
        lang, src = row["language_code"], a["original_language"]
        if self.human_touched(row) and not p.get("force"):
            raise IngestionError("human_draft_exists", "A person edited this translation; the machine translation "
                                                       "was not written.")
        done = dict(outcome="translated", document_id=a["document_id"], version_id=None, changed=False, warning=None)
        if not self.needs_translation(row, orig["content_hash"]) and not p.get("force"):
            return done | dict(message="Already translated from exactly this text; nothing to do.")
        cached = self._cached(orig["content_hash"], lang, row["id"])
        if cached is None:
            if daily_budget_exceeded(self.store, self.settings, job["id"]):
                raise IngestionError("translation_daily_limit", "Today's machine-translation budget is used up; the "
                                                                "job continues tomorrow.")
            parts = len(chunk_text(orig["body"], self.settings.translation_chunk_chars))
            if parts + 1 > self.settings.translation_max_requests_per_job:
                raise IngestionError("too_long", f"The announcement is too long for automatic translation ({parts} "
                                                 "parts); translate it by hand.")
            event(job["id"], "translate", f"Translating from {src} into {lang} with {self.llm.name}:{self.llm.model}.")
            try:
                out = translate_document(self.llm, title=orig["title"], body=orig["body"], source_lang=src,
                                         target_lang=lang, chunk_chars=self.settings.translation_chunk_chars,
                                         on_progress=lambda i, n: heartbeat(job["id"]))
            except LLMError as exc:
                raise IngestionError(exc.code, exc.message) from exc
            title, body, provider, model = out["title"], out["body"], out["provider"], out["model"]
        else:
            event(job["id"], "translate", "Identical text was translated before; reusing that translation.")
            title, body, provider, model = cached["title"], cached["body"], cached.get("provider"), cached.get("model")
        # re-check: the original or the human state may have changed while the model was working
        row = get_one(self.store, "announcement_translations", id=row["id"])
        if row is None or self.reviews.original(a["id"])["content_hash"] != orig["content_hash"]:
            raise IngestionError("source_changed", "The announcement changed while it was translated; discarded.")
        if self.human_touched(row) and not p.get("force"):
            raise IngestionError("human_draft_exists", "A person edited this translation meanwhile; discarded.")
        warnings = validate_translation(f"{orig['title']}\n{orig['body']}", f"{title}\n{body}", src, lang)
        status = "needs_review" if warnings else "machine_draft"
        row = self.store.update("announcement_translations", dict(
            title=title, body=body, translation_status=status, source_content_hash=orig["content_hash"],
            is_outdated=False, provider=provider, model=model, generated_at=now(), warnings=warnings,
            review_note=None, reviewed_by=None, reviewed_at=None, original_verified_by=None, original_verified_at=None,
            last_edited_by=None, last_edited_at=None, submitted_at=None), {"id": row["id"]})[0]
        self.store.insert("translation_revisions", dict(
            translation_id=row["id"], title=title, body=body, translation_status=status,
            source_content_hash=orig["content_hash"], action="generate",
            note=f"machine translation ({provider}:{model}); {len(warnings)} check warning(s)", actor_id=None))
        self.store.insert("audit_log", dict(action="translation.machine_generated", entity_type="announcement",
                                            entity_id=a["id"], actor_id=job.get("requested_by"),
                                            details={"language": lang, "status": status, "warnings": len(warnings),
                                                     "provider": provider, "model": model}))
        if warnings and self.reviews is not None:
            self.notes.notify_many(self.reviews._people(lang, "review"), "translation_review",
                                   f"Machine translation needs review ({lang}): {a['title'][:110]}",
                                   entity_type="announcement", entity_id=a["id"],
                                   link=f"/admin/translations/{a['id']}/{lang}")
        return done | dict(message=f"Machine translation into {lang}: {status} ({len(warnings)} check warning(s)).")

    # ---------------------------------------------------------------- public
    def public_translation(self, a: dict[str, Any], body: str, content_hash: str,
                           language: str | None) -> dict[str, Any] | None:
        """The translation students see for ``language``: human-approved (verified) or, when allowed, a clean
        machine translation of exactly the current text. None = show the original."""
        if not language or language == a["original_language"]:
            return None
        row = self._row(a["id"], language)
        if row is None or row.get("is_outdated") or row.get("source_content_hash") != content_hash:
            return None
        high_risk = is_high_risk(a["title"], body)
        if row["translation_status"] == "human_approved":
            kind = "verified"
        elif row["translation_status"] == "machine_draft" and self.machine_made(row) \
                and public_machine_allowed(self.settings, high_risk):
            kind = "machine"
        else:
            return None
        return dict(status=kind, language=language, title=row["title"], body=row["body"], high_risk=high_risk,
                    reviewed_at=row.get("reviewed_at") if kind == "verified" else None,
                    generated_at=row.get("generated_at") if kind == "machine" else None)

    def admin_info(self, row: dict[str, Any] | None) -> dict[str, Any]:
        job = self.last_job(row["id"]) if row else None
        return dict(state=automation_state(row, job), machine_made=bool(row and self.machine_made(row)),
                    provider=(row or {}).get("provider"), model=(row or {}).get("model"),
                    generated_at=(row or {}).get("generated_at"), warnings=(row or {}).get("warnings") or [],
                    job=dict(id=job["id"], status=job["status"], error_code=job.get("error_code"),
                             error_message=job.get("error_message"), created_at=job["created_at"],
                             run_after=job.get("run_after")) if job else None,
                    llm_enabled=self.llm.enabled)


def translation_llm(settings: Settings, llm: LLMProvider) -> LLMProvider:
    """The provider for translation jobs: TRANSLATION_MODEL (Gemini) as primary with the usual fallback, else the
    assistant's provider. Same key, same retry / quota / circuit-breaker handling."""
    model = (settings.translation_model or "").strip()
    if not model or not llm.enabled or llm.name != "gemini":
        return llm
    from app.services.llm.base import build_llm_from_settings

    return build_llm_from_settings(settings.model_copy(update={"gemini_primary_model": model}))


def require_translation_access(user: Any, language: str, perms: dict[str, bool]) -> None:
    if not (perms.get("can_edit") or perms.get("can_review") or user.role in ("admin", "super_admin")):
        raise Forbidden(f"You are not assigned to {language} translations.")
