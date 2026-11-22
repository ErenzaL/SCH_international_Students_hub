"""Supabase JWT verification + role-based authorization (enforced on the backend).

Verification strategy:
  1. If SUPABASE_JWT_SECRET is set and the token header says HS256 -> verify with the secret.
  2. Otherwise (asymmetric signing keys: ES256/RS256) -> verify with the project's JWKS
     (``{SUPABASE_URL}/auth/v1/.well-known/jwks.json``), cached.
The role is NEVER read from the token; it is loaded from public.profiles for each request.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import jwt
from fastapi import Depends, Request
from jwt import PyJWKClient

from app.core.config import Settings, get_settings
from app.core.errors import Forbidden, NotAuthenticated, SupabaseNotConfigured
from app.repositories.base import Query, Store, get_one

log = logging.getLogger("app.auth")


@dataclass
class AuthUser:
    id: str
    email: str | None
    role: str
    display_name: str | None = None
    preferred_language: str = "en"
    languages: list[str] = field(default_factory=list)
    # per-language team permissions: {"id": {"support": True, "review": False, "lead": False}}
    perms: dict[str, dict[str, bool]] = field(default_factory=dict)
    preferred_language_confirmed: bool = False

    @property
    def is_admin(self) -> bool:
        return self.role in ("super_admin", "admin")

    @property
    def is_staff(self) -> bool:
        return self.role in ("super_admin", "admin", "supporter")


class TokenVerifier:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._jwks: PyJWKClient | None = None
        self._lock = threading.Lock()

    def _jwks_client(self) -> PyJWKClient:
        with self._lock:
            if self._jwks is None:
                if not self.settings.supabase_url:
                    raise SupabaseNotConfigured()
                self._jwks = PyJWKClient(
                    f"{self.settings.supabase_url}/auth/v1/.well-known/jwks.json", cache_keys=True, lifespan=3600
                )
            return self._jwks

    def verify(self, token: str) -> dict[str, Any]:
        s = self.settings
        try:
            header = jwt.get_unverified_header(token)
            alg = header.get("alg", "")
            if alg == "none":
                raise NotAuthenticated("Unsigned tokens are not accepted.", code="invalid_token")
            if alg == "HS256":
                if not s.supabase_jwt_secret:
                    raise NotAuthenticated(
                        "HS256 token received but SUPABASE_JWT_SECRET is not configured.", code="invalid_token"
                    )
                key: Any = s.supabase_jwt_secret
                algorithms = ["HS256"]
            elif alg in ("ES256", "RS256"):
                key = self._jwks_client().get_signing_key_from_jwt(token).key
                algorithms = [alg]
            else:
                raise NotAuthenticated("Unsupported token algorithm.", code="invalid_token")
            claims = jwt.decode(
                token,
                key,
                algorithms=algorithms,
                audience=s.supabase_jwt_audience,
                options={"require": ["exp", "sub"]},
            )
        except NotAuthenticated:
            raise
        except SupabaseNotConfigured:
            raise
        except jwt.ExpiredSignatureError as exc:
            raise NotAuthenticated("Token has expired.", code="invalid_token") from exc
        except (jwt.PyJWTError, Exception) as exc:  # noqa: BLE001 - never leak parser details
            log.info("token rejected: %s", type(exc).__name__)
            raise NotAuthenticated("Invalid authentication token.", code="invalid_token") from exc
        return claims


_verifier: TokenVerifier | None = None
_verifier_key: tuple[str, str] | None = None


def get_verifier(settings: Settings = Depends(get_settings)) -> TokenVerifier:
    global _verifier, _verifier_key
    key = (settings.supabase_url, settings.supabase_jwt_secret)
    if _verifier is None or _verifier_key != key:
        _verifier, _verifier_key = TokenVerifier(settings), key
    return _verifier


def get_store(request: Request) -> Store:
    store = getattr(request.app.state, "store", None)
    if store is None:
        raise SupabaseNotConfigured()
    return store


def _bearer(request: Request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise NotAuthenticated("Missing bearer token.")
    return token.strip()


def get_current_user(
    request: Request,
    store: Store = Depends(get_store),
    verifier: TokenVerifier = Depends(get_verifier),
) -> AuthUser:
    claims = verifier.verify(_bearer(request))
    profile = get_one(store, "profiles", id=claims["sub"])  # role always comes from the DB, never from the token
    if profile is None:
        raise Forbidden("No profile exists for this account.", code="no_profile")
    langs: list[str] = []
    perms: dict[str, dict[str, bool]] = {}
    # language permissions only count while the user holds a staff role (a demotion revokes them at once)
    if profile["role"] in ("supporter", "admin"):
        rows, _ = store.select("supporter_languages", Query(eq={"supporter_id": profile["id"]}))
        for r in rows:
            lead = bool(r.get("is_team_lead", False))
            perms[r["language_code"]] = {"support": bool(r.get("can_support", True)) or lead,
                                         "review": bool(r.get("can_review_translations", False)) or lead, "lead": lead}
        langs = sorted(perms)
    return AuthUser(
        id=profile["id"],
        email=profile.get("email") or claims.get("email"),
        role=profile["role"],
        display_name=profile.get("display_name"),
        preferred_language=profile.get("preferred_language") or "en",
        languages=langs,
        perms=perms,
        preferred_language_confirmed=bool(profile.get("preferred_language_confirmed", False)),
    )


def require_roles(*roles: str):
    allowed = set(roles)

    def dep(user: AuthUser = Depends(get_current_user)) -> AuthUser:
        if user.role not in allowed:
            raise Forbidden(f"This action requires one of the roles: {', '.join(sorted(allowed))}.")
        return user

    return dep


require_admin = require_roles("super_admin", "admin")
require_staff = require_roles("super_admin", "admin", "supporter")
require_super_admin = require_roles("super_admin")

_ = time  # (kept for potential clock injection in tests)
