from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.api.admin_sources import job_view
from app.api.deps import Pagination, get_services
from app.core.errors import Conflict, NotFound
from app.repositories.base import Query as DbQuery
from app.repositories.base import get_many, get_one
from app.schemas.api import LanguagesUpdate, RoleUpdate
from app.security.auth import AuthUser, require_admin, require_super_admin
from app.services.container import Services

router = APIRouter(prefix="/api/v1/admin", tags=["admin: system"])


def audit_view(r: dict, names: dict[str, str]) -> dict:  # type: ignore[type-arg]
    return dict(id=str(r["id"]), action=r["action"], entity_type=r["entity_type"], entity_id=r.get("entity_id"),
                actor_id=r.get("actor_id"), actor_name=names.get(r.get("actor_id") or ""), details=r["details"],
                created_at=r["created_at"])


def _names(svc: Services, ids: list) -> dict[str, str]:  # type: ignore[type-arg]
    return {k: v.get("display_name") or v.get("email") or "" for k, v in get_many(svc.store, "profiles", ids).items()}


@router.get("/overview")
def overview(svc: Services = Depends(get_services), _: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    def count(table: str, **eq) -> int:  # type: ignore[no-untyped-def]
        _r, n = svc.store.select(table, DbQuery(eq=eq, limit=1, cols="id"), count=True)
        return n or 0

    docs_ok = svc.store.select("source_documents", DbQuery(is_null={"current_version_id": False}, limit=1, cols="id"),
                               count=True)[1]
    jobs, _n = svc.store.select("ingestion_jobs", DbQuery(order=[("created_at", True)], limit=5))
    titles = {k: v["title"] for k, v in get_many(svc.store, "knowledge_sources", [j["source_id"] for j in jobs]).items()}
    audit, _n = svc.store.select("audit_log", DbQuery(order=[("created_at", True), ("id", True)], limit=8))
    names = _names(svc, [a.get("actor_id") for a in audit])
    return dict(
        sources_total=count("knowledge_sources"), sources_failed=count("knowledge_sources", status="failed"),
        versions_pending=count("document_versions", verification_status="pending_review"),
        announcements_pending=count("announcements", publication_status="pending_approval"),
        documents_approved=docs_ok or 0,
        recent_jobs=[job_view(svc.store, j, titles.get(j["source_id"])) for j in jobs],
        recent_audit=[audit_view(a, names) for a in audit])


@router.get("/settings")
def settings_view(svc: Services = Depends(get_services), _: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    s = svc.settings
    return dict(
        supabase_configured=s.supabase_configured, embedding_provider=s.embedding_provider,
        embedding_model=svc.embedder.model_id, embedding_dimensions=s.embedding_dimensions,
        allowed_domains=s.allowed_domains, max_upload_mb=s.max_upload_mb, max_response_mb=s.max_response_mb,
        llm_provider="none" if not svc.llm.enabled else svc.llm.name,
        answer_generation="enabled" if svc.llm.enabled else "disabled",
        llm_models=dict(primary=getattr(svc.llm, "primary", getattr(svc.llm, "model", "")) or None,
                        fallback=getattr(svc.llm, "fallback", "") or None) if svc.llm.enabled else None,
        rate_limits=dict(search_per_minute=s.rate_limit_search_per_minute,
                         ingest_per_minute=s.rate_limit_ingest_per_minute,
                         public_per_minute=s.rate_limit_public_per_minute,
                         chat_user_per_minute=s.rate_limit_chat_user_per_minute,
                         chat_anonymous_global_per_minute=s.rate_limit_chat_anonymous_global_per_minute),
        ai_daily_limits=dict(per_client=s.ai_daily_limit_per_client, per_user=s.ai_daily_limit_per_user,
                             global_=s.ai_daily_limit_global))


@router.get("/system/client-ip")
def client_ip_diagnostics(request: Request, svc: Services = Depends(get_services),
                          _: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    """How the backend identifies the caller (to verify CLIENT_IP_HEADER / TRUSTED_PROXY_HOPS on a deployment).

    Check: call this once normally and once with a made-up ``True-Client-IP`` / ``X-Forwarded-For`` header. The
    resolved IP must stay your real IP both times; if a made-up value appears, that header is client-controlled."""
    from app.core.rate_limit import client_ip

    s = svc.settings
    header = (s.client_ip_header or "").lower()
    return dict(resolved_client_ip=client_ip(request, s), client_ip_header=header or None,
                client_ip_header_value=request.headers.get(header) if header else None,
                x_forwarded_for=request.headers.get("x-forwarded-for"), trusted_proxy_hops=s.trusted_proxy_hops,
                socket_peer=request.client.host if request.client else None)


@router.get("/system/llm-usage")
def llm_usage(svc: Services = Depends(get_services), _: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    """Operational LLM metrics since the last restart (no prompts, answers or personal data)."""
    from app.core.rate_limit import ai_budget
    from app.services.llm.usage import usage

    return dict(provider=svc.llm.name if svc.llm.enabled else "none", usage=usage.snapshot(),
                daily_budget=ai_budget.snapshot() | {"global_limit": svc.settings.ai_daily_limit_global})


@router.get("/audit-log")
def audit_log(pg: Pagination = Depends(), svc: Services = Depends(get_services),
              _: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    rows, total = svc.store.select("audit_log", DbQuery(order=[("created_at", True), ("id", True)], limit=pg.page_size,
                                                       offset=(pg.page - 1) * pg.page_size), count=True)
    names = _names(svc, [r.get("actor_id") for r in rows])
    return pg.wrap([audit_view(r, names) for r in rows], total or 0)


def _user_view(p: dict, langs: list[str]) -> dict:  # type: ignore[type-arg]
    return dict(id=p["id"], email=p.get("email"), display_name=p.get("display_name"), role=p["role"],
                preferred_language=p["preferred_language"], languages=sorted(langs), created_at=p["created_at"])


@router.get("/users")
def list_users(pg: Pagination = Depends(), svc: Services = Depends(get_services),
               _: AuthUser = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    rows, total = svc.store.select("profiles", DbQuery(order=[("created_at", True)], limit=pg.page_size,
                                                      offset=(pg.page - 1) * pg.page_size), count=True)
    langs_rows, _n = svc.store.select("supporter_languages", DbQuery(in_={"supporter_id": [r["id"] for r in rows]})) \
        if rows else ([], None)
    langs: dict[str, list[str]] = {}
    for lr in langs_rows:
        langs.setdefault(lr["supporter_id"], []).append(lr["language_code"])
    return pg.wrap([_user_view(r, langs.get(r["id"], [])) for r in rows], total or 0)


@router.patch("/users/{user_id}/role")
def update_role(user_id: str, body: RoleUpdate, svc: Services = Depends(get_services),
                actor: AuthUser = Depends(require_super_admin)) -> dict:  # type: ignore[type-arg]
    target = get_one(svc.store, "profiles", id=user_id)
    if target is None:
        raise NotFound("User not found.")
    if target["role"] == "super_admin" and body.role != "super_admin":
        _r, n = svc.store.select("profiles", DbQuery(eq={"role": "super_admin"}, limit=1, cols="id"), count=True)
        if (n or 0) <= 1:
            raise Conflict("Cannot demote the last super_admin.")
    updated = svc.store.update("profiles", {"role": body.role}, {"id": user_id})[0]
    svc.store.insert("audit_log", dict(action="user.role_change", entity_type="profile", entity_id=user_id,
                                       actor_id=actor.id, details={"from": target["role"], "to": body.role}))
    if body.role not in ("supporter", "admin", "super_admin"):
        # access is already revoked (permissions require a staff role); hand their open tickets back to the queue
        svc.support.release_for(user_id, actor)
    langs, _n = svc.store.select("supporter_languages", DbQuery(eq={"supporter_id": user_id}))
    return _user_view(updated, [x["language_code"] for x in langs])


@router.put("/users/{user_id}/languages")
def update_languages(user_id: str, body: LanguagesUpdate, svc: Services = Depends(get_services),
                     actor: AuthUser = Depends(require_super_admin)) -> dict:  # type: ignore[type-arg]
    """Simple form: support permission for each language (use PUT /admin/users/{id}/team for review / lead)."""
    target = get_one(svc.store, "profiles", id=user_id)
    if target is None:
        raise NotFound("User not found.")
    langs = sorted(set(body.languages))
    svc.store.delete("supporter_languages", {"supporter_id": user_id})
    svc.store.insert_many("supporter_languages", [dict(supporter_id=user_id, language_code=lang, assigned_by=actor.id)
                                                  for lang in langs])
    svc.store.insert("audit_log", dict(action="user.languages_change", entity_type="profile", entity_id=user_id,
                                       actor_id=actor.id, details={"languages": langs}))
    return _user_view(target, langs)
