"""The SQL given to people who run it on production: exactly one SELECT, nothing that writes, locks or calls functions of ours."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

CHECKS = sorted((Path(__file__).resolve().parents[2] / "supabase" / "checks").glob("*.sql"))


def code(path: Path) -> str:
    return re.sub(r"'(?:[^']|'')*'", "''", re.sub(r"--.*", "", path.read_text())).strip().lower()


def test_there_are_checks():
    assert [p.name for p in CHECKS] == ["attachments_to_review.sql", "titles_to_review.sql"]


@pytest.mark.parametrize("path", CHECKS, ids=lambda p: p.name)
def test_one_select_and_nothing_else(path):
    sql = code(path)
    assert sql.startswith("select ") and sql.count(";") == 1 and sql.endswith(";")
    for word in ("insert", "update", "delete", "truncate", "alter", "drop", "create", "grant", "revoke", "merge", "copy", "call", "do",
                 "lock", "into", "for share", "for no key", "vacuum", "set", "begin", "commit", "execute", "notify", "nextval",
                 "dblink"):
        assert not re.search(rf"\b{re.escape(word)}\b", sql), word
    assert "pg_" not in sql
    functions = set(re.findall(r"\b([a-z_]+)\s*\(", sql)) - {"and", "or", "from", "not", "exists", "select", "in", "where", "on", "case"}
    assert functions <= {"regexp_replace", "split_part", "string_agg", "jsonb_array_elements", "coalesce", "nullif"}, functions
