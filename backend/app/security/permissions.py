"""Language-scoped permissions (mirrors public.has_language_permission / can_view_ticket_content in SQL).

* ``support``  - may see the language's waiting queue (metadata only) and be assigned tickets
* ``review``   - may approve / reject translations into the language
* ``lead``     - language team lead (language-scoped admin): triage, (re)assign, read tickets of that language
* super_admin  - all languages. A plain ``admin`` has NO support/translation access without an assignment.
Queue visibility never implies access to private ticket content.
"""
from __future__ import annotations

from typing import Any

from app.core.errors import Forbidden
from app.security.auth import AuthUser

STAFF = ("supporter", "admin", "super_admin")


def has_perm(user: AuthUser, lang: str, perm: str) -> bool:
    if user.role == "super_admin":
        return True
    if user.role not in ("supporter", "admin"):
        return False
    p = user.perms.get(lang) or {}
    return bool(p.get(perm)) if perm != "any" else bool(p)


def languages_with(user: AuthUser, perm: str) -> list[str]:
    if user.role == "super_admin":
        return ["ko", "en", "id", "vi", "zh-CN"]
    return sorted(lang for lang in user.perms if has_perm(user, lang, perm))


def require_perm(user: AuthUser, lang: str, perm: str, what: str) -> None:
    if not has_perm(user, lang, perm):
        raise Forbidden(f"You are not authorized to {what} for language '{lang}'.")


def can_view_ticket_content(user: AuthUser, ticket: dict[str, Any]) -> bool:
    if ticket["student_id"] == user.id:
        return True
    if ticket.get("assigned_to") == user.id and user.role in STAFF:
        return True
    return has_perm(user, ticket["language"], "lead")
