"""Version-linked translations of knowledge documents (migration 0011).

* The original document/version is authoritative and never modified. A translation row belongs to exactly one
  approved original version (``version_id`` + ``source_content_hash``).
* When a new original version becomes active (approval -> index -> activate, or a rollback), the rows made from
  the previous version are marked ``is_outdated`` (kept for audit) and new ``todo`` rows are created for the new
  version, linked to the previous translation for comparison. The language team is notified.
* AI drafts are produced by durable ``translate_document`` jobs and are always ``machine_draft`` (never verified).
* Editing needs the language's ``support`` or ``review`` permission; approve / reject / request changes need
  ``review`` for that language (also enforced by a database trigger). Students only ever see human-approved,
  current translations (plus, if enabled, clearly-labelled machine drafts).
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.core.config import Settings
from app.core.errors import DuplicateError, Forbidden, InvalidState, NotFound, ValidationFailed
from app.repositories.base import Query, Store, get_many, get_one
from app.security.auth import AuthUser
from app.security.permissions import has_perm, languages_with
from app.services.gpu_routing import gpu_executor
from app.services.ingestion.errors import IngestionError
from app.services.llm.base import LLMError, LLMProvider
from app.services.notifications import UserNotificationService
from app.services.translation.auto import (
    auto_languages,
    automation_state,
    daily_budget_exceeded,
    public_machine_allowed,
    require_not_touched_since,
)
from app.services.translation.quality import (
    is_high_risk,
    local_model_warnings,
    validate_summary,
    validate_translation,
)
from app.services.translation_drafts import (
    extract_headings,
    preservation_warnings,
    summarize_document,
    translate_document,
)
from app.services.translations import LANG_NAMES, TARGETS, language_people

HUMAN_STATES = ("draft", "in_review", "human_approved")   # never overwritten by an AI draft without force
REVIEWABLE = ("machine_draft", "needs_review", "draft", "in_review", "changes_requested", "rejected", "human_approved")


def now() -> str:
    return datetime.now(UTC).isoformat()


class DocumentTranslationService:
    def __init__(self, store: Store, llm: LLMProvider, notes: UserNotificationService, settings: Settings):
        self.store = store
        self.llm = llm
        self.notes = notes
        self.settings = settings
        self.ingestion: Any = None   # set by the container (IngestionService) - creates the durable jobs
        self.jobs: Any = None        # JobRunner
        self.public: Any = None      # PublicService: what students can see right now

    @property
    def can_generate(self) -> bool:
        return self.llm.enabled or gpu_executor(self.store, self.settings, "translate_document") is not None

    # ------------------------------------------------------------ eligibility
    @staticmethod
    def eligible(doc: dict[str, Any] | None, source: dict[str, Any] | None) -> bool:
        """Same rule as the public Knowledge Center (announcements have their own translation workflow)."""
        if not doc or not source or doc.get("document_type") == "announcement":
            return False
        if source.get("authority_type") == "supporter_submitted":
            return False
        if source.get("source_type") == "kakao_message" and source.get("authority_type") != "staff_communication":
            return False
        return True

    def _context(self, document_id: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        d = get_one(self.store, "source_documents", id=document_id)
        if d is None:
            raise NotFound("Document not found.")
        s = get_one(self.store, "knowledge_sources", id=d["source_id"])
        if not self.eligible(d, s):
            raise InvalidState("This document is not part of the Knowledge Center and is not translated.")
        v = get_one(self.store, "document_versions", id=d["current_version_id"]) if d.get("current_version_id") else None
        if v is None or v["verification_status"] != "approved":
            raise InvalidState("The original has no approved version yet; translate it after approval.")
        assert s is not None
        return d, s, v

    @staticmethod
    def original(d: dict[str, Any], s: dict[str, Any], v: dict[str, Any]) -> dict[str, Any]:
        return dict(document_id=d["id"], version_id=v["id"], version_number=v["version_number"], title=d["title"],
                    body=v["extracted_text"], language=d.get("language") or "ko", content_hash=v["content_hash"],
                    headings=extract_headings(v["extracted_text"]), source_url=d.get("canonical_url") or s.get("original_url"),
                    organization=s["organization"], category=s["category"], approved_at=v.get("approved_at"),
                    is_live=not d["is_canceled"] and not d.get("archived_at") and s["is_active"])

    def _rows(self, document_id: str) -> list[dict[str, Any]]:
        rows, _ = self.store.select("document_translations", Query(eq={"document_id": document_id},
                                                                   order=[("created_at", True)]))
        return rows

    def _current(self, document_id: str, version_id: str, language: str) -> dict[str, Any] | None:
        return get_one(self.store, "document_translations", version_id=version_id, language_code=language)

    def _names(self, ids: list[str | None]) -> dict[str, str]:
        return {k: (p.get("display_name") or p.get("email") or "") for k, p in
                get_many(self.store, "profiles", [i for i in ids if i]).items()}

    def _revision(self, t: dict[str, Any], action: str, actor_id: str | None, note: str | None = None) -> None:
        self.store.insert("document_translation_revisions", dict(
            translation_id=t["id"], title=t.get("title"), headings=t.get("headings") or [], body=t.get("body"),
            translation_status=t["translation_status"], source_content_hash=t.get("source_content_hash"), action=action,
            note=note, provider=t.get("provider"), model=t.get("model"), actor_id=actor_id))

    def _audit(self, action: str, document_id: str, actor_id: str | None, **details: Any) -> None:
        self.store.insert("audit_log", dict(action=action, entity_type="source_document", entity_id=document_id,
                                            actor_id=actor_id, details=details))

    @staticmethod
    def _link(document_id: str, language: str) -> str:
        return f"/admin/translations/documents/{document_id}/{language}"

    # ------------------------------------------------------------------ sync
    def sync(self, document_id: str, actor_id: str | None = None) -> dict[str, int]:
        """Idempotent: outdate rows of older versions, create tasks for the current approved version."""
        d = get_one(self.store, "source_documents", id=document_id)
        s = get_one(self.store, "knowledge_sources", id=d["source_id"]) if d else None
        if not self.eligible(d, s) or not d or not d.get("current_version_id"):
            return dict(created=0, outdated=0)
        v = get_one(self.store, "document_versions", id=d["current_version_id"])
        if v is None or v["verification_status"] != "approved":
            return dict(created=0, outdated=0)
        rows = self._rows(document_id)
        outdated = 0
        outdated_langs: set[str] = set()
        for r in rows:
            if r["version_id"] == v["id"] and r.get("is_outdated") and r["source_content_hash"] == v["content_hash"]:
                # rollback to this exact original: translations made from it are valid again
                r2 = self.store.update("document_translations", dict(is_outdated=False, outdated_at=None),
                                       {"id": r["id"]})[0]
                self._revision(r2, "restored", actor_id, f"v{v['version_number']} is the active original again.")
                r.update(is_outdated=False)
            elif r["version_id"] != v["id"] and not r.get("is_outdated"):
                r2 = self.store.update("document_translations", dict(is_outdated=True, outdated_at=now()),
                                       {"id": r["id"]})[0]
                self._revision(r2, "outdated", actor_id, f"The original changed (now v{v['version_number']}).")
                outdated += 1
                if r["translation_status"] != "todo":
                    outdated_langs.add(r["language_code"])
        created_langs: list[str] = []
        current = {r["language_code"] for r in rows if r["version_id"] == v["id"]}
        for lang in TARGETS:
            if lang == (d.get("language") or "ko") or lang in current:
                continue
            prev = next((r for r in reversed(rows) if r["language_code"] == lang and r["translation_status"] != "todo"),
                        None)
            try:
                self.store.insert("document_translations", dict(
                    document_id=d["id"], version_id=v["id"], source_version_number=v["version_number"],
                    source_content_hash=v["content_hash"], language_code=lang, translation_status="todo",
                    previous_translation_id=prev["id"] if prev else None))
            except Exception:  # noqa: BLE001 - a concurrent sync created it (unique version_id + language)
                continue
            created_langs.append(lang)
            updated = lang in outdated_langs
            self.notes.notify_many(language_people(self.store, lang, "any"),
                                   "translation_outdated" if updated else "translation_task",
                                   (f"Original updated (v{v['version_number']}): re-review the {LANG_NAMES[lang]} "
                                    f"translation of '{d['title'][:100]}'") if updated else
                                   f"New {LANG_NAMES[lang]} translation task: {d['title'][:120]}",
                                   entity_type="source_document", entity_id=d["id"], link=self._link(d["id"], lang))
        if created_langs or outdated:
            self._audit("document_translation.sync", d["id"], actor_id, version_number=v["version_number"],
                        created=created_langs, outdated=outdated)
        if created_langs and self.settings.auto_translate_documents and self.can_generate and self.ingestion:
            for lang in [x for x in created_langs if x in auto_languages(self.settings)]:
                try:
                    self._queue(d, s, v, lang, actor_id, force=False)  # type: ignore[arg-type]
                except Exception:  # noqa: BLE001 - drafts are optional; the original stays searchable
                    pass
        return dict(created=len(created_langs), outdated=outdated)

    # -------------------------------------------------------------- permissions
    def permissions(self, user: AuthUser, language: str) -> dict[str, bool]:
        can_edit = has_perm(user, language, "support") or has_perm(user, language, "review")
        return dict(can_edit=can_edit, can_review=has_perm(user, language, "review"),
                    can_generate=can_edit or user.role in ("admin", "super_admin"))

    def _require_access(self, user: AuthUser, language: str) -> dict[str, bool]:
        if language not in TARGETS:
            raise ValidationFailed("Unsupported language.")
        perms = self.permissions(user, language)
        if not (perms["can_edit"] or perms["can_review"] or user.role in ("admin", "super_admin")):
            raise Forbidden(f"You are not assigned to {LANG_NAMES.get(language, language)} translations.")
        return perms

    # ------------------------------------------------------------------ views
    def view(self, t: dict[str, Any], names: dict[str, str] | None = None) -> dict[str, Any]:
        names = names if names is not None else self._names([t.get("reviewed_by"), t.get("last_edited_by")])
        status = t["translation_status"]
        return dict(id=t["id"], document_id=t["document_id"], version_id=t["version_id"],
                    source_version_number=t["source_version_number"], source_content_hash=t["source_content_hash"],
                    language_code=t["language_code"], title=t.get("title") or "", headings=t.get("headings") or [],
                    body=t.get("body") or "", translation_status=status, is_outdated=bool(t.get("is_outdated")),
                    outdated_at=t.get("outdated_at"), provider=t.get("provider"), model=t.get("model"),
                    generated_at=t.get("generated_at"), human_edited=bool(t.get("human_edited")),
                    is_machine_translated=status in ("machine_draft", "needs_review"), warnings=t.get("warnings") or [],
                    scope=t.get("scope") or "full",
                    review_note=t.get("review_note"), reviewed_by=t.get("reviewed_by"),
                    reviewed_by_name=names.get(t.get("reviewed_by") or ""), reviewed_at=t.get("reviewed_at"),
                    last_edited_by=t.get("last_edited_by"), last_edited_by_name=names.get(t.get("last_edited_by") or ""),
                    last_edited_at=t.get("last_edited_at"), submitted_at=t.get("submitted_at"),
                    previous_translation_id=t.get("previous_translation_id"), updated_at=t.get("updated_at"),
                    created_at=t.get("created_at"),
                    verified=status == "human_approved" and not t.get("is_outdated"))

    def _open_job(self, translation_id: str) -> dict[str, Any] | None:
        rows, _ = self.store.select("ingestion_jobs", Query(
            eq={"job_type": "translate_document", "payload->>translation_id": translation_id},
            in_={"status": ["queued", "running"]}, limit=1))
        return rows[0] if rows else None

    def _last_job(self, translation_id: str) -> dict[str, Any] | None:
        rows, _ = self.store.select("ingestion_jobs", Query(
            eq={"job_type": "translate_document", "payload->>translation_id": translation_id},
            order=[("created_at", True)], limit=1))
        return rows[0] if rows else None

    @staticmethod
    def _job_brief(j: dict[str, Any] | None) -> dict[str, Any] | None:
        if not j:
            return None
        return dict(id=j["id"], status=j["status"], error_code=j.get("error_code"), error_message=j.get("error_message"),
                    created_at=j["created_at"], completed_at=j.get("completed_at"))

    def overview(self, document_id: str, user: AuthUser) -> dict[str, Any]:
        """Admin → Documents → Translations tab: one entry per target language for the current version."""
        d, s, v = self._context(document_id)
        self.sync(document_id, user.id)
        rows = self._rows(document_id)
        names = self._names([x for r in rows for x in (r.get("reviewed_by"), r.get("last_edited_by"))])
        langs = []
        for lang in TARGETS:
            if lang == (d.get("language") or "ko"):
                continue
            cur = next((r for r in rows if r["version_id"] == v["id"] and r["language_code"] == lang), None)
            older = [r for r in rows if r["language_code"] == lang and r["version_id"] != v["id"]]
            item = self.view(cur, names) if cur else None
            if item:
                item.pop("body", None)
            job = self._last_job(cur["id"]) if cur else None
            langs.append(dict(language=lang, translation=item, job=self._job_brief(job), state=automation_state(cur, job),
                              automatic=lang in auto_languages(self.settings),
                              has_outdated_previous=any(r["translation_status"] != "todo" for r in older),
                              previous_verified=any(r["translation_status"] == "human_approved" for r in older),
                              **self.permissions(user, lang)))
        verified = sum(1 for x in langs if x["translation"] and x["translation"]["verified"])
        return dict(document_id=d["id"], title=d["title"], original_language=d.get("language") or "ko",
                    version_id=v["id"], version_number=v["version_number"], languages=langs,
                    completion=dict(verified=verified, total=len(langs)),
                    llm=dict(enabled=self.can_generate, provider=self.llm.name, model=self.llm.model))

    def detail(self, document_id: str, language: str, user: AuthUser) -> dict[str, Any]:
        perms = self._require_access(user, language)
        d, s, v = self._context(document_id)
        self.sync(document_id, user.id)
        orig = self.original(d, s, v)
        if language == orig["language"]:
            raise ValidationFailed("This is the original language of the document.")
        t = self._current(document_id, v["id"], language)
        previous = None
        if t and t.get("previous_translation_id"):
            p = get_one(self.store, "document_translations", id=t["previous_translation_id"])
            if p:
                pv = get_one(self.store, "document_versions", id=p["version_id"])
                previous = dict(translation=self.view(p), original_body=pv["extracted_text"] if pv else None,
                                original_version_number=p["source_version_number"])
        revs: list[dict[str, Any]] = []
        if t:
            rows, _ = self.store.select("document_translation_revisions", Query(
                eq={"translation_id": t["id"]}, order=[("id", True)], limit=100))
            names = self._names([r.get("actor_id") for r in rows])
            revs = [{**r, "actor_name": names.get(r.get("actor_id") or "")} for r in rows]
        return dict(original=orig, translation=self.view(t) if t else None, previous=previous, revisions=revs,
                    permissions=perms, language=language, job=self._job_brief(self._last_job(t["id"])) if t else None,
                    llm=dict(enabled=self.can_generate, provider=self.llm.name, model=self.llm.model))

    def tasks(self, user: AuthUser, *, status: str | None, language: str | None, outdated: bool | None,
              page: int, size: int) -> tuple[list[dict[str, Any]], int]:
        langs = sorted(set(languages_with(user, "support")) | set(languages_with(user, "review")))
        if language:
            if language not in langs:
                raise Forbidden(f"You are not assigned to {LANG_NAMES.get(language, language)} translations.")
            langs = [language]
        if not langs:
            return [], 0
        q = Query(in_={"language_code": langs}, eq={"is_outdated": bool(outdated)}, order=[("updated_at", True)],
                  limit=size, offset=(page - 1) * size)
        if status:
            q.eq["translation_status"] = status
        rows, total = self.store.select("document_translations", q, count=True)
        docs = get_many(self.store, "source_documents", [r["document_id"] for r in rows])
        names = self._names([x for r in rows for x in (r.get("reviewed_by"), r.get("last_edited_by"))])
        out = []
        for r in rows:
            d = docs.get(r["document_id"])
            if d is None:
                continue
            item = self.view(r, names)
            item.pop("body", None)
            item.update(document_title=d["title"], original_language=d.get("language") or "ko",
                        document_live=not d["is_canceled"] and not d.get("archived_at"),
                        **{f"can_{k}": val for k, val in self.permissions(user, r["language_code"]).items()})
            out.append(item)
        return out, total or 0

    def set_original_language(self, document_id: str, language: str, user: AuthUser) -> dict[str, Any]:
        """Correct a mislabelled original language (e.g. an English page tagged 'ko'). The original text is
        unchanged; translation tasks follow (the new original language needs none, the old one gets a task)."""
        if user.role not in ("admin", "super_admin"):
            raise Forbidden("Only admins can change a document's original language.")
        if language not in TARGETS:
            raise ValidationFailed("Unsupported language.")
        d = get_one(self.store, "source_documents", id=document_id)
        if d is None:
            raise NotFound("Document not found.")
        old = d.get("language") or "ko"
        if old == language:
            return self.overview(document_id, user)
        self.store.update("source_documents", {"language": language}, {"id": document_id})
        for r in self._rows(document_id):
            if r["language_code"] != language or r.get("is_outdated"):
                continue
            if r["translation_status"] == "todo":
                self.store.delete("document_translations", {"id": r["id"]})
            else:   # keep the work for audit, but it is no longer a translation of anything
                r2 = self.store.update("document_translations", dict(is_outdated=True, outdated_at=now()),
                                       {"id": r["id"]})[0]
                self._revision(r2, "outdated", user.id, f"{LANG_NAMES[language]} is now the original language.")
        self._audit("document.language_changed", document_id, user.id, **{"from": old, "to": language})
        self.sync(document_id, user.id)
        return self.overview(document_id, user)

    # ------------------------------------------------------------- AI drafts
    def request_drafts(self, document_id: str, languages: list[str], user: AuthUser, background: Any = None,
                       force: bool = False) -> list[dict[str, Any]]:
        if not self.can_generate:
            raise InvalidState("AI translation drafts need an LLM provider (set LLM_PROVIDER and an API key). "
                               "Translations can still be written by hand.", code="llm_disabled")
        d, s, v = self._context(document_id)
        self.sync(document_id, user.id)
        langs = [lang for lang in dict.fromkeys(languages) if lang != (d.get("language") or "ko")]
        if not langs:
            raise ValidationFailed("Choose at least one target language other than the original language.")
        for lang in langs:
            if not self.permissions(user, lang)["can_generate"]:
                raise Forbidden(f"You are not assigned to {LANG_NAMES.get(lang, lang)} translations.")
        out = []
        for lang in langs:
            job = self._queue(d, s, v, lang, user.id, force=force)
            out.append(dict(language=lang, job_id=job["id"], status=job["status"]))
            if job.get("_new"):
                self.jobs.enqueue(job, background)
        return out

    def _queue(self, d: dict[str, Any], s: dict[str, Any], v: dict[str, Any], lang: str, actor_id: str | None,
               force: bool) -> dict[str, Any]:
        t = self._current(d["id"], v["id"], lang)
        if t is None:
            raise NotFound("No translation task for this language.")
        if t["translation_status"] in HUMAN_STATES and not force:
            raise InvalidState(f"The {LANG_NAMES[lang]} translation already has human work "
                               f"('{t['translation_status']}'). Generating a new AI draft would replace it.",
                               code="human_draft_exists")
        open_job = self._open_job(t["id"])
        if open_job:
            return open_job
        executor = gpu_executor(self.store, self.settings, "translate_document")
        try:
            job = self.ingestion.create_job(s, "manual", actor_id, payload=dict(
                document_id=d["id"], version_id=v["id"], translation_id=t["id"], language=lang, force=force),
                job_type="translate_document", executor=executor)
        except DuplicateError:          # queued concurrently (unique index): use that job
            existing = self._open_job(t["id"])
            if existing is None:
                raise
            return existing
        self._audit("document_translation.draft_requested", d["id"], actor_id, language=lang, job_id=job["id"])
        self.ingestion.event(job["id"], "queued", f"{LANG_NAMES[lang]} AI draft queued for v{v['version_number']}"
                                                 f"{' (GPU worker)' if executor else ''}.")
        return {**job, "_new": True}

    def require_approved(self, document_id: str, version_id: str) -> None:
        """Every provider: only the approved, current version of a public document is translated (and stored)."""
        try:
            _d, _s, v = self.public._public_doc(document_id)
        except NotFound as exc:
            raise IngestionError("source_not_public", "The original is not public.") from exc
        if v["id"] != version_id:
            raise IngestionError("source_changed", "The original changed; nothing was written.")

    def prepare(self, job: dict[str, Any]) -> dict[str, Any]:
        """Check a job and collect its input. ``finished`` is set when there is nothing left to generate."""
        p = job.get("payload") or {}
        t = get_one(self.store, "document_translations", id=p.get("translation_id"))
        if t is None:
            raise IngestionError("translation_missing", "The translation task no longer exists.")
        d = get_one(self.store, "source_documents", id=t["document_id"])
        v = get_one(self.store, "document_versions", id=t["version_id"])
        if not d or not v or d.get("current_version_id") != v["id"] or t.get("is_outdated"):
            raise IngestionError("source_changed", "The original changed before the draft was generated; "
                                                   "nothing was written.")
        if t["translation_status"] in HUMAN_STATES and not p.get("force"):
            raise IngestionError("human_draft_exists", "A person edited this translation meanwhile; the AI draft "
                                                       "was not written.")
        self.require_approved(d["id"], v["id"])
        require_not_touched_since(t, job, bool(p.get("force")))
        lang = t["language_code"]
        src = d.get("language") or "ko"
        body = v["extracted_text"] or ""
        if t["translation_status"] in ("machine_draft", "needs_review") and t.get("provider") \
                and t["source_content_hash"] == v["content_hash"] and not p.get("force"):
            finished = dict(outcome="translated", document_id=d["id"], version_id=v["id"], changed=False, warning=None,
                        message="Already translated from exactly this version; nothing to do.")
        else:
            finished = None
        return dict(t=t, d=d, v=v, lang=lang, src=src, body=body, finished=finished, force=bool(p.get("force")))

    def is_summary(self, body: str) -> bool:
        """Long documents get a translated title and a summary instead of a full translation."""
        if len(body) > self.settings.translation_full_max_chars:
            return True
        from app.services.translation_drafts import chunk_text as parts_of

        return len(parts_of(body, self.settings.translation_chunk_chars)) + 1 > self.settings.translation_max_requests_per_job

    def run_job(self, job: dict[str, Any], heartbeat: Any, event: Any) -> dict[str, Any]:
        """Executed by the ingestion worker (job_type translate_document). Raises IngestionError on failure."""
        work = self.prepare(job)
        if work["finished"]:
            return work["finished"]
        d, v, lang, src, body = work["d"], work["v"], work["lang"], work["src"], work["body"]
        if daily_budget_exceeded(self.store, self.settings, job["id"]):
            raise IngestionError("translation_daily_limit", "Today's machine-translation budget is used up; the job "
                                                            "continues tomorrow.")
        summary = self.is_summary(body)
        event(job["id"], "translate", f"{'Summarizing' if summary else 'Translating'} v{v['version_number']} from "
                                      f"{LANG_NAMES.get(src, src)} into {LANG_NAMES[lang]} with "
                                      f"{self.llm.name}:{self.llm.model}.")

        def progress(i: int, n: int) -> None:
            heartbeat(job["id"])
            event(job["id"], "translate", f"Translated part {i}/{n}.")

        try:
            if summary:   # long document: title + labelled AI summary; the original file stays the full document
                out = summarize_document(self.llm, title=d["title"], body=body, source_lang=src, target_lang=lang,
                                         max_source_chars=self.settings.translation_summary_source_chars)
                heartbeat(job["id"])
            else:
                out = translate_document(self.llm, title=d["title"], body=body, source_lang=src,
                                         target_lang=lang, chunk_chars=self.settings.translation_chunk_chars,
                                         on_progress=progress)
        except LLMError as exc:
            raise IngestionError(exc.code, exc.message) from exc
        return self.store_result(job, work, out, summary=summary)

    def store_result(self, job: dict[str, Any], work: dict[str, Any], out: dict[str, Any], *, summary: bool,
                     always_review: bool = False) -> dict[str, Any]:
        """``out``: title, body, headings, provider, model, chunks (and partial, source_chars for a summary).
        ``always_review``: never 'machine_draft' (which may be shown to students), even when every check passed."""
        t, d, v, lang, src, body = work["t"], work["d"], work["v"], work["lang"], work["src"], work["body"]
        title = d["title"]
        original = f"{d['title']}\n{body}"
        translated = f"{out['title']}\n{out['body']}"
        checks = validate_summary(original, out["body"], lang) if summary else \
            validate_translation(original, translated, src, lang)
        if out["provider"] == "ollama":
            checks += local_model_warnings(original, translated, src, lang)
        # re-check: the original or the human state may have changed while the model was working
        t = get_one(self.store, "document_translations", id=t["id"])
        d = get_one(self.store, "source_documents", id=d["id"])
        if not t or not d or d.get("current_version_id") != t["version_id"] or t.get("is_outdated") or d["title"] != title:
            raise IngestionError("source_changed", "The original changed while the draft was generated; discarded.")
        self.require_approved(d["id"], v["id"])
        require_not_touched_since(t, job, work["force"])
        if t["translation_status"] in HUMAN_STATES and not work["force"]:
            raise IngestionError("human_draft_exists", "A person edited this translation meanwhile; draft discarded.")
        out["warnings"] = checks
        # drafts of local models are never 'machine_draft' (which may be shown to students)
        status = "needs_review" if checks or always_review or out["provider"] == "ollama" else "machine_draft"
        t = self.store.update("document_translations", dict(
            title=out["title"], body=out["body"], headings=out["headings"], translation_status=status,
            scope="summary" if summary else "full",
            provider=out["provider"], model=out["model"], generated_at=now(), warnings=out["warnings"],
            human_edited=False, reviewed_by=None, reviewed_at=None, original_verified=False, review_note=None,
            submitted_at=None), {"id": t["id"]})[0]
        self._revision(t, "generate", job.get("requested_by"), f"{'summary' if summary else str(out['chunks']) + ' part(s)'}"
                       f"{' of the first ' + str(out['source_chars']) + ' characters' if out.get('partial') else ''}; "
                       f"{len(out['warnings'])} warning(s)")
        self._audit("document_translation.generated", d["id"], job.get("requested_by"), language=lang,
                    provider=out["provider"], model=out["model"], warnings=len(out["warnings"]))
        self.notes.notify_many(language_people(self.store, lang, "any"), "translation_task",
                               f"AI draft ready for {LANG_NAMES[lang]} review: {d['title'][:110]}",
                               entity_type="source_document", entity_id=d["id"], link=self._link(d["id"], lang))
        return dict(outcome="translated", document_id=d["id"], version_id=v["id"], changed=False, warning=None,
                    message=f"{LANG_NAMES[lang]} machine {'summary' if summary else 'translation'}: {status} "
                            f"({len(out['warnings'])} check warning(s)).")

    # ----------------------------------------------------------------- writes
    def _editable(self, document_id: str, language: str, user: AuthUser) -> tuple[dict[str, Any], dict[str, Any]]:
        perms = self._require_access(user, language)
        d, s, v = self._context(document_id)
        self.sync(document_id, user.id)
        t = self._current(document_id, v["id"], language)
        if t is None:
            raise ValidationFailed("This is the original language of the document.")
        return perms, t

    def save(self, document_id: str, language: str, data: dict[str, Any], user: AuthUser) -> dict[str, Any]:
        perms, t = self._editable(document_id, language, user)
        if not perms["can_edit"]:
            raise Forbidden(f"You are not assigned to {LANG_NAMES.get(language, language)} translations.")
        if self._open_job(t["id"]):
            raise InvalidState("An AI draft is being generated for this language; wait for it to finish.")
        d, s, v = self._context(document_id)
        title, body = data["title"].strip(), data["body"].strip()
        if not title or not body:
            raise ValidationFailed("Title and body are required.")
        submit = bool(data.get("submit"))
        row = dict(title=title, body=body, headings=extract_headings(body),
                   translation_status="in_review" if submit else "draft", human_edited=True,
                   warnings=preservation_warnings(f"{d['title']}\n{v['extracted_text']}", f"{title}\n{body}"),
                   review_note=None, reviewed_by=None, reviewed_at=None, original_verified=False,
                   last_edited_by=user.id, last_edited_at=now(), submitted_at=now() if submit else None)
        t = self.store.update("document_translations", row, {"id": t["id"]})[0]   # an edit voids an approval
        self._revision(t, "submit" if submit else "save", user.id)
        self._audit("document_translation.submit" if submit else "document_translation.save", document_id, user.id,
                    language=language)
        if submit:
            self.notes.notify_many([u for u in language_people(self.store, language, "review") if u != user.id],
                                   "translation_review",
                                   f"{LANG_NAMES[language]} translation waiting for review: {d['title'][:110]}",
                                   entity_type="source_document", entity_id=document_id,
                                   link=self._link(document_id, language))
        return self.detail(document_id, language, user)

    def _reviewable(self, document_id: str, language: str, user: AuthUser) -> dict[str, Any]:
        perms, t = self._editable(document_id, language, user)
        if not perms["can_review"]:
            raise Forbidden(f"You are not authorized to review {LANG_NAMES.get(language, language)} translations.")
        if t["translation_status"] == "todo":
            raise NotFound("There is no translation draft to review yet.")
        return t

    def approve(self, document_id: str, language: str, user: AuthUser, original_verified: bool,
                note: str | None = None) -> dict[str, Any]:
        t = self._reviewable(document_id, language, user)
        if not original_verified:
            raise ValidationFailed("Confirm that you checked this translation against the original document.")
        if t["translation_status"] == "human_approved":
            raise InvalidState("Translation is already approved.")
        d, s, v = self._context(document_id)
        if t["source_content_hash"] != v["content_hash"] or t.get("is_outdated"):
            raise InvalidState("The original changed after this translation was written.", code="translation_outdated")
        t = self.store.update("document_translations", dict(
            translation_status="human_approved", reviewed_by=user.id, reviewed_at=now(), original_verified=True,
            review_note=note), {"id": t["id"]})[0]
        self._revision(t, "approve", user.id, note)
        self._audit("document_translation.approve", document_id, user.id, language=language,
                    version_number=t["source_version_number"], was_machine=t.get("provider") is not None,
                    human_edited=bool(t.get("human_edited")))
        if t.get("last_edited_by") and t["last_edited_by"] != user.id:
            self.notes.notify(t["last_edited_by"], "translation_approved",
                              f"Your {LANG_NAMES[language]} translation was approved and published",
                              entity_type="source_document", entity_id=document_id,
                              link=self._link(document_id, language))
        return self.detail(document_id, language, user)

    def reject(self, document_id: str, language: str, user: AuthUser, reason: str) -> dict[str, Any]:
        t = self._reviewable(document_id, language, user)
        t = self.store.update("document_translations", dict(translation_status="rejected", review_note=reason,
                                                            reviewed_by=None, reviewed_at=None, original_verified=False),
                              {"id": t["id"]})[0]
        self._revision(t, "reject", user.id, reason)
        self._audit("document_translation.reject", document_id, user.id, language=language)
        self.notes.notify(t.get("last_edited_by"), "translation_rejected", f"{LANG_NAMES[language]} translation rejected",
                          body=reason[:300], entity_type="source_document", entity_id=document_id,
                          link=self._link(document_id, language))
        return self.detail(document_id, language, user)

    def request_changes(self, document_id: str, language: str, user: AuthUser, note: str) -> dict[str, Any]:
        t = self._reviewable(document_id, language, user)
        t = self.store.update("document_translations", dict(translation_status="changes_requested", review_note=note,
                                                            reviewed_by=None, reviewed_at=None, original_verified=False),
                              {"id": t["id"]})[0]
        self._revision(t, "request_changes", user.id, note)
        self._audit("document_translation.request_changes", document_id, user.id, language=language)
        self.notes.notify(t.get("last_edited_by"), "translation_changes_requested",
                          f"Changes requested on the {LANG_NAMES[language]} translation", body=note[:300],
                          entity_type="source_document", entity_id=document_id, link=self._link(document_id, language))
        return self.detail(document_id, language, user)

    # ----------------------------------------------------------------- public
    def public_translation(self, doc: dict[str, Any], version_id: str, language: str | None) -> dict[str, Any] | None:
        if not language or language == (doc.get("language") or "ko"):
            return None
        t = self._current(doc["id"], version_id, language)
        if t is None or t.get("is_outdated") or t["source_content_hash"] is None:
            return None
        if t["translation_status"] == "human_approved":
            kind = "verified"
        elif t["translation_status"] == "machine_draft" and t.get("provider") and not t.get("human_edited"):
            kind = "machine"
        else:
            return None
        v = get_one(self.store, "document_versions", id=version_id) or {}
        high_risk = is_high_risk(doc.get("title"), v.get("extracted_text"))
        if kind == "machine" and not public_machine_allowed(self.settings, high_risk):
            return None
        return dict(status=kind, language=language, title=t["title"], content=t["body"], headings=t.get("headings") or [],
                    reviewed_at=t.get("reviewed_at") if kind == "verified" else None,
                    generated_at=t.get("generated_at") if kind == "machine" else None,
                    source_version_number=t["source_version_number"], scope=t.get("scope") or "full",
                    high_risk=high_risk)

    def verified_languages(self, version_ids: list[str]) -> dict[str, list[str]]:
        if not version_ids:
            return {}
        rows, _ = self.store.select("document_translations", Query(
            in_={"version_id": version_ids}, eq={"translation_status": "human_approved", "is_outdated": False},
            cols="version_id,language_code"))
        out: dict[str, list[str]] = {}
        for r in rows:
            out.setdefault(r["version_id"], []).append(r["language_code"])
        return out

    def display_titles(self, version_ids: list[str], language: str) -> dict[str, tuple[str, str]]:
        """{version_id: (title, 'verified' | 'machine')} for list pages: approved translations, plus clean machine
        translations when they are public (lists show titles only; the risk label is on the document page)."""
        out = {k: (v, "verified") for k, v in self.verified_titles(version_ids, language).items()}
        if not version_ids or language not in TARGETS or not self.settings.public_machine_translations \
                or self.settings.machine_translation_high_risk == "review":
            return out
        rows, _ = self.store.select("document_translations", Query(
            in_={"version_id": version_ids}, eq={"translation_status": "machine_draft", "is_outdated": False,
                                                 "language_code": language, "human_edited": False},
            cols="version_id,title,provider"))
        for r in rows:
            if r.get("provider") and r["version_id"] not in out:
                out[r["version_id"]] = (r["title"], "machine")
        return out

    def verified_titles(self, version_ids: list[str], language: str) -> dict[str, str]:
        if not version_ids or language not in TARGETS:
            return {}
        rows, _ = self.store.select("document_translations", Query(
            in_={"version_id": version_ids},
            eq={"translation_status": "human_approved", "is_outdated": False, "language_code": language},
            cols="version_id,title"))
        return {r["version_id"]: r["title"] for r in rows}
