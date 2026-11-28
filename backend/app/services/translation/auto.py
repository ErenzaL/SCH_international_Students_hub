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
from app.core.errors import DuplicateError, Forbidden, InvalidState, NotFound, ValidationFailed
from app.repositories.base import Query, Store, get_one
from app.services.gpu_routing import announcement_route, available_workers, gemini_fallback, routed_types
from app.services.ingestion.errors import IngestionError
from app.services.llm.base import LLMError, LLMProvider
from app.services.translation.quality import is_high_risk, local_translation_warnings, validate_translation
from app.services.translation_drafts import chunk_text, translate_document

log = logging.getLogger("app.translation")

TRANSLATION_JOB_TYPES = ("translate_document", "translate_announcement")
BLOCKED_MESSAGES = {
    "translation_worker_disabled": "Announcement translations are made by the university GPU worker, which is not "
                                   "switched on (GPU_WORKER_ENABLED). The server's Gemini is not used for them "
                                   "(TRANSLATION_FALLBACK_TO_GEMINI=false). Translate by hand meanwhile.",
    "llm_disabled": "Machine translation needs an AI provider (the GPU worker, or LLM_PROVIDER with an API key and "
                    "TRANSLATION_FALLBACK_TO_GEMINI=true).",
}
SUPPORTED = ("ko", "en", "id", "vi", "zh-CN")
HUMAN_WORK = ("in_review", "changes_requested", "human_approved", "rejected", "draft")


def now() -> str:
    return datetime.now(UTC).isoformat()


def machine_languages(settings: Settings) -> list[str]:
    """Languages in which announcements get MACHINE drafts (Release 1: ko, en, id)."""
    return [x for x in (s.strip() for s in settings.announcement_machine_languages.split(",")) if x in SUPPORTED]


def auto_languages(settings: Settings) -> list[str]:
    allowed = machine_languages(settings)
    return [x for x in (s.strip() for s in settings.auto_translate_languages.split(",")) if x in allowed]


def require_not_touched_since(row: dict[str, Any], job: dict[str, Any], forced: bool) -> None:
    """"Replace the person's draft" was decided for the draft of that moment, not for work done while the job waited."""
    touched = [datetime.fromisoformat(x) for x in (row.get("last_edited_at"), row.get("reviewed_at")) if x]
    if forced and touched and max(touched) > datetime.fromisoformat(job["created_at"]):
        raise IngestionError("human_draft_exists", "A person worked on this translation after the request; nothing was "
                                                   "replaced.")


def daily_budget_exceeded(store: Store, settings: Settings, job_id: str) -> bool:
    """True when today's (UTC) translation job budget is used up (this job excluded). Jobs of the GPU worker use no
    model quota and are not counted."""
    start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    _rows, n = store.select("ingestion_jobs", Query(
        in_={"job_type": list(TRANSLATION_JOB_TYPES), "status": ["running", "succeeded", "failed"]},
        gte={"started_at": start}, neq={"id": job_id}, cols="id", limit=1,
        eq={"executor": "local"} if settings.gpu_worker_enabled else {}), count=True)
    return (n or 0) >= settings.translation_daily_job_limit


def seconds_until_tomorrow() -> int:
    t = datetime.now(UTC)
    nxt = (t + timedelta(days=1)).replace(hour=0, minute=5, second=0, microsecond=0)
    return int((nxt - t).total_seconds())


def public_machine_allowed(settings: Settings, high_risk: bool) -> bool:
    return settings.public_machine_translations and not (high_risk and settings.machine_translation_high_risk == "review")


# a queued job with one of these codes waits for a quota / budget / the emergency stop (not an error of the text)
DEFER_CODES = ("llm_quota", "translation_daily_limit", "llm_background_budget", "llm_background_stopped")


