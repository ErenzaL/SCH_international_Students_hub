"""Endpoints of the GPU worker (worker credential only) and their administration (super admins / admins).

Everything here is 404 unless GPU_WORKER_ENABLED is on."""
from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.api.deps import get_services
from app.core.rate_limit import client_ip, limiter
from app.schemas.api import Lang
from app.security.auth import AuthUser, _bearer, require_admin, require_super_admin
from app.services.container import Services
from app.services.gpu_worker import FINAL_CODES, RELEASE_CODE, RETRY_CODES

router = APIRouter(prefix="/api/v1/gpu", tags=["gpu worker"])
admin = APIRouter(prefix="/api/v1/admin/gpu", tags=["admin: gpu worker"])


def enabled(svc: Services = Depends(get_services)) -> Services:
    svc.gpu.require_enabled()
    return svc


def worker(request: Request, response: Response, svc: Services = Depends(enabled)) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    ip = client_ip(request, svc.settings)
    try:
        w = svc.gpu.authenticate(_bearer(request))
    except Exception:
        limiter.check(ip, "gpu-auth-failed", 20)     # guessing is hopeless (256-bit tokens); keep it cheap as well
        raise
    limiter.check(w["id"], "gpu-worker", 120)
    return w


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Metrics(Strict):
    """Numbers only: there is no field a worker could put text into."""

    duration_ms: int = Field(default=0, ge=0, le=86_400_000)
    input_tokens: int = Field(default=0, ge=0, le=10_000_000)
    output_tokens: int = Field(default=0, ge=0, le=10_000_000)
    model_calls: int = Field(default=0, ge=0, le=1000)
    repairs: int = Field(default=0, ge=0, le=1000)
    parts: int = Field(default=1, ge=0, le=1000)


class Lease(Strict):
    lease_token: UUID


class Complete(Lease):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
    body: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80_000)]
    model: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,99}$")]
    metrics: Metrics = Metrics()

    @field_validator("title", "body")
    @classmethod
    def _plain(cls, v: str) -> str:
        if any((ord(c) < 32 and c not in "\n\t\r") or 0xD800 <= ord(c) <= 0xDFFF or ord(c) == 127 for c in v):
            raise ValueError("control characters are not allowed")
        return v


class Fail(Lease):
    code: Annotated[str, StringConstraints(max_length=40)]
    metrics: Metrics = Metrics()

    @field_validator("code")
    @classmethod
    def _known(cls, v: str) -> str:
        if v not in RETRY_CODES and v not in FINAL_CODES and v != RELEASE_CODE:
            raise ValueError("unknown code")
        return v


# ----------------------------------------------------------------------------- worker
@router.post("/claim")
def claim(body: Lease, svc: Services = Depends(enabled), w: dict = Depends(worker)) -> dict:  # type: ignore[type-arg]
    """The next job, or ``job: null`` with state ``idle`` | ``paused``. Repeating a request with the same
    ``lease_token`` returns the same job."""
    return svc.gpu.claim(w, str(body.lease_token))


@router.post("/jobs/{job_id}/heartbeat")
def heartbeat(job_id: UUID, body: Lease, svc: Services = Depends(enabled), w: dict = Depends(worker)) -> dict:  # type: ignore[type-arg]
    """Renew the lease. ``cancel: true`` = stop working on it."""
    return svc.gpu.heartbeat(w, str(job_id), str(body.lease_token))


@router.post("/jobs/{job_id}/complete")
def complete(job_id: UUID, body: Complete, svc: Services = Depends(enabled), w: dict = Depends(worker)) -> dict:  # type: ignore[type-arg]
    """Hand in a draft. It is always stored as ``needs_review``."""
    return svc.gpu.complete(w, str(job_id), str(body.lease_token), title=body.title, body=body.body, model=body.model,
                            metrics=body.metrics.model_dump())


@router.post("/jobs/{job_id}/fail")
def fail(job_id: UUID, body: Fail, svc: Services = Depends(enabled), w: dict = Depends(worker)) -> dict:  # type: ignore[type-arg]
    return svc.gpu.fail(w, str(job_id), str(body.lease_token), body.code, body.metrics.model_dump())


# ------------------------------------------------------------------------------ admin
class WorkerCreate(Strict):
    name: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{1,40}$")]


class Rotate(Strict):
    grace_minutes: int = Field(default=0, ge=0, le=1440)


class StatusPatch(Strict):
    status: Literal["active", "paused", "revoked"]


class QueueMissing(Strict):
    limit: int = Field(default=10, ge=1, le=50)
    languages: list[Lang] = Field(default_factory=list, max_length=5)
    kinds: list[Literal["announcement", "document"]] = Field(default=["announcement"], min_length=1, max_length=2)
    dry_run: bool = True


@admin.get("/status")
def gpu_status(svc: Services = Depends(enabled), _: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    return svc.gpu.status()


@admin.post("/workers", status_code=201)
def create_worker(body: WorkerCreate, response: Response, svc: Services = Depends(enabled),
                  user: AuthUser = Depends(require_super_admin)) -> dict:  # type: ignore[type-arg]
    """The token is in this response only."""
    response.headers["Cache-Control"] = "no-store"
    return svc.gpu.create_worker(body.name, user.id)


@admin.post("/workers/{worker_id}/rotate")
def rotate_worker(worker_id: UUID, body: Rotate, response: Response, svc: Services = Depends(enabled),
                  user: AuthUser = Depends(require_super_admin)) -> dict:  # type: ignore[type-arg]
    """A new token (in this response only). The old one stops at once, or after ``grace_minutes``."""
    response.headers["Cache-Control"] = "no-store"
    return svc.gpu.rotate(str(worker_id), user.id, body.grace_minutes)


@admin.patch("/workers/{worker_id}")
def set_worker_status(worker_id: UUID, body: StatusPatch, svc: Services = Depends(enabled),
                      user: AuthUser = Depends(require_super_admin)) -> dict:  # type: ignore[type-arg]
    """Pause, resume or (permanently) revoke."""
    return svc.gpu.set_status(str(worker_id), body.status, user.id)


@admin.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: UUID, svc: Services = Depends(enabled), user: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    return svc.gpu.cancel(str(job_id), user.id)


@admin.post("/jobs/queue-missing")
def queue_missing(body: QueueMissing, svc: Services = Depends(enabled), user: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    return svc.gpu.queue_missing(user.id, limit=body.limit, languages=list(body.languages), kinds=list(body.kinds),
                                 dry_run=body.dry_run)
