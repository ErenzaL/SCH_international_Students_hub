"""AI Support Office agents: directory, requests, instant tools, durable tasks, and (admin) schedules.

Read-only lookups over published content work for everyone (rate limited). Tasks belong to a signed-in student and
are only ever visible to that student; every permission is checked server-side (registry + tool registry)."""
from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.api.deps import Pagination, get_services
from app.core.rate_limit import client_ip, rate_limit
from app.schemas.api import Lang
from app.security.auth import AuthUser, get_current_user, get_store, get_verifier, require_admin
from app.services.container import Services

router = APIRouter(prefix="/api/v1", tags=["agents"])


def optional_user(request: Request) -> AuthUser | None:
    """The signed-in user when a bearer token is sent (an invalid token is still an error), else None."""
    if not request.headers.get("authorization"):
        return None
    from app.core.config import get_settings

    settings = request.app.dependency_overrides.get(get_settings, get_settings)()
    return get_current_user(request, get_store(request), get_verifier(settings))


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AgentRequest(Body):
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
    language: Lang | None = None


class ToolRun(Body):
    tool: Annotated[str, StringConstraints(max_length=60)]
    params: dict[str, Any] = Field(default_factory=dict)
    language: Lang | None = None


class TaskCreate(Body):
    task_type: Annotated[str, StringConstraints(max_length=60)]
    params: dict[str, Any] = Field(default_factory=dict)
    language: Lang | None = None
    idempotency_key: Annotated[str, StringConstraints(min_length=8, max_length=100)] | None = None


class Decision(Body):
    approve: bool


class ScheduleUpdate(Body):
    enabled: bool | None = None
    interval_minutes: int | None = Field(default=None, ge=60, le=10080)
    urls: list[Annotated[str, StringConstraints(max_length=1000)]] | None = Field(default=None, max_length=5)
    #: monitoring settings: source_ids, max_items_per_source, max_sources, notify_admins, summarize_new, review
    params: dict[str, Any] | None = None


class DiscoverySourceCreate(Body):
    agent_id: Literal["announcement", "scholarship", "career", "events", "immigration", "academic", "topik"]
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=200)]
    kind: Literal["sch_board", "listing", "page", "saramin_api", "data_go_kr_jobs", "work24_api"]
    url: Annotated[str, StringConstraints(strip_whitespace=True, min_length=8, max_length=1000)]
    config: dict[str, Any] = Field(default_factory=dict)
    category: Annotated[str, StringConstraints(max_length=60)] | None = None
    language: Lang = "ko"
    enabled: bool = True


class DiscoverySourcePatch(Body):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=200)] | None = None
    config: dict[str, Any] | None = None
    category: Annotated[str, StringConstraints(max_length=60)] | None = None
    language: Lang | None = None
    enabled: bool | None = None
    reset_failures: bool = False


class ReviewNote(Body):
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] | None = None


@router.get("/agents", dependencies=[Depends(rate_limit("public"))])
def list_agents(svc: Services = Depends(get_services), user: AuthUser | None = Depends(optional_user)) -> dict:  # type: ignore[type-arg]
    """Every agent with its job description, tools (and whether each is available), allowed actions, and its
    current state for this viewer (working / waiting / completed / error / idle - from the viewer's own tasks)."""
    return dict(items=svc.agents.directory(user), signed_in=user is not None,
                is_admin=bool(user is not None and user.is_admin))


@router.get("/agents/{agent_id}/monitoring", dependencies=[Depends(rate_limit("public"))])
def agent_monitoring(agent_id: str, svc: Services = Depends(get_services),
                     user: AuthUser | None = Depends(optional_user)) -> dict:  # type: ignore[type-arg]
    """A monitoring desk's public status: configured official sources (name, public URL, last check, ok /
    attention), whether a check is running and whether automatic checks are on. Admins also get errors, failure
    counts, disabled sources, schedule settings and the number of candidates waiting for review. Never items."""
    return svc.agents.monitoring_status(user, agent_id)