def _ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        t = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def job_stalled(job: dict[str, Any] | None, settings: Settings, at: datetime | None = None) -> bool:
    """A job nobody is working on although it should be: queued and due for longer than the worker needs to pick it
    up, or running without a heartbeat (its worker died; the claim re-queues it)."""
    if not job:
        return False
    at = at or datetime.now(UTC)
    if job.get("executor") == "gpu":
        # waiting for the GPU worker is not "stalled" (an idle worker looks for work every 5-60 min); a leased job is
        # stalled once its lease ran out (the worker died): the sweep / a new request puts it back in the queue
        lease = _ts(job.get("lease_expires_at"))
        return job.get("status") == "running" and lease is not None and lease < at
    if job.get("status") == "running":
        beat = _ts(job.get("heartbeat_at")) or _ts(job.get("started_at"))
        return beat is not None and (at - beat).total_seconds() > settings.job_stale_seconds
    if job.get("status") == "queued":
        times = [x for x in (_ts(job.get("run_after")), _ts(job.get("created_at")), _ts(job.get("updated_at"))) if x]
        due = max(times) if times else None
        return due is not None and due <= at and \
            (at - due).total_seconds() > max(settings.translation_stall_seconds, 3 * settings.job_poll_seconds)
    return False


def automation_state(row: dict[str, Any] | None, job: dict[str, Any] | None, settings: Settings | None = None) -> str:
    """One status for admins:
    ready (nothing requested yet) | pending (queued) | processing | stalled (queued or running but nobody works on it) |
    quota (waiting for a quota / budget / the emergency stop) | retrying (an automatic retry after an error) |
    completed (unreviewed machine draft) | needs_review | failed (retry available) | outdated | approved |
    human_draft (a person is working on it)."""
    if row is None:
        return "ready"
    if row.get("is_outdated"):
        return "outdated"
    open_job = job if job and job.get("status") in ("queued", "running") else None
    if open_job:
        if settings is not None and job_stalled(open_job, settings):
            return "stalled"
        if open_job["status"] == "running":
            return "processing"
        if open_job.get("error_code") in DEFER_CODES and (_ts(open_job.get("run_after")) or datetime.now(UTC)) > datetime.now(UTC):
            return "quota"
        if open_job.get("error_code") and (_ts(open_job.get("run_after")) or datetime.now(UTC)) > datetime.now(UTC):
            return "retrying"
        return "pending"
    st = row.get("translation_status")
    if st == "human_approved":
        return "approved"
    if st == "needs_review":
        return "needs_review" if not row.get("last_edited_by") else "human_draft"
    if st == "machine_draft":
        return "completed" if row.get("provider") and not row.get("last_edited_by") else "human_draft"
    if st == "todo":
        return "failed" if job and job.get("status") == "failed" else "ready"
    return "human_draft"


def clean_targets(targets: Any, original: str, allowed: list[str]) -> list[str]:
    """Selected machine-translation languages: known, in this release's scope, never the original, no duplicates."""
    out: list[str] = []
    for x in targets or []:
        x = str(x).strip()
        if x in allowed and x != original and x not in out:
            out.append(x)
    return out


