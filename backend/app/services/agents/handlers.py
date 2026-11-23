"""What each task type does. Handlers only call registered tools through ``ToolRegistry.run`` (so every permission
check and step log applies) and return structured output; nothing here writes content or talks to a model directly."""
from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any

from app.core.errors import AppError
from app.repositories.base import Query, get_one

if TYPE_CHECKING:
    from app.services.agents.tasks import AgentTaskService
    from app.services.agents.tools import ToolContext

Handler = Any
MAX_DETAIL = 10          # announcements whose dates are extracted per run (bounded work per task)


def _clean(params: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in (params or {}).items() if k not in ("delegated_from", "approved_by", "approved_at")}


def _fingerprint(item: dict[str, Any]) -> str:
    key = "|".join(str(item.get(k) or "") for k in ("title", "deadline", "event_date", "published_at", "status"))
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _previous_fingerprints(svc: AgentTaskService, task: dict[str, Any]) -> dict[str, str] | None:
    """What this student (or this schedule) saw last time: the basis for "new" and "updated"."""
    if task.get("schedule_id"):
        s = get_one(svc.store, "agent_schedules", id=task["schedule_id"]) or {}
        return (s.get("state") or {}).get("fingerprints")
    rows, _ = svc.store.select("agent_tasks", Query(
        eq={"requested_by": task["requested_by"], "task_type": task["task_type"], "status": "completed"},
        neq={"id": task["id"]}, order=[("completed_at", True)], limit=1))
    return ((rows[0].get("output") or {}).get("fingerprints")) if rows else None


def _mark_changes(svc: AgentTaskService, task: dict[str, Any], out: dict[str, Any]) -> dict[str, Any]:
    prev = _previous_fingerprints(svc, task)
    current: dict[str, str] = {}
    new = updated = 0
    for it in out["items"]:
        if not it.get("id"):
            continue
        fp = current[it["id"]] = _fingerprint(it)
        it["change"] = None
        if prev is None:
            pass
        elif it["id"] not in prev:
            it["change"], new = "new", new + 1
        elif prev[it["id"]] != fp:
            it["change"], updated = "updated", updated + 1
    out.update(fingerprints=current, first_run=prev is None, new_count=new, updated_count=updated)
    if prev is None:
        out["notes"].append("first_check")
    if task.get("schedule_id"):
        s = get_one(svc.store, "agent_schedules", id=task["schedule_id"]) or {}
        svc.store.update("agent_schedules", dict(state=dict(s.get("state") or {}) | {"fingerprints": current}),
                         {"id": task["schedule_id"]})
    return out


def _with_dates(svc: AgentTaskService, ctx: ToolContext, out: dict[str, Any]) -> dict[str, Any]:
    for it in [i for i in out["items"] if i.get("kind") == "announcement"][:MAX_DETAIL]:
        ctx.checkpoint("extracting dates")
        d = svc.tools.run(ctx, "deadline_extraction", dict(announcement_id=it["id"]))
        it["dates"] = d["items"]
    return out


def _official_pages(svc: AgentTaskService, ctx: ToolContext, task: dict[str, Any], out: dict[str, Any]) -> dict[str, Any]:
    """Pages an ADMIN configured on the schedule (never URLs from a student or a model)."""
    if not task.get("schedule_id"):
        return out
    s = get_one(svc.store, "agent_schedules", id=task["schedule_id"]) or {}
    for url in ((s.get("params") or {}).get("urls") or [])[:5]:
        ctx.checkpoint("checking official pages")
        try:
            page = svc.tools.run(ctx, "official_page_fetch", dict(url=url))
            out["items"].extend(page["items"])
        except AppError as exc:   # shown as a failed item, never silently dropped
            out["items"].append(dict(kind="external_page", title=url, href=url, error=exc.code, reliability=None))
    out["count"] = len(out["items"])
    return out


def scan(tool: str) -> Handler:
    def run(svc: AgentTaskService, ctx: ToolContext, task: dict[str, Any]) -> dict[str, Any]:
        out = svc.tools.run(ctx, tool, _clean(task["params"]))
        out = _with_dates(svc, ctx, out)
        out = _official_pages(svc, ctx, task, out)
        return _mark_changes(svc, task, out)
    return run


def digest(tool: str, params: dict[str, Any]) -> Handler:
    def run(svc: AgentTaskService, ctx: ToolContext, task: dict[str, Any]) -> dict[str, Any]:
        out = svc.tools.run(ctx, tool, params)
        if tool == "announcement_search":
            out = _with_dates(svc, ctx, out)
        return _mark_changes(svc, task, out)
    return run


def same_tool(svc: AgentTaskService, ctx: ToolContext, task: dict[str, Any]) -> dict[str, Any]:
    return svc.tools.run(ctx, task["task_type"], _clean(task["params"]))


def summarize(svc: AgentTaskService, ctx: ToolContext, task: dict[str, Any]) -> dict[str, Any]:
    p = _clean(task["params"])
    ref = p["ref"]
    is_announcement = get_one(svc.store, "announcements", id=ref) is not None
    out = svc.tools.run(ctx, "summarize_document", dict(language=p.get("language") or ctx.language,
                                                        **({"announcement_id": ref} if is_announcement
                                                           else {"document_id": ref})))
    out["generated_by"] = out["items"][0].get("model") or "model"
    return out


def support_request(svc: AgentTaskService, ctx: ToolContext, task: dict[str, Any]) -> dict[str, Any]:
    return svc.tools.run(ctx, "create_support_request", _clean(task["params"]))


def lookup(svc: AgentTaskService, ctx: ToolContext, task: dict[str, Any]) -> dict[str, Any]:
    p = _clean(task["params"])
    svc._lookup_tool(ctx.agent, p["tool"])
    return svc.tools.run(ctx, p["tool"], p.get("params") or {})


def delegated(svc: AgentTaskService, ctx: ToolContext, task: dict[str, Any]) -> dict[str, Any]:
    p = _clean(task["params"])
    child = svc.tools.run(ctx, "create_agent_task", dict(agent_id=p["agent_id"], task_type="lookup",
                                                          params=dict(tool=p["tool"], params=p.get("params") or {})))
    sub = child["items"][0]
    if sub["status"] != "completed":
        raise AppError(sub.get("error_message") or "The specialist could not finish this.",
                       code=sub.get("error_code") or "delegation_failed")
    out = dict(sub["output"])
    out.pop("provenance", None)
    out.update(handled_by=p["agent_id"], child_task_id=sub["id"])
    return out


HANDLERS: dict[str, Handler] = {
    "scholarship_scan": scan("scholarship_search"),
    "career_scan": scan("career_opportunity_search"),
    "event_digest": digest("event_search", {"days": 60}),
    "announcement_digest": digest("announcement_search", {"limit": 20}),
    "visa_checklist": same_tool,
    "academic_checklist": same_tool,
    "topik_dates": lambda svc, ctx, task: svc.tools.run(ctx, "topik_dates", {}),
    "summarize_announcement": summarize,
    "explain_document": summarize,
    "support_request": support_request,
    "lookup": lookup,
    "delegated_search": delegated,
}
