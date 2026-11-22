"""Language-routed human support (AI -> Global Supporter handoff).

Access model (also enforced by RLS: public.can_view_ticket_content):
  * students: only their own tickets
  * queue visibility: supporters/leads of a language see WAITING tickets' metadata (number, subject, priority,
    time) for that language - never the summary, shared messages or thread
  * content: the current assignee, team leads of the ticket's language, super admins
  * plain admins have no support access without a language assignment
Every staff read of ticket content and every assignment change is audited. Message bodies are never logged.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.errors import AppError, Conflict, Forbidden, InvalidState, NotFound, ValidationFailed
from app.repositories.base import Query, Store, get_many, get_one
from app.security.auth import AuthUser
from app.security.permissions import can_view_ticket_content, has_perm, languages_with, require_perm
from app.services.conversations import ConversationService
from app.services.notifications import UserNotificationService

log = logging.getLogger("app.support")
ACTIVE = ("assigned", "open", "waiting_for_student")
LANG_NAMES = {"ko": "Korean", "en": "English", "id": "Indonesian", "vi": "Vietnamese", "zh-CN": "Chinese"}


def now() -> str:
    return datetime.now(UTC).isoformat()


class SupportService:
    def __init__(self, store: Store, conversations: ConversationService, notes: UserNotificationService,
                 retention_days: int = 365):
        self.store = store
        self.conversations = conversations
        self.notes = notes
        self.retention_days = retention_days

    # ---------------------------------------------------------------- helpers
    def _ticket(self, ticket_id: str) -> dict[str, Any]:
        t = get_one(self.store, "support_tickets", id=ticket_id)
        if t is None:
            raise NotFound("Ticket not found.")
        return t

    def _audit(self, action: str, ticket_id: str, actor: AuthUser | None, **details: Any) -> None:
        self.store.insert("audit_log", dict(action=action, entity_type="support_ticket", entity_id=ticket_id,
                                            actor_id=actor.id if actor else None, details=details))

    def _names(self, ids: list[str | None]) -> dict[str, str]:
        return {k: (v.get("display_name") or "Global Supporter")
                for k, v in get_many(self.store, "profiles", [i for i in ids if i]).items()}

    def _leads(self, language: str) -> list[str]:
        rows, _ = self.store.select("supporter_languages", Query(eq={"language_code": language, "is_team_lead": True}))
        profs = get_many(self.store, "profiles", [r["supporter_id"] for r in rows])
        leads = [r["supporter_id"] for r in rows if (profs.get(r["supporter_id"]) or {}).get("role") in ("supporter", "admin")]
        if leads:
            return leads
        supers, _ = self.store.select("profiles", Query(eq={"role": "super_admin"}, cols="id"))
        return [s["id"] for s in supers]

    def _content_or_403(self, t: dict[str, Any], user: AuthUser) -> None:
        if not can_view_ticket_content(user, t):
            # identical response whether the ticket exists in another language or not (no ID probing)
            raise NotFound("Ticket not found.")

    def _post(self, t: dict[str, Any], author: AuthUser | None, role: str, body: str, kind: str = "message") -> dict[str, Any]:
        m = self.store.insert("support_ticket_messages", dict(ticket_id=t["id"], author_id=author.id if author else None,
                                                              author_role=role, kind=kind, body=body))
        patch = {"last_message_at": m["created_at"], "updated_at": now()}
        patch["last_student_message_at" if role == "student" else "last_staff_message_at"] = m["created_at"]
        self.store.update("support_tickets", patch, {"id": t["id"]})
        return m

    def student_view(self, t: dict[str, Any], *, with_thread: bool = False) -> dict[str, Any]:
        names = self._names([t.get("assigned_to")])
        out = {k: t.get(k) for k in ("id", "ticket_number", "language", "subject", "summary", "priority", "status",
                                       "created_at", "updated_at", "last_message_at", "resolved_at", "satisfaction",
                                       "satisfaction_comment", "consent_at", "context_withdrawn_at", "escalated")}
        out["assigned_supporter"] = ({"display_name": names.get(t["assigned_to"], "Global Supporter")}
                                     if t.get("assigned_to") and t["status"] != "waiting" else None)
        out["team"] = f"{LANG_NAMES[t['language']]} support team"
        out["shared_context"] = t.get("shared_context") or []
        out["status_message"] = self.status_message(t)
        if with_thread:
            out["messages"] = self._thread(t)
        return out

    def staff_view(self, t: dict[str, Any], user: AuthUser, *, with_thread: bool = False) -> dict[str, Any]:
        out = self.student_view(t, with_thread=with_thread)
        student = get_one(self.store, "profiles", id=t["student_id"]) or {}
        out.update(assigned_to=t.get("assigned_to"), assigned_at=t.get("assigned_at"), accepted_at=t.get("accepted_at"),
                   escalation_reason=t.get("escalation_reason"), student_display_name=student.get("display_name"),
                   student_preferred_language=student.get("preferred_language"), is_mine=t.get("assigned_to") == user.id,
                   can_manage=has_perm(user, t["language"], "lead"))
        return out

    def queue_view(self, t: dict[str, Any], user: AuthUser, names: dict[str, str]) -> dict[str, Any]:
        """Metadata only (no summary / shared messages / thread)."""
        return dict(id=t["id"], ticket_number=t["ticket_number"], language=t["language"], subject=t["subject"],
                    priority=t["priority"], status=t["status"], created_at=t["created_at"],
                    last_message_at=t.get("last_message_at"), escalated=t.get("escalated", False),
                    assigned_to=t.get("assigned_to"), assigned_to_name=names.get(t.get("assigned_to") or ""),
                    is_mine=t.get("assigned_to") == user.id, can_open=can_view_ticket_content(user, t))

    def _thread(self, t: dict[str, Any]) -> list[dict[str, Any]]:
        rows, _ = self.store.select("support_ticket_messages", Query(eq={"ticket_id": t["id"]}, order=[("created_at", False)],
                                                                     limit=1000))
        names = self._names([r.get("author_id") for r in rows if r["author_role"] != "student"])
        return [dict(id=r["id"], author_role=r["author_role"], kind=r["kind"], body=r["body"], created_at=r["created_at"],
                     author_name=names.get(r.get("author_id") or "") if r["author_role"] in ("supporter", "admin") else None)
                for r in rows]

    @staticmethod
    def status_message(t: dict[str, Any]) -> str:
        return {
            "waiting": "Waiting for an available Global Supporter in your language. You will be notified when someone "
                       "accepts your request.",
            "assigned": "A Global Supporter has been assigned and will accept your request soon.",
            "open": "A Global Supporter is handling your request.",
            "waiting_for_student": "The supporter is waiting for your reply.",
            "resolved": "This request is resolved. You can reopen it if you still need help.",
        }[t["status"]]

    # ---------------------------------------------------------------- student
    def create_ticket(self, user: AuthUser, body: dict[str, Any]) -> dict[str, Any]:
        if not body.get("consent"):
            raise ValidationFailed("Please confirm that you agree to share the selected information with a Global Supporter.")
        lang = body.get("language") or user.preferred_language
        shared: list[dict[str, Any]] = []
        conv_id = body.get("conversation_id")
        if conv_id:
            shared = self.conversations.selected_messages(conv_id, user.id, body.get("message_ids") or [])
        elif body.get("message_ids"):
            raise ValidationFailed("message_ids require a conversation_id.")
        t = self.store.insert("support_tickets", dict(
            student_id=user.id, language=lang, subject=body["subject"].strip(), summary=body["summary"].strip(),
            source_conversation_id=conv_id, shared_context=shared, consent_at=now(), status="waiting"))
        self._audit("ticket.create", t["id"], user, language=lang, shared_messages=len(shared),
                    from_conversation=bool(conv_id))
        if body.get("additional_message"):
            self._post(t, user, "student", body["additional_message"].strip())
        t = self.route(t["id"])
        return self.student_view(t, with_thread=True)

    def route(self, ticket_id: str) -> dict[str, Any]:
        self.store.rpc("route_support_ticket", {"p_ticket_id": ticket_id})
        t = self._ticket(ticket_id)
        label = f"#{t['ticket_number']}"
        if t["status"] == "assigned":
            self.notes.notify(t["assigned_to"], "ticket_assigned", f"New {LANG_NAMES[t['language']]} support request {label}",
                              entity_type="support_ticket", entity_id=t["id"], link=f"/admin/support/{t['id']}")
            self.notes.notify(t["student_id"], "ticket_created", f"Support request {label} received",
                              body="A Global Supporter has been assigned.", entity_type="support_ticket",
                              entity_id=t["id"], link=f"/support/requests/{t['id']}")
        else:
            self.notes.notify(t["student_id"], "ticket_waiting", f"Support request {label} is waiting",
                              body="No supporter for your language is available right now. Your request stays in the "
                                   "queue and you will be notified.", entity_type="support_ticket", entity_id=t["id"],
                              link=f"/support/requests/{t['id']}")
            self.notes.notify_many(self._leads(t["language"]), "ticket_unassigned",
                                   f"Unassigned {LANG_NAMES[t['language']]} request {label}: no supporter available",
                                   entity_type="support_ticket", entity_id=t["id"], link="/admin/support")
            # supporters of the language can claim it from the queue
            rows, _ = self.store.select("supporter_languages", Query(eq={"language_code": t["language"], "can_support": True}))
            self.notes.notify_many([r["supporter_id"] for r in rows], "ticket_queued",
                                   f"New {LANG_NAMES[t['language']]} request {label} in the queue",
                                   entity_type="support_ticket", entity_id=t["id"], link="/admin/support")
        return t

    def my_tickets(self, user: AuthUser, page: int, size: int) -> tuple[list[dict[str, Any]], int]:
        rows, total = self.store.select("support_tickets", Query(eq={"student_id": user.id}, order=[("created_at", True)],
                                                                 limit=size, offset=(page - 1) * size), count=True)
        return [self.student_view(r) for r in rows], total or 0

    def get_for(self, ticket_id: str, user: AuthUser) -> dict[str, Any]:
        t = get_one(self.store, "support_tickets", id=ticket_id)
        if t is None:
            raise NotFound("Ticket not found.")
        self._content_or_403(t, user)
        if t["student_id"] == user.id:
            return self.student_view(t, with_thread=True)
        self._audit("ticket.view", t["id"], user, as_role=user.role)  # staff access to private content is audited
        return self.staff_view(t, user, with_thread=True)

    def student_reply(self, ticket_id: str, user: AuthUser, body: str) -> dict[str, Any]:
        t = self._ticket(ticket_id)
        if t["student_id"] != user.id:
            raise NotFound("Ticket not found.")
        if t["status"] == "resolved":
            raise InvalidState("This request is resolved. Reopen it to continue the conversation.")
        self._post(t, user, "student", body)
        if t["status"] == "waiting_for_student":
            self.store.update("support_tickets", {"status": "open"}, {"id": t["id"]})
        self.notes.notify(t.get("assigned_to"), "student_reply", f"New reply on request #{t['ticket_number']}",
                          entity_type="support_ticket", entity_id=t["id"], link=f"/admin/support/{t['id']}")
        return self.student_view(self._ticket(ticket_id), with_thread=True)

    def student_resolve(self, ticket_id: str, user: AuthUser) -> dict[str, Any]:
        t = self._ticket(ticket_id)
        if t["student_id"] != user.id:
            raise NotFound("Ticket not found.")
        return self._resolve(t, user, by_student=True)

    def reopen(self, ticket_id: str, user: AuthUser) -> dict[str, Any]:
        t = self._ticket(ticket_id)
        self._content_or_403(t, user)
        if t["status"] != "resolved":
            raise InvalidState("Only resolved requests can be reopened.")
        status = "open" if t.get("assigned_to") else "waiting"
        self.store.update("support_tickets", dict(status=status, resolved_at=None, satisfaction=None,
                                                  satisfaction_comment=None), {"id": t["id"]})
        self._post(t, None, "system", "Request reopened.", "status")
        self._audit("ticket.reopen", t["id"], user)
        if status == "waiting":
            self.route(t["id"])
        elif t["student_id"] == user.id:
            self.notes.notify(t["assigned_to"], "ticket_reopened", f"Request #{t['ticket_number']} was reopened",
                              entity_type="support_ticket", entity_id=t["id"], link=f"/admin/support/{t['id']}")
        else:
            self.notes.notify(t["student_id"], "ticket_reopened", f"Request #{t['ticket_number']} was reopened",
                              entity_type="support_ticket", entity_id=t["id"], link=f"/support/requests/{t['id']}")
        t = self._ticket(ticket_id)
        return self.student_view(t, with_thread=True) if t["student_id"] == user.id else self.staff_view(t, user, with_thread=True)

    def feedback(self, ticket_id: str, user: AuthUser, rating: int, comment: str | None) -> dict[str, Any]:
        t = self._ticket(ticket_id)
        if t["student_id"] != user.id:
            raise NotFound("Ticket not found.")
        if t["status"] != "resolved":
            raise InvalidState("Feedback can be given after the request is resolved.")
        self.store.update("support_tickets", dict(satisfaction=rating, satisfaction_comment=comment), {"id": t["id"]})
        self._audit("ticket.feedback", t["id"], user, rating=rating)
        return self.student_view(self._ticket(ticket_id), with_thread=True)

    def withdraw_context(self, ticket_id: str, user: AuthUser) -> dict[str, Any]:
        """The student withdraws the AI-conversation excerpt they shared (the thread itself is kept)."""
        t = self._ticket(ticket_id)
        if t["student_id"] != user.id:
            raise NotFound("Ticket not found.")
        self.store.update("support_tickets", dict(shared_context=[], context_withdrawn_at=now()), {"id": t["id"]})
        self._audit("ticket.context_withdrawn", t["id"], user)
        self.notes.notify(t.get("assigned_to"), "context_withdrawn",
                          f"The student withdrew shared conversation content on #{t['ticket_number']}",
                          entity_type="support_ticket", entity_id=t["id"], link=f"/admin/support/{t['id']}")
        return self.student_view(self._ticket(ticket_id), with_thread=True)

    # ------------------------------------------------------------------ staff
    def inbox(self, user: AuthUser, view: str, language: str | None, page: int, size: int
              ) -> tuple[list[dict[str, Any]], int]:
        langs = languages_with(user, "support")
        if language:
            require_perm(user, language, "support", "view the support queue")
            langs = [language]
        q = Query(order=[("created_at", True)], limit=size, offset=(page - 1) * size)
        if view == "queue":       # waiting tickets in my languages (metadata only)
            if not langs:
                return [], 0
            q.eq["status"] = "waiting"
            q.in_["language"] = langs
            q.order = [("created_at", False)]
        elif view == "team":      # everything in languages I lead (team leads / super admins)
            lead = [lg for lg in langs if has_perm(user, lg, "lead")]
            if not lead:
                raise Forbidden("Only team leads can view the whole language queue.")
            q.in_["language"] = lead
        else:                     # my assigned tickets by state
            q.eq["assigned_to"] = user.id
            states = {"mine": list(ACTIVE), "open": ["open"], "waiting": ["waiting_for_student"], "resolved": ["resolved"],
                      "assigned": ["assigned"]}.get(view)
            if states is None:
                raise ValidationFailed(f"Unknown inbox view '{view}'.")
            q.in_["status"] = states
        rows, total = self.store.select("support_tickets", q, count=True)
        names = self._names([r.get("assigned_to") for r in rows])
        return [self.queue_view(r, user, names) for r in rows], total or 0

    def counts(self, user: AuthUser) -> dict[str, int]:
        langs = languages_with(user, "support")

        def c(**eq: Any) -> int:
            in_ = {k: v for k, v in eq.items() if isinstance(v, list)}
            eq2 = {k: v for k, v in eq.items() if not isinstance(v, list)}
            _r, n = self.store.select("support_tickets", Query(eq=eq2, in_=in_, limit=1, cols="id"), count=True)
            return n or 0

        return dict(queue=c(status="waiting", language=langs) if langs else 0,
                    assigned=c(assigned_to=user.id, status="assigned"), open=c(assigned_to=user.id, status="open"),
                    waiting_for_student=c(assigned_to=user.id, status="waiting_for_student"),
                    resolved=c(assigned_to=user.id, status="resolved"))

    def _staff_ticket(self, ticket_id: str, user: AuthUser) -> dict[str, Any]:
        t = get_one(self.store, "support_tickets", id=ticket_id)
        if t is None or user.role not in ("supporter", "admin", "super_admin"):
            raise NotFound("Ticket not found.")
        return t

    def accept(self, ticket_id: str, user: AuthUser) -> dict[str, Any]:
        """Accept an assigned ticket, or claim a waiting one from my language queue (concurrency-safe)."""
        t = self._staff_ticket(ticket_id, user)
        if t["status"] == "waiting":
            if not has_perm(user, t["language"], "support"):
                raise NotFound("Ticket not found.")
            try:
                self.store.rpc("assign_support_ticket", dict(p_ticket_id=t["id"], p_supporter=user.id, p_actor=user.id,
                                                             p_reason="claimed from queue", p_expect_waiting=True))
            except AppError as exc:
                if "already taken" in exc.message:
                    raise Conflict("Another supporter accepted this request first.") from exc
                raise
            t = self._ticket(ticket_id)
        if t.get("assigned_to") != user.id:
            if has_perm(user, t["language"], "support"):
                raise Conflict("Another supporter accepted this request first.")
            raise NotFound("Ticket not found.")
        if t["status"] == "assigned":
            self.store.update("support_tickets", dict(status="open", accepted_at=now()), {"id": t["id"]})
            self._post(t, None, "system", "A Global Supporter joined the conversation.", "status")
            self._audit("ticket.accept", t["id"], user)
            self.notes.notify(t["student_id"], "ticket_accepted", f"A Global Supporter accepted request #{t['ticket_number']}",
                              entity_type="support_ticket", entity_id=t["id"], link=f"/support/requests/{t['id']}")
        return self.staff_view(self._ticket(ticket_id), user, with_thread=True)

    def staff_reply(self, ticket_id: str, user: AuthUser, body: str, *, info_request: bool = False) -> dict[str, Any]:
        t = self._staff_ticket(ticket_id, user)
        self._content_or_403(t, user)
        if t["status"] in ("waiting", "assigned") and t.get("assigned_to") == user.id:
            self.accept(ticket_id, user)
            t = self._ticket(ticket_id)
        if t["status"] == "resolved":
            raise InvalidState("Reopen the request before replying.")
        if t.get("assigned_to") != user.id and not has_perm(user, t["language"], "lead"):
            raise Forbidden("Only the assigned supporter or a team lead can reply.")
        self._post(t, user, "admin" if user.role in ("admin", "super_admin") else "supporter", body,
                   "info_request" if info_request else "message")
        self.store.update("support_tickets", {"status": "waiting_for_student" if info_request else "open"}, {"id": t["id"]})
        self._audit("ticket.reply", t["id"], user, info_request=info_request)  # body is never written to the audit log
        self.notes.notify(t["student_id"], "supporter_reply", f"New reply on your request #{t['ticket_number']}",
                          entity_type="support_ticket", entity_id=t["id"], link=f"/support/requests/{t['id']}")
        return self.staff_view(self._ticket(ticket_id), user, with_thread=True)

    def set_waiting(self, ticket_id: str, user: AuthUser) -> dict[str, Any]:
        t = self._staff_ticket(ticket_id, user)
        self._require_handler(t, user)
        if t["status"] not in ("open", "assigned"):
            raise InvalidState("Only open requests can be marked as waiting for the student.")
        self.store.update("support_tickets", {"status": "waiting_for_student"}, {"id": t["id"]})
        self._audit("ticket.waiting", t["id"], user)
        return self.staff_view(self._ticket(ticket_id), user, with_thread=True)

    def staff_resolve(self, ticket_id: str, user: AuthUser) -> dict[str, Any]:
        t = self._staff_ticket(ticket_id, user)
        self._require_handler(t, user)
        return self._resolve(t, user, by_student=False)

    def _resolve(self, t: dict[str, Any], user: AuthUser, by_student: bool) -> dict[str, Any]:
        if t["status"] == "resolved":
            raise InvalidState("Already resolved.")
        if t["status"] == "waiting" and not by_student:
            raise InvalidState("Accept the request before resolving it.")
        self.store.update("support_tickets", dict(status="resolved", resolved_at=now()), {"id": t["id"]})
        self._post(t, None, "system", "Request marked as resolved.", "status")
        self._audit("ticket.resolve", t["id"], user, by_student=by_student)
        if by_student:
            self.notes.notify(t.get("assigned_to"), "ticket_resolved", f"Request #{t['ticket_number']} resolved by the student",
                              entity_type="support_ticket", entity_id=t["id"], link=f"/admin/support/{t['id']}")
            return self.student_view(self._ticket(t["id"]), with_thread=True)
        self.notes.notify(t["student_id"], "ticket_resolved", f"Your request #{t['ticket_number']} was resolved",
                          body="Tell us how it went, or reopen it if you still need help.", entity_type="support_ticket",
                          entity_id=t["id"], link=f"/support/requests/{t['id']}")
        return self.staff_view(self._ticket(t["id"]), user, with_thread=True)

    def escalate(self, ticket_id: str, user: AuthUser, reason: str) -> dict[str, Any]:
        t = self._staff_ticket(ticket_id, user)
        self._require_handler(t, user)
        self.store.update("support_tickets", dict(escalated=True, escalation_reason=reason, escalated_at=now(),
                                                  priority="high" if t["priority"] in ("low", "normal") else t["priority"]),
                          {"id": t["id"]})
        self._audit("ticket.escalate", t["id"], user, reason=reason)
        self.notes.notify_many([u for u in self._leads(t["language"]) if u != user.id], "ticket_escalated",
                               f"Escalation requested on {LANG_NAMES[t['language']]} request #{t['ticket_number']}",
                               entity_type="support_ticket", entity_id=t["id"], link=f"/admin/support/{t['id']}")
        return self.staff_view(self._ticket(ticket_id), user, with_thread=True)

    def transfer(self, ticket_id: str, user: AuthUser, to_supporter: str | None, reason: str | None) -> dict[str, Any]:
        """Reassign (current assignee, team lead or super admin). The previous assignee loses access immediately."""
        t = self._staff_ticket(ticket_id, user)
        if not (t.get("assigned_to") == user.id or has_perm(user, t["language"], "lead")):
            raise NotFound("Ticket not found.")
        if to_supporter is None and not has_perm(user, t["language"], "lead") and t.get("assigned_to") != user.id:
            raise Forbidden("Not allowed.")
        prev = t.get("assigned_to")
        self.store.rpc("assign_support_ticket", dict(p_ticket_id=t["id"], p_supporter=to_supporter, p_actor=user.id,
                                                     p_reason=reason, p_expect_waiting=False))
        t2 = self._ticket(ticket_id)
        if to_supporter:
            self.notes.notify(to_supporter, "ticket_assigned", f"Request #{t['ticket_number']} was assigned to you",
                              entity_type="support_ticket", entity_id=t["id"], link=f"/admin/support/{t['id']}")
        else:
            self.route(t["id"])
        if prev and prev != to_supporter:
            self.notes.notify(prev, "ticket_reassigned", f"Request #{t['ticket_number']} was reassigned",
                              entity_type="support_ticket", entity_id=t["id"], link="/admin/support")
        t2 = self._ticket(ticket_id)
        return self.staff_view(t2, user, with_thread=False) if can_view_ticket_content(user, t2) else \
            self.queue_view(t2, user, self._names([t2.get("assigned_to")]))

    def set_priority(self, ticket_id: str, user: AuthUser, priority: str) -> dict[str, Any]:
        t = self._staff_ticket(ticket_id, user)
        self._require_handler(t, user)
        self.store.update("support_tickets", {"priority": priority}, {"id": t["id"]})
        self._audit("ticket.priority", t["id"], user, priority=priority)
        return self.staff_view(self._ticket(ticket_id), user, with_thread=True)

    def _require_handler(self, t: dict[str, Any], user: AuthUser) -> None:
        if not (t.get("assigned_to") == user.id or has_perm(user, t["language"], "lead")):
            raise NotFound("Ticket not found.")

    def release_for(self, user_id: str, actor: AuthUser) -> int:
        """A supporter lost their role: return their active tickets to the queue (access is already revoked)."""
        rows, _ = self.store.select("support_tickets", Query(eq={"assigned_to": user_id}, in_={"status": list(ACTIVE)}))
        for t in rows:
            self.store.rpc("assign_support_ticket", dict(p_ticket_id=t["id"], p_supporter=None, p_actor=actor.id,
                                                         p_reason="assignee lost support access", p_expect_waiting=False))
            self.route(t["id"])
        return len(rows)

    # -------------------------------------------------------------- retention
    def purge_expired(self) -> dict[str, int]:
        cutoff = (datetime.now(UTC) - timedelta(days=self.retention_days)).isoformat()
        tickets, _ = self.store.select("support_tickets", Query(eq={"status": "resolved"}, lt={"resolved_at": cutoff}, cols="id"))
        for t in tickets:
            self.store.delete("support_ticket_messages", {"ticket_id": t["id"]})
            self.store.delete("support_ticket_assignments", {"ticket_id": t["id"]})
            self.store.delete("support_tickets", {"id": t["id"]})
        convs, _ = self.store.select("ai_conversations", Query(lt={"updated_at": cutoff}, cols="id"))
        for c in convs:
            self.store.delete("ai_messages", {"conversation_id": c["id"]})
            self.store.delete("ai_conversations", {"id": c["id"]})
        return dict(tickets=len(tickets), conversations=len(convs))
