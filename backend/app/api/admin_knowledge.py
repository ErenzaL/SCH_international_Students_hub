"""Knowledge overview counts, the trusted-domain allowlist, and the external scheduler hook."""
from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, Header

from app.api.deps import get_services
from app.core.errors import AppError, NotFound
from app.schemas.api import DomainAdd
from app.security.auth import AuthUser, require_admin, require_super_admin
from app.services.container import Services

router = APIRouter(prefix="/api/v1/admin", tags=["admin: knowledge"])
internal = APIRouter(prefix="/api/v1/internal", tags=["internal"])


@router.get("/knowledge/stats")
def knowledge_stats(svc: Services = Depends(get_services), _: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    """Real database counts for the Knowledge Sources overview cards."""
    stats = svc.store.rpc("knowledge_stats", {}) or {}
    ocr_ok, ocr_reason = svc.ocr.available()
    return {**stats, "ocr_provider": svc.ocr.name, "ocr_available": ocr_ok, "ocr_reason": ocr_reason,
            "job_execution": svc.settings.job_execution, "embedding_model": svc.embedder.model_id}


@router.get("/allowed-domains")
def list_domains(svc: Services = Depends(get_services), _: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    return {"items": svc.domains.list()}


@router.post("/allowed-domains", status_code=201)
def add_domain(body: DomainAdd, svc: Services = Depends(get_services),
               user: AuthUser = Depends(require_super_admin)) -> dict:  # type: ignore[type-arg]
    return svc.domains.add(body.domain, body.note, user.id)


@router.delete("/allowed-domains/{domain}", status_code=204)
def remove_domain(domain: str, svc: Services = Depends(get_services),
                  user: AuthUser = Depends(require_super_admin)) -> None:
    svc.domains.remove(domain, user.id)


@internal.post("/sync/run-due", status_code=202)
def run_due(x_cron_secret: str | None = Header(default=None), svc: Services = Depends(get_services)) -> dict:  # type: ignore[type-arg]
    """Called by an external scheduler (GitHub Actions / Supabase Cron / Render Cron) with X-Cron-Secret.
    Queues sync jobs for due sources; the worker processes them. New content still needs review."""
    secret = svc.settings.cron_secret
    if not secret:
        raise NotFound("Not found.")  # endpoint disabled unless CRON_SECRET is configured
    if not x_cron_secret or not hmac.compare_digest(x_cron_secret, secret):
        raise AppError("Invalid scheduler secret.", code="forbidden", status_code=403)
    queued, skipped = [], []
    for source in svc.ingestion.due_sources():
        if svc.ingestion.has_open_job(source["id"]):
            skipped.append(source["id"])
            continue
        job = svc.ingestion.create_job(source, "schedule", None)
        queued.append(job["id"])
        svc.jobs.enqueue(job)
    return dict(queued=len(queued), skipped=len(skipped), job_ids=queued)