@router.post("/agents/{agent_id}/requests", dependencies=[Depends(rate_limit("search"))])
def agent_request(agent_id: str, body: AgentRequest, request: Request, background: BackgroundTasks,
                  svc: Services = Depends(get_services), user: AuthUser | None = Depends(optional_user)) -> dict:  # type: ignore[type-arg]
    return svc.agents.handle_request(user, agent_id, body.message, body.language, client_ip(request, svc.settings),
                                     background)


@router.post("/agents/{agent_id}/tools", dependencies=[Depends(rate_limit("search"))])
def run_tool(agent_id: str, body: ToolRun, request: Request, svc: Services = Depends(get_services),
             user: AuthUser | None = Depends(optional_user)) -> dict:  # type: ignore[type-arg]
    """Run one instant, read-only tool of this agent (background tools must be started as a task)."""
    return svc.agents.run_tool(user, agent_id, body.tool, body.params, body.language, client_ip(request, svc.settings))


@router.post("/agents/{agent_id}/tasks", status_code=201, dependencies=[Depends(rate_limit("ingest"))])
def create_task(agent_id: str, body: TaskCreate, background: BackgroundTasks, svc: Services = Depends(get_services),
                user: AuthUser = Depends(get_current_user)) -> dict:  # type: ignore[type-arg]
    return svc.agents.create(user, agent_id, body.task_type, body.params, language=body.language,
                             idempotency_key=body.idempotency_key, background=background)


@router.get("/agent-tasks")
def list_tasks(agent_id: str | None = None,
               status: Literal["queued", "running", "awaiting_approval", "completed", "failed", "cancelled"] | None = None,
               pg: Pagination = Depends(), svc: Services = Depends(get_services),
               user: AuthUser = Depends(get_current_user)) -> dict:  # type: ignore[type-arg]
    items, total = svc.agents.list(user, agent_id=agent_id, status=status, page=pg.page, size=pg.page_size)
    return pg.wrap(items, total)


@router.get("/agent-tasks/{task_id}")
def get_task(task_id: str, svc: Services = Depends(get_services), user: AuthUser = Depends(get_current_user)) -> dict:  # type: ignore[type-arg]
    return svc.agents.get(user, task_id)


@router.post("/agent-tasks/{task_id}/cancel")
def cancel_task(task_id: str, svc: Services = Depends(get_services), user: AuthUser = Depends(get_current_user)) -> dict:  # type: ignore[type-arg]
    return svc.agents.cancel(user, task_id)


@router.post("/agent-tasks/{task_id}/decision")
def decide_task(task_id: str, body: Decision, background: BackgroundTasks, svc: Services = Depends(get_services),
                user: AuthUser = Depends(get_current_user)) -> dict:  # type: ignore[type-arg]
    """Confirm or decline an action that waits for approval (e.g. sending a request to a Global Supporter)."""
    return svc.agents.decide(user, task_id, body.approve, background)


