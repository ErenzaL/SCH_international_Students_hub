"""Persistent, private AI conversations (students' own data; never indexed into the shared RAG corpus).

Answer generation (LLM) is not enabled yet: the assistant replies with approved passages + citations and a
short framing sentence in the conversation language. It never invents facts, never pretends a human joined,
and offers a Global Supporter when evidence is missing or the question needs an individual decision.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from app.core.errors import Forbidden, InvalidState, NotFound
from app.repositories.base import Query, Store, get_one
from app.services.retrieval.service import RetrievalService

LANGS = ("ko", "en", "id", "vi", "zh-CN")
PASSAGE_CHARS = 420

TEXT: dict[str, dict[str, str]] = {
    "found": {
        "en": "Here is what approved official sources say. This is general guidance, not a decision about your case:",
        "ko": "승인된 공식 자료의 내용입니다. 일반적인 안내이며 개인 사안에 대한 결정이 아닙니다:",
        "id": "Berikut informasi dari sumber resmi yang telah disetujui. Ini panduan umum, bukan keputusan atas kasus Anda:",
        "vi": "Đây là thông tin từ các nguồn chính thức đã được duyệt. Đây là hướng dẫn chung, không phải quyết định cho trường hợp của bạn:",
        "zh-CN": "以下是已审核官方资料中的内容。这只是一般性指导，并非针对您个人情况的决定：",
    },
    "none": {
        "en": "I could not find this in the approved SCH and Korean government sources, so I cannot answer it reliably.",
        "ko": "승인된 순천향대학교 및 한국 정부 자료에서 관련 내용을 찾지 못해 신뢰할 수 있는 답변을 드릴 수 없습니다.",
        "id": "Saya tidak menemukan informasi ini di sumber resmi SCH dan pemerintah Korea yang disetujui, jadi saya tidak dapat menjawab dengan andal.",
        "vi": "Tôi không tìm thấy thông tin này trong các nguồn chính thức đã duyệt của SCH và chính phủ Hàn Quốc nên không thể trả lời chính xác.",
        "zh-CN": "我在已审核的顺天乡大学和韩国政府资料中没有找到相关内容，因此无法给出可靠的回答。",
    },
    "individual": {
        "en": "Your question may depend on your personal situation. Only the responsible office can decide individual cases.",
        "ko": "질문 내용은 개인 상황에 따라 달라질 수 있습니다. 개별 사안은 담당 부서만 결정할 수 있습니다.",
        "id": "Pertanyaan Anda mungkin bergantung pada situasi pribadi Anda. Hanya kantor yang berwenang yang dapat memutuskan kasus individu.",
        "vi": "Câu hỏi của bạn có thể phụ thuộc vào hoàn cảnh cá nhân. Chỉ văn phòng phụ trách mới có thể quyết định từng trường hợp.",
        "zh-CN": "您的问题可能取决于个人情况。个人案例只能由负责部门决定。",
    },
    "offer": {
        "en": "You can ask a Global Supporter for help. Nothing is shared until you choose what to send.",
        "ko": "글로벌 서포터에게 도움을 요청할 수 있습니다. 보낼 내용을 직접 선택하기 전에는 아무것도 공유되지 않습니다.",
        "id": "Anda dapat meminta bantuan Global Supporter. Tidak ada yang dibagikan sampai Anda memilih apa yang dikirim.",
        "vi": "Bạn có thể nhờ Global Supporter hỗ trợ. Không có gì được chia sẻ cho đến khi bạn chọn nội dung gửi đi.",
        "zh-CN": "您可以向全球支持者求助。在您选择要发送的内容之前，不会共享任何信息。",
    },
}
_HUMAN = re.compile(r"(human|real person|talk to (a|someone)|supporter|staff|상담|사람|담당자|서포터|manusia|orang|"
                    r"petugas|người thật|nhân viên|tư vấn|人工|真人|客服|工作人员)", re.I)
_INDIVIDUAL = re.compile(r"(\bmy (visa|case|application|status|situation)\b|will i (be|get)|am i (allowed|eligible)|"
                         r"can i (still|get)|제 (비자|경우|신청|상황)|내 (비자|경우|신청|상황)|저는.*(되나요|가능한가요)|"
                         r"visa saya|kasus saya|apakah saya (bisa|boleh)|visa của tôi|trường hợp của tôi|tôi có được|"
                         r"我的(签证|情况|申请)|我能不能|我可以.*吗)", re.I)
_DISPUTE = re.compile(r"(wrong|incorrect|not true|that'?s not|틀렸|아닌데|잘못|salah|tidak benar|sai rồi|không đúng|"
                      r"不对|错了|不正确)", re.I)


def t(key: str, lang: str) -> str:
    return TEXT[key].get(lang) or TEXT[key]["en"]


class ConversationService:
    def __init__(self, store: Store, retrieval: RetrievalService, *, retention_days: int = 365):
        self.store = store
        self.retrieval = retrieval
        self.retention_days = retention_days

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
    def ask(self, conversation_id: str, user_id: str, content: str, language: str | None = None) -> dict[str, Any]:
        c = self.get_own(conversation_id, user_id)
        lang = language if language in LANGS else c["language"]  # per-message language never changes the profile
        now = datetime.now(UTC).isoformat()
        user_msg = self.store.insert("ai_messages", dict(conversation_id=c["id"], role="user", content=content[:8000],
                                                          language=lang))
        res = self.retrieval.search(content, language=lang, top_k=4)
        hits = res["results"]
        reasons = []
        if not hits:
            reasons.append("no_evidence")
        if _HUMAN.search(content):
            reasons.append("asked_for_human")
        if _INDIVIDUAL.search(content):
            reasons.append("individual_decision")
        if _DISPUTE.search(content):
            reasons.append("disputed_answer")
        parts = [t("found", lang) if hits else t("none", lang)]
        citations = []
        for i, h in enumerate(hits, 1):
            passage = re.sub(r"\s+", " ", h["passage"]).strip()
            passage = passage[:PASSAGE_CHARS] + ("…" if len(passage) > PASSAGE_CHARS else "")
            parts.append(f"[{i}] {h['document_title']}{' – ' + h['heading'] if h.get('heading') else ''}\n{passage}")
            citations.append({k: h.get(k) for k in ("document_id", "version_id", "chunk_id", "document_title", "heading",
                                                    "source_url", "organization", "authority_type", "verified_at",
                                                    "is_stale", "page", "similarity")} | {"n": i})
        if "individual_decision" in reasons:
            parts.append(t("individual", lang))
        offer = bool(reasons)
        if offer:
            parts.append(t("offer", lang))
        assistant = self.store.insert("ai_messages", dict(
            conversation_id=c["id"], role="assistant", content="\n\n".join(parts)[:8000], language=lang,
            citations=citations, metadata={"offer_handoff": offer, "handoff_reasons": reasons, "evidence": len(hits),
                                           "retrieval_mode": res["retrieval"]["mode"], "answer_generation": "disabled",
                                           "warning": res["retrieval"].get("warning")}))
        title = c["title"]
        if c["message_count"] == 0 and title == "New conversation":
            title = re.sub(r"\s+", " ", content).strip()[:60] or title
        self.store.update("ai_conversations", dict(
            message_count=c["message_count"] + 2, last_message_at=now, title=title, updated_at=now,
            last_message_preview=re.sub(r"\s+", " ", content).strip()[:120]), {"id": c["id"]})
        return dict(user_message=user_msg, assistant_message=assistant, conversation=self.view(
            self.get_own(conversation_id, user_id)))

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
