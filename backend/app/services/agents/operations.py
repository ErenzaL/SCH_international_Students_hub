"""What administrators see and may do with the agents: all tasks (metadata only, never a student's text), re-run, cancel, pause
a desk, health, storage. Reading never changes anything; every action is audited."""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from app.core.errors import InvalidState, NotFound
from app.repositories.base import Query, get_one
from app.services.agents.registry import AGENTS
from app.services.agents.tasks import ADMIN_TASKS, APPROVAL_TASKS, DISCOVERY_AGENTS, FINISHED, now_iso

if TYPE_CHECKING:
    from app.security.auth import AuthUser
    from app.services.container import Services

log = logging.getLogger("app.agents.ops")
STUCK_MINUTES = 120              # a queued job / task older than this is reported
WARN, CRITICAL = 0.70, 0.90      # share of DATABASE_LIMIT_MB
ALERT_HOURS = 24
#: tasks an administrator sees in full: no student asked for them
SYSTEM_TASKS = ADMIN_TASKS


def _age_minutes(v: str | None, now: datetime) -> int | None:
    return int((now - datetime.fromisoformat(v)).total_seconds() // 60) if v else None


class AgentOperations:
    def __init__(self, svc: Services):
        self.svc = svc
        self.store = svc.store
        self.settings = svc.settings

    # ================================================================== tasks
    def _view(self, t: dict[str, Any]) -> dict[str, Any]:
        """Metadata of any task. Parameters, output and step log only for monitoring tasks (no student content in them)."""
        a = AGENTS.get(t["agent_id"])
        out = {k: t.get(k) for k in ("id", "agent_id", "task_type", "status", "stage", "attempts", "max_attempts", "error_code",
                                     "created_at", "started_at", "completed_at", "heartbeat_at", "cancel_requested", "run_after")}
        system = t["task_type"] in SYSTEM_TASKS
        out.update(agent_name=a.name if a else t["agent_id"],
                   requested="schedule" if not t.get("requested_by") else "administrator" if system else "student",
                   can_rerun=self._can_rerun(t), can_cancel=t["status"] not in FINISHED)
        if system or not t.get("requested_by"):
            o = t.get("output") or {}
            out.update(error_message=t.get("error_message"), progress=t.get("progress") or {}, result_count=o.get("count"),
                       new_count=o.get("new_count"), updated_count=o.get("updated_count"), sources=o.get("sources"))
        return out

    @staticmethod
    def _can_rerun(t: dict[str, Any]) -> bool:
        # a write that may already have happened (a support request) is never repeated for the student
        return t["status"] == "failed" and t["task_type"] not in APPROVAL_TASKS and not t.get("parent_task_id")

    def tasks(self, *, agent_id: str | None, status: str | None, page: int, size: int) -> tuple[list[dict[str, Any]], int]:
        eq = {k: v for k, v in (("agent_id", agent_id), ("status", status)) if v}
        rows, total = self.store.select("agent_tasks", Query(eq=eq, is_null={"parent_task_id": True}, order=[("created_at", True)],
                                                             limit=size, offset=(page - 1) * size), count=True)
        return [self._view(r) for r in rows], total or 0

    def _task(self, task_id: str) -> dict[str, Any]:
        t = get_one(self.store, "agent_tasks", id=task_id)
        if t is None:
            raise NotFound("Task not found.")
        return t

    def task(self, task_id: str) -> dict[str, Any]:
        t = self._task(task_id)
        out = self._view(t)
        rows, _ = self.store.select("agent_task_events", Query(eq={"task_id": t["id"]}, order=[("id", False)], limit=200))
        system = t["task_type"] in SYSTEM_TASKS
        out["events"] = [dict(agent_id=r["agent_id"], step=r["step"], tool=r.get("tool"), created_at=r["created_at"],
                              message=r["message"] if system else None) for r in rows]
        return out

    def rerun(self, admin: AuthUser, task_id: str, background: Any = None) -> dict[str, Any]:
        t = self._task(task_id)
        if not self._can_rerun(t):
            raise InvalidState("Only failed tasks without side effects can be run again.")
        rows = self.store.update("agent_tasks", dict(status="queued", stage="queued", attempts=0, error_code=None, error_message=None,
                                                     completed_at=None, locked_by=None, cancel_requested=False, run_after=now_iso()),
                                 {"id": t["id"], "status": "failed"})
        if not rows:
            raise InvalidState("The task changed in the meantime.")
        self._audit(admin, "agent_task.rerun", t)
        self.svc.agents._event(t, t["agent_id"], "queued", None, "Queued again by an administrator")
        self.svc.agents._enqueue(rows[0], background)
        return self._view(self._task(task_id))

    def cancel(self, admin: AuthUser, task_id: str) -> dict[str, Any]:
        t = self._task(task_id)
        if t["status"] in FINISHED:
            raise InvalidState("This task has already finished.")
        rows = []
        if t["status"] in ("queued", "awaiting_approval"):
            rows = self.store.update("agent_tasks", dict(status="cancelled", stage="cancelled", completed_at=now_iso()),
                                     {"id": t["id"], "status": t["status"]})
        if not rows:
            self.store.update("agent_tasks", dict(cancel_requested=True), {"id": t["id"]})
        self.svc.agents._event(t, t["agent_id"], "cancel", None, "Cancelled by an administrator")
        self._audit(admin, "agent_task.cancel", t)
        return self._view(self._task(task_id))

    def _audit(self, admin: AuthUser, action: str, t: dict[str, Any], **details: Any) -> None:
        self.store.insert("audit_log", dict(action=action, entity_type="agent_task", entity_id=t["id"], actor_id=admin.id,
                                            details=dict(agent=t["agent_id"], task_type=t["task_type"], **details)))

    # ================================================================== pause
    def set_paused(self, admin: AuthUser, agent_id: str, paused: bool, note: str | None) -> dict[str, Any]:
        if agent_id not in AGENTS:
            raise NotFound("Agent not found.")
        row = dict(paused=paused, note=note, updated_by=admin.id)
        try:
            if get_one(self.store, "agent_controls", agent_id=agent_id):
                self.store.update("agent_controls", row, {"agent_id": agent_id})
            else:
                self.store.insert("agent_controls", dict(row, agent_id=agent_id))
        except Exception as exc:  # noqa: BLE001
            raise InvalidState("Pausing needs migration 0017 on this database.", code="migration_missing") from exc
        self.store.insert("audit_log", dict(action="agent.pause" if paused else "agent.resume", entity_type="agent", entity_id=None,
                                            actor_id=admin.id, details=dict(agent=agent_id, note=note)))
        if not paused:
            self.svc.jobs.kick()
        return dict(agent_id=agent_id, paused=paused, note=note)

    # ================================================================== health
    def health(self) -> dict[str, Any]:
        now = datetime.now(UTC)
        since = (now - timedelta(days=7)).isoformat()
        rows, _ = self.store.select("agent_tasks", Query(gte={"created_at": since}, order=[("created_at", True)], limit=2000,
                                                         cols="id,agent_id,task_type,status,created_at,completed_at,error_code,heartbeat_at"))
        paused = self.svc.agents.paused_agents()
        scheds = self.svc.agents._schedules()
        sources = self.svc.discovery.list_sources()
        agents = []
        for a in AGENTS.values():
            mine = [r for r in rows if r["agent_id"] == a.id]
            count = {s: sum(1 for r in mine if r["status"] == s) for s in ("queued", "running", "awaiting_approval", "completed", "failed", "cancelled")}
            done = [r["completed_at"] for r in mine if r["status"] == "completed" and r.get("completed_at")]
            failed = [r for r in mine if r["status"] == "failed"]
            src = [s for s in sources if s["agent_id"] == a.id]
            tools = self.svc.agents.tools.describe(self.svc, a)
            agents.append(dict(
                id=a.id, name=a.name, title=a.title, paused=a.id in paused, interface=a.interface.type, tasks_7d=count,
                last_success_at=max(done) if done else None,
                last_failure_at=failed[0].get("completed_at") if failed else None, last_error=failed[0].get("error_code") if failed else None,
                tools_available=sum(1 for t in tools if t["available"]), tools_unavailable=[t["name"] for t in tools if not t["available"]],
                monitors=a.id in DISCOVERY_AGENTS, sources=len(src), sources_enabled=sum(1 for s in src if s["enabled"]),
                sources_failing=sum(1 for s in src if s["consecutive_failures"]),
                schedules=[dict(id=s["id"], task_type=s["task_type"], enabled=s["enabled"], interval_minutes=s["interval_minutes"],
                                last_run_at=s.get("last_run_at"), last_success_at=s.get("last_success_at"), last_error=s.get("last_error"))
                           for s in scheds if s["agent_id"] == a.id]))
        return dict(checked_at=now.isoformat(), schedules_enabled_on_server=self.settings.agent_schedules_enabled,
                    tasks_enabled=self.settings.agent_tasks_enabled, queues=self.queues(now), agents=agents)

    def queues(self, now: datetime | None = None) -> dict[str, Any]:
        now = now or datetime.now(UTC)
        out: dict[str, Any] = {}
        for name, table, extra in (("agent_tasks", "agent_tasks", {}), ("jobs", "ingestion_jobs", {"executor": "local"}),
                                   ("gpu_jobs", "ingestion_jobs", {"executor": "gpu"})):
            try:
                q, nq = self.store.select(table, Query(eq={"status": "queued", **extra}, order=[("created_at", False)], limit=1), count=True)
                _r, nr = self.store.select(table, Query(eq={"status": "running", **extra}, cols="id", limit=1), count=True)
                _f, nf = self.store.select(table, Query(eq={"status": "failed", **extra}, gte={"created_at": (now - timedelta(days=7)).isoformat()},
                                                        cols="id", limit=1), count=True)
            except Exception:  # noqa: BLE001 - the executor column needs migration 0016
                out[name] = None
                continue
            oldest = _age_minutes(q[0]["created_at"], now) if q else None
            due = not q or not q[0].get("run_after") or datetime.fromisoformat(q[0]["run_after"]) <= now
            out[name] = dict(queued=nq or 0, running=nr or 0, failed_7d=nf or 0, oldest_queued_minutes=oldest,
                             stuck=bool(oldest is not None and due and oldest > STUCK_MINUTES and name != "gpu_jobs"))
        if out.get("jobs") is None:        # before migration 0016
            _q, nq = self.store.select("ingestion_jobs", Query(eq={"status": "queued"}, cols="id", limit=1), count=True)
            out["jobs"] = dict(queued=nq or 0, running=None, failed_7d=None, oldest_queued_minutes=None, stuck=False)
        return out

    # ================================================================== storage
    def storage(self) -> dict[str, Any]:
        limit = self.settings.database_limit_mb * 1024 * 1024
        try:
            rows = self.store.rpc("storage_overview", {}) or []
        except Exception:  # noqa: BLE001
            return dict(available=False, reason="migration_missing", limit_bytes=limit)
        total = next((r["total_bytes"] for r in rows if r["table_name"] == "(database)"), 0)
        tables = sorted((r for r in rows if r["table_name"] != "(database)"), key=lambda r: -(r["total_bytes"] or 0))
        share = total / limit if limit else 0.0
        counts = {}
        since = (datetime.now(UTC) - timedelta(days=30)).isoformat()
        for t in ("source_documents", "document_versions", "document_chunks", "announcement_translations", "document_translations",
                  "agent_tasks", "agent_task_events", "ingestion_jobs", "ingestion_events", "audit_log", "discovered_items"):
            try:
                _r, n = self.store.select(t, Query(gte={"created_at": since}, limit=1), count=True)
                counts[t] = n or 0
            except Exception:  # noqa: BLE001
                counts[t] = None
        return dict(available=True, database_bytes=total, limit_bytes=limit, share=round(share, 4),
                    level="critical" if share >= CRITICAL else "warning" if share >= WARN else "ok",
                    tables=tables[:25], rows_added_30d=counts)

    # ================================================================== alerts (called by the scheduler hook)
    def alert(self) -> list[str]:
        """At most one notification per kind and day; never raises."""
        sent = []
        try:
            st = self.storage()
            if st.get("level") in ("warning", "critical"):
                sent += self._notify("storage_threshold", f"Database uses {round(st['share'] * 100)} % of its limit",
                                     "See Admin → Agents → Storage. Nothing is deleted automatically.",
                                     "error" if st["level"] == "critical" else "warning")
            for name, q in self.queues().items():
                if q and q["stuck"]:
                    sent += self._notify(f"queue_stuck_{name}", f"Queue '{name}': {q['queued']} waiting, the oldest for {q['oldest_queued_minutes']} minutes",
                                         "Is the API worker running (JOB_EXECUTION=worker)?", "warning")
        except Exception:  # noqa: BLE001
            log.exception("operations alert failed")
        return sent

    def _notify(self, kind: str, title: str, message: str, severity: str) -> list[str]:
        since = (datetime.now(UTC) - timedelta(hours=ALERT_HOURS)).isoformat()
        rows, _ = self.store.select("admin_notifications", Query(eq={"kind": kind}, gte={"created_at": since}, limit=1))
        if rows:
            return []
        self.svc.notifications.notify(kind, title, message, severity=severity, link="/admin/agents")
        return [kind]
