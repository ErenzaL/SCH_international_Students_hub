"""Read large JSONL intermediates whether they are stored plain (local working copy) or gzip-compressed (committed).

The repository keeps files above ~5 MB only as ``<name>.jsonl.gz`` (see research/README.md, "Large files");
scripts keep writing plain ``.jsonl``. A plain local file takes precedence over the compressed copy.
"""
from __future__ import annotations

import gzip
from pathlib import Path
from typing import IO


def resolve(path: Path) -> Path:
    path = Path(path)
    if path.exists():
        return path
    gz = path.with_name(path.name + ".gz")
    if gz.exists():
        return gz
    raise FileNotFoundError(f"{path} (or {gz.name})")


def open_jsonl(path: Path) -> IO[str]:
    p = resolve(path)
    return gzip.open(p, "rt", encoding="utf-8") if p.suffix == ".gz" else p.open(encoding="utf-8")
