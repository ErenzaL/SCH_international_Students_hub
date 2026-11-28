"""Server side of the outbound-only GPU worker (university server; docs/gpu-worker.md).

The worker calls the API over HTTPS; nothing ever connects to the worker. It can do exactly four things: claim a
translation job, renew its lease, hand in text, or report a failure code.

* Credentials: one random token per worker, stored as SHA-256, with expiry, rotation (short overlap), pause and
  revocation. A worker is not a user: its token is useless on every other endpoint, and user tokens are useless here.
* Data: a job contains only the title and text of PUBLIC, approved, current content. Nothing about the person who
  requested it, no conversations, tickets, student text or credentials.
* Results are drafts: the status is always ``needs_review`` (``machine_draft`` can be shown to students, so it is not
  used), checked by the server, and approval needs a human reviewer (also enforced by the database for documents).
* Durability: jobs are ``ingestion_jobs`` rows with ``executor = 'gpu'``. A lease that is not renewed expires and the
  job is queued again. The lease token is chosen by the worker, so repeating a request is safe.
* The text that was sent is fingerprinted: if the original changed meanwhile, the result is discarded and the job is
  queued again with the new text.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.errors import Conflict, DuplicateError, InvalidState, NotAuthenticated, NotFound
from app.repositories.base import Query, get_one
from app.services.gpu_routing import available_workers, gemini_fallback, routed_types
from app.services.ingestion.errors import IngestionError

log = logging.getLogger("app.gpu")

TOKEN = re.compile(r"schgw_([0-9a-f]{32})_([A-Za-z0-9_-]{43})")
MAX_RELEASES = 20            # jobs handed back by a worker that shuts down are not counted as attempts, up to this
SUBMIT_SECONDS = 120         # time reserved for storing a result
# what a worker may report; it never supplies error text
RETRY_CODES = {"llm_unavailable", "llm_timeout", "llm_rate_limited", "llm_empty", "llm_malformed", "llm_error",
               "job_timeout"}
FINAL_CODES = {"llm_model": "The model is not installed on the GPU worker.",
               "llm_context": "The text is too long for the GPU worker's model.",
               "llm_truncated": "The generated text was cut off.",
               "llm_bad_request": "The model rejected the request.",
               "invalid_job": "The GPU worker could not read the job."}
RELEASE_CODE = "worker_shutdown"


class LeaseLost(Conflict):
    code = "lease_lost"


def utcnow() -> datetime:
    return datetime.now(UTC)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _time(v: str | None) -> datetime | None:
    return datetime.fromisoformat(v) if v else None


class GpuWorkerService:
    def __init__(self, services: Any):
        self.svc = services
        self.store = services.store
        self.settings = services.settings
        self._alerted: datetime | None = None
        self._no_schema = False         # feature off and migration 0016 not applied: nothing to sweep

    def require_enabled(self) -> None:
        if not self.settings.gpu_worker_enabled:
            raise NotFound("Not found.")

    def _audit(self, action: str, worker_id: str, actor_id: str | None, **details: Any) -> None:
        self.store.insert("audit_log", dict(action=action, entity_type="gpu_worker", entity_id=worker_id,
                                            actor_id=actor_id, details=details))

    # ============================================================ credentials (super admins)
    def _new_token(self, worker_id: str) -> str:
        return f"schgw_{uuid.UUID(worker_id).hex}_{secrets.token_urlsafe(32)}"

    def _expiry(self) -> str:
        return (utcnow() + timedelta(days=self.settings.gpu_worker_token_days)).isoformat()

    def create_worker(self, name: str, actor_id: str) -> dict[str, Any]:
        wid = str(uuid.uuid4())
        token = self._new_token(wid)
        try:
            w = self.store.insert("gpu_workers", dict(id=wid, name=name, token_hash=_hash(token),
                                                      expires_at=self._expiry(), created_by=actor_id))
        except DuplicateError as exc:
            raise Conflict("A GPU worker with this name already exists.") from exc
        self._audit("gpu_worker.created", wid, actor_id, name=name)
        return self.worker_view(w) | {"token": token}        # shown once, never stored

    def _worker(self, worker_id: str) -> dict[str, Any]:
        w = get_one(self.store, "gpu_workers", id=worker_id)
        if w is None:
            raise NotFound("GPU worker not found.")
        return w

    def rotate(self, worker_id: str, actor_id: str, grace_minutes: int) -> dict[str, Any]:
        w = self._worker(worker_id)
        if w["status"] == "revoked":
            raise InvalidState("This credential is revoked; create a new worker.")
        token = self._new_token(w["id"])
        valid = min(utcnow() + timedelta(minutes=grace_minutes), _time(w["expires_at"]) or utcnow())
        w = self.store.update("gpu_workers", dict(
            token_hash=_hash(token), expires_at=self._expiry(), rotated_at=utcnow().isoformat(),
            previous_token_hash=w["token_hash"] if grace_minutes else None,
            previous_valid_until=valid.isoformat() if grace_minutes else None), {"id": w["id"]})[0]
        self._audit("gpu_worker.rotated", w["id"], actor_id, grace_minutes=grace_minutes)
        return self.worker_view(w) | {"token": token}

    def set_status(self, worker_id: str, status: str, actor_id: str) -> dict[str, Any]:
        w = self._worker(worker_id)
        if w["status"] == "revoked":
            raise InvalidState("This credential is revoked; create a new worker.")
        patch: dict[str, Any] = {"status": status}
        if status == "revoked":
            patch.update(revoked_at=utcnow().isoformat(), previous_token_hash=None, previous_valid_until=None)
        # never undo a revocation that happened a moment ago
        rows = self.store.update("gpu_workers", patch, {"id": w["id"], "status": w["status"]})
        if not rows:
            raise Conflict("The worker was changed at the same time; try again.")
        if status == "revoked":           # its job is free at once (its lease cannot be used any more)
            self.store.update("ingestion_jobs", {"lease_expires_at": (utcnow() - timedelta(hours=1)).isoformat()},
                              {"executor": "gpu", "status": "running", "locked_by": f"gpu:{w['id']}"})
            self.store.rpc("expire_gpu_leases", {})
        self._audit(f"gpu_worker.{status}", w["id"], actor_id)
        return self.worker_view(rows[0])

    def worker_view(self, w: dict[str, Any]) -> dict[str, Any]:
        seen = _time(w.get("last_seen_at"))
        return dict(id=w["id"], name=w["name"], status=w["status"], expires_at=w["expires_at"],
                    expired=(_time(w["expires_at"]) or utcnow()) <= utcnow(), last_seen_at=w.get("last_seen_at"),
                    seconds_since_seen=int((utcnow() - seen).total_seconds()) if seen else None,
                    created_at=w.get("created_at"), rotated_at=w.get("rotated_at"), revoked_at=w.get("revoked_at"))

    def authenticate(self, token: str) -> dict[str, Any]:
        """The worker a token belongs to. Every failure looks the same to the caller."""
        m = TOKEN.fullmatch(token)
        w = get_one(self.store, "gpu_workers", id=str(uuid.UUID(m.group(1)))) if m else None
        given = _hash(token)
        ok = hmac.compare_digest(given, (w or {}).get("token_hash") or "0" * 64)
        prev_until = _time((w or {}).get("previous_valid_until"))
        prev = hmac.compare_digest(given, (w or {}).get("previous_token_hash") or "0" * 64)
        now = utcnow()
        # the overlap of a rotated token has its own, earlier end; the current token ends at expires_at
        valid = w is not None and w["status"] != "revoked" and (
            (ok and (_time(w["expires_at"]) or now) > now) or (prev and prev_until is not None and prev_until > now))
        if not valid or w is None:
            raise NotAuthenticated("Invalid worker credential.", code="invalid_worker_credential")
        seen = _time(w.get("last_seen_at"))
        if seen is None or (now - seen).total_seconds() > 30:
            self.store.update("gpu_workers", {"last_seen_at": now.isoformat()}, {"id": w["id"]})
        return w

    # ================================================================== worker: claim
    def job_types_for(self, model: str | None) -> list[str]:
        """Job types a worker running ``model`` may claim: announcements only with ANNOUNCEMENT_TRANSLATION_MODEL
        (a worker that does not say which model it runs is checked when it hands in the draft)."""
        types = routed_types(self.settings)
        if model is not None and model.strip() != self.settings.announcement_translation_model.strip():
            types = [t for t in types if t != "translate_announcement"]
        return types

    def claim(self, worker: dict[str, Any], lease_token: str, model: str | None = None) -> dict[str, Any]:
        s = self.settings
        if worker["status"] == "paused":
            return dict(state="paused", job=None)
        types = self.job_types_for(model)
        if not types:
            return dict(state="idle", job=None)
        for _ in range(10):      # jobs that turn out to need nothing are finished here and the next one is tried
            rows = self.store.rpc("claim_gpu_job", dict(
                p_worker=worker["id"], p_lease_token=lease_token, p_lease_seconds=s.gpu_worker_lease_seconds,
                p_job_types=types, p_max_running=s.gpu_worker_max_running))
            rows = [rows] if isinstance(rows, dict) else [r for r in rows or [] if r and r.get("id")]
            if not rows:
                return dict(state="idle", job=None)
            job = rows[0]
            task = self._task(job)
            if task is None:
                continue
            stats = dict(job.get("statistics") or {}, gpu_input=task["input_sha256"], gpu_worker=worker["name"])
            if not self.store.update("ingestion_jobs", {"statistics": stats}, self._owned(job, worker, lease_token)):
                continue
            self.svc.ingestion.event(job["id"], "lease", f"Claimed by GPU worker {worker['name']} (attempt "
                                                         f"{job['attempts']} of {job['max_attempts']}).")
            log.info("gpu claim worker=%s job=%s type=%s attempt=%s", worker["name"], job["id"], job["job_type"],
                     job["attempts"])
            return dict(state="job", job=task | dict(
                id=job["id"], lease_token=lease_token, lease_seconds=s.gpu_worker_lease_seconds,
                max_seconds=s.gpu_worker_job_max_seconds))
        return dict(state="idle", job=None)

    @staticmethod
    def _owned(job: dict[str, Any], worker: dict[str, Any], lease_token: str) -> dict[str, Any]:
        return dict(id=job["id"], executor="gpu", status="running", lease_token=lease_token,
                    locked_by=f"gpu:{worker['id']}")

    def _source(self, job: dict[str, Any]) -> dict[str, Any] | None:
        return get_one(self.store, "knowledge_sources", id=job["source_id"]) if job.get("source_id") else None

    def _finish(self, job: dict[str, Any], *, result: dict[str, Any] | None = None, error: IngestionError | None = None,
                **stats: Any) -> dict[str, Any]:
        return self.svc.ingestion._finish(job, self._source(job), result=result, error=error,
                                          stats=dict(job.get("statistics") or {}, **stats))

    def _task(self, job: dict[str, Any]) -> dict[str, Any] | None:
        """The job's input, or None when the job was finished here (nothing to do, or no longer allowed)."""
        try:
            kind, work = self._prepare(job)
        except IngestionError as exc:
            self._finish(job, error=exc)
            return None
        if work["finished"]:
            self._finish(job, result=work["finished"])
            return None
        return self._input(kind, work)

    def _prepare(self, job: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """Existing job checks plus: only content that is public right now leaves the server."""
        source = self._source(job)
        if source is None:
            raise IngestionError("source_deleted", "The source was deleted.")
        if not source["is_active"]:
            raise IngestionError("source_inactive", "The source is disabled.")
        # both check that the text is approved and public right now (the same rules as for every other provider)
        if job["job_type"] == "translate_announcement":
            return "announcement", self.svc.announcement_translator.prepare(job)
        if job["job_type"] != "translate_document":
            raise IngestionError("not_permitted", "This job type is not available to GPU workers.")
        work = self.svc.doc_translations.prepare(job)
        # stricter than the API's own model: never replace anything a reviewer has already handled
        row = work["t"]
        if not work["force"] and (row.get("human_edited") or row["translation_status"] in ("changes_requested", "rejected")):
            raise IngestionError("human_draft_exists", "A person has worked on this translation; nothing was replaced.")
        return "document", work

    def _input(self, kind: str, work: dict[str, Any]) -> dict[str, Any]:
        s = self.settings
        if kind == "announcement":
            title, body, summary = work["orig"]["title"], work["orig"]["body"], False
        else:
            title, body = work["d"]["title"], work["body"]
            summary = self.svc.doc_translations.is_summary(body, work["summary"])
        task = dict(kind=kind, mode="summarize" if summary else "translate", source_language=work["src"],
                    target_language=work["lang"], title=title, body=body)
        fingerprint = hashlib.sha256(json.dumps(task, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        return task | dict(input_sha256=fingerprint, chunk_chars=s.gpu_worker_chunk_chars,
                           max_source_chars=min(s.gpu_worker_max_source_chars, s.translation_summary_source_chars))

    # ============================================================== worker: lease / result
    def _leased(self, worker: dict[str, Any], job_id: str, lease_token: str) -> dict[str, Any]:
        """The job, if this worker's lease is the latest one (also when it is finished already)."""
        job = get_one(self.store, "ingestion_jobs", id=job_id)
        if job is None or job.get("executor") != "gpu" or job.get("lease_token") != lease_token \
                or job["status"] not in ("running", "succeeded", "failed"):
            raise LeaseLost("This lease is no longer valid.")
        if job["status"] == "running" and job["locked_by"] not in (f"gpu:{worker['id']}", f"gpu-submit:{worker['id']}"):
            raise LeaseLost("This lease is no longer valid.")
        return job

    def heartbeat(self, worker: dict[str, Any], job_id: str, lease_token: str) -> dict[str, Any]:
        job = self._leased(worker, job_id, lease_token)
        if job["status"] != "running":
            raise LeaseLost("This job is already finished.")
        if job.get("cancel_requested"):
            return dict(cancel=True, lease_seconds=0)
        started = _time(job.get("started_at")) or utcnow()
        left = self.settings.gpu_worker_job_max_seconds - (utcnow() - started).total_seconds()
        if left <= 0:
            return dict(cancel=True, lease_seconds=0)
        seconds = int(min(self.settings.gpu_worker_lease_seconds, left))
        now = utcnow()
        if not self.store.update("ingestion_jobs", dict(
                heartbeat_at=now.isoformat(), lease_expires_at=(now + timedelta(seconds=seconds)).isoformat()),
                self._owned(job, worker, lease_token)):
            raise LeaseLost("This lease is no longer valid.")
        return dict(cancel=False, lease_seconds=seconds)

    def _cancelled(self, job: dict[str, Any], eq: dict[str, Any]) -> dict[str, Any]:
        rows = self.store.update("ingestion_jobs", dict(
            status="failed", completed_at=utcnow().isoformat(), locked_by=None, error_code="cancelled",
            error_message="Cancelled by an administrator."), eq)
        if not rows:
            raise LeaseLost("This lease is no longer valid.")
        self.svc.ingestion.event(job["id"], "finish", "Cancelled by an administrator; nothing was stored.",
                                 level="warning")
        return rows[0]

    def _requeue(self, job: dict[str, Any], eq: dict[str, Any], message: str, **stats: Any) -> None:
        """Back to the queue without counting the attempt (bounded by the caller)."""
        if not self.store.update("ingestion_jobs", dict(
                status="queued", locked_by=None, lease_token=None, lease_expires_at=None,
                run_after=utcnow().isoformat(), attempts=max(0, int(job["attempts"]) - 1),
                statistics=dict(job.get("statistics") or {}, **stats)), eq):
            raise LeaseLost("This lease is no longer valid.")
        self.svc.ingestion.event(job["id"], "requeue", message, level="warning")

    def complete(self, worker: dict[str, Any], job_id: str, lease_token: str, *, title: str, body: str, model: str,
                 metrics: dict[str, int]) -> dict[str, Any]:
        job = self._leased(worker, job_id, lease_token)
        if job["status"] != "running":                 # the first response was lost: same answer, nothing stored twice
            return dict(status=job["status"], duplicate=True)
        if model not in [m.strip() for m in self.settings.gpu_worker_models.split(",")] or \
                (job["job_type"] == "translate_announcement"
                 and model != self.settings.announcement_translation_model.strip()):
            raise InvalidState("Results of this model are not accepted.", code="model_not_allowed")
        owned = self._owned(job, worker, lease_token)
        if job.get("cancel_requested"):
            self._cancelled(job, owned)
            return dict(status="cancelled", duplicate=False)
        # exactly one request stores the result; a concurrent repeat gets 409 and asks again
        submit = owned | {"locked_by": f"gpu-submit:{worker['id']}"}
        rows = self.store.update("ingestion_jobs", dict(
            locked_by=submit["locked_by"],
            lease_expires_at=(utcnow() + timedelta(seconds=SUBMIT_SECONDS)).isoformat()), owned | {"cancel_requested": False})
        if not rows:
            raise Conflict("The result is being stored.", code="submission_in_progress")
        job = rows[0]
        try:
            return self._store_result(worker, job, submit, title, body, model, metrics)
        except LeaseLost:
            raise
        except Exception:
            # e.g. the database was unreachable: give the lease back so the worker can hand the result in again
            self.store.update("ingestion_jobs", {"locked_by": f"gpu:{worker['id']}"}, submit)
            raise

    def _store_result(self, worker: dict[str, Any], job: dict[str, Any], submit: dict[str, Any], title: str, body: str,
                      model: str, metrics: dict[str, int]) -> dict[str, Any]:
        from app.services.translation_drafts import extract_headings

        gpu = dict(metrics, model=model, worker=worker["name"])
        try:
            kind, work = self._prepare(job)
            if work["finished"]:
                self._finish(job, result=work["finished"], gpu=gpu)
                return dict(status="succeeded", duplicate=False)
            task = self._input(kind, work)
            stats = job.get("statistics") or {}
            if task["input_sha256"] != stats.get("gpu_input"):
                n = int(stats.get("source_changes") or 0) + 1
                if n > 5:
                    raise IngestionError("source_changed", "The original keeps changing; the result was discarded.")
                self._requeue(job, submit, "The original changed while it was translated: the result was discarded and "
                                           "the job is queued again.", source_changes=n)
                return dict(status="requeued", duplicate=False)
            if kind == "announcement":
                result = self.svc.announcement_translator.store_result(job, work, title, body, "ollama", model,
                                                                       always_review=True)
            else:
                summary = task["mode"] == "summarize"
                out = dict(title=title, body=body, headings=extract_headings(body), provider="ollama", model=model,
                           chunks=max(1, metrics.get("parts", 1)), partial=len(work["body"]) > task["max_source_chars"],
                           source_chars=min(len(work["body"]), task["max_source_chars"]))
                result = self.svc.doc_translations.store_result(job, work, out, summary=summary, always_review=True)
        except IngestionError as exc:
            done = self._finish(job, error=exc, gpu=gpu)
            return dict(status=done["status"], error=exc.code, duplicate=False)
        self._finish(job, result=result, gpu=gpu)
        log.info("gpu complete worker=%s job=%s %s", worker["name"], job["id"],
                 " ".join(f"{k}={v}" for k, v in metrics.items()))
        return dict(status="succeeded", duplicate=False)

    def fail(self, worker: dict[str, Any], job_id: str, lease_token: str, code: str, metrics: dict[str, int]
             ) -> dict[str, Any]:
        job = self._leased(worker, job_id, lease_token)
        if job["status"] != "running":
            return dict(status=job["status"], duplicate=True)
        owned = self._owned(job, worker, lease_token)
        if job.get("cancel_requested"):
            self._cancelled(job, owned)
            return dict(status="cancelled", duplicate=False)
        log.info("gpu fail worker=%s job=%s error=%s", worker["name"], job["id"], code)
        stats = job.get("statistics") or {}
        releases = int(stats.get("releases") or 0) + 1
        if code == RELEASE_CODE and releases <= MAX_RELEASES:
            self._requeue(job, owned, "The GPU worker stopped and handed the job back.", releases=releases)
            return dict(status="queued", duplicate=False)
        # take the lease first, so that a repeated request cannot count the failure twice
        rows = self.store.update("ingestion_jobs", {"locked_by": f"gpu-submit:{worker['id']}"}, owned)
        if not rows:
            raise LeaseLost("This lease is no longer valid.")
        error = IngestionError(code, FINAL_CODES[code]) if code in FINAL_CODES else \
            IngestionError("llm_unavailable", "The GPU worker's model could not finish this job.")
        done = self._finish(rows[0], error=error, gpu=dict(metrics, worker=worker["name"], error=code))
        return dict(status=done["status"], duplicate=False)

    # ===================================================================== admin
    def cancel(self, job_id: str, actor_id: str) -> dict[str, Any]:
        job = get_one(self.store, "ingestion_jobs", id=job_id)
        if job is None or job.get("executor") != "gpu":
            raise NotFound("GPU job not found.")
        self.store.rpc("expire_gpu_leases", {})
        # queued: ends now; running: the worker stops at its next heartbeat, or the lease ends
        if self.store.update("ingestion_jobs", dict(
                status="failed", completed_at=utcnow().isoformat(), cancel_requested=True, error_code="cancelled",
                error_message="Cancelled by an administrator."), {"id": job_id, "executor": "gpu", "status": "queued"}):
            status = "cancelled"
        elif self.store.update("ingestion_jobs", {"cancel_requested": True},
                               {"id": job_id, "executor": "gpu", "status": "running"}):
            status = "cancelling"
        else:
            raise InvalidState("This job is already finished.")
        self.store.insert("audit_log", dict(action="gpu_job.cancelled", entity_type="ingestion_job", entity_id=job_id,
                                            actor_id=actor_id, details={"status": status}))
        return dict(id=job_id, status=status)

    def _may_use_server_model(self, job: dict[str, Any]) -> bool:
        """GPU_WORKER_ON_EXPIRY=local may hand a job to the server's model - an announcement translation only with
        TRANSLATION_FALLBACK_TO_GEMINI (paid models are never used for them otherwise)."""
        if self.settings.gpu_worker_on_expiry.strip().lower() != "local":
            return False
        if job.get("job_type") == "translate_announcement":
            return gemini_fallback(self.settings) and self.svc.announcement_translator.llm.enabled
        return bool(self.svc.doc_translations.llm.enabled)

    def sweep(self) -> dict[str, int]:
        """Housekeeping of GPU jobs, whatever happened to the worker. Never raises.

        * lost leases are re-queued (or failed after the attempt limit);
        * worker enabled: an ANNOUNCEMENT translation keeps waiting for the worker however long it is offline (a
          clear waiting status and a daily alert; nothing paid is used). Only with TRANSLATION_FALLBACK_TO_GEMINI it is
          treated like a document translation: after GPU_WORKER_MAX_QUEUE_HOURS it fails visibly or goes to the
          server's own model (GPU_WORKER_ON_EXPIRY=local);
        * worker disabled: every open GPU job ends at once (failed, or the server's model where allowed above)."""
        out = dict(expired_leases=0, failed=0, rerouted=0)
        if self._no_schema:
            return out
        try:
            enabled = self.settings.gpu_worker_enabled
            if enabled:
                out["expired_leases"] = int(self.store.rpc("expire_gpu_leases", {}) or 0)
            cutoff = (utcnow() - timedelta(hours=self.settings.gpu_worker_max_queue_hours)).isoformat()
            rows, _ = self.store.select("ingestion_jobs", Query(
                eq={"executor": "gpu"}, in_={"status": ["queued"] if enabled else ["queued", "running"]},
                lt={"created_at": cutoff} if enabled else {}, order=[("created_at", False)], limit=200))
            reason = "No GPU worker fetched this job in time." if enabled else "The GPU worker is switched off."
            for j in rows:
                local = self._may_use_server_model(j)
                if enabled and j.get("job_type") == "translate_announcement" and not gemini_fallback(self.settings):
                    continue                      # keeps waiting for the worker (see the docstring)
                eq = dict(id=j["id"], executor="gpu", status=j["status"], attempts=j["attempts"])
                if local:
                    if self.store.update("ingestion_jobs", dict(
                            executor="local", status="queued", locked_by=None, lease_token=None, lease_expires_at=None,
                            run_after=utcnow().isoformat(), cancel_requested=False), eq):
                        out["rerouted"] += 1
                        self.svc.ingestion.event(j["id"], "reroute", f"{reason} Using the server's own model.",
                                                 level="warning")
                elif self.store.update("ingestion_jobs", dict(
                        status="failed", completed_at=utcnow().isoformat(), locked_by=None, lease_token=None,
                        lease_expires_at=None, error_code="gpu_worker_unavailable",
                        error_message=f"{reason} Request the translation again."), eq):
                    out["failed"] += 1
                    self.svc.ingestion.event(j["id"], "finish", f"{reason} Request the translation again.", level="error")
            if out["rerouted"]:
                self.svc.jobs.kick()
            if out["failed"] or out["rerouted"]:
                log.warning("gpu sweep failed=%d rerouted=%d", out["failed"], out["rerouted"])
                self.svc.notifications.notify(
                    "translation_failed", "Translations were not fetched by the GPU worker",
                    f"{reason} {out['failed']} failed (request them again), {out['rerouted']} given to the server's own model.",
                    severity="warning", link="/admin/translations")
            if enabled:
                self._alert_if_offline()
        except Exception as exc:  # noqa: BLE001 - housekeeping must never stop the job worker
            if not self.settings.gpu_worker_enabled:
                self._no_schema = True
                log.info("gpu sweep skipped (%s)", type(exc).__name__)
            else:
                log.exception("gpu sweep failed")
        return out

    def _alert_if_offline(self) -> None:
        if available_workers(self.store, self.settings):
            return
        now = utcnow()
        if self._alerted is not None and now - self._alerted < timedelta(hours=24):
            return
        _rows, waiting = self.store.select("ingestion_jobs", Query(eq={"executor": "gpu", "status": "queued"}, cols="id",
                                                                   limit=1), count=True)
        if waiting:
            self._alerted = now
            fallback = gemini_fallback(self.settings)
            self.svc.notifications.notify(
                "translation_failed", "No GPU worker is available",
                f"{waiting} translation job(s) wait for it. "
                + ("Announcement translations keep waiting until it is back (no paid model is used); "
                   if not fallback else "New announcement requests use the server's Gemini (TRANSLATION_FALLBACK_TO_GEMINI); ")
                + f"document translations end after {self.settings.gpu_worker_max_queue_hours} hours.",
                severity="warning", link="/admin/translations")

    def status(self) -> dict[str, Any]:
        self.sweep()
        workers, _ = self.store.select("gpu_workers", Query(order=[("created_at", False)]))
        since = (utcnow() - timedelta(days=1)).isoformat()

        def count(status: str, **kw: Any) -> int:
            _r, n = self.store.select("ingestion_jobs", Query(eq={"executor": "gpu", "status": status}, cols="id",
                                                              limit=1, **kw), count=True)
            return n or 0

        done, _ = self.store.select("ingestion_jobs", Query(
            eq={"executor": "gpu"}, in_={"status": ["succeeded", "failed"]}, gte={"completed_at": since},
            order=[("completed_at", True)], limit=200, cols="id,status,error_code,statistics"))
        gpu = [(j.get("statistics") or {}).get("gpu") or {} for j in done if j["status"] == "succeeded"]
        timed = [g for g in gpu if g.get("duration_ms")]
        errors: dict[str, int] = {}
        for j in done:
            if j["status"] == "failed":
                errors[j.get("error_code") or "unknown"] = errors.get(j.get("error_code") or "unknown", 0) + 1
        open_jobs, _ = self.store.select("ingestion_jobs", Query(
            eq={"executor": "gpu"}, in_={"status": ["queued", "running"]}, order=[("created_at", False)], limit=50,
            cols="id,job_type,status,attempts,max_attempts,created_at,run_after,lease_expires_at,cancel_requested,"
                 "error_code,payload"))
        return dict(
            enabled=self.settings.gpu_worker_enabled, available=bool(available_workers(self.store, self.settings)),
            routed_job_types=routed_types(self.settings), workers=[self.worker_view(w) for w in workers],
            queue=dict(queued=count("queued"), running=count("running")),
            last_24h=dict(
                succeeded=sum(j["status"] == "succeeded" for j in done), failed=errors,
                average_seconds=round(sum(g["duration_ms"] for g in timed) / len(timed) / 1000, 1) if timed else None,
                input_tokens=sum(g.get("input_tokens", 0) for g in gpu),
                output_tokens=sum(g.get("output_tokens", 0) for g in gpu)),
            oldest_queued_at=next((j["created_at"] for j in open_jobs if j["status"] == "queued"), None),
            jobs=[{k: v for k, v in j.items() if k != "payload"} | {"language": (j.get("payload") or {}).get("language")}
                  for j in open_jobs])

    def queue_missing(self, actor_id: str, *, limit: int, languages: list[str], kinds: list[str],
                      dry_run: bool) -> dict[str, Any]:
        """Queue missing or outdated translations of published content (announcements first)."""
        from app.services.translation import backfill
        from app.services.translation.auto import SUPPORTED

        for k in kinds:
            if f"translate_{k}" not in routed_types(self.settings):
                raise InvalidState(f"GPU jobs of type translate_{k} are not enabled.")
        langs = languages or list(SUPPORTED)
        items = [i for i in backfill.plan(self.svc, langs)["items"] if i["kind"] in kinds and not i["queued"]
                 and not i["too_long"]]
        if dry_run:
            return dict(dry_run=True, missing=len(items), queued=[],
                        next=[{k: i[k] for k in ("kind", "id", "language", "mode", "chars")} for i in items[:limit]])
        if not available_workers(self.store, self.settings):
            raise InvalidState("No GPU worker contacted the server recently; start it first.", code="gpu_worker_unavailable")
        queued = backfill.apply(self.svc, limit, langs, kinds=kinds)
        self.store.insert("audit_log", dict(action="gpu_job.queue_missing", entity_type="ingestion_job",
                                            actor_id=actor_id, details=dict(queued=len(queued), languages=langs)))
        return dict(dry_run=False, missing=len(items), queued=queued, next=[])
