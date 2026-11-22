"""Language-scoped translation review for announcements.

* Editing (save draft / submit) needs ``support`` or ``review`` permission for the language; approving,
  rejecting and requesting changes need ``review`` (designated translation reviewers, team leads,
  super admins). Plain admins need an assignment like everyone else.
* Approval requires: the original announcement is published (admin-verified), the reviewer confirms
  they checked the translation against the original, and the translation matches the CURRENT original
  (``source_content_hash``). Each language is approved / published independently.
* When the original changes, translations made from the old text are flagged ``is_outdated`` and
  disappear from the public site until re-reviewed.
Translation tasks never expose support tickets or AI conversations.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.core.errors import Forbidden, InvalidState, NotFound, ValidationFailed
from app.repositories.base import Query, Store, get_many, get_one
from app.security.auth import AuthUser
from app.security.permissions import has_perm, languages_with, require_perm
from app.services.announcements import AnnouncementService
from app.services.ingestion.normalize import content_hash
from app.services.notifications import UserNotificationService

TARGETS = ("ko", "en", "id", "vi", "zh-CN")
LANG_NAMES = {"ko": "Korean", "en": "English", "id": "Indonesian", "vi": "Vietnamese", "zh-CN": "Chinese"}
EDITABLE = ("todo", "machine_draft", "in_review", "changes_requested", "rejected", "human_approved")


def now() -> str:
    return datetime.now(UTC).isoformat()


def language_people(store: Store, language: str, perm: str) -> list[str]:
    """Supporters/admins assigned to a language with the given permission ('review', 'support' or 'any')."""
    rows, _ = store.select("supporter_languages", Query(eq={"language_code": language}))
    profs = get_many(store, "profiles", [r["supporter_id"] for r in rows])
    out = []
    for r in rows:
        if (profs.get(r["supporter_id"]) or {}).get("role") not in ("supporter", "admin"):
            continue
        ok = {"review": r.get("can_review_translations") or r.get("is_team_lead"),
              "any": True}.get(perm, r.get("can_support"))
        if ok:
            out.append(r["supporter_id"])
    return out


class TranslationReviewService:
    def __init__(self, store: Store, announcements: AnnouncementService, notes: UserNotificationService):
        self.store = store
        self.ann = announcements
        self.notes = notes

    # ---------------------------------------------------------------- original
    def original(self, announcement_id: str) -> dict[str, Any]:
        a = self.ann._get(announcement_id)
        v = self.ann._open_or_latest_version(a["document_id"])
        body = v["extracted_text"] if v else ""
        return dict(announcement_id=a["id"], title=a["title"], body=body, language=a["original_language"],
                    publication_status=a["publication_status"], version_id=v["id"] if v else None,
                    content_hash=content_hash(f"{a['title']}\n\n{body}"), category=a["category"],
                    deadline=a.get("deadline"), event_date=a.get("event_date"), is_test_data=a.get("is_test_data", False))

    def _row(self, announcement_id: str, language: str) -> dict[str, Any] | None:
        return get_one(self.store, "announcement_translations", announcement_id=announcement_id, language_code=language)

    def view(self, t: dict[str, Any], orig: dict[str, Any], names: dict[str, str] | None = None) -> dict[str, Any]:
        names = names if names is not None else self._names([t.get("reviewed_by"), t.get("last_edited_by")])
        outdated = bool(t.get("is_outdated")) or bool(t.get("source_content_hash")
                                                       and t["source_content_hash"] != orig["content_hash"]
                                                       and t["translation_status"] != "todo")
        return dict(id=t["id"], announcement_id=t["announcement_id"], language_code=t["language_code"], title=t["title"],
                    body=t["body"], translation_status=t["translation_status"], is_outdated=outdated,
                    review_note=t.get("review_note"), reviewed_by=t.get("reviewed_by"),
                    reviewed_by_name=names.get(t.get("reviewed_by") or ""), reviewed_at=t.get("reviewed_at"),
                    last_edited_by=t.get("last_edited_by"), last_edited_by_name=names.get(t.get("last_edited_by") or ""),
                    last_edited_at=t.get("last_edited_at"), submitted_at=t.get("submitted_at"),
                    original_verified_at=t.get("original_verified_at"), updated_at=t.get("updated_at"),
                    is_machine_translated=t["translation_status"] == "machine_draft",
                    published=t["translation_status"] == "human_approved" and not outdated
                    and orig["publication_status"] == "published")

    def _names(self, ids: list[str | None]) -> dict[str, str]:
        return {k: (v.get("display_name") or v.get("email") or "") for k, v in
                get_many(self.store, "profiles", [i for i in ids if i]).items()}

    def permissions(self, user: AuthUser, language: str) -> dict[str, bool]:
        return dict(can_edit=has_perm(user, language, "support") or has_perm(user, language, "review"),
                    can_review=has_perm(user, language, "review"))

    def _revision(self, t: dict[str, Any], action: str, user: AuthUser | None, note: str | None = None) -> None:
        self.store.insert("translation_revisions", dict(
            translation_id=t["id"], title=t.get("title"), body=t.get("body"), translation_status=t["translation_status"],
            source_content_hash=t.get("source_content_hash"), action=action, note=note, actor_id=user.id if user else None))

    def _audit(self, action: str, a_id: str, user: AuthUser | None, **details: Any) -> None:
        self.store.insert("audit_log", dict(action=action, entity_type="announcement", entity_id=a_id,
                                            actor_id=user.id if user else None, details=details))

    def _people(self, language: str, perm: str) -> list[str]:
        return language_people(self.store, language, perm)

    # ------------------------------------------------------------------- reads
    def detail(self, announcement_id: str, language: str, user: AuthUser) -> dict[str, Any]:
        perms = self.permissions(user, language)
        if not (perms["can_edit"] or perms["can_review"]):
            raise Forbidden(f"You are not assigned to {LANG_NAMES.get(language, language)} translations.")
        orig = self.original(announcement_id)
        t = self._row(announcement_id, language)
        revs: list[dict[str, Any]] = []
        if t:
            rows, _ = self.store.select("translation_revisions", Query(eq={"translation_id": t["id"]}, order=[("id", True)],
                                                                       limit=100))
            names = self._names([r.get("actor_id") for r in rows])
            revs = [{**r, "actor_name": names.get(r.get("actor_id") or "")} for r in rows]
        return dict(original=orig, translation=self.view(t, orig) if t else None, revisions=revs, permissions=perms,
                    language=language)

    def tasks(self, user: AuthUser, status: str | None, language: str | None, outdated: bool | None, page: int,
              size: int) -> tuple[list[dict[str, Any]], int]:
        langs = sorted(set(languages_with(user, "support")) | set(languages_with(user, "review")))
        if language:
            if language not in langs:
                raise Forbidden(f"You are not assigned to {LANG_NAMES.get(language, language)} translations.")
            langs = [language]
        if not langs:
            return [], 0
        q = Query(in_={"language_code": langs}, order=[("updated_at", True)], limit=size, offset=(page - 1) * size)
        if status:
            q.eq["translation_status"] = status
        if outdated is not None:
            q.eq["is_outdated"] = outdated
        rows, total = self.store.select("announcement_translations", q, count=True)
        anns = get_many(self.store, "announcements", [r["announcement_id"] for r in rows])
        names = self._names([x for r in rows for x in (r.get("reviewed_by"), r.get("last_edited_by"))])
        out = []
        origs: dict[str, dict[str, Any]] = {}
        for r in rows:
            a = anns.get(r["announcement_id"])
            if a is None:
                continue
            if a["id"] not in origs:
                origs[a["id"]] = self.original(a["id"])
            item = self.view(r, origs[a["id"]], names)
            item.update(announcement_title=a["title"], announcement_status=a["publication_status"],
                        original_language=a["original_language"], **{f"can_{k}": v for k, v in
                                                                      self.permissions(user, r["language_code"]).items()})
            out.append(item)
        return out, total or 0

    # ------------------------------------------------------------------ writes
    def save(self, announcement_id: str, language: str, data: dict[str, Any], user: AuthUser) -> dict[str, Any]:
        perms = self.permissions(user, language)
        if not perms["can_edit"]:
            raise Forbidden(f"You are not assigned to {LANG_NAMES.get(language, language)} translations.")
        orig = self.original(announcement_id)
        if language == orig["language"]:
            raise ValidationFailed("The original language does not need a translation.")
        if orig["publication_status"] == "canceled":
            raise InvalidState("Canceled announcements cannot be translated.")
        submit = data.get("translation_status") == "in_review" or bool(data.get("submit"))
        status = "in_review" if submit else "machine_draft"  # machine_draft = draft not yet submitted for review
        row = dict(title=data["title"].strip(), body=data["body"].strip(), translation_status=status,
                   source_content_hash=orig["content_hash"], is_outdated=False, review_note=None,
                   reviewed_by=None, reviewed_at=None, original_verified_by=None, original_verified_at=None,
                   last_edited_by=user.id, last_edited_at=now(), submitted_at=now() if submit else None)
        t = self._row(announcement_id, language)
        if t:
            t = self.store.update("announcement_translations", row, {"id": t["id"]})[0]  # an edit voids an approval
        else:
            t = self.store.insert("announcement_translations", dict(announcement_id=announcement_id, language_code=language,
                                                                    **row))
        self._revision(t, "submit" if submit else "save", user)
        self._audit("translation.submit" if submit else "translation.save", announcement_id, user, language=language)
        if submit:
            self.notes.notify_many([u for u in self._people(language, "review") if u != user.id], "translation_review",
                                   f"{LANG_NAMES[language]} translation waiting for review: {orig['title'][:120]}",
                                   entity_type="announcement", entity_id=announcement_id,
                                   link=f"/admin/translations/{announcement_id}/{language}")
        return self.detail(announcement_id, language, user)

    def _reviewable(self, announcement_id: str, language: str, user: AuthUser) -> tuple[dict[str, Any], dict[str, Any]]:
        require_perm(user, language, "review", "review translations")
        orig = self.original(announcement_id)
        t = self._row(announcement_id, language)
        if t is None or t["translation_status"] == "todo":
            raise NotFound("There is no translation draft to review yet.")
        return orig, t

    def approve(self, announcement_id: str, language: str, user: AuthUser, original_verified: bool,
                note: str | None = None) -> dict[str, Any]:
        orig, t = self._reviewable(announcement_id, language, user)
        if orig["publication_status"] != "published":
            raise InvalidState("The original announcement must be approved and published before its translations.")
        if not original_verified:
            raise ValidationFailed("Confirm that you checked this translation against the original announcement.")
        if t["translation_status"] == "human_approved" and not self.view(t, orig)["is_outdated"]:
            raise InvalidState("Translation is already approved.")
        if t.get("is_outdated") or t.get("source_content_hash") != orig["content_hash"]:
            raise InvalidState("The original announcement changed after this translation was written. Update the "
                               "translation against the current original first.", code="translation_outdated")
        t = self.store.update("announcement_translations", dict(
            translation_status="human_approved", reviewed_by=user.id, reviewed_at=now(), original_verified_by=user.id,
            original_verified_at=now(), review_note=note), {"id": t["id"]})[0]
        self._revision(t, "approve", user, note)
        self._audit("translation.approve", announcement_id, user, language=language, original_verified=True)
        self.notes.notify(t.get("last_edited_by") if t.get("last_edited_by") != user.id else None, "translation_approved",
                          f"Your {LANG_NAMES[language]} translation was approved and published",
                          entity_type="announcement", entity_id=announcement_id,
                          link=f"/admin/translations/{announcement_id}/{language}")
        return self.detail(announcement_id, language, user)

    def reject(self, announcement_id: str, language: str, user: AuthUser, reason: str) -> dict[str, Any]:
        _orig, t = self._reviewable(announcement_id, language, user)
        t = self.store.update("announcement_translations", dict(translation_status="rejected", review_note=reason,
                                                                reviewed_by=user.id, reviewed_at=now()), {"id": t["id"]})[0]
        self._revision(t, "reject", user, reason)
        self._audit("translation.reject", announcement_id, user, language=language)
        self.notes.notify(t.get("last_edited_by"), "translation_rejected", f"{LANG_NAMES[language]} translation rejected",
                          body=reason[:300], entity_type="announcement", entity_id=announcement_id,
                          link=f"/admin/translations/{announcement_id}/{language}")
        return self.detail(announcement_id, language, user)

    def request_changes(self, announcement_id: str, language: str, user: AuthUser, note: str) -> dict[str, Any]:
        _orig, t = self._reviewable(announcement_id, language, user)
        t = self.store.update("announcement_translations", dict(translation_status="changes_requested", review_note=note,
                                                                reviewed_by=None, reviewed_at=None), {"id": t["id"]})[0]
        self._revision(t, "request_changes", user, note)
        self._audit("translation.request_changes", announcement_id, user, language=language)
        self.notes.notify(t.get("last_edited_by"), "translation_changes_requested",
                          f"Changes requested on the {LANG_NAMES[language]} translation", body=note[:300],
                          entity_type="announcement", entity_id=announcement_id,
                          link=f"/admin/translations/{announcement_id}/{language}")
        return self.detail(announcement_id, language, user)

    def share_text(self, announcement_id: str, language: str, user: AuthUser) -> dict[str, Any]:
        """Formatted approved translation to paste into the language's KakaoTalk group."""
        if not self.permissions(user, language)["can_edit"] and not has_perm(user, language, "review"):
            raise Forbidden(f"You are not assigned to {LANG_NAMES.get(language, language)} translations.")
        orig = self.original(announcement_id)
        t = self._row(announcement_id, language)
        if t is None or not self.view(t, orig)["published"]:
            raise InvalidState("Only approved, up-to-date translations of published announcements can be shared.")
        lines = [t["title"], "", t["body"].strip()]
        if orig.get("deadline"):
            lines += ["", f"Deadline / 마감: {orig['deadline']}"]
        lines += ["", f"Original (Korean): /announcements/{announcement_id}"]
        self._audit("translation.copy_for_kakaotalk", announcement_id, user, language=language)
        return dict(text="\n".join(lines), language=language, announcement_id=announcement_id)

    # ------------------------------------------------------------------- hooks
    def on_original_published(self, announcement_id: str, actor: AuthUser | None) -> int:
        """Create translation tasks for every other language and notify that language's team."""
        orig = self.original(announcement_id)
        created = 0
        for lang in TARGETS:
            if lang == orig["language"]:
                continue
            if self._row(announcement_id, lang) is None:
                self.store.insert("announcement_translations", dict(announcement_id=announcement_id, language_code=lang,
                                                                    title="", body="", translation_status="todo"))
                created += 1
                self.notes.notify_many(self._people(lang, "any"), "translation_task",
                                       f"New {LANG_NAMES[lang]} translation task: {orig['title'][:120]}",
                                       entity_type="announcement", entity_id=announcement_id,
                                       link=f"/admin/translations/{announcement_id}/{lang}")
        self.mark_outdated(announcement_id, actor)
        return created

    def mark_outdated(self, announcement_id: str, actor: AuthUser | None) -> int:
        orig = self.original(announcement_id)
        rows, _ = self.store.select("announcement_translations", Query(eq={"announcement_id": announcement_id}))
        n = 0
        for t in rows:
            if t["translation_status"] == "todo" or t.get("is_outdated"):
                continue
            if t.get("source_content_hash") and t["source_content_hash"] != orig["content_hash"]:
                t = self.store.update("announcement_translations", {"is_outdated": True}, {"id": t["id"]})[0]
                self._revision(t, "outdated", actor, "The original announcement changed.")
                n += 1
                self.notes.notify_many(self._people(t["language_code"], "any"), "translation_outdated",
                                       f"Original changed: re-review the {LANG_NAMES[t['language_code']]} translation of "
                                       f"'{orig['title'][:100]}'", entity_type="announcement", entity_id=announcement_id,
                                       link=f"/admin/translations/{announcement_id}/{t['language_code']}")
        if n:
            self._audit("translation.outdated", announcement_id, actor, count=n)
        return n
