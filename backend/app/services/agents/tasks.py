"""Agent tasks: durable, owned, auditable units of agent work.

* A task is a row in ``agent_tasks`` FIRST; it is executed by the existing worker (``JobRunner``, via the
  ``claim_agent_task`` RPC with ``FOR UPDATE SKIP LOCKED``), or by a request background task in inline mode.
  It is never executed inside the HTTP handler that created it.
* Lifecycle: queued -> running -> completed | failed | cancelled; actions with side effects start in
  ``awaiting_approval`` and only run after the owner approves. Transient failures re-queue with backoff up to
  ``max_attempts``; tasks of a dead worker are re-queued by the claim RPC.
* Every step (tool call, delegation, result, error, approval) is stored in ``agent_task_events`` with the agent
  that performed it, so the student sees who did what and from which sources (provenance).
* Delegation is controlled: only to agents listed in ``can_delegate_to``, depth <= 2, never back to an agent
  already in the chain.
* Scheduled agents use the same tasks (``requested_by`` = null). They run only when the server switch
  ``AGENT_SCHEDULES_ENABLED`` is on AND an admin enabled that schedule; both are off by default.
"""
from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from fastapi import BackgroundTasks
from pydantic import ValidationError

from app.core.errors import (
    AppError,
    Conflict,
    DuplicateError,
    Forbidden,
    NotAuthenticated,
    NotFound,
    ValidationFailed,
)
from app.repositories.base import Query, get_one
from app.services.agents.registry import AGENTS, AgentDefinition, get_agent
from app.services.agents.router import plan_request
from app.services.agents.tools import (
    TOOLS,
    P,
    SourceCheckParams,
    SupportRequestParams,
    ToolContext,
    ToolRegistry,
    TopicParams,
)
from app.services.announcements import today_kst

if TYPE_CHECKING:
    from app.security.auth import AuthUser
    from app.services.container import Services

log = logging.getLogger("app.agents")
ACTIVE = ("queued", "running", "awaiting_approval")
FINISHED = ("completed", "failed", "cancelled")
MAX_DEPTH = 2
RECENT_SECONDS = 15 * 60          # a finished task colours its agent (completed / error) for this long


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


class TaskCancelled(Exception):
    pass


class TaskTimeout(AppError):
    status_code, code = 504, "timeout"


class QuotaExceeded(AppError):
    status_code, code = 429, "task_quota"


# ---------------------------------------------------------------------------------------------- task types
class ScanParams(P):
    q: str | None = None


class RefParams(P):
    ref: str
    language: str | None = None


class LookupParams(P):
    tool: str
    params: dict[str, Any] = {}


class DelegateParams(P):
    agent_id: str
    tool: str
    params: dict[str, Any] = {}


TASK_PARAMS: dict[str, type[P]] = {
    "scholarship_scan": ScanParams, "career_scan": ScanParams, "event_digest": ScanParams,
    "announcement_digest": ScanParams, "visa_checklist": TopicParams, "academic_checklist": TopicParams,
    "topik_dates": ScanParams, "summarize_announcement": RefParams, "explain_document": RefParams,
    "support_request": SupportRequestParams, "lookup": LookupParams, "delegated_search": DelegateParams,
    "announcement_discovery": SourceCheckParams, "opportunity_discovery": SourceCheckParams,
    "guidance_discovery": SourceCheckParams, "event_discovery": SourceCheckParams,
}
#: tasks that crawl official websites: administrators (or an admin-enabled schedule) only
ADMIN_TASKS = {"announcement_discovery", "opportunity_discovery", "guidance_discovery", "event_discovery"}
#: agents that can have official sources (discovery_sources.agent_id)
DISCOVERY_AGENTS = ("announcement", "scholarship", "career", "events", "immigration", "academic", "topik")
LLM_TASKS = {"summarize_announcement", "explain_document"}
APPROVAL_TASKS = {"support_request"}


def task_types_of(agent: AgentDefinition) -> tuple[str, ...]:
    # every agent can run its own read tools as a background "lookup" (used for delegation)
    return (*agent.task_types, "lookup")


