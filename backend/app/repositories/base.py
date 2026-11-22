"""Data-access contract. Services depend on this Protocol only.

Implementations:
  * SupabaseStore  - real PostgREST/RPC access with the service-role key (production)
  * MemoryStore    - in-process fake used by unit tests and the offline demo script.
                     It is NEVER selected automatically when Supabase is not configured.
"""
from __future__ import annotations

from typing import Any, Protocol

Row = dict[str, Any]


class Query:
    """Filter spec understood by both stores (kept deliberately small)."""

    def __init__(
        self,
        *,
        eq: dict[str, Any] | None = None,
        neq: dict[str, Any] | None = None,
        in_: dict[str, list[Any]] | None = None,
        gte: dict[str, Any] | None = None,
        lte: dict[str, Any] | None = None,
        gt: dict[str, Any] | None = None,
        lt: dict[str, Any] | None = None,
        is_null: dict[str, bool] | None = None,
        or_ilike: list[tuple[str, str]] | None = None,  # (column, text) pairs OR-ed together
        or_eq: list[tuple[str, Any]] | None = None,  # (column, value) pairs OR-ed together
        order: list[tuple[str, bool]] | None = None,  # (column, descending)
        limit: int | None = None,
        offset: int = 0,
        cols: str | None = None,  # PostgREST column list, e.g. 'id,version_id' (avoids fetching embeddings)
    ) -> None:
        self.eq = eq or {}
        self.neq = neq or {}
        self.in_ = in_ or {}
        self.gte = gte or {}
        self.lte = lte or {}
        self.gt = gt or {}
        self.lt = lt or {}
        self.is_null = is_null or {}
        self.or_ilike = or_ilike or []
        self.or_eq = or_eq or []
        self.order = order or []
        self.limit = limit
        self.offset = offset
        self.cols = cols


class Store(Protocol):
    def select(self, table: str, query: Query | None = None, *, count: bool = False) -> tuple[list[Row], int | None]: ...

    def insert(self, table: str, row: Row) -> Row:
        """Raises DuplicateError on unique violations."""
        ...

    def insert_many(self, table: str, rows: list[Row]) -> list[Row]: ...

    def update(self, table: str, patch: Row, eq: dict[str, Any]) -> list[Row]: ...

    def delete(self, table: str, eq: dict[str, Any]) -> None: ...

    def rpc(self, name: str, params: dict[str, Any]) -> Any:
        """Transactional DB functions (approve/reject/rollback/...) and search_knowledge."""
        ...

    # -- convenience wrappers implemented once in helpers below --


class FileStorage(Protocol):
    def upload(self, path: str, data: bytes, content_type: str) -> None: ...

    def download(self, path: str) -> bytes: ...

    def remove(self, path: str) -> None: ...


# --------------------------------------------------------------------------
# Small helpers built on the primitives (shared by services)
# --------------------------------------------------------------------------
def get_one(store: Store, table: str, **eq: Any) -> Row | None:
    rows, _ = store.select(table, Query(eq=eq, limit=1))
    return rows[0] if rows else None


def get_many(store: Store, table: str, ids: list[Any], column: str = "id") -> dict[Any, Row]:
    ids = [i for i in dict.fromkeys(ids) if i is not None]
    if not ids:
        return {}
    rows, _ = store.select(table, Query(in_={column: ids}))
    return {r[column]: r for r in rows}
