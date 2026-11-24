"""Announcement workflow: draft -> submit -> approve/reject (-> cancel), translations, public views."""
from __future__ import annotations

import logging
import re
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

from app.core.constants import ADMIN_ROLES
from app.core.errors import Conflict, DuplicateError, Forbidden, InvalidState, NotFound, ValidationFailed
from app.repositories.base import Query, Store, get_many, get_one
from app.security.auth import AuthUser
from app.services.indexing import IndexingService
from app.services.ingestion.normalize import content_hash, normalize_text
from app.services.ingestion.privacy import redact_personal_info

KST = timezone(timedelta(hours=9))
SUBMISSION_SOURCES = {
    "manual_text": dict(title="Manual announcements (entered by admins / supporters)",
                        organization="Soonchunhyang University (manual entry with evidence)",
                        authority_type="official_university"),
    "kakao_message": dict(title="Supporter-submitted announcements (KakaoTalk, manually pasted)",
                          organization="SCH Global Supporters", authority_type="supporter_submitted"),
}


log = logging.getLogger("app.announcements")

def today_kst() -> date:
    return datetime.now(KST).date()


def compute_status(valid_from: str | None, deadline: str | None, today: date | None = None) -> str:
    today = today or today_kst()
    if deadline and date.fromisoformat(deadline) < today:
        return "expired"
    if valid_from and date.fromisoformat(valid_from) > today:
        return "upcoming"
    return "active"


def _start_of_day(d: str | date | None) -> str | None:
    if d is None:
        return None
    d = date.fromisoformat(d) if isinstance(d, str) else d
    return datetime(d.year, d.month, d.day, tzinfo=KST).astimezone(UTC).isoformat()


def _end_of_day(d: str | date | None) -> str | None:
    if d is None:
        return None
    d = date.fromisoformat(d) if isinstance(d, str) else d
    return (datetime(d.year, d.month, d.day, tzinfo=KST) + timedelta(days=1)).astimezone(UTC).isoformat()


def excerpt(text: str, n: int = 220) -> str:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith(("#", "[Page"))]
    flat = re.sub(r"\s+", " ", " ".join(lines))
    return flat if len(flat) <= n else flat[: n - 1].rstrip() + "…"