class AgentTaskService:
    def __init__(self, svc: Services):
        self.svc = svc
        self.store = svc.store
        self.settings = svc.settings
        self.tools = ToolRegistry()
        self.worker_id = "inline"

    # ================================================================== pause (migration 0017)
    def paused_agents(self) -> set[str]:
        try:
            rows, _ = self.store.select("agent_controls", Query(eq={"paused": True}, cols="agent_id", limit=50))
        except Exception:  # noqa: BLE001 - migration 0017 not applied: nothing can be paused
            return set()
        return {r["agent_id"] for r in rows}

    # ================================================================== directory
    def directory(self, user: AuthUser | None) -> list[dict[str, Any]]:
        states = self.agent_states(user)
        schedules = {(s["agent_id"]) for s in self._schedules() if s["enabled"] and self.settings.agent_schedules_enabled}
        checking = self.monitoring_activity()
        paused = self.paused_agents()
        known: dict[str, str | None] = {}
        role = user.role if user is not None else "visitor"
        out = []
        for a in AGENTS.values():
            actions = [dict(id=x.id, kind=x.kind, target=x.target, params=x.params, admin_only=x.roles is not None and "supporter" not in x.roles)
                       for x in a.actions if x.roles is None or (user is not None and user.role in x.roles)]
            visible = {x["id"] for x in actions}
            state = states.get(a.id, dict(state="idle", active=0, awaiting=0))
            if state["state"] in ("idle", "completed") and a.id in checking:
                # a monitoring check of official websites is running (scheduled or started by an admin): public,
                # nothing about who started it or what it found
                state = dict(state, state="working")
            interface = a.interface.view_for(role) | dict(
                task_actions=[x for x in a.interface.task_actions if x in visible])
            out.append(dict(
                id=a.id, character_id=a.character_id, name=a.name, title=a.title, department=a.department,
                description=a.description, scope=a.scope, languages=list(a.languages), fixed_language=a.fixed_language,
                tools=self.tools.describe(self.svc, a, known), task_types=list(a.task_types),
                can_delegate_to=list(a.can_delegate_to), restricted_actions=list(a.restricted_actions),
                actions=actions, monitoring=a.id in schedules, interface=interface,
                monitoring_check_running=a.id in checking, paused=a.id in paused, **state))
        return out

    def monitoring_activity(self) -> set[str]:
        """Agents with an official-source check queued or running right now (any requester)."""
        rows, _ = self.store.select("agent_tasks", Query(in_={"task_type": sorted(ADMIN_TASKS),
                                                              "status": ["queued", "running"]},
                                                         cols="agent_id", limit=20))
        return {r["agent_id"] for r in rows}

    def monitoring_status(self, user: AuthUser | None, agent_id: str) -> dict[str, Any]:
        """What a monitoring desk shows: its configured official sources, their coarse health, the last checks and
        whether automatic checks are switched on. Everyone sees names, public URLs, times and ok / attention;
        admins also see errors, failure counts, disabled sources and the schedule settings."""
        agent = self._agent(agent_id)
        admin = user is not None and user.is_admin
        sources = [s for s in self.svc.discovery.list_sources(agent_id=agent.id) if admin or s["enabled"]]

        def health(s: dict[str, Any]) -> str:
            if not s.get("last_checked_at"):
                return "not_checked"
            return "ok" if s.get("last_status") in ("ok", "partial") and not s.get("consecutive_failures") \
                else "attention"

        src_out = []
        for s in sources:
            row = dict(name=s["name"], url=s["url"], kind=s["kind"], health=health(s),
                       last_checked_at=s.get("last_checked_at"), last_success_at=s.get("last_success_at"))
            if admin:
                row.update(id=s["id"], enabled=s["enabled"], last_status=s.get("last_status"),
                           last_error=s.get("last_error"), consecutive_failures=s.get("consecutive_failures", 0))
            src_out.append(row)
        scheds = []
        for s in self._schedules():
            if s["agent_id"] != agent.id:
                continue
            state = "active" if s["enabled"] and self.settings.agent_schedules_enabled else \
                "off_on_server" if s["enabled"] and admin else "disabled"     # server settings: admins only
            row = dict(task_type=s["task_type"], state=state, interval_minutes=s.get("interval_minutes"),
                       last_run_at=s.get("last_run_at"), last_success_at=s.get("last_success_at"),
                       next_run_at=s.get("next_run_at") if state == "active" else None)
            if admin:
                row.update(id=s["id"], enabled=s["enabled"], last_error=s.get("last_error"),
                           params=s.get("params") or {})
            scheds.append(row)
        checks = [s["last_checked_at"] for s in sources if s.get("last_checked_at")]
        successes = [s["last_success_at"] for s in sources if s.get("last_success_at")]
        out: dict[str, Any] = dict(
            agent_id=agent.id, supported=agent.id in DISCOVERY_AGENTS, sources=src_out, schedules=scheds,
            checking=agent.id in self.monitoring_activity(),
            last_checked_at=max(checks) if checks else None, last_success_at=max(successes) if successes else None)
        if admin:
            out["schedules_enabled_on_server"] = self.settings.agent_schedules_enabled
            if agent.id in DISCOVERY_AGENTS:
                out["candidates_waiting"] = len(self.svc.discovery.candidates(agent_id=agent.id, limit=200))
        return out

    def agent_states(self, user: AuthUser | None) -> dict[str, dict[str, Any]]:
        """Backend-owned state per agent for this viewer: working / waiting / completed / error / idle."""
        if user is None:
            return {}
        rows, _ = self.store.select("agent_tasks", Query(eq={"requested_by": user.id}, order=[("updated_at", True)],
                                                         limit=100, cols="id,agent_id,status,updated_at,completed_at"))
        cutoff = (datetime.now(UTC) - timedelta(seconds=RECENT_SECONDS)).isoformat()
        out: dict[str, dict[str, Any]] = {}
        for r in rows:
            s = out.setdefault(r["agent_id"], dict(state="idle", active=0, awaiting=0, last_task_id=None))
            if r["status"] in ("queued", "running"):
                s["active"] += 1
            elif r["status"] == "awaiting_approval":
                s["awaiting"] += 1
            if s["last_task_id"] is None:
                s["last_task_id"] = r["id"]
                recent = (r.get("completed_at") or "") >= cutoff
                s["recent"] = "completed" if r["status"] == "completed" and recent else \
                    "error" if r["status"] == "failed" and recent else None
        for s in out.values():
            s["state"] = "working" if s["active"] else "waiting" if s["awaiting"] else s.pop("recent", None) or "idle"
            s.pop("recent", None)
        return out

    # ================================================================== instant tools and requests
    def _agent(self, agent_id: str) -> AgentDefinition:
        a = get_agent(agent_id)
        if a is None:
            raise NotFound("Agent not found.")
        return a

    def _ctx(self, agent: AgentDefinition, user: AuthUser | None, language: str | None, **kw: Any) -> ToolContext:
        lang = agent.fixed_language or language or (user.preferred_language if user else "en")
        return ToolContext(svc=self.svc, agent=agent, user=user, language=lang, **kw)

    def run_tool(self, user: AuthUser | None, agent_id: str, tool: str, params: dict[str, Any],
                 language: str | None, client_key: str) -> dict[str, Any]:
        from app.core.rate_limit import limiter

        agent = self._agent(agent_id)
        limiter.check(f"user:{user.id}" if user else client_key, "agent-tool", self.settings.agent_tool_runs_per_minute)
        out = self.tools.run(self._ctx(agent, user, language), tool, params)
        return dict(route="tool", agent_id=agent.id, handled_by=agent.id, result=out)

    def handle_request(self, user: AuthUser | None, agent_id: str, message: str, language: str | None,
                       client_key: str, background: BackgroundTasks | None = None) -> dict[str, Any]:
        """A free-text request to one agent -> answer / tool / task / approval / clarify (see router.py)."""
        agent = self._agent(agent_id)
        plan = plan_request(agent, message, signed_in=user is not None)
        base = dict(route=plan.route, agent_id=agent.id, handled_by=plan.agent_id, reason=plan.reason)
        if plan.route == "answer":
            return base | dict(handled_by=agent.id, language=self._ctx(agent, user, language).language)
        if plan.route == "clarify":
            return base | dict(options=plan.options)
        worker = self._agent(plan.agent_id)
        delegated = worker.id != agent.id
        if delegated and worker.id not in agent.can_delegate_to:
            # not this desk's job, and this agent may not hand work over: point to the right desk
            return dict(route="redirect", agent_id=agent.id, handled_by=None, reason=plan.reason,
                        suggested_agent=worker.id, suggested_character=worker.character_id)
        if plan.route == "tool":
            out = self.run_tool(user, worker.id, plan.target or "", plan.params, language, client_key)
            return base | dict(result=out["result"], delegated_from=agent.id if delegated else None)
        if user is None:
            raise NotAuthenticated("Sign in so the agent can work on this for you and keep the result.")
        params = dict(plan.params)
        if plan.target in ("summarize_announcement", "explain_document"):
            params = dict(ref=params["ref"], language=self._ctx(agent, user, language).language)
        task = self.create(user, worker.id, plan.target or "", params, language=language, background=background,
                           delegated_from=agent.id if delegated else None)
        return base | dict(task=task, delegated_from=agent.id if delegated else None)

    # ================================================================== create / read / cancel / approve
    def _validate(self, task_type: str, params: dict[str, Any]) -> dict[str, Any]:
        model = TASK_PARAMS.get(task_type)
        if model is None:
            raise ValidationFailed(f"Unknown task type '{task_type}'.")
        try:
            return model.model_validate(params or {}).model_dump(exclude_none=True)
        except ValidationError as exc:
            raise ValidationFailed("Invalid task parameters.",
                                   details={"errors": [dict(loc=list(e["loc"]), msg=e["msg"]) for e in exc.errors()]}) from exc

    def _check_quota(self, user: AuthUser) -> None:
        _, active = self.store.select("agent_tasks", Query(eq={"requested_by": user.id}, in_={"status": list(ACTIVE)},
                                                           cols="id", limit=1), count=True)
        if (active or 0) >= self.settings.agent_max_active_tasks_per_user:
            raise QuotaExceeded("You already have several tasks in progress. Wait for one to finish or cancel one.",
                                details={"limit": self.settings.agent_max_active_tasks_per_user})
        midnight = datetime.combine(today_kst(), datetime.min.time()).replace(tzinfo=UTC) - timedelta(hours=9)
        _, today = self.store.select("agent_tasks", Query(eq={"requested_by": user.id},
                                                          gte={"created_at": midnight.isoformat()}, cols="id", limit=1),
                                     count=True)
        if (today or 0) >= self.settings.agent_daily_tasks_per_user:
            raise QuotaExceeded("You have reached today's limit for agent tasks. Please try again tomorrow.",
                                details={"limit": self.settings.agent_daily_tasks_per_user})

    def create(self, user: AuthUser | None, agent_id: str, task_type: str, params: dict[str, Any], *,
               language: str | None = None, idempotency_key: str | None = None, background: BackgroundTasks | None = None,
               parent: dict[str, Any] | None = None, schedule_id: str | None = None,
               delegated_from: str | None = None) -> dict[str, Any]:
        if not self.settings.agent_tasks_enabled:
            raise AppError("Agent tasks are switched off on this server.", code="tasks_disabled", status_code=503)
        agent = self._agent(agent_id)
        if agent.id in self.paused_agents():
            raise AppError(f"{agent.name} is paused by an administrator.", code="agent_paused", status_code=503)
        if task_type not in task_types_of(agent):
            raise Forbidden(f"{agent.name} does not handle '{task_type}' tasks.", code="task_not_allowed")
        if task_type in ADMIN_TASKS and not (schedule_id or (user is not None and user.is_admin)):
            raise Forbidden("Checking official websites is limited to administrators.", code="admin_only")
        if task_type in ADMIN_TASKS and self._discovery_active(agent.id):
            # one check of an agent's official websites at a time (two admins, a double click, a schedule)
            raise Conflict("A check of these official websites is already running; its result will appear here.",
                           code="check_running")
        clean = self._validate(task_type, params)
        if task_type == "lookup":       # a lookup may only use one of this agent's own, instant, read-only tools
            self._lookup_tool(agent, clean["tool"])
        if task_type in LLM_TASKS:
            reason = TOOLS["summarize_document"].unavailable_reason(self.svc)
            if reason:
                raise AppError(reason, code="tool_unavailable", status_code=409)
        if user is not None and parent is None:
            self._check_quota(user)
            if task_type in LLM_TASKS:   # model work counts against the student's daily AI budget
                from app.core.rate_limit import limit_ai_action

                limit_ai_action(user.id, self.settings, ai_enabled=True)
        depth = (parent["depth"] + 1) if parent else 0
        lang = agent.fixed_language or language or (user.preferred_language if user else None)
        row = dict(agent_id=agent.id, task_type=task_type, requested_by=user.id if user else None,
                   parent_task_id=parent["id"] if parent else None, depth=depth, language=lang,
                   params=clean | ({"delegated_from": delegated_from} if delegated_from else {}),
                   status="awaiting_approval" if task_type in APPROVAL_TASKS else "queued",
                   idempotency_key=idempotency_key, schedule_id=schedule_id,
                   stage="awaiting_approval" if task_type in APPROVAL_TASKS else "queued")
        try:
            task = self.store.insert("agent_tasks", row)
        except DuplicateError:
            existing = self._active_duplicate(user, idempotency_key)
            if existing is None:
                raise
            return self.view(existing)
        if delegated_from:
            self._event(task, delegated_from, "delegate", None,
                        f"{AGENTS[delegated_from].name} handed this to {agent.name}", dict(to=agent.id))
        if task["status"] == "awaiting_approval":
            self._event(task, agent.id, "approval", None, f"{agent.name} prepared this and is waiting for your "
                                                          "confirmation", dict(preview=clean))
        else:
            self._event(task, agent.id, "queued", None, f"Queued for {agent.name}")
            if parent is None:
                self._enqueue(task, background)
        return self.view(task)

    def _lookup_tool(self, agent: AgentDefinition, tool: str) -> None:
        t = TOOLS.get(tool)
        if t is None or tool not in agent.allowed_tools or t.writes or t.needs_approval or tool in (
                "create_agent_task", "get_agent_task_status"):
            raise Forbidden(f"{agent.name} cannot run '{tool}' as a lookup.", code="tool_not_allowed")

    def _active_duplicate(self, user: AuthUser | None, key: str | None) -> dict[str, Any] | None:
        if not key:
            return None
        rows, _ = self.store.select("agent_tasks", Query(eq={"idempotency_key": key}, in_={"status": list(ACTIVE)}))
        rows = [r for r in rows if r.get("requested_by") == (user.id if user else None)]
        return rows[0] if rows else None

    def _owned(self, user: AuthUser, task_id: str) -> dict[str, Any]:
        t = get_one(self.store, "agent_tasks", id=task_id)
        if t is None or t.get("requested_by") != user.id:
            raise NotFound("Task not found.")       # someone else's task looks exactly like a missing one
        return t

    def view(self, t: dict[str, Any], *, events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        a = AGENTS.get(t["agent_id"])
        out = {k: t.get(k) for k in ("id", "agent_id", "task_type", "status", "stage", "language", "params", "output",
                                       "citations", "error_code", "error_message", "attempts", "max_attempts",
                                       "parent_task_id", "depth", "created_at", "updated_at", "started_at",
                                       "completed_at", "cancel_requested", "progress", "schedule_id")}
        out["agent_name"] = a.name if a else t["agent_id"]
        out["scheduled"] = t.get("requested_by") is None
        if events is not None:
            out["events"] = events
        return out

    def _events(self, task_id: str) -> list[dict[str, Any]]:
        rows, _ = self.store.select("agent_task_events", Query(eq={"task_id": task_id}, order=[("id", False)], limit=200))
        return [dict(id=r["id"], agent_id=r["agent_id"], step=r["step"], tool=r.get("tool"), message=r["message"],
                     data=r.get("data") or {}, created_at=r["created_at"]) for r in rows]

    def get(self, user: AuthUser, task_id: str, *, with_events: bool = True) -> dict[str, Any]:
        t = self._owned(user, task_id)
        if not with_events:
            return self.view(t)
        children, _ = self.store.select("agent_tasks", Query(eq={"parent_task_id": t["id"]}, order=[("created_at", False)]))
        out = self.view(t, events=self._events(t["id"]))
        out["children"] = [self.view(c, events=self._events(c["id"])) for c in children]
        return out

    def list(self, user: AuthUser, *, agent_id: str | None, status: str | None, page: int, size: int
             ) -> tuple[list[dict[str, Any]], int]:
        eq: dict[str, Any] = {"requested_by": user.id}
        if agent_id:
            eq["agent_id"] = agent_id
        if status:
            eq["status"] = status
        rows, total = self.store.select("agent_tasks", Query(eq=eq, is_null={"parent_task_id": True},
                                                             order=[("created_at", True)], limit=size,
                                                             offset=(page - 1) * size), count=True)
        return [self.view(r) for r in rows], total or 0

    def cancel(self, user: AuthUser, task_id: str) -> dict[str, Any]:
        t = self._owned(user, task_id)
        if t["status"] in FINISHED:
            raise AppError("This task has already finished.", code="invalid_state", status_code=409)
        if t["status"] in ("queued", "awaiting_approval"):
            rows = self.store.update("agent_tasks", dict(status="cancelled", stage="cancelled", completed_at=now_iso()),
                                     {"id": t["id"], "status": t["status"]})
            if rows:
                self._event(t, t["agent_id"], "cancel", None, "Cancelled by you")
                return self.view(rows[0])
            t = self._owned(user, task_id)
        # running: the worker stops at its next step
        rows = self.store.update("agent_tasks", dict(cancel_requested=True), {"id": t["id"]})
        self._event(t, t["agent_id"], "cancel", None, "Cancellation requested; the agent stops at its next step")
        return self.view(rows[0] if rows else t)

    def decide(self, user: AuthUser, task_id: str, approve: bool, background: BackgroundTasks | None = None
               ) -> dict[str, Any]:
        """The owner confirms (or declines) an action that waits for approval. Only that exact, stored request runs."""
        t = self._owned(user, task_id)
        if t["status"] != "awaiting_approval":
            raise AppError("This task is not waiting for your confirmation.", code="invalid_state", status_code=409)
        if not approve:
            rows = self.store.update("agent_tasks", dict(status="cancelled", stage="declined", completed_at=now_iso()),
                                     {"id": t["id"], "status": "awaiting_approval"})
            self._event(t, t["agent_id"], "approval", None, "You declined; nothing was sent")
            return self.view(rows[0] if rows else self._owned(user, task_id))
        params = dict(t["params"]) | {"approved_by": user.id, "approved_at": now_iso()}
        rows = self.store.update("agent_tasks", dict(status="queued", stage="approved", params=params, run_after=now_iso()),
                                 {"id": t["id"], "status": "awaiting_approval"})
        if not rows:
            raise AppError("This task changed in the meantime. Reload it.", code="invalid_state", status_code=409)
        self._event(t, t["agent_id"], "approval", None, "You confirmed")
        self._enqueue(rows[0], background)
        return self.view(rows[0])

    # ================================================================== execution
    def _enqueue(self, task: dict[str, Any], background: BackgroundTasks | None) -> None:
        if self.svc.jobs.inline:
            if background is not None:
                background.add_task(self.run_inline, task["id"])
            else:
                self.run_inline(task["id"])
        else:
            self.svc.jobs.kick()

    def run_inline(self, task_id: str) -> None:
        rows = self.store.update("agent_tasks", dict(status="running", started_at=now_iso(), heartbeat_at=now_iso(),
                                                     locked_by=self.worker_id),
                                 {"id": task_id, "status": "queued"})
        if rows:
            t = rows[0]
            self.store.update("agent_tasks", dict(attempts=t["attempts"] + 1), {"id": task_id})
            t["attempts"] += 1
            self.execute(t)

    def claim(self, worker: str, stale_seconds: int) -> dict[str, Any] | None:
        rows = self.store.rpc("claim_agent_task", dict(p_worker=worker, p_stale_seconds=stale_seconds))
        if isinstance(rows, dict):
            rows = [rows]
        rows = [r for r in (rows or []) if r and r.get("id")]
        return rows[0] if rows else None

    def _event(self, task: dict[str, Any], agent_id: str, step: str, tool: str | None, message: str,
               data: dict[str, Any] | None = None) -> None:
        try:
            self.store.insert("agent_task_events", dict(task_id=task["id"], agent_id=agent_id, step=step, tool=tool,
                                                        message=message[:2000], data=data or {}))
        except Exception:  # noqa: BLE001 - the step log must never break the task itself
            log.exception("could not record agent task event")

    def _checkpoint(self, task: dict[str, Any], started: float, stage: str) -> None:
        cur = get_one(self.store, "agent_tasks", id=task["id"]) or {}
        if cur.get("cancel_requested"):
            raise TaskCancelled()
        if time.monotonic() - started > self.settings.agent_task_timeout_seconds:
            raise TaskTimeout(f"The task took longer than {self.settings.agent_task_timeout_seconds} s and was stopped.")
        self.store.update("agent_tasks", dict(stage=stage, heartbeat_at=now_iso()), {"id": task["id"]})

    def _owner(self, task: dict[str, Any]) -> AuthUser | None:
        if not task.get("requested_by"):
            return None
        from app.security.auth import user_from_profile

        p = get_one(self.store, "profiles", id=task["requested_by"])
        return None if p is None else user_from_profile(self.store, p)

    def execute(self, task: dict[str, Any]) -> None:
        agent = AGENTS.get(task["agent_id"])
        started = time.monotonic()
        if agent is None:
            self._finish(task, "failed", error=("unknown_agent", "This agent no longer exists."))
            return
        self._event(task, agent.id, "start", None, f"{agent.name} started (attempt {task['attempts']})")
        user = self._owner(task)
        if task.get("requested_by") and user is None:
            self._finish(task, "failed", error=("no_owner", "The account that requested this task no longer exists."))
            return
        ctx = self._ctx(agent, user, task.get("language"), in_task=True, task=task, depth=task.get("depth", 0),
                        approved=bool((task.get("params") or {}).get("approved_by")))
        ctx.log = lambda agent_id, step, tool, message, data=None: self._event(task, agent_id, step, tool, message, data)
        ctx.checkpoint = lambda stage: self._checkpoint(task, started, stage)
        ctx.progress = lambda p: self.store.update("agent_tasks", {"progress": p}, {"id": task["id"]})
        ctx.system = task.get("requested_by") is None and bool(task.get("schedule_id"))
        try:
            from app.services.agents.handlers import HANDLERS

            ctx.checkpoint("working")
            output = HANDLERS[task["task_type"]](self, ctx, task)
            ctx.checkpoint("finishing")
        except TaskCancelled:
            self._finish(task, "cancelled", stage="cancelled")
            self._event(task, agent.id, "cancel", None, "Stopped: cancelled by you")
            return
        except Exception as exc:  # noqa: BLE001 - every failure is recorded on the task, never swallowed
            code, message, transient = _classify(exc)
            if transient and task["attempts"] < task["max_attempts"]:
                delay = 30 * 2 ** (task["attempts"] - 1)
                self.store.update("agent_tasks", dict(status="queued", stage="retry_wait", locked_by=None,
                                                      error_code=code, error_message=message,
                                                      run_after=(datetime.now(UTC) + timedelta(seconds=delay)).isoformat()),
                                  {"id": task["id"]})
                self._event(task, agent.id, "error", None, f"Temporary problem ({code}); retrying in {delay} s",
                            dict(code=code))
                return
            self._finish(task, "failed", error=(code, message))
            self._event(task, agent.id, "error", None, message, dict(code=code))
            if task.get("schedule_id"):
                self.store.update("agent_schedules", dict(last_error=f"{code}: {message}"[:500]), {"id": task["schedule_id"]})
                notes = getattr(self.svc, "notifications", None)
                if notes is not None:      # nobody is watching a scheduled task: tell the admins
                    notes.notify("agent_schedule_failed", f"Scheduled {task['task_type']} failed ({agent.name})",
                                 message[:500], severity="error", entity_type="agent_task", entity_id=task["id"])
            return
        citations = [dict(title=i.get("title"), href=i.get("href"), kind=i.get("kind"), reliability=i.get("reliability"))
                     for i in output.get("items", []) if i.get("href")][:40]
        output["provenance"] = dict(agent_id=agent.id, generated_by=output.pop("generated_by", "deterministic"),
                                    finished_at=now_iso())
        self._finish(task, "completed", output=output, citations=citations)
        self._event(task, agent.id, "result", None, f"{agent.name} finished: {output.get('count', 0)} result(s)",
                    dict(count=output.get("count", 0)))
        if task.get("schedule_id"):
            self.store.update("agent_schedules", dict(last_success_at=now_iso(), last_error=None),
                              {"id": task["schedule_id"]})

    def _finish(self, task: dict[str, Any], status: str, *, output: dict[str, Any] | None = None,
                citations: list[dict[str, Any]] | None = None, error: tuple[str, str] | None = None,
                stage: str | None = None) -> None:
        patch: dict[str, Any] = dict(status=status, stage=stage or status, completed_at=now_iso(), locked_by=None)
        if output is not None:
            patch.update(output=output, citations=citations or [], error_code=None, error_message=None)
        if error:
            patch.update(error_code=error[0], error_message=error[1][:1000])
        self.store.update("agent_tasks", patch, {"id": task["id"]})

    # ================================================================== delegation
    def delegate(self, ctx: ToolContext, agent_id: str, task_type: str, params: dict[str, Any]) -> dict[str, Any]:
        """Run a sub-task by another agent INSIDE the current task (same worker), with full provenance."""
        parent = ctx.task
        if parent is None:
            raise Forbidden("Delegation happens only inside a task.", code="delegation_not_allowed")
        target = self._agent(agent_id)
        if target.id not in ctx.agent.can_delegate_to:
            raise Forbidden(f"{ctx.agent.name} may not hand work to {target.name}.", code="delegation_not_allowed")
        if parent["depth"] + 1 > MAX_DEPTH:
            raise Forbidden("Delegation is limited to two levels.", code="delegation_depth")
        chain = self._chain(parent)
        if target.id in chain:
            raise Forbidden("An agent cannot hand work back to an agent already working on this request.",
                            code="delegation_loop")
        child = self.create(ctx.user, target.id, task_type, params, language=ctx.language, parent=parent,
                            delegated_from=ctx.agent.id)
        ctx.log(ctx.agent.id, "delegate", None, f"{ctx.agent.name} asked {target.name} to help", dict(child=child["id"],
                                                                                                to=target.id))
        row = self.store.update("agent_tasks", dict(status="running", started_at=now_iso(), heartbeat_at=now_iso(),
                                                    attempts=1, locked_by=self.worker_id),
                                {"id": child["id"], "status": "queued"})
        if row:
            self.execute(row[0])
        done = get_one(self.store, "agent_tasks", id=child["id"]) or {}
        return self.view(done)

    def _chain(self, task: dict[str, Any]) -> list[str]:
        chain, cur, guard = [], task, 0
        while cur and guard < MAX_DEPTH + 2:
            chain.append(cur["agent_id"])
            delegated_from = (cur.get("params") or {}).get("delegated_from")
            if delegated_from:
                chain.append(delegated_from)
            cur = get_one(self.store, "agent_tasks", id=cur["parent_task_id"]) if cur.get("parent_task_id") else None
            guard += 1
        return chain

    # ================================================================== schedules (disabled by default)
    def _schedules(self) -> list[dict[str, Any]]:
        rows, _ = self.store.select("agent_schedules", Query(order=[("agent_id", False)]))
        return rows

    def schedules(self) -> dict[str, Any]:
        return dict(globally_enabled=self.settings.agent_schedules_enabled,
                    items=[self._schedule_view(s) for s in self._schedules()])

    @staticmethod
    def _schedule_view(s: dict[str, Any]) -> dict[str, Any]:
        a = AGENTS.get(s["agent_id"])
        return {k: s.get(k) for k in ("id", "agent_id", "task_type", "enabled", "interval_minutes", "last_run_at",
                                      "last_success_at", "next_run_at", "last_error", "updated_at")} | dict(
            agent_name=a.name if a else s["agent_id"], params=s.get("params") or {})

    def update_schedule(self, admin: AuthUser, schedule_id: str, *, enabled: bool | None,
                        interval_minutes: int | None, urls: list[str] | None,
                        params: dict[str, Any] | None = None) -> dict[str, Any]:
        s = get_one(self.store, "agent_schedules", id=schedule_id)
        if s is None:
            raise NotFound("Schedule not found.")
        patch: dict[str, Any] = dict(updated_by=admin.id)
        if enabled is not None:
            patch["enabled"] = enabled
            if enabled and not s["enabled"]:
                patch["next_run_at"] = now_iso()
        if interval_minutes is not None:
            if not 60 <= interval_minutes <= 10080:
                raise ValidationFailed("interval_minutes must be between 60 and 10080.")
            patch["interval_minutes"] = interval_minutes
        if urls is not None:
            self._check_urls(urls)
            patch["params"] = dict(s.get("params") or {}) | {"urls": urls}
        if params:
            patch["params"] = dict(patch.get("params") or s.get("params") or {}) | self._check_schedule_params(s, params)
        rows = self.store.update("agent_schedules", patch, {"id": schedule_id})
        self.store.insert("audit_log", dict(action="agent_schedule.update", entity_type="agent_schedule",
                                            entity_id=schedule_id, actor_id=admin.id,
                                            details={k: v for k, v in patch.items() if k != "updated_by"}))
        return self._schedule_view(rows[0])

    def _check_schedule_params(self, s: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        """Monitoring settings an admin may change: which sources, limits, notifications. Review cannot be turned
        off: discovered content always waits for an admin."""
        allowed = {"source_ids", "max_items_per_source", "max_sources", "notify_admins", "summarize_new", "review"}
        unknown = set(params) - allowed
        if unknown:
            raise ValidationFailed(f"Unknown schedule settings: {', '.join(sorted(unknown))}.")
        out: dict[str, Any] = {}
        if "source_ids" in params:
            ids = list(params["source_ids"] or [])
            own = {x["id"] for x in self.svc.discovery.list_sources(s["agent_id"])}
            if len(ids) > 10 or not set(ids) <= own:
                raise ValidationFailed("source_ids must be up to 10 sources of this agent.")
            out["source_ids"] = ids
        for k, lo, hi in (("max_items_per_source", 1, 30), ("max_sources", 1, 10)):
            if k in params:
                v = int(params[k])
                if not lo <= v <= hi:
                    raise ValidationFailed(f"{k} must be between {lo} and {hi}.")
                out[k] = v
        for k in ("notify_admins", "summarize_new"):
            if k in params:
                out[k] = bool(params[k])
        if "review" in params:
            if params["review"] != "admin":
                raise ValidationFailed("Discovered content always needs an admin's review; it cannot be published "
                                       "automatically.")
            out["review"] = "admin"
        return out

    def _check_urls(self, urls: list[str]) -> None:
        from app.security.url_guard import validate_url_syntax

        if len(urls) > 5:
            raise ValidationFailed("At most 5 official pages per schedule.")
        for u in urls:
            try:   # same allowlist rules as the fetcher (which also checks DNS / SSRF on every fetch)
                validate_url_syntax(u, self.svc.domains.domains())
            except AppError as exc:
                raise ValidationFailed(f"{u}: {exc.message}") from exc

    def _discovery_active(self, agent_id: str) -> bool:
        rows, _ = self.store.select("agent_tasks", Query(eq={"agent_id": agent_id},
                                                         in_={"task_type": sorted(ADMIN_TASKS),
                                                              "status": ["queued", "running"]}, cols="id", limit=1))
        return bool(rows)

    def _content_work_pending(self) -> bool:
        """Documents are being ingested / indexed / translated (or wait for the worker) right now."""
        now = now_iso()
        # jobs of the GPU worker use no capacity of this server and may wait for hours
        own = {"executor": "local"} if self.settings.gpu_worker_enabled else {}
        rows, _ = self.store.select("ingestion_jobs", Query(eq={"status": "running", **own}, cols="id", limit=1))
        if rows:
            return True
        rows, _ = self.store.select("ingestion_jobs", Query(eq={"status": "queued", **own}, lte={"run_after": now},
                                                            cols="id", limit=1))
        return bool(rows)

    def run_due_schedules(self) -> dict[str, Any]:
        """Called by the scheduler hook (run-due). Does nothing unless switched on globally AND per schedule."""
        if not self.settings.agent_schedules_enabled:
            return dict(enabled=False, queued=0)
        now = datetime.now(UTC)
        queued = postponed = 0
        paused = self.paused_agents()
        for s in self._schedules():
            if s["agent_id"] in paused:
                continue
            if not s["enabled"] or (s.get("next_run_at") and datetime.fromisoformat(s["next_run_at"]) > now):
                continue
            if s["task_type"] in ADMIN_TASKS and self._content_work_pending():
                # official-source checks only start when the worker has capacity: try again in 15 minutes
                self.store.update("agent_schedules", dict(next_run_at=(now + timedelta(minutes=15)).isoformat()),
                                  {"id": s["id"]})
                postponed += 1
                continue
            nxt = (now + timedelta(minutes=s["interval_minutes"])).isoformat()
            self.store.update("agent_schedules", dict(last_run_at=now.isoformat(), next_run_at=nxt), {"id": s["id"]})
            try:
                self.create(None, s["agent_id"], s["task_type"], {}, idempotency_key=f"schedule:{s['id']}",
                            schedule_id=s["id"])
                queued += 1
            except AppError as exc:
                self.store.update("agent_schedules", dict(last_error=exc.message[:500]), {"id": s["id"]})
        return dict(enabled=True, queued=queued, postponed=postponed)

    # ================================================================== retention
    def purge_expired(self) -> int:
        cutoff = (datetime.now(UTC) - timedelta(days=self.settings.agent_task_retention_days)).isoformat()
        rows, _ = self.store.select("agent_tasks", Query(in_={"status": list(FINISHED)}, lt={"created_at": cutoff},
                                                         is_null={"parent_task_id": True}, cols="id", limit=500))
        for r in rows:   # the database cascades; deleting children and events explicitly keeps every store consistent
            children, _ = self.store.select("agent_tasks", Query(eq={"parent_task_id": r["id"]}, cols="id"))
            for c in [*children, r]:
                self.store.delete("agent_task_events", {"task_id": c["id"]})
            for c in children:
                self.store.delete("agent_tasks", {"id": c["id"]})
            self.store.delete("agent_tasks", {"id": r["id"]})
        return len(rows)


def _classify(exc: Exception) -> tuple[str, str, bool]:
    """(code, student-safe message, transient?)"""
    from app.services.ingestion.errors import IngestionError
    from app.services.llm.base import LLMError

    if isinstance(exc, LLMError):
        return exc.code, "The AI model is not available right now." if exc.transient else \
            "The AI model could not complete this.", exc.transient
    if isinstance(exc, IngestionError):
        return exc.code, exc.message, exc.code in ("timeout", "connect_error", "http_502", "http_503", "http_504")
    if isinstance(exc, AppError):
        transient = exc.code in ("fetch_failed",) and str((exc.details or {}).get("reason", "")).startswith(
            ("timeout", "connect", "http_5"))
        return exc.code, exc.message, transient
    log.exception("agent task failed")
    return "internal_error", "Something went wrong while working on this task.", False
