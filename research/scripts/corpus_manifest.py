"""Corpus manifest from the public snapshot: no full text, only what the analyses need."""
import hashlib
import json
import re
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[2]
# usage: corpus_manifest.py [public_corpus.json] [output.json]   (defaults: corpus_v1 files)
src = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "backend/.eval-cache/public_corpus.json"
dst = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "research/data/corpus_manifest.json"
items = json.loads(src.read_text())
out = []
for d in items:
    text = d.get("content") or ""
    out.append(dict(id=d["id"], title=d["title"], language=d.get("language"), category=d.get("category"),
                    kind=d.get("kind") or "document", chars=len(text),
                    has_source_url=bool((d.get("source_url") or "").strip()),
                    page_markers=len(set(re.findall(r"\[Page (\d+)\]", text))) or None,
                    content_sha256_16=hashlib.sha256(text.encode()).hexdigest()[:16]))
dst.write_text(json.dumps(dict(
    snapshot_sha256_16=hashlib.sha256(src.read_bytes()).hexdigest()[:16], items=out), ensure_ascii=False, indent=1))
print(f"manifest: {len(out)} items")
