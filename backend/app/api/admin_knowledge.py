"""Knowledge overview counts, the trusted-domain allowlist, and the external scheduler hook."""
from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, Header

from app.api.deps import get_services
from app.core.errors import AppError, NotFound
from app.repositories.base import Query as DbQuery
from app.repositories.base import get_many
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


def _count(svc: Services, table: str, **kw) -> int:  # type: ignore[no-untyped-def]
    _rows, total = svc.store.select(table, DbQuery(limit=1, cols="id" if table != "source_documents" else "id", **kw),
                                    count=True)
    return total or 0


@router.get("/rag/health")
def rag_health(svc: Services = Depends(get_services), _: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    """Searchability audit of every published document + lightweight statistics, computed on demand (read-only:
    no alerts are written, nothing is re-indexed; scheduled checks alert via ``python -m app.cli check-rag``)."""
    return svc.rag_health.audit(notify=False)


@router.get("/rag/status")
def rag_status(svc: Services = Depends(get_services), _: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    """RAG synchronization dashboard: real database counts + the indexing queue."""
    stats = svc.store.rpc("knowledge_stats", {}) or {}
    model = svc.embedder.model_id
    idx = {"job_type": "index_version"}
    counts = dict(
        sources_registered=stats.get("sources_total", 0), sources_active=stats.get("sources_active", 0),
        sources_failed_or_blocked=stats.get("sources_failed", 0),
        pending_review=_count(svc, "document_versions", eq={"verification_status": "pending_review"},
                              is_null={"activation_requested_at": True}),
        waiting_for_indexing=_count(svc, "ingestion_jobs", eq={**idx, "status": "queued"}),
        indexing_now=_count(svc, "ingestion_jobs", eq={**idx, "status": "running"}),
        indexing_failed=_count(svc, "document_versions", eq={"verification_status": "pending_review",
                                                            "indexing_status": "failed"}),
        active_versions=stats.get("documents_approved", 0),
        searchable_chunks=stats.get("searchable_chunks", 0),
        chunks_with_current_model=_count(svc, "document_chunks", eq={"embedding_model": model}),
        failed_jobs=stats.get("jobs_failed", 0),
    )
    jobs, _c = svc.store.select("ingestion_jobs", DbQuery(eq=idx, order=[("created_at", True)], limit=30))
    vids = [(j.get("payload") or {}).get("version_id") for j in jobs]
    versions = get_many(svc.store, "document_versions", [v for v in vids if v])
    docs = get_many(svc.store, "source_documents", [v["document_id"] for v in versions.values()])
    queue = []
    for j in jobs:
        v = versions.get((j.get("payload") or {}).get("version_id")) or {}
        d = docs.get(v.get("document_id")) or {}
        queue.append(dict(job_id=j["id"], status=j["status"], attempts=j.get("attempts"), max_attempts=j.get("max_attempts"),
                          error_code=j.get("error_code"), error_message=j.get("error_message"), run_after=j.get("run_after"),
                          created_at=j["created_at"], started_at=j.get("started_at"), completed_at=j.get("completed_at"),
                          version_id=v.get("id"), version_number=v.get("version_number"),
                          version_status=v.get("verification_status"), indexing_status=v.get("indexing_status"),
                          document_id=d.get("id"), document_title=d.get("title"), statistics=j.get("statistics") or {}))
    acts, _c = svc.store.select("audit_log", DbQuery(eq={"action": "version.activate"}, order=[("created_at", True)], limit=10))
    adocs = get_many(svc.store, "source_documents", [(a.get("details") or {}).get("document_id") for a in acts])
    sources, _c = svc.store.select("knowledge_sources", DbQuery(order=[("last_checked_at", True)], limit=50, cols=(
        "id,title,source_type,status,sync_frequency,last_checked_at,last_success_at,last_change_at,is_active")))
    return dict(
        counts=counts, last_sync_at=stats.get("latest_success_at"),
        embedding=dict(model=model, dimensions=svc.settings.embedding_dimensions, provider=svc.settings.embedding_provider,
                       loaded=bool(getattr(svc.embedder, "loaded", True))),
        job_execution=svc.settings.job_execution, queue=queue,
        recent_activations=[dict(at=a["created_at"], document_id=(a.get("details") or {}).get("document_id"),
                                 document_title=(adocs.get((a.get("details") or {}).get("document_id")) or {}).get("title"),
                                 version_number=(a.get("details") or {}).get("version_number"),
                                 chunks=(a.get("details") or {}).get("chunks")) for a in acts],
        sources=sources)


@router.get("/notifications")
def notifications(limit: int = 50, svc: Services = Depends(get_services),
                  user: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    return svc.notifications.list(user.id, limit)


@router.post("/notifications/read", status_code=204)
def notifications_read(svc: Services = Depends(get_services), user: AuthUser = Depends(require_admin)) -> None:
    svc.notifications.mark_read(user.id)


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
    svc.jobs.kick()  # also drains queued indexing jobs / pending retries (the instance may just have woken up)
    purged = svc.support.purge_expired()  # retention policy for private student data
    return dict(queued=len(queued), skipped=len(skipped), job_ids=queued, purged=purged)
