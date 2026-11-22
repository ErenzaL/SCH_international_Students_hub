"""Account settings, AI conversations, notifications, support tickets, supporter inbox, language teams.

Identity always comes from the verified token; every object is re-checked against the caller (students
only reach their own rows; staff only reach tickets their language permission/assignment allows).
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.api.deps import Pagination, get_services
from app.api.sse import sse
from app.core.errors import Forbidden, NotFound, ValidationFailed
from app.core.rate_limit import rate_limit
from app.repositories.base import Query as DbQuery
from app.repositories.base import get_many, get_one
from app.schemas.api import (
    AnonymousChat,
    Availability,
    ConversationCreate,
    ConversationMessage,
    ConversationPatch,
    Lang,
    NotificationsRead,
    ProfilePatch,
    ReasonBody,
    TeamUpdate,
    TicketCreate,
    TicketFeedback,
    TicketPriority,
    TicketReply,
    TicketTransfer,
)
from app.security.auth import AuthUser, get_current_user, require_staff, require_super_admin
from app.security.permissions import has_perm, languages_with
from app.services.container import Services

router = APIRouter(prefix="/api/v1", tags=["support"])


# ------------------------------------------------------------------- account
@router.patch("/me", tags=["auth"])
def update_me(body: ProfilePatch, svc: Services = Depends(get_services),
              user: AuthUser = Depends(get_current_user)) -> dict:  # type: ignore[type-arg]
    """Change the preferred language (UI default, assistant language, support routing) or display name.
    Existing tickets keep their language; only new requests use the new preference."""
    patch = body.model_dump(exclude_unset=True, exclude_none=True)
    if "preferred_language" in patch:
        patch["preferred_language_confirmed"] = True
    if patch:
        svc.store.update("profiles", patch, {"id": user.id})  # role is never updatable here
        if "preferred_language" in patch and patch["preferred_language"] != user.preferred_language:
            svc.store.insert("audit_log", dict(action="profile.language_change", entity_type="profile", entity_id=user.id,
                                               actor_id=user.id, details={"from": user.preferred_language,
                                                                          "to": patch["preferred_language"]}))
    p = get_one(svc.store, "profiles", id=user.id) or {}
    return dict(id=user.id, email=user.email, display_name=p.get("display_name"), role=p.get("role", user.role),
                preferred_language=p.get("preferred_language"),
                preferred_language_confirmed=p.get("preferred_language_confirmed", False),
                languages=user.languages, is_staff=user.is_staff)


@router.get("/me/notifications")
def my_notifications(unread_only: bool = False, limit: int = 50, before_id: int | None = None,
                     svc: Services = Depends(get_services), user: AuthUser = Depends(get_current_user)) -> dict:  # type: ignore[type-arg]
    return svc.user_notifications.list(user.id, unread_only=unread_only, limit=limit, before_id=before_id)


@router.post("/me/notifications/read")
def mark_notifications_read(body: NotificationsRead | None = None, svc: Services = Depends(get_services),
                            user: AuthUser = Depends(get_current_user)) -> dict:  # type: ignore[type-arg]
    return {"marked": svc.user_notifications.mark_read(user.id, body.ids if body else None)}


# ------------------------------------------------------------- conversations
@router.get("/conversations")
def list_conversations(q: str | None = None, pg: Pagination = Depends(), svc: Services = Depends(get_services),
                       user: AuthUser = Depends(get_current_user)) -> dict:  # type: ignore[type-arg]
    items, total = svc.conversations.list(user.id, pg.page, pg.page_size, q)
    return pg.wrap(items, total)


@router.post("/conversations", status_code=201)
def create_conversation(body: ConversationCreate, svc: Services = Depends(get_services),
                        user: AuthUser = Depends(get_current_user)) -> dict:  # type: ignore[type-arg]
    return svc.conversations.create(user.id, body.language or user.preferred_language, body.title)


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: str, svc: Services = Depends(get_services),
                     user: AuthUser = Depends(get_current_user)) -> dict:  # type: ignore[type-arg]
    return svc.conversations.detail(conversation_id, user.id)


@router.patch("/conversations/{conversation_id}")
def update_conversation(conversation_id: str, body: ConversationPatch, svc: Services = Depends(get_services),
                        user: AuthUser = Depends(get_current_user)) -> dict:  # type: ignore[type-arg]
    return svc.conversations.update(conversation_id, user.id, body.model_dump(exclude_unset=True))


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: str, svc: Services = Depends(get_services),
                        user: AuthUser = Depends(get_current_user)) -> None:
    svc.conversations.delete(conversation_id, user.id)


@router.post("/conversations/{conversation_id}/messages", status_code=201, dependencies=[Depends(rate_limit("search"))])
def ask(conversation_id: str, body: ConversationMessage, svc: Services = Depends(get_services),
        user: AuthUser = Depends(get_current_user)) -> dict:  # type: ignore[type-arg]
    return svc.conversations.ask(conversation_id, user.id, body.content, body.language)


@router.post("/conversations/{conversation_id}/messages/stream", dependencies=[Depends(rate_limit("search"))])
def ask_stream(conversation_id: str, body: ConversationMessage, request: Request, svc: Services = Depends(get_services),
               user: AuthUser = Depends(get_current_user)) -> StreamingResponse:
    """Same as POST …/messages, streamed as server-sent events (status, delta…, done | error)."""
    svc.conversations.get_own(conversation_id, user.id)   # 404 before the stream starts
    return sse(lambda emit: svc.conversations.ask(conversation_id, user.id, body.content, body.language, emit=emit),
               getattr(request.state, "request_id", None))


@router.post("/conversations/{conversation_id}/handoff-draft")
def handoff_draft(conversation_id: str, svc: Services = Depends(get_services),
                  user: AuthUser = Depends(get_current_user)) -> dict:  # type: ignore[type-arg]
    """A reviewable draft of a Global Supporter request (nothing is sent). The student confirms with
    POST /support/tickets (consent=true); the request is routed to the team of their preferred language."""
    c = svc.conversations.get_own(conversation_id, user.id)
    from app.services.assistant.handoff import build_handoff_draft

    return build_handoff_draft(svc.store, svc.conversations.llm, c, user.preferred_language)


@router.post("/assistant/chat", dependencies=[Depends(rate_limit("search"))])
def anonymous_chat(body: AnonymousChat, svc: Services = Depends(get_services)) -> dict:  # type: ignore[type-arg]
    """For visitors who are not signed in: grounded answers without stored history or supporter handoff."""
    if not svc.settings.assistant_anonymous_chat:
        raise Forbidden("Please sign in to use the assistant.")
    return svc.conversations.ask_anonymous(body.message, body.language or "en", [m.model_dump() for m in body.history])


@router.post("/assistant/chat/stream", dependencies=[Depends(rate_limit("search"))])
def anonymous_chat_stream(body: AnonymousChat, request: Request,
                          svc: Services = Depends(get_services)) -> StreamingResponse:
    if not svc.settings.assistant_anonymous_chat:
        raise Forbidden("Please sign in to use the assistant.")
    history = [m.model_dump() for m in body.history]
    return sse(lambda emit: svc.conversations.ask_anonymous(body.message, body.language or "en", history, emit=emit),
               getattr(request.state, "request_id", None))


# ------------------------------------------------------------ student tickets
@router.post("/support/tickets", status_code=201, dependencies=[Depends(rate_limit("ingest"))])
def create_ticket(body: TicketCreate, svc: Services = Depends(get_services),
                  user: AuthUser = Depends(get_current_user)) -> dict:  # type: ignore[type-arg]
    """Explicit, consented handoff: only the selected messages are copied into the request."""
    return svc.support.create_ticket(user, body.model_dump())


@router.get("/support/tickets")
def my_tickets(pg: Pagination = Depends(), svc: Services = Depends(get_services),
               user: AuthUser = Depends(get_current_user)) -> dict:  # type: ignore[type-arg]
    items, total = svc.support.my_tickets(user, pg.page, pg.page_size)
    return pg.wrap(items, total)


@router.get("/support/tickets/{ticket_id}")
def get_ticket(ticket_id: str, svc: Services = Depends(get_services),
               user: AuthUser = Depends(get_current_user)) -> dict:  # type: ignore[type-arg]
    """Student: own ticket. Staff: only when assigned, team lead of the language, or super admin (audited)."""
    return svc.support.get_for(ticket_id, user)


@router.post("/support/tickets/{ticket_id}/messages", status_code=201)
def reply(ticket_id: str, body: TicketReply, svc: Services = Depends(get_services),
          user: AuthUser = Depends(get_current_user)) -> dict:  # type: ignore[type-arg]
    t = get_one(svc.store, "support_tickets", id=ticket_id)
    if t is not None and t["student_id"] == user.id:
        return svc.support.student_reply(ticket_id, user, body.body)
    return svc.support.staff_reply(ticket_id, user, body.body)


@router.post("/support/tickets/{ticket_id}/resolve")
def resolve(ticket_id: str, svc: Services = Depends(get_services), user: AuthUser = Depends(get_current_user)) -> dict:  # type: ignore[type-arg]
    t = get_one(svc.store, "support_tickets", id=ticket_id)
    if t is not None and t["student_id"] == user.id:
        return svc.support.student_resolve(ticket_id, user)
    return svc.support.staff_resolve(ticket_id, user)


@router.post("/support/tickets/{ticket_id}/reopen")
def reopen(ticket_id: str, svc: Services = Depends(get_services), user: AuthUser = Depends(get_current_user)) -> dict:  # type: ignore[type-arg]
    return svc.support.reopen(ticket_id, user)


@router.post("/support/tickets/{ticket_id}/feedback")
def feedback(ticket_id: str, body: TicketFeedback, svc: Services = Depends(get_services),
             user: AuthUser = Depends(get_current_user)) -> dict:  # type: ignore[type-arg]
    return svc.support.feedback(ticket_id, user, body.rating, body.comment)


@router.post("/support/tickets/{ticket_id}/withdraw-context")
def withdraw_context(ticket_id: str, svc: Services = Depends(get_services),
                     user: AuthUser = Depends(get_current_user)) -> dict:  # type: ignore[type-arg]
    return svc.support.withdraw_context(ticket_id, user)


# ------------------------------------------------------------ supporter inbox
@router.get("/support/inbox")
def inbox(view: Literal["queue", "mine", "assigned", "open", "waiting", "resolved", "team"] = "mine",
          language: Lang | None = None, pg: Pagination = Depends(), svc: Services = Depends(get_services),
          user: AuthUser = Depends(require_staff)) -> dict:  # type: ignore[type-arg]
    """``queue`` = waiting tickets in my languages (metadata only). ``team`` = team leads only."""
    items, total = svc.support.inbox(user, view, language, pg.page, pg.page_size)
    return {**pg.wrap(items, total), "counts": svc.support.counts(user),
            "languages": languages_with(user, "support"), "lead_languages": languages_with(user, "lead")}


@router.post("/support/tickets/{ticket_id}/accept")
def accept(ticket_id: str, svc: Services = Depends(get_services), user: AuthUser = Depends(require_staff)) -> dict:  # type: ignore[type-arg]
    return svc.support.accept(ticket_id, user)


@router.post("/support/tickets/{ticket_id}/request-info")
def request_info(ticket_id: str, body: TicketReply, svc: Services = Depends(get_services),
                 user: AuthUser = Depends(require_staff)) -> dict:  # type: ignore[type-arg]
    return svc.support.staff_reply(ticket_id, user, body.body, info_request=True)


@router.post("/support/tickets/{ticket_id}/waiting")
def mark_waiting(ticket_id: str, svc: Services = Depends(get_services), user: AuthUser = Depends(require_staff)) -> dict:  # type: ignore[type-arg]
    return svc.support.set_waiting(ticket_id, user)


@router.post("/support/tickets/{ticket_id}/escalate")
def escalate(ticket_id: str, body: ReasonBody, svc: Services = Depends(get_services),
             user: AuthUser = Depends(require_staff)) -> dict:  # type: ignore[type-arg]
    return svc.support.escalate(ticket_id, user, body.reason)


@router.post("/support/tickets/{ticket_id}/transfer")
def transfer(ticket_id: str, body: TicketTransfer, svc: Services = Depends(get_services),
             user: AuthUser = Depends(require_staff)) -> dict:  # type: ignore[type-arg]
    return svc.support.transfer(ticket_id, user, body.to_supporter_id, body.reason)


@router.post("/support/tickets/{ticket_id}/priority")
def priority(ticket_id: str, body: TicketPriority, svc: Services = Depends(get_services),
             user: AuthUser = Depends(require_staff)) -> dict:  # type: ignore[type-arg]
    return svc.support.set_priority(ticket_id, user, body.priority)


@router.get("/support/tickets/{ticket_id}/transfer-targets")
def transfer_targets(ticket_id: str, svc: Services = Depends(get_services),
                     user: AuthUser = Depends(require_staff)) -> dict:  # type: ignore[type-arg]
    """Supporters allowed to take this ticket (same language). Only for its handler / team lead."""
    t = get_one(svc.store, "support_tickets", id=ticket_id)
    if t is None or not (t.get("assigned_to") == user.id or has_perm(user, t["language"], "lead")):
        raise NotFound("Ticket not found.")
    rows, _ = svc.store.select("supporter_languages", DbQuery(eq={"language_code": t["language"]}))
    profs = get_many(svc.store, "profiles", [r["supporter_id"] for r in rows])
    status = get_many(svc.store, "support_agent_status", [r["supporter_id"] for r in rows], column="supporter_id")
    out = [dict(id=r["supporter_id"], display_name=profs[r["supporter_id"]].get("display_name"),
                is_available=(status.get(r["supporter_id"]) or {}).get("is_available", True))
           for r in rows if (r.get("can_support") or r.get("is_team_lead"))
           and (profs.get(r["supporter_id"]) or {}).get("role") in ("supporter", "admin")
           and r["supporter_id"] != t.get("assigned_to")]
    return {"items": out, "language": t["language"]}


@router.put("/support/me/availability")
def set_availability(body: Availability, svc: Services = Depends(get_services),
                     user: AuthUser = Depends(require_staff)) -> dict:  # type: ignore[type-arg]
    row = {"is_available": body.is_available}
    if body.max_active_tickets:
        row["max_active_tickets"] = body.max_active_tickets
    if get_one(svc.store, "support_agent_status", supporter_id=user.id):
        svc.store.update("support_agent_status", row, {"supporter_id": user.id})
    else:
        svc.store.insert("support_agent_status", {"supporter_id": user.id, **row})
    return get_one(svc.store, "support_agent_status", supporter_id=user.id) or {}


# -------------------------------------------------------------- language teams
def _team_view(svc: Services, langs: list[str]) -> list[dict]:  # type: ignore[type-arg]
    rows, _ = svc.store.select("supporter_languages", DbQuery(in_={"language_code": langs}))
    profs = get_many(svc.store, "profiles", [r["supporter_id"] for r in rows])
    status = get_many(svc.store, "support_agent_status", [r["supporter_id"] for r in rows], column="supporter_id")
    out = []
    for lang in langs:
        members = [dict(user_id=r["supporter_id"], display_name=(profs.get(r["supporter_id"]) or {}).get("display_name"),
                        email=(profs.get(r["supporter_id"]) or {}).get("email"),
                        role=(profs.get(r["supporter_id"]) or {}).get("role"), can_support=r.get("can_support", True),
                        can_review_translations=r.get("can_review_translations", False),
                        is_team_lead=r.get("is_team_lead", False),
                        is_available=(status.get(r["supporter_id"]) or {}).get("is_available", True))
                   for r in rows if r["language_code"] == lang]
        _w, waiting = svc.store.select("support_tickets", DbQuery(eq={"language": lang, "status": "waiting"}, limit=1,
                                                                 cols="id"), count=True)
        _o, active = svc.store.select("support_tickets", DbQuery(eq={"language": lang},
                                                                in_={"status": ["assigned", "open", "waiting_for_student"]},
                                                                limit=1, cols="id"), count=True)
        out.append(dict(language=lang, members=members, waiting=waiting or 0, active=active or 0))
    return out


@router.get("/admin/language-teams")
def language_teams(svc: Services = Depends(get_services), user: AuthUser = Depends(require_staff)) -> dict:  # type: ignore[type-arg]
    """Super admins: all teams. Team leads: only the languages they lead."""
    langs = languages_with(user, "lead")
    if not langs:
        raise NotFound("Not found.")
    return {"items": _team_view(svc, langs), "can_manage_members": user.role == "super_admin"}


@router.put("/admin/users/{user_id}/team")
def update_team(user_id: str, body: TeamUpdate, svc: Services = Depends(get_services),
                actor: AuthUser = Depends(require_super_admin)) -> dict:  # type: ignore[type-arg]
    """Set a user's language assignments and per-language permissions (super admin only, audited)."""
    target = get_one(svc.store, "profiles", id=user_id)
    if target is None:
        raise NotFound("User not found.")
    langs = [a.language for a in body.assignments]
    if len(langs) != len(set(langs)):
        raise ValidationFailed("Each language may appear only once.")
    before, _ = svc.store.select("supporter_languages", DbQuery(eq={"supporter_id": user_id}))
    svc.store.delete("supporter_languages", {"supporter_id": user_id})
    svc.store.insert_many("supporter_languages", [dict(supporter_id=user_id, language_code=a.language,
                                                       can_support=a.can_support,
                                                       can_review_translations=a.can_review_translations,
                                                       is_team_lead=a.is_team_lead, assigned_by=actor.id)
                                                  for a in body.assignments])
    if body.is_available is not None or body.max_active_tickets:
        row = {k: v for k, v in (("is_available", body.is_available), ("max_active_tickets", body.max_active_tickets))
               if v is not None}
        if get_one(svc.store, "support_agent_status", supporter_id=user_id):
            svc.store.update("support_agent_status", row, {"supporter_id": user_id})
        else:
            svc.store.insert("support_agent_status", {"supporter_id": user_id, **row})
    svc.store.insert("audit_log", dict(action="team.update", entity_type="profile", entity_id=user_id, actor_id=actor.id,
                                       details={"before": [{k: r.get(k) for k in ("language_code", "can_support",
                                                                                  "can_review_translations", "is_team_lead")}
                                                           for r in before],
                                                "after": [a.model_dump() for a in body.assignments]}))
    # tickets in languages the user no longer supports go back to the queue
    keep = {a.language for a in body.assignments if a.can_support or a.is_team_lead}
    rows, _ = svc.store.select("support_tickets", DbQuery(eq={"assigned_to": user_id},
                                                          in_={"status": ["assigned", "open", "waiting_for_student"]}))
    for t in rows:
        if t["language"] not in keep:
            svc.store.rpc("assign_support_ticket", dict(p_ticket_id=t["id"], p_supporter=None, p_actor=actor.id,
                                                        p_reason="supporter removed from language team",
                                                        p_expect_waiting=False))
            svc.support.route(t["id"])
    after, _ = svc.store.select("supporter_languages", DbQuery(eq={"supporter_id": user_id}))
    return {"user_id": user_id, "assignments": after}