class AnnouncementAutoTranslator:
    """Machine translations of published announcements (title + full body; announcements are never summarized)."""

    def __init__(self, store: Store, llm: LLMProvider, settings: Settings, notes: Any):
        self.store = store
        self.llm = llm
        self.settings = settings
        self.notes = notes
        self.ingestion: Any = None    # IngestionService (creates the durable jobs, logs events)
        self.jobs: Any = None         # JobRunner
        self.public: Any = None       # PublicService: what students can see right now
        self.reviews: Any = None      # TranslationReviewService (original text + hash, reviewer lists)
        self.services: Any = None     # the Services container (backfill planning)

    def route(self) -> tuple[str | None, str | None]:
        """('gpu' | 'local', None) or (None, reason): see gpu_routing.announcement_route."""
        return announcement_route(self.store, self.settings, self.llm.enabled)

    @property
    def can_generate(self) -> bool:
        return self.route()[1] is None

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

    def selected_targets(self, a: dict[str, Any]) -> list[str]:
        """Languages to machine-translate when ``a`` is published: the admin's choice saved with the announcement
        (``source_documents.metadata.translation_targets``); announcements saved before that choice existed follow
        AUTO_TRANSLATE_ANNOUNCEMENTS / AUTO_TRANSLATE_LANGUAGES."""
        allowed = machine_languages(self.settings)
        if a.get("original_language") not in allowed:
            return []                     # Release 1: only between ko, en and id
        doc = get_one(self.store, "source_documents", id=a["document_id"]) or {}
        chosen = (doc.get("metadata") or {}).get("translation_targets")
        if isinstance(chosen, list):
            return clean_targets(chosen, a["original_language"], allowed)
        if not self.settings.auto_translate_announcements:
            return []
        return clean_targets(auto_languages(self.settings), a["original_language"], allowed)

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
        if language not in machine_languages(self.settings) or a["original_language"] not in machine_languages(self.settings):
            raise InvalidState(f"Machine drafts of announcements are offered only between "
                               f"{', '.join(machine_languages(self.settings)) or 'no languages'} in this release. A "
                               f"reviewer can still translate it by hand.", code="language_out_of_scope")
        executor, blocked = self.route()
        if blocked:
            raise InvalidState(BLOCKED_MESSAGES[blocked], code=blocked)
        row = self._row(announcement_id, language) or self.store.insert("announcement_translations", dict(
            announcement_id=announcement_id, language_code=language, title="", body="", translation_status="todo"))
        if self.approved_current(row, a):
            # a reviewed translation of exactly the current text is never replaced by machine output
            raise InvalidState("This translation was approved by a reviewer for the current text; it is not replaced "
                               "by a machine translation.", code="translation_approved")
        if self.human_touched(row) and not force:
            raise InvalidState("A person is working on this translation; a machine translation would replace it.",
                               code="human_draft_exists")
        if not force and self.machine_made(row) and \
                not self.needs_translation(row, self.reviews.original(announcement_id)["content_hash"]):
            last = self.last_job(row["id"])
            if last is not None:
                return last          # a machine draft of exactly this text exists: no new job, no inference
        existing = self.open_job(row["id"])
        if existing:
            # the same request again (another click, a second publication event): never a second job or model call.
            # A job nobody picked up (the worker slept or stopped) is handed to the worker again - safe: the claim is
            # atomic and the job checks its own state before calling the model.
            if existing.get("executor") == "gpu" and job_stalled(existing, self.settings):
                self.store.rpc("expire_gpu_leases", {})       # the dead worker's lease ends now: queued again
            elif self.jobs is not None and existing.get("executor") != "gpu" and \
                    (existing["status"] == "queued" or job_stalled(existing, self.settings)):
                if job_stalled(existing, self.settings):
                    self.ingestion.event(existing["id"], "resume", "Requested again while waiting; the worker was "
                                                                   "woken up.", level="warning")
                self.jobs.enqueue(existing, background) if existing["status"] == "queued" else self.jobs.kick()
            return existing
        try:
            job = self.ingestion.create_job(self._source(a), "manual", actor_id, job_type="translate_announcement",
                                            payload=dict(announcement_id=announcement_id, translation_id=row["id"],
                                                         language=language, force=force),
                                            executor="gpu" if executor == "gpu" else None)
        except DuplicateError:          # queued concurrently (unique index): use that job
            existing = self.open_job(row["id"])
            if existing is None:
                raise
            return existing
        self.ingestion.event(job["id"], "queued", f"Machine translation into {language} queued for the announcement"
                                                 f"{' (GPU worker, ' + self.settings.announcement_translation_model + ')' if executor == 'gpu' else ' (server model)'}.")
        self.store.insert("audit_log", dict(action="translation.machine_requested", entity_type="announcement",
                                            entity_id=announcement_id, actor_id=actor_id,
                                            details={"language": language, "job_id": job["id"]}))
        if enqueue and self.jobs is not None:     # backfill: leave it to the API worker (enqueue=False)
            self.jobs.enqueue(job, background)
        return job

    def approved_current(self, row: dict[str, Any] | None, a: dict[str, Any]) -> bool:
        if not row or row.get("translation_status") != "human_approved" or row.get("is_outdated"):
            return False
        return row.get("source_content_hash") == self.reviews.original(a["id"])["content_hash"]

    def on_published(self, announcement_id: str, actor_id: str | None, background: Any = None) -> list[dict[str, Any]]:
        """Publication hook: queue the missing / outdated machine translations of the SELECTED languages (never blocks
        publication; repeated events queue nothing twice: one open job per translation, cached results)."""
        if not (self.can_generate and self.ingestion):
            return []
        a = get_one(self.store, "announcements", id=announcement_id)
        if a is None or a["publication_status"] != "published":
            return []
        targets = self.selected_targets(a)
        if not targets:
            return []
        h = self.reviews.original(announcement_id)["content_hash"]
        out = []
        for lang in targets:
            if lang == a["original_language"] or not self.needs_translation(self._row(announcement_id, lang), h):
                continue
            try:
                out.append(self.queue(announcement_id, lang, actor_id, background=background))
            except Exception:  # noqa: BLE001 - a translation must never break publication
                log.exception("could not queue the %s translation of announcement %s", lang, announcement_id)
        return out

    def backfill(self, actor_id: str, *, languages: list[str], limit: int, dry_run: bool) -> dict[str, Any]:
        """Bounded backfill of announcement drafts (see the route). Jobs wait for the GPU worker if it is offline."""
        from app.services.translation import backfill as bf

        executor, blocked = self.route()
        langs = [x for x in (languages or machine_languages(self.settings)) if x in machine_languages(self.settings)]
        if not langs:
            raise ValidationFailed(f"Machine drafts are offered only in {', '.join(machine_languages(self.settings))}.")
        items = [i for i in bf.plan(self._svc(), langs)["items"] if i["kind"] == "announcement"]
        todo = [i for i in items if not i["queued"] and not i["too_long"]]
        out = dict(dry_run=dry_run, missing=len(todo), already_queued=sum(1 for i in items if i["queued"]),
                   too_long=sum(1 for i in items if i["too_long"]), languages=langs, route=executor,
                   worker=self.worker_status(), queued=[],
                   next=[{k: i[k] for k in ("id", "title", "language", "chars")} for i in todo[:limit]])
        if dry_run:
            return out
        if blocked:
            raise InvalidState(BLOCKED_MESSAGES[blocked], code=blocked)
        queued = bf.apply(self._svc(), limit, langs, kinds=["announcement"])
        for q in queued:                 # local jobs (TRANSLATION_FALLBACK_TO_GEMINI): wake the API's worker once
            job = get_one(self.store, "ingestion_jobs", id=q["job_id"])
            if job and self.jobs is not None and job.get("executor") != "gpu":
                self.jobs.enqueue(job)
        self.store.insert("audit_log", dict(action="translation.backfill", entity_type="announcement", entity_id=None,
                                            actor_id=actor_id, details=dict(queued=len(queued), languages=langs,
                                                                            limit=limit)))
        return out | dict(queued=queued, next=[])

    def _svc(self) -> Any:
        """The few services the backfill planner reads (settings, store, this translator, reviews, documents)."""
        return self.services

    # ------------------------------------------------------------------- run
    def _cached(self, content_hash: str, language: str, exclude: str) -> dict[str, Any] | None:
        rows, _ = self.store.select("announcement_translations", Query(
            eq={"source_content_hash": content_hash, "language_code": language, "translation_status": "machine_draft"},
            neq={"id": exclude}, limit=5))
        return next((r for r in rows if self.machine_made(r)), None)

    def require_approved(self, announcement_id: str, orig: dict[str, Any]) -> None:
        """Every provider: only text that is approved and public right now is translated (and stored)."""
        try:
            public = self.public.get_announcement(announcement_id)
        except NotFound as exc:
            raise IngestionError("source_not_public", "The original is not public.") from exc
        if public["body"] != orig["body"] or public["title"] != orig["title"]:
            raise IngestionError("source_unapproved", "The announcement has an unapproved change; request the "
                                                      "translation again after it is approved.")

    def prepare(self, job: dict[str, Any]) -> dict[str, Any]:
        """Check a job and collect its input. ``finished`` is set when there is nothing left to generate."""
        p = job.get("payload") or {}
        row = get_one(self.store, "announcement_translations", id=p.get("translation_id"))
        if row is None:
            raise IngestionError("translation_missing", "The translation task no longer exists.")
        a = get_one(self.store, "announcements", id=row["announcement_id"])
        if a is None or a["publication_status"] != "published":
            raise IngestionError("source_changed", "The announcement is no longer published; nothing was translated.")
        orig = self.reviews.original(a["id"])
        self.require_approved(a["id"], orig)
        require_not_touched_since(row, job, bool(p.get("force")))
        lang, src = row["language_code"], a["original_language"]
        if self.human_touched(row) and not p.get("force"):
            raise IngestionError("human_draft_exists", "A person edited this translation; the machine translation "
                                                       "was not written.")
        done = dict(outcome="translated", document_id=a["document_id"], version_id=None, changed=False, warning=None)
        finished = None
        if not self.needs_translation(row, orig["content_hash"]) and not p.get("force"):
            finished = done | dict(message="Already translated from exactly this text; nothing to do.")
        return dict(row=row, a=a, orig=orig, lang=lang, src=src, done=done, finished=finished, force=bool(p.get("force")))

    def run_job(self, job: dict[str, Any], heartbeat: Any, event: Any) -> dict[str, Any]:
        """The SERVER's model (the GPU worker's jobs never come here). Refused unless TRANSLATION_FALLBACK_TO_GEMINI:
        also a job queued before the setting changed, or one handed back after a long wait, never reaches Gemini."""
        if not gemini_fallback(self.settings):
            raise IngestionError("translation_fallback_disabled",
                                 "Announcements are translated by the GPU worker "
                                 f"({self.settings.announcement_translation_model}); the server's model is not used "
                                 "(TRANSLATION_FALLBACK_TO_GEMINI=false). Request the translation again.")
        work = self.prepare(job)
        if work["finished"]:
            return work["finished"]
        row, orig, lang, src = work["row"], work["orig"], work["lang"], work["src"]
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
            usage_row = job_usage(provider, model, out.get("input_tokens"), out.get("output_tokens"), parts + 1)
        else:
            event(job["id"], "translate", "Identical text was translated before; reusing that translation.")
            title, body, provider, model = cached["title"], cached["body"], cached.get("provider"), cached.get("model")
            usage_row = job_usage(provider, model, 0, 0, 0) | {"cached": True}
        res = self.store_result(job, work, title, body, provider, model)
        return res | {"usage": usage_row}

    def store_result(self, job: dict[str, Any], work: dict[str, Any], title: str, body: str, provider: str | None,
                     model: str | None, *, always_review: bool = False) -> dict[str, Any]:
        """``always_review``: never 'machine_draft' (which may be shown to students), even when every check passed."""
        a, orig, lang, src, done = work["a"], work["orig"], work["lang"], work["src"], work["done"]
        # re-check: the original or the human state may have changed while the model was working
        row = get_one(self.store, "announcement_translations", id=work["row"]["id"])
        if row is None or self.reviews.original(a["id"])["content_hash"] != orig["content_hash"]:
            raise IngestionError("source_changed", "The announcement changed while it was translated; discarded.")
        self.require_approved(a["id"], orig)
        require_not_touched_since(row, job, work["force"])
        if self.human_touched(row) and not work["force"]:
            raise IngestionError("human_draft_exists", "A person edited this translation meanwhile; discarded.")
        check = local_translation_warnings if provider == "ollama" else validate_translation
        warnings = check(f"{orig['title']}\n{orig['body']}", f"{title}\n{body}", src, lang)
        # drafts of local models are never 'machine_draft' (which may be shown to students)
        status = "needs_review" if warnings or always_review or provider == "ollama" else "machine_draft"
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
        if status == "needs_review" and self.reviews is not None:
            self.notes.notify_many(self.reviews._people(lang, "review"), "translation_review",
                                   f"Machine translation needs review ({lang}): {a['title'][:110]}",
                                   entity_type="announcement", entity_id=a["id"],
                                   link=f"/admin/translations/{a['id']}/{lang}")
        return done | dict(message=f"Machine translation into {lang}: {status} ({len(warnings)} check warning(s)).")

    # ---------------------------------------------------------------- public
    def public_translation(self, a: dict[str, Any], body: str, content_hash: str,
                           language: str | None) -> dict[str, Any] | None:
        """The translation students see for ``language``: only a reviewer-approved (verified) translation of exactly
        the current text. Unreviewed machine drafts of announcements are never shown, whatever
        PUBLIC_MACHINE_TRANSLATIONS says (Release 1 rule). None = show the original."""
        if not language or language == a["original_language"]:
            return None
        row = self._row(a["id"], language)
        if row is None or row.get("is_outdated") or row.get("source_content_hash") != content_hash:
            return None
        if row["translation_status"] != "human_approved":
            return None
        return dict(status="verified", language=language, title=row["title"], body=row["body"],
                    high_risk=is_high_risk(a["title"], body), reviewed_at=row.get("reviewed_at"), generated_at=None)

    def blocked_reason(self, a: dict[str, Any] | None, language: str | None, row: dict[str, Any] | None
                       ) -> dict[str, str] | None:
        """Why a machine translation cannot be requested right now (None = it can). Shown next to the button."""
        allowed = machine_languages(self.settings)
        if a is None or language is None:
            return None
        if a["publication_status"] != "published":
            return dict(code="not_published", message="The original announcement must be approved and published first.")
        if language == a["original_language"]:
            return dict(code="original_language", message="This is the original language.")
        if language not in allowed or a["original_language"] not in allowed:
            return dict(code="language_out_of_scope", message=f"Machine drafts are offered only between "
                                                              f"{', '.join(allowed)} in this release; translate by hand.")
        blocked = self.route()[1]
        if blocked:
            return dict(code=blocked, message=BLOCKED_MESSAGES[blocked])
        if self.approved_current(row, a):
            return dict(code="translation_approved", message="A reviewer approved this translation for the current "
                                                             "text; it is protected from machine output.")
        return None

    def worker_status(self) -> dict[str, Any]:
        """The GPU worker as the panel shows it (no names, no tokens)."""
        if "translate_announcement" not in routed_types(self.settings):
            return dict(enabled=False, online=False, last_seen_at=None)
        try:
            workers = available_workers(self.store, self.settings)
        except Exception:  # noqa: BLE001 - migration 0016 missing: shown as offline, never an error page
            workers = []
        seen = max((w.get("last_seen_at") or "" for w in workers), default="") or None
        return dict(enabled=True, online=bool(workers), last_seen_at=seen)

    def admin_info(self, row: dict[str, Any] | None, a: dict[str, Any] | None = None,
                   language: str | None = None) -> dict[str, Any]:
        job = self.last_job(row["id"]) if row else None
        worker = self.worker_status()
        state = automation_state(row, job, self.settings)
        if job and job.get("executor") == "gpu" and job["status"] == "queued" and state in ("pending", "stalled") \
                and not worker["online"]:
            state = "waiting_worker"          # nothing is wrong with the job: the university computer is offline
        blocked = self.blocked_reason(a, language, row)
        stats = (job or {}).get("statistics") or {}
        return dict(state=state, machine_made=bool(row and self.machine_made(row)),
                    provider=(row or {}).get("provider"), model=(row or {}).get("model"),
                    generated_at=(row or {}).get("generated_at"), warnings=(row or {}).get("warnings") or [],
                    job=dict(id=job["id"], status=job["status"], error_code=job.get("error_code"),
                             error_message=job.get("error_message"), created_at=job["created_at"],
                             run_after=job.get("run_after"), attempts=job.get("attempts"),
                             max_attempts=job.get("max_attempts"), started_at=job.get("started_at"),
                             heartbeat_at=job.get("heartbeat_at"), completed_at=job.get("completed_at"),
                             deferrals=stats.get("deferrals"), usage=stats.get("usage"),
                             stalled=job_stalled(job, self.settings)) if job else None,
                    llm_enabled=self.can_generate, blocked=blocked, worker=worker,
                    executor=(job or {}).get("executor") or ("local" if job else None),
                    configured=self.configured(),
                    # the panel refreshes itself while something happens on the server
                    poll_seconds=3 if state in ("pending", "processing") else (30 if state == "waiting_worker" else None))

    def configured(self) -> dict[str, Any]:
        """Where a new request would run right now (shown to admins; no secrets)."""
        executor, blocked = self.route()
        if executor == "gpu":
            return dict(route="gpu_worker", provider="ollama", model=self.settings.announcement_translation_model,
                        fallback_to_gemini=gemini_fallback(self.settings))
        if executor == "local":
            return dict(route="server", provider=getattr(self.llm, "name", None),
                        model=getattr(self.llm, "primary", None) or getattr(self.llm, "model", None),
                        fallback_to_gemini=True)
        return dict(route=None, provider=None, model=None, fallback_to_gemini=gemini_fallback(self.settings),
                    blocked=blocked)


