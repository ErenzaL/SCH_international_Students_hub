"""Main loop: one job at a time. Claim -> generate (renewing the lease) -> hand in a draft or report a code."""
from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from app.gpu_worker.config import Config, ConfigError, read_token
from app.gpu_worker.generate import Cancelled, check_job, generate
from app.gpu_worker.hub import CredentialRejected, Hub, HubError, LeaseLost
from app.services.llm.base import LLMError

log = logging.getLogger("gpu_worker")
KST = timezone(timedelta(hours=9))
REPORTABLE = {"llm_unavailable", "llm_timeout", "llm_rate_limited", "llm_empty", "llm_malformed", "llm_error",
              "llm_model", "llm_context", "llm_truncated", "llm_bad_request"}
SUBMIT_FOR = 900.0      # keep trying to hand in a finished draft for this long (it is only kept in memory)
EXIT_OK, EXIT_CONFIG, EXIT_CREDENTIAL = 0, 78, 77


class Worker:
    def __init__(self, config: Config, llm: Any, hub: Hub | None = None, *,
                 now: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self.config, self.llm, self.now = config, llm, now
        self.hub = hub or Hub(config.hub_url, lambda: read_token(config.token_file))
        self.stop = threading.Event()
        self.metrics = dict(claimed=0, completed=0, failed=0, cancelled=0, lost=0, requeued=0)

    # ------------------------------------------------------------------- one job
    def _renew(self, job: dict[str, Any], done: threading.Event, ended: threading.Event, why: dict[str, str]) -> None:
        """Renew the lease until ``done``. Sets ``ended`` (and stops the model) when the job must not go on."""
        path, started = f"/jobs/{job['id']}/heartbeat", time.monotonic()
        interval = max(1.0, job["lease_seconds"] / 4)
        while not done.wait(min(interval, 5.0) if self.stop.is_set() else interval):
            reason = None
            if time.monotonic() - started > job["max_seconds"]:
                reason = "timeout"
            else:
                try:
                    if self.hub.post(path, {"lease_token": job["lease_token"]}).get("cancel"):
                        reason = "cancel"
                except LeaseLost:
                    reason = "lost"
                except (CredentialRejected, ConfigError):
                    reason = "credential"
                except HubError as exc:      # offline: go on, the result may still be accepted
                    log.warning("job=%s heartbeat error=%s", job["id"], exc.code)
            if reason:
                why["reason"] = reason
                self._abort(done, ended)
                return

    def _abort(self, done: threading.Event, ended: threading.Event) -> None:
        """Stop the running generation (again, if a call was just starting)."""
        ended.set()
        while not done.is_set():
            self.llm.close()
            done.wait(0.5)

    def run_job(self, raw: dict[str, Any]) -> str:
        """Returns completed | failed | cancelled | lost | requeued | released."""
        t0 = time.monotonic()
        lease = str(raw.get("lease_token"))
        try:
            job = check_job(raw)
        except ValueError:
            log.error("job=%s invalid", raw.get("id"))
            return self._report(str(raw.get("id")), lease, "invalid_job", {})
        done, ended, why = threading.Event(), threading.Event(), {"reason": ""}
        renew = threading.Thread(target=self._renew, args=(job, done, ended, why), name="lease", daemon=True)
        renew.start()
        # a stop request (SIGTERM) also ends the current generation
        self._current = (done, ended, why)
        if self.stop.is_set():
            self.request_stop()
        out: dict[str, Any] | None = None
        code, model = "", None
        try:
            out, model = generate(self.llm, job, ended, style=getattr(self.config, "prompt_style", "auto"))
        except Cancelled:
            pass
        except LLMError as exc:
            code = exc.code if exc.code in REPORTABLE else "llm_error"
        except Exception as exc:  # noqa: BLE001 - one bad job must not stop the worker
            log.error("job=%s unexpected error=%s", job["id"], type(exc).__name__)
            code = "llm_error"
        finally:
            self._current = None
            done.set()
            renew.join(timeout=100)
        metrics = dict(duration_ms=int((time.monotonic() - t0) * 1000))
        if model is not None and out is not None:
            metrics |= dict(input_tokens=model.input_tokens, output_tokens=model.output_tokens, model_calls=model.calls,
                            repairs=model.repairs, parts=out["chunks"])
        if out is None and ended.is_set():
            reason = why["reason"]
            if reason == "lost":
                return "lost"
            if reason == "credential":
                raise CredentialRejected("invalid_worker_credential", 401)
            if reason == "stop":
                self._report(job["id"], lease, "worker_shutdown", metrics, deadline=8.0)
                return "released"
            return self._report(job["id"], lease, "job_timeout", metrics)   # a cancelled job is answered 'cancelled'
        if out is None:
            return self._report(job["id"], lease, code, metrics)
        body = dict(lease_token=lease, title=out["title"][:500], body=out["body"], model=out["model"], metrics=metrics)
        try:
            r = self.hub.post(f"/jobs/{job['id']}/complete", body, deadline=SUBMIT_FOR, stop=self.stop)
        except LeaseLost:
            return "lost"
        except CredentialRejected:
            raise
        except HubError as exc:
            log.error("job=%s result not accepted error=%s", job["id"], exc.code)
            if exc.status in (409, 413, 422):      # repeating it cannot help
                return self._report(job["id"], lease, "llm_malformed", metrics)
            return "lost"
        log.info("job=%s status=%s %s", job["id"], r.get("status"), " ".join(f"{k}={v}" for k, v in metrics.items()))
        return {"succeeded": "completed", "requeued": "requeued", "cancelled": "cancelled"}.get(str(r.get("status")), "failed")

    def _report(self, job_id: str, lease: str, code: str, metrics: dict[str, int], deadline: float = 300.0) -> str:
        try:
            r = self.hub.post(f"/jobs/{job_id}/fail", dict(lease_token=lease, code=code, metrics=metrics),
                              deadline=deadline, stop=None if deadline < 10 else self.stop)
        except LeaseLost:
            return "lost"
        except CredentialRejected:
            raise
        except HubError:
            return "lost"           # the lease expires and the server queues the job again
        log.warning("job=%s code=%s status=%s", job_id, code, r.get("status"))
        return "cancelled" if r.get("status") == "cancelled" else "failed"

    _current: tuple[threading.Event, threading.Event, dict[str, str]] | None = None

    def request_stop(self) -> None:
        self.stop.set()
        current = self._current
        if current is not None:
            done, ended, why = current
            why["reason"] = why["reason"] or "stop"
            threading.Thread(target=self._abort, args=(done, ended), daemon=True).start()

    # ---------------------------------------------------------------------- loop
    def model_ready(self) -> bool:
        """Jobs are only claimed while the model can run, so an Ollama outage uses up no attempts."""
        try:
            names = self.llm.installed_models()
        except LLMError as exc:
            log.warning("ollama error=%s", exc.code)
            return False
        if self.llm.model not in names:
            log.error("ollama model %s is not installed", self.llm.model)
            return False
        return True

    def step(self) -> str:
        """Claim and run at most one job: idle | paused | offline | no_model | outside_hours | a run_job result."""
        hours = self.config.active_hours
        if hours and not hours[0] <= self.now().astimezone(KST).hour < hours[1]:
            return "outside_hours"
        if not self.model_ready():
            return "no_model"
        try:
            # the server hands announcement jobs only to a worker that runs the configured translation model
            r = self.hub.post("/claim", {"lease_token": str(uuid.uuid4()), "model": self.llm.model}, deadline=120.0,
                              stop=self.stop)
        except CredentialRejected:
            raise
        except HubError as exc:
            log.warning("claim error=%s", exc.code)
            return "offline"
        if not isinstance(r.get("job"), dict):
            return "paused" if r.get("state") == "paused" else "idle"
        self.metrics["claimed"] += 1
        log.info("job=%s claimed %s->%s mode=%s", r["job"].get("id"), r["job"].get("source_language"),
                 r["job"].get("target_language"), r["job"].get("mode"))
        result = self.run_job(r["job"])
        if result in self.metrics:
            self.metrics[result] += 1
        return result

    def run(self, mode: str = "service") -> int:
        """``once``: one job. ``drain``: until the queue is empty. ``service``: until stopped."""
        idle = self.config.idle_min
        failures = 0
        while not self.stop.is_set():
            result = self.step()
            if mode == "once" or (mode == "drain" and result in ("idle", "paused", "offline", "no_model", "outside_hours")):
                break
            if result in ("completed", "requeued", "cancelled"):
                idle, failures = self.config.idle_min, 0
                continue
            if result in ("failed", "lost"):
                failures += 1
                if mode == "drain" and failures >= 5:
                    log.error("stopping after %d failures in a row", failures)
                    break
                self.stop.wait(min(300.0, 5.0 * 2 ** min(failures, 6)) if failures > 1 else 1.0)
                continue
            if result == "released":
                break
            self.stop.wait(idle)
            idle = min(self.config.idle_max, idle * 2)
        log.info("stopped %s", " ".join(f"{k}={v}" for k, v in self.metrics.items()))
        return EXIT_OK