class AnnouncementService:
    def __init__(self, store: Store, indexer: IndexingService):
        self.store = store
        self.indexer = indexer
        self.rag_health: Any = None     # RagHealthService (wired by the container)

    # ------------------------------------------------------------ helpers
    def _names(self, ids: list[str | None]) -> dict[str, str]:
        profiles = get_many(self.store, "profiles", [i for i in ids if i])
        return {k: (v.get("display_name") or v.get("email") or "") for k, v in profiles.items()}

    def _submission_source(self, source_type: str, created_by: str) -> dict[str, Any]:
        spec = SUBMISSION_SOURCES[source_type]
        src = get_one(self.store, "knowledge_sources", source_type=source_type, title=spec["title"])
        if src:
            return src
        return self.store.insert("knowledge_sources", dict(
            title=spec["title"], organization=spec["organization"], source_type=source_type,
            authority_type=spec["authority_type"], scope="university", category="university-announcements",
            language="ko", sync_frequency="manual", is_active=True, status="registered", created_by=created_by))

    def _open_or_latest_version(self, document_id: str) -> dict[str, Any] | None:
        versions, _ = self.store.select("document_versions", Query(eq={"document_id": document_id},
                                                                    order=[("version_number", True)]))
        for v in versions:
            if v["verification_status"] in ("draft", "pending_review"):
                return v
        doc = get_one(self.store, "source_documents", id=document_id)
        cur = doc and doc.get("current_version_id")
        for v in versions:
            if v["id"] == cur:
                return v
        return versions[0] if versions else None

    def approved_version(self, document_id: str) -> dict[str, Any] | None:
        """The version students see (never an edit that waits for approval)."""
        doc = get_one(self.store, "source_documents", id=document_id)
        v = get_one(self.store, "document_versions", id=doc["current_version_id"]) \
            if doc and doc.get("current_version_id") else None
        return v if v and v["verification_status"] == "approved" else None

    def _translations(self, announcement_id: str, public: bool = False) -> list[dict[str, Any]]:
        eq: dict[str, Any] = {"announcement_id": announcement_id}
        if public:
            eq["translation_status"] = "human_approved"
        rows, _ = self.store.select("announcement_translations", Query(eq=eq, order=[("language_code", False)]))
        if public:  # an approved translation of an older original is hidden until it is re-reviewed
            rows = [r for r in rows if not r.get("is_outdated")]
        else:
            rows = [r for r in rows if r["translation_status"] != "todo"]
        names = self._names([r.get("reviewed_by") for r in rows])
        return [dict(
            id=r["id"], announcement_id=r["announcement_id"], language_code=r["language_code"], title=r["title"],
            body=r["body"], translation_status=r["translation_status"], reviewed_by=r.get("reviewed_by"),
            reviewed_by_name=names.get(r.get("reviewed_by") or ""), reviewed_at=r.get("reviewed_at"),
            is_machine_translated=r["translation_status"] == "machine_draft") for r in rows]

    def admin_view(self, a: dict[str, Any]) -> dict[str, Any]:
        v = self._open_or_latest_version(a["document_id"])
        names = self._names([a.get("created_by"), a.get("approved_by")])
        return dict(
            id=a["id"], document_id=a["document_id"], version_id=v["id"] if v else None, title=a["title"],
            category=a["category"], target_audience=a.get("target_audience"), event_date=a.get("event_date"),
            deadline=a.get("deadline"), valid_from=a.get("valid_from"), publication_status=a["publication_status"],
            original_language=a["original_language"], body=v["extracted_text"] if v else "",
            source_type=a["source_type"], evidence_note=a.get("evidence_note"), evidence_url=a.get("evidence_url"),
            created_by=a.get("created_by"), created_by_name=names.get(a.get("created_by") or ""),
            created_at=a["created_at"], submitted_at=a.get("submitted_at"), approved_by=a.get("approved_by"),
            approved_at=a.get("approved_at"), rejection_reason=a.get("rejection_reason"),
            is_test_data=a["is_test_data"], translations=self._translations(a["id"]))

    def _get(self, announcement_id: str) -> dict[str, Any]:
        a = get_one(self.store, "announcements", id=announcement_id)
        if a is None:
            raise NotFound("Announcement not found.")
        return a

    def _check_access(self, a: dict[str, Any], user: AuthUser) -> None:
        if user.role in ADMIN_ROLES:
            return
        if user.role == "supporter" and a.get("created_by") == user.id:
            return
        raise Forbidden("You can only access announcements you created.")

    # ----------------------------------------------------------- admin read
    def list_admin(self, user: AuthUser, status: str | None, q: str | None, page: int, size: int
                   ) -> tuple[list[dict[str, Any]], int]:
        eq: dict[str, Any] = {}
        if status:
            eq["publication_status"] = status
        if user.role == "supporter":
            eq["created_by"] = user.id
        elif user.role not in ADMIN_ROLES:
            raise Forbidden("Staff role required.")
        rows, total = self.store.select("announcements", Query(
            eq=eq, or_ilike=[("title", q)] if q else [], order=[("created_at", True)], limit=size,
            offset=(page - 1) * size), count=True)
        return [self.admin_view(a) for a in rows], total or 0

    def get_admin(self, announcement_id: str, user: AuthUser) -> dict[str, Any]:
        a = self._get(announcement_id)
        self._check_access(a, user)
        return self.admin_view(a)

    def history(self, announcement_id: str, user: AuthUser) -> list[dict[str, Any]]:
        a = self._get(announcement_id)
        self._check_access(a, user)
        rows, _ = self.store.select("audit_log", Query(
            eq={"entity_type": "announcement", "entity_id": announcement_id}, order=[("created_at", False), ("id", False)]))
        names = self._names([r.get("actor_id") for r in rows])
        return [dict(id=str(r["id"]), action=r["action"], entity_type=r["entity_type"], entity_id=r["entity_id"],
                     actor_id=r.get("actor_id"), actor_name=names.get(r.get("actor_id") or ""), details=r["details"],
                     created_at=r["created_at"]) for r in rows]

    # ---------------------------------------------------------------- write
    def _prepare_text(self, body: str, source_type: str, authorized: bool) -> str:
        if source_type == "kakao_message":
            if not authorized:
                raise ValidationFailed("KakaoTalk submissions require confirmation that an authorized supporter "
                                       "provided this material (authorized_by_supporter = true).")
            body, _stats = redact_personal_info(body)
        text = normalize_text(body)
        if len(text) < 10:
            raise ValidationFailed("The announcement text is empty after cleaning.")
        return text

    def create(self, data: dict[str, Any], user: AuthUser) -> dict[str, Any]:
        if user.role == "student":
            raise Forbidden("Staff role required.")
        text = self._prepare_text(data["body"], data["source_type"], data.get("authorized_by_supporter", False))
        source = self._submission_source(data["source_type"], user.id)
        doc = self.store.insert("source_documents", dict(
            source_id=source["id"], external_id=f"announcement-{_uuid()}", title=data["title"],
            language=data["original_language"], document_type="announcement"))
        self.store.insert("document_versions", dict(
            document_id=doc["id"], version_number=1, extracted_text=text, content_hash=content_hash(text),
            source_published_at=_iso(data.get("source_published_at")), verification_status="draft",
            valid_from=_start_of_day(data.get("valid_from")), valid_until=_end_of_day(data.get("deadline")),
            created_by=user.id))
        a = self.store.insert("announcements", dict(
            document_id=doc["id"], title=data["title"], category=data["category"],
            target_audience=data.get("target_audience"), event_date=_d(data.get("event_date")),
            deadline=_d(data.get("deadline")), valid_from=_d(data.get("valid_from")),
            original_language=data["original_language"], source_type=data["source_type"],
            evidence_note=data.get("evidence_note"), evidence_url=data.get("evidence_url"), created_by=user.id,
            publication_status="draft"))
        self.store.insert("audit_log", dict(action="announcement.create", entity_type="announcement", entity_id=a["id"],
                                            actor_id=user.id, details={"source_type": data["source_type"]}))
        if data.get("submit"):
            return self.submit(a["id"], user)
        return self.admin_view(a)

    def update(self, announcement_id: str, patch: dict[str, Any], user: AuthUser) -> dict[str, Any]:
        a = self._get(announcement_id)
        self._check_access(a, user)
        if a["publication_status"] not in ("draft", "rejected"):
            raise InvalidState(f"Only draft or rejected announcements can be edited (this one is "
                               f"'{a['publication_status']}'). Cancel it and create a new one instead.")
        clearable = ("target_audience", "event_date", "deadline", "valid_from", "evidence_note", "evidence_url")
        # explicit null clears an optional field; required fields (title/body/category) ignore null
        fields = {k: v for k, v in patch.items() if v is not None or k in clearable}
        new_deadline = _d(fields.get("deadline", a.get("deadline")))
        new_from = _d(fields.get("valid_from", a.get("valid_from")))
        if new_deadline and new_from and new_deadline < new_from:
            raise ValidationFailed("deadline cannot be before valid_from")

        versions, _ = self.store.select("document_versions", Query(eq={"document_id": a["document_id"]},
                                                                    order=[("version_number", True)]))
        draft = next((v for v in versions if v["verification_status"] == "draft"), None)
        text = self._prepare_text(fields["body"], a["source_type"], True) if "body" in fields else None
        v_patch: dict[str, Any] = dict(valid_from=_start_of_day(new_from), valid_until=_end_of_day(new_deadline))
        if draft is None:  # editing a rejected announcement: preserve the rejected version, start a new draft
            base_text = text if text is not None else versions[0]["extracted_text"]
            try:
                self.store.insert("document_versions", dict(
                    document_id=a["document_id"], version_number=versions[0]["version_number"] + 1,
                    extracted_text=base_text, content_hash=content_hash(base_text), verification_status="draft",
                    created_by=user.id, **v_patch))
            except DuplicateError as exc:
                raise Conflict("This text is identical to an earlier version of this announcement; "
                               "change the text before resubmitting.") from exc
        else:
            if text is not None and content_hash(text) != draft["content_hash"]:
                v_patch.update(extracted_text=text, content_hash=content_hash(text))
            try:
                self.store.update("document_versions", v_patch, {"id": draft["id"]})
            except DuplicateError as exc:
                raise Conflict("This text is identical to an earlier version of this announcement.") from exc
        a_patch = {k: (_d(v) if k in ("event_date", "deadline", "valid_from") else v) for k, v in fields.items()
                   if k != "body"}
        a_patch["publication_status"] = "draft"
        if "title" in fields:
            self.store.update("source_documents", {"title": fields["title"]}, {"id": a["document_id"]})
        a = self.store.update("announcements", a_patch, {"id": a["id"]})[0]
        self.store.insert("audit_log", dict(action="announcement.update", entity_type="announcement", entity_id=a["id"],
                                            actor_id=user.id, details={"fields": sorted(fields.keys())}))
        return self.admin_view(a)

    def submit(self, announcement_id: str, user: AuthUser) -> dict[str, Any]:
        a = self._get(announcement_id)
        self._check_access(a, user)
        versions, _ = self.store.select("document_versions", Query(eq={"document_id": a["document_id"],
                                                                        "verification_status": "draft"}))
        if not versions:
            raise InvalidState("There is no draft content to submit.")
        # chunk + embed now (embedding failure is tolerated here; approval re-checks and blocks)
        self.indexer.index_version(versions[0]["id"])
        self.store.rpc("submit_announcement", dict(p_announcement_id=announcement_id, p_actor=user.id))
        return self.admin_view(self._get(announcement_id))

    def approve(self, announcement_id: str, user: AuthUser, note: str | None) -> dict[str, Any]:
        a = self._get(announcement_id)
        if a["publication_status"] != "pending_approval":
            raise InvalidState(f"Only announcements pending approval can be approved (this one is "
                               f"'{a['publication_status']}').")
        versions, _ = self.store.select("document_versions", Query(eq={"document_id": a["document_id"],
                                                                        "verification_status": "pending_review"}))
        if versions:
            self.indexer.ensure_indexed(versions[0]["id"])
        self.store.rpc("approve_announcement", dict(p_announcement_id=announcement_id, p_actor=user.id, p_note=note))
        health_svc = getattr(self, "rag_health", None)
        if versions and health_svc is not None:
            try:   # published: verify students can find it (alert admins if not; never undo the publication)
                health = health_svc.check_version(versions[0]["id"])
                if not health["ok"]:
                    health_svc.alert(health)
            except Exception:  # noqa: BLE001
                log.exception("searchability check failed for announcement %s", announcement_id)
        return self.admin_view(self._get(announcement_id))

    def reject(self, announcement_id: str, user: AuthUser, reason: str) -> dict[str, Any]:
        self._get(announcement_id)
        self.store.rpc("reject_announcement", dict(p_announcement_id=announcement_id, p_actor=user.id, p_reason=reason))
        return self.admin_view(self._get(announcement_id))

    def cancel(self, announcement_id: str, user: AuthUser, reason: str) -> dict[str, Any]:
        self._get(announcement_id)
        self.store.rpc("cancel_announcement", dict(p_announcement_id=announcement_id, p_actor=user.id, p_reason=reason))
        return self.admin_view(self._get(announcement_id))

    # --------------------------------------------------------- translations
    def _assert_language_access(self, user: AuthUser, language: str) -> None:
        if user.role in ADMIN_ROLES:
            return
        if user.role == "supporter" and language in user.languages:
            return
        raise Forbidden(f"You are not assigned to translate into '{language}'.")

    def upsert_translation(self, announcement_id: str, language: str, data: dict[str, Any], user: AuthUser
                           ) -> dict[str, Any]:
        a = self._get(announcement_id)
        self._assert_language_access(user, language)
        if language == a["original_language"]:
            raise ValidationFailed("The original language does not need a translation.")
        if a["publication_status"] == "canceled":
            raise InvalidState("Canceled announcements cannot be translated.")
        existing = get_one(self.store, "announcement_translations", announcement_id=announcement_id,
                           language_code=language)
        row = dict(title=data["title"], body=data["body"], translation_status=data["translation_status"],
                   reviewed_by=None, reviewed_at=None)  # any edit voids a previous human approval
        if existing:
            self.store.update("announcement_translations", row, {"id": existing["id"]})
        else:
            self.store.insert("announcement_translations", dict(announcement_id=announcement_id,
                                                                language_code=language, **row))
        self.store.insert("audit_log", dict(action="translation.save", entity_type="announcement", entity_id=announcement_id,
                                            actor_id=user.id, details={"language": language,
                                                                       "status": data["translation_status"]}))
        return next(t for t in self._translations(announcement_id) if t["language_code"] == language)

    def approve_translation(self, announcement_id: str, language: str, user: AuthUser) -> dict[str, Any]:
        self._get(announcement_id)
        self._assert_language_access(user, language)
        t = get_one(self.store, "announcement_translations", announcement_id=announcement_id, language_code=language)
        if t is None:
            raise NotFound("Translation not found.")
        if t["translation_status"] == "human_approved":
            raise InvalidState("Translation is already approved.")
        self.store.update("announcement_translations", dict(
            translation_status="human_approved", reviewed_by=user.id, reviewed_at=datetime.now(UTC).isoformat()),
            {"id": t["id"]})
        self.store.insert("audit_log", dict(action="translation.approve", entity_type="announcement",
                                            entity_id=announcement_id, actor_id=user.id, details={"language": language}))
        return next(x for x in self._translations(announcement_id) if x["language_code"] == language)

    def list_translations(self, user: AuthUser, status: str | None, language: str | None, page: int, size: int
                          ) -> tuple[list[dict[str, Any]], int]:
        eq: dict[str, Any] = {}
        if status:
            eq["translation_status"] = status
        in_: dict[str, list[Any]] = {}
        if language:
            eq["language_code"] = language
        if user.role == "supporter":
            if not user.languages:
                return [], 0
            in_["language_code"] = user.languages
        rows, total = self.store.select("announcement_translations", Query(
            eq=eq, in_=in_, order=[("updated_at", True)], limit=size, offset=(page - 1) * size), count=True)
        anns = get_many(self.store, "announcements", [r["announcement_id"] for r in rows])
        names = self._names([r.get("reviewed_by") for r in rows])
        items = [dict(
            id=r["id"], announcement_id=r["announcement_id"], language_code=r["language_code"], title=r["title"],
            body=r["body"], translation_status=r["translation_status"], reviewed_by=r.get("reviewed_by"),
            reviewed_by_name=names.get(r.get("reviewed_by") or ""), reviewed_at=r.get("reviewed_at"),
            is_machine_translated=r["translation_status"] == "machine_draft",
            announcement_title=(anns.get(r["announcement_id"]) or {}).get("title")) for r in rows]
        return items, total or 0


def _uuid() -> str:
    import uuid

    return str(uuid.uuid4())


def _iso(dt: datetime | None) -> str | None:
    return dt.astimezone(UTC).isoformat() if dt else None


def _d(d: date | str | None) -> str | None:
    return d.isoformat() if isinstance(d, date) else d