def job_usage(provider: str | None, model: str | None, input_tokens: int | None, output_tokens: int | None,
              calls: int) -> dict[str, Any]:
    """What one translation job used (kept on the job; ESTIMATED cost from LLM_PRICES, never an invoice)."""
    from app.services.llm.usage import usage

    cost, priced = usage.prices.estimate(provider or "", model or "", input_tokens, output_tokens, None)
    return dict(provider=provider, model=model, input_tokens=int(input_tokens or 0), output_tokens=int(output_tokens or 0),
                model_calls=calls, est_cost_usd=cost if priced else None)


def translation_llm(settings: Settings, llm: LLMProvider, budget: Any = None, flags: Any = None) -> LLMProvider:
    """The provider for BACKGROUND work (translation jobs, AI summaries, discovery summaries).

    With Gemini it is always its own provider instance: TRANSLATION_MODEL (or the assistant's models) with its own
    circuit breaker, and - when a budget is given - a gate before every attempt that charges the per-day background
    budget (``llm_background_daily_attempts``), so background work never uses the chatbot's reserved quota. With a
    separate TRANSLATION_MODEL it has no fallback: it must not fail over onto the chatbot's fallback model.

    BACKGROUND_LLM_PROVIDER selects another provider for background work only (e.g. local Ollama translation drafts
    while the assistant stays on Gemini). Neither side ever falls back to the other's provider."""
    chosen = settings.background_llm_provider.strip().lower()
    separate = bool(chosen and chosen != settings.llm_provider.strip().lower())
    if separate:
        from app.services.llm.base import build_llm_from_settings

        settings = settings.model_copy(update={"llm_provider": chosen})
        llm = build_llm_from_settings(settings)
    if not llm.enabled:
        return llm
    from app.services.llm.controls import BackgroundControls

    def gated(provider: LLMProvider) -> tuple[LLMProvider, Any]:
        if budget is None:
            return provider, None
        ctl = BackgroundControls(settings, budget, flags, provider.name, getattr(provider, "primary", provider.model))
        provider.background_controls = ctl  # type: ignore[attr-defined]

        def gate() -> bool:
            ctl.check()                 # raises the precise reason (stopped / budget / spending limit)
            return True
        return provider, gate

    if llm.name != "gemini":
        if separate:                    # never relabel the chatbot's own provider instance
            llm.lane = "background"  # type: ignore[attr-defined]
        llm, gate = gated(llm)
        return BudgetedLLM(llm, gate) if gate else llm
    from app.services.llm.base import build_llm_from_settings

    # never the chatbot's fallback model: background work must not fail over onto the chat lane's quota
    model = (settings.translation_model or "").strip() or settings.gemini_primary_model
    bg = build_llm_from_settings(settings.model_copy(update={"gemini_primary_model": model, "gemini_fallback_model": ""}))
    bg.lane = "background"  # type: ignore[attr-defined]
    bg, gate = gated(bg)
    bg.attempt_gate = gate  # type: ignore[attr-defined]
    return bg


class BudgetedLLM:
    """Non-Gemini providers (tests, other vendors): the same per-day background budget, charged per call."""

    def __init__(self, inner: LLMProvider, gate: Any):
        self._inner, self._gate = inner, gate

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def _check(self) -> None:
        if not self._gate():
            raise LLMError("llm_background_budget", "Today's AI budget for background work is used up; the "
                                                    "chatbot's share of the model quota is reserved.")

    def complete(self, *a: Any, **kw: Any) -> Any:
        self._check()
        return self._inner.complete(*a, **kw)

    def stream(self, *a: Any, **kw: Any) -> Any:
        self._check()
        return self._inner.stream(*a, **kw)

    async def acomplete(self, *a: Any, **kw: Any) -> Any:
        self._check()
        return await self._inner.acomplete(*a, **kw)  # type: ignore[attr-defined]

    async def astream(self, *a: Any, **kw: Any) -> Any:
        self._check()
        return await self._inner.astream(*a, **kw)  # type: ignore[attr-defined]


def require_translation_access(user: Any, language: str, perms: dict[str, bool]) -> None:
    if not (perms.get("can_edit") or perms.get("can_review") or user.role in ("admin", "super_admin")):
        raise Forbidden(f"You are not assigned to {language} translations.")