# ------------------------------------------------------------------ admin: schedules (disabled by default)
@router.get("/admin/agent-schedules")
def list_schedules(svc: Services = Depends(get_services), _: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    return svc.agents.schedules()


@router.patch("/admin/agent-schedules/{schedule_id}")
def update_schedule(schedule_id: str, body: ScheduleUpdate, svc: Services = Depends(get_services),
                    admin: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    return svc.agents.update_schedule(admin, schedule_id, enabled=body.enabled,
                                      interval_minutes=body.interval_minutes, urls=body.urls, params=body.params)


# ------------------------------------------------------------------ admin: operations
class AgentControl(Body):
    paused: bool
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None


@router.get("/admin/agent-operations")
def agent_operations(svc: Services = Depends(get_services), _: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    """Health of every desk: tasks of the last 7 days, last success / failure, sources, schedules, queues."""
    return svc.operations.health()


@router.get("/admin/agent-operations/tasks")
def all_agent_tasks(agent_id: str | None = None,
                    status: Literal["queued", "running", "awaiting_approval", "completed", "failed", "cancelled"] | None = None,
                    pg: Pagination = Depends(), svc: Services = Depends(get_services),
                    _: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    """Every task as metadata. A student's parameters and results are never included."""
    items, total = svc.operations.tasks(agent_id=agent_id, status=status, page=pg.page, size=pg.page_size)
    return pg.wrap(items, total)


@router.get("/admin/agent-operations/tasks/{task_id}")
def one_agent_task(task_id: str, svc: Services = Depends(get_services), _: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    return svc.operations.task(task_id)


@router.post("/admin/agent-operations/tasks/{task_id}/rerun", status_code=202)
def rerun_agent_task(task_id: str, background: BackgroundTasks, svc: Services = Depends(get_services),
                     admin: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    return svc.operations.rerun(admin, task_id, background)


@router.post("/admin/agent-operations/tasks/{task_id}/cancel")
def cancel_any_agent_task(task_id: str, svc: Services = Depends(get_services),
                          admin: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    return svc.operations.cancel(admin, task_id)


@router.put("/admin/agent-operations/agents/{agent_id}")
def control_agent(agent_id: str, body: AgentControl, svc: Services = Depends(get_services),
                  admin: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    return svc.operations.set_paused(admin, agent_id, body.paused, body.note)


@router.get("/admin/storage")
def storage_overview(svc: Services = Depends(get_services), _: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    """Sizes only. Nothing is ever deleted here."""
    return svc.operations.storage()


# ------------------------------------------------------------------ admin: official-source discovery
@router.get("/admin/discovery/sources")
def discovery_sources(agent_id: str | None = None, svc: Services = Depends(get_services),
                      _: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    return dict(items=svc.discovery.list_sources(agent_id), allowed_domains=svc.domains.domains())


@router.post("/admin/discovery/sources", status_code=201)
def create_discovery_source(body: DiscoverySourceCreate, svc: Services = Depends(get_services),
                            admin: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    if body.category is not None:
        from app.core.constants import CATEGORY_SLUGS
        from app.core.errors import ValidationFailed

        if body.category not in CATEGORY_SLUGS:
            raise ValidationFailed("Unknown category.")
    return svc.discovery.create_source(admin.id, body.model_dump())


@router.get("/admin/discovery/catalog")
def discovery_catalog(svc: Services = Depends(get_services), _: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    """Prepared official sources that were checked live; adding one is an ordinary source creation."""
    return dict(items=svc.discovery.catalog())


@router.patch("/admin/discovery/sources/{source_id}")
def update_discovery_source(source_id: str, body: DiscoverySourcePatch, svc: Services = Depends(get_services),
                            admin: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    return svc.discovery.update_source(admin.id, source_id, body.model_dump())


@router.delete("/admin/discovery/sources/{source_id}", status_code=204)
def delete_discovery_source(source_id: str, svc: Services = Depends(get_services),
                            admin: AuthUser = Depends(require_admin)) -> None:
    svc.discovery.delete_source(admin.id, source_id)


@router.get("/admin/discovery/items")
def discovery_items(agent_id: str | None = None,
                    status: Literal["candidate", "dismissed", "imported", "all"] = "candidate",
                    svc: Services = Depends(get_services), _: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    return dict(items=svc.discovery.candidates(agent_id=agent_id, status=status, limit=100))


@router.post("/admin/discovery/items/{item_id}/dismiss")
def dismiss_item(item_id: str, body: ReviewNote, svc: Services = Depends(get_services),
                 admin: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    return svc.discovery.dismiss(admin.id, item_id, body.note)


@router.post("/admin/discovery/items/{item_id}/send-to-review", status_code=202,
             dependencies=[Depends(rate_limit("ingest"))])
def send_item_to_review(item_id: str, background: BackgroundTasks, svc: Services = Depends(get_services),
                        admin: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    """Register the official page as a knowledge source and queue its ingestion: it becomes a pending_review version
    in the normal review screen. Nothing is approved or published here."""
    return svc.discovery.send_to_review(admin.id, item_id, background)
