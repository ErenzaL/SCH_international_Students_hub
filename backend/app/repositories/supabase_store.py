"""Supabase implementation of the Store (PostgREST + RPC with the service-role key).

The service-role key bypasses RLS, so authorization is enforced *before* any call
here (JWT verification + role checks in app.security.auth) and again inside the
SECURITY DEFINER SQL functions (assert_admin_actor).
"""
from __future__ import annotations

import logging
import re
from typing import Any

from postgrest.exceptions import APIError
from supabase import Client, ClientOptions, create_client

from app.core.config import Settings
from app.core.errors import (
    AppError,
    Conflict,
    DuplicateError,
    Forbidden,
    InvalidState,
    NotFound,
    UpstreamError,
    ValidationFailed,
)
from app.repositories.base import FileStorage, Query, Row

log = logging.getLogger("app.store")
_SAFE = re.compile(r"[,()*%\\]")


def translate_db_error(exc: APIError) -> Exception:
    """Map PostgREST/PostgreSQL errors to API errors without leaking SQL internals."""
    code = getattr(exc, "code", None) or ""
    message = getattr(exc, "message", None) or str(exc)
    if code == "23505":
        return DuplicateError(message)
    if code == "42501":
        return Forbidden("Not permitted by database policy.")
    if code == "P0002":
        return NotFound(message)
    if code == "55000":
        text = message.split(":", 1)
        if message.startswith("not_indexed"):
            return InvalidState(
                "This version has no complete embeddings yet. Run 'Reprocess' first.", code="not_indexed"
            )
        return InvalidState(text[1].strip() if len(text) > 1 else message)
    if code == "22P02" and "uuid" in message.lower():
        return NotFound("Not found.")
    if code in ("22023", "23514", "23502", "23503", "22P02"):
        return ValidationFailed(message)
    if code == "23000":
        return Conflict(message)
    log.error("database error code=%s message=%s", code, message)
    return UpstreamError("The database request failed.", details={"db_code": code})


class SupabaseStore:
    def __init__(self, settings: Settings):
        self.client: Client = create_client(
            settings.supabase_url,
            settings.supabase_service_role_key,
            options=ClientOptions(postgrest_client_timeout=30, storage_client_timeout=60),
        )

    # ---- helpers ---------------------------------------------------------
    def _apply(self, q: Any, query: Query) -> Any:
        for col, val in query.eq.items():
            q = q.eq(col, val)
        for col, val in query.neq.items():
            q = q.neq(col, val)
        for col, vals in query.in_.items():
            q = q.in_(col, list(vals))
        for col, val in query.gte.items():
            q = q.gte(col, val)
        for col, val in query.lte.items():
            q = q.lte(col, val)
        for col, val in query.gt.items():
            q = q.gt(col, val)
        for col, val in query.lt.items():
            q = q.lt(col, val)
        for col, is_null in query.is_null.items():
            q = q.is_(col, "null") if is_null else q.not_.is_(col, "null")
        if query.or_ilike:
            q = q.or_(",".join(f"{c}.ilike.*{_SAFE.sub(' ', t)}*" for c, t in query.or_ilike))
        if query.or_eq:
            q = q.or_(",".join(f"{c}.eq.{_SAFE.sub(' ', str(v))}" for c, v in query.or_eq))
        for col, desc in query.order:
            q = q.order(col, desc=desc)
        return q

    def _run(self, fn):  # type: ignore[no-untyped-def]
        try:
            return fn()
        except APIError as exc:
            raise translate_db_error(exc) from exc
        except AppError:
            raise
        except Exception as exc:  # network errors etc.
            log.error("supabase request failed: %s", type(exc).__name__)
            raise UpstreamError("Could not reach the database.") from exc

    # ---- primitives ------------------------------------------------------
    def select(self, table: str, query: Query | None = None, *, count: bool = False):  # type: ignore[no-untyped-def]
        query = query or Query()

        def go():  # type: ignore[no-untyped-def]
            q = self.client.table(table).select(query.cols or "*", count="exact" if count else None)
            q = self._apply(q, query)
            if query.limit is not None:
                q = q.range(query.offset, query.offset + query.limit - 1)
            elif query.offset:
                q = q.range(query.offset, query.offset + 999)
            return q.execute()

        res = self._run(go)
        return list(res.data or []), (res.count if count else None)

    def insert(self, table: str, row: Row) -> Row:
        res = self._run(lambda: self.client.table(table).insert(row).execute())
        return res.data[0]

    def insert_many(self, table: str, rows: list[Row]) -> list[Row]:
        if not rows:
            return []
        out: list[Row] = []
        for i in range(0, len(rows), 50):  # keep request bodies modest (embeddings are large)
            batch = rows[i : i + 50]
            res = self._run(lambda b=batch: self.client.table(table).insert(b).execute())
            out.extend(res.data or [])
        return out

    def update(self, table: str, patch: Row, eq: dict[str, Any]) -> list[Row]:
        def go():  # type: ignore[no-untyped-def]
            q = self.client.table(table).update(patch)
            for col, val in eq.items():
                q = q.eq(col, val)
            return q.execute()

        return list(self._run(go).data or [])

    def delete(self, table: str, eq: dict[str, Any]) -> None:
        def go():  # type: ignore[no-untyped-def]
            q = self.client.table(table).delete()
            for col, val in eq.items():
                q = q.eq(col, val)
            return q.execute()

        self._run(go)

    def rpc(self, name: str, params: dict[str, Any]) -> Any:
        return self._run(lambda: self.client.rpc(name, params).execute()).data


class SupabaseFileStorage(FileStorage):
    """Private bucket access. Objects are never exposed through public URLs."""

    def __init__(self, store: SupabaseStore, bucket: str):
        self._bucket = store.client.storage.from_(bucket)

    def upload(self, path: str, data: bytes, content_type: str) -> None:
        try:
            self._bucket.upload(path, data, {"content-type": content_type, "upsert": "true"})
        except Exception as exc:  # noqa: BLE001
            log.error("storage upload failed: %s", type(exc).__name__)
            raise UpstreamError("Could not store the uploaded file in private storage.") from exc

    def download(self, path: str) -> bytes:
        try:
            return self._bucket.download(path)
        except Exception as exc:  # noqa: BLE001
            log.error("storage download failed: %s", type(exc).__name__)
            raise UpstreamError("Could not read the stored file from private storage.") from exc

    def remove(self, path: str) -> None:
        try:
            self._bucket.remove([path])
        except Exception as exc:  # noqa: BLE001
            log.error("storage remove failed: %s", type(exc).__name__)
            raise UpstreamError("Could not remove the stored file.") from exc
