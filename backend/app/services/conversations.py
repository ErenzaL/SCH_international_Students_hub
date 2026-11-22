"""Persistent, private AI conversations (students' own data; never indexed into the shared RAG corpus).

Each turn runs the RAG-first engine (``services/assistant/engine.py``): grounded answers from approved ORIGINAL
passages with [n] citations, evidence assessment, and a Global Supporter offered only when genuinely needed (the
student must confirm; requests are created only by the explicit support endpoint).
"""
from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from app.core.config import Settings
from app.core.errors import Forbidden, InvalidState, NotFound
from app.repositories.base import Query, Store, get_one
from app.services.assistant.engine import _HUMAN, AssistantEngine  # noqa: F401  (_HUMAN re-exported for tests)
from app.services.llm.base import LLMProvider
from app.services.retrieval.service import RetrievalService

LANGS = ("ko", "en", "id", "vi", "zh-CN")


class ConversationService:
    def __init__(self, store: Store, retrieval: RetrievalService, *, retention_days: int = 365,
                 llm: LLMProvider | None = None, settings: Settings | None = None):
        self.store = store
        self.retrieval = retrieval
        self.retention_days = retention_days
        self.settings = settings or Settings(_env_file=None)  # type: ignore[call-arg]
        self.history_turns = self.settings.assistant_history_turns
        from app.core.rate_limit import ai_budget

        limit = self.settings.ai_daily_limit_global
        self.engine = AssistantEngine(retrieval, llm, self.settings, budget=lambda: ai_budget.take("global", limit))

    @property
    def llm(self) -> LLMProvider:
        return self.engine.llm

    @llm.setter
    def llm(self, provider: LLMProvider) -> None:
        self.engine.llm = provider

    # ------------------------------------------------------------ access
    def get_own(self, conversation_id: str, user_id: str) -> dict[str, Any]:
        c = get_one(self.store, "ai_conversations", id=conversation_id)
        if c is None or c["user_id"] != user_id:  # same error for "missing" and "not yours"
            raise NotFound("Conversation not found.")
        return c

    def view(self, c: dict[str, Any]) -> dict[str, Any]:
        return {k: c.get(k) for k in ("id", "title", "language", "is_private", "message_count", "last_message_at",
                                       "last_message_preview", "created_at", "updated_at")}

    # -------------------------------------------------------------- crud
    def list(self, user_id: str, page: int, size: int, q: str | None = None) -> tuple[list[dict[str, Any]], int]:
        rows, total = self.store.select("ai_conversations", Query(
            eq={"user_id": user_id}, or_ilike=[("title", q)] if q else [],
            order=[("last_message_at", True), ("created_at", True)], limit=size, offset=(page - 1) * size), count=True)
        return [self.view(r) for r in rows], total or 0

    def create(self, user_id: str, language: str, title: str | None = None) -> dict[str, Any]:
        if language not in LANGS:
            raise InvalidState("Unsupported language.")
        return self.view(self.store.insert("ai_conversations", dict(user_id=user_id, language=language,
                                                                    title=(title or "New conversation")[:200])))

    def detail(self, conversation_id: str, user_id: str) -> dict[str, Any]:
        c = self.get_own(conversation_id, user_id)
        msgs, _ = self.store.select("ai_messages", Query(eq={"conversation_id": c["id"]}, order=[("created_at", False)],
                                                         limit=500))
        return {**self.view(c), "messages": msgs}

    def update(self, conversation_id: str, user_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        self.get_own(conversation_id, user_id)
        fields = {k: v for k, v in patch.items() if k in ("title", "is_private", "language") and v is not None}
        if not fields:
            return self.view(self.get_own(conversation_id, user_id))
        fields["updated_at"] = datetime.now(UTC).isoformat()
        return self.view(self.store.update("ai_conversations", fields, {"id": conversation_id})[0])

    def delete(self, conversation_id: str, user_id: str) -> None:
        """Hard delete (messages cascade). Support tickets keep only the copy the student consented to share."""
        self.get_own(conversation_id, user_id)
        self.store.delete("ai_messages", {"conversation_id": conversation_id})
        self.store.delete("ai_conversations", {"id": conversation_id})

    # --------------------------------------------------------------- ask
    def ask(self, conversation_id: str, user_id: str, content: str, language: str | None = None,
            emit: Any = None) -> dict[str, Any]:
        """One RAG-first assistant turn (see services/assistant/engine.py), persisted in the student's own history.
        A per-message language never changes the profile."""
        c = self.get_own(conversation_id, user_id)
        lang = language if language in LANGS else c["language"]
        now = datetime.now(UTC).isoformat()
        history, _ = self.store.select("ai_messages", Query(eq={"conversation_id": c["id"]},
                                                          order=[("created_at", True)], limit=self.history_turns))
        history.reverse()
        user_msg = self.store.insert("ai_messages", dict(conversation_id=c["id"], role="user", content=content[:8000],
                                                          language=lang))
        out = self.engine.respond(content, language=lang, history=history, emit=emit)
        assistant = self.store.insert("ai_messages", dict(
            conversation_id=c["id"], role="assistant", content=out["answer"][:8000], language=out["language"],
            citations=out["citations"], metadata=self._metadata(out)))
        title = c["title"]
        if c["message_count"] == 0 and title == "New conversation":
            title = re.sub(r"\s+", " ", content).strip()[:60] or title
        self.store.update("ai_conversations", dict(
            message_count=c["message_count"] + 2, last_message_at=now, title=title, updated_at=now,
            last_message_preview=re.sub(r"\s+", " ", content).strip()[:120]), {"id": c["id"]})
        return dict(user_message=user_msg, assistant_message=assistant, conversation=self.view(
            self.get_own(conversation_id, user_id)))

    @staticmethod
    def _metadata(out: dict[str, Any]) -> dict[str, Any]:
        r = out.get("retrieval") or {}
        return {"offer_handoff": out["offer_handoff"], "handoff_reasons": out["handoff_reasons"],
                "evidence_level": out["evidence"], "weak_evidence": bool(out.get("weak_evidence")),
                "individual": out["individual"], "follow_ups": out["follow_ups"],
                "evidence": r.get("hits", 0), "retrieval_mode": r.get("mode"), "warning": r.get("warning"),
                "rewritten": r.get("rewritten", False), "latency_ms": out.get("latency_ms"),
                "stale_evidence": any(c.get("is_stale") for c in out["citations"]),
                "insufficient_evidence": out["evidence"] == "none", **(out.get("generation") or {})}

    def ask_anonymous(self, content: str, language: str, history: list[dict[str, Any]], emit: Any = None
                      ) -> dict[str, Any]:
        """Stateless turn for visitors who are not signed in: nothing is stored; the client sends recent turns.
        Supporter handoff needs an account, so the offer only tells the visitor to sign in."""
        clean = [{"role": m["role"], "content": str(m["content"])[:2000]} for m in history[-self.history_turns:]
                 if m.get("role") in ("user", "assistant") and m.get("content")]
        out = self.engine.respond(content, language=language if language in LANGS else "en", history=clean, emit=emit)
        return dict(answer=out["answer"], language=out["language"], citations=out["citations"],
                    metadata=self._metadata(out) | {"sign_in_required_for_handoff": out["offer_handoff"]})

    def selected_messages(self, conversation_id: str, user_id: str, message_ids: list[str]) -> list[dict[str, Any]]:
        """Messages the student explicitly selected for sharing (must all belong to their conversation)."""
        c = self.get_own(conversation_id, user_id)
        if c["is_private"]:
            raise Forbidden("This conversation is marked private and cannot be shared with supporters.")
        if not message_ids:
            return []
        rows, _ = self.store.select("ai_messages", Query(eq={"conversation_id": c["id"]}, in_={"id": message_ids}))
        if len(rows) != len(set(message_ids)):
            raise NotFound("Some selected messages do not belong to this conversation.")
        rows.sort(key=lambda r: r["created_at"])
        return [dict(role=r["role"], content=r["content"], created_at=r["created_at"],
                     citations=[{k: x.get(k) for k in ("document_title", "source_url")} for x in r.get("citations") or []])
                for r in rows]
