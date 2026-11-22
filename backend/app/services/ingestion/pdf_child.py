"""Child process for PDF text extraction (see ``pdf_isolation``). Never import this from the web process.

Protocol on stdout, one line per message:  ``P <done> <total>`` progress · ``R <json>`` result · ``E <json>`` error.
Nothing from the document is written to stderr or logs.
"""
from __future__ import annotations

import json
import os
import sys


def _be_the_first_to_go(memory_limit_mb: int) -> None:
    """Make the kernel's OOM killer pick this child before the API process, and optionally cap its memory."""
    try:
        with open("/proc/self/oom_score_adj", "w") as fh:   # Linux (Render); raising it needs no privileges
            fh.write("1000")
    except OSError:
        pass
    try:
        os.nice(5)   # leave CPU to the API on a 0.1 CPU instance
    except OSError:
        pass
    if memory_limit_mb > 0:
        try:
            import resource

            limit = memory_limit_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
        except (ImportError, ValueError, OSError):
            pass


def main() -> int:
    path, opts = sys.argv[1], json.loads(sys.argv[2])
    _be_the_first_to_go(int(opts.get("memory_limit_mb") or 0))
    from app.services.ingestion.errors import ExtractionError
    from app.services.ingestion.extractors_files import extract_pdf

    def emit(kind: str, payload: str) -> None:
        sys.stdout.write(f"{kind} {payload}\n")
        sys.stdout.flush()

    try:
        with open(path, "rb") as fh:
            data = fh.read()
        ex = extract_pdf(data, opts.get("filename") or "document.pdf", table_mode=opts.get("table_mode", "off"),
                         max_table_items=int(opts.get("max_table_items") or 1500),
                         max_pages=int(opts.get("max_pages") or 0) or None,
                         on_page=lambda done, total: emit("P", f"{done} {total}"))
    except ExtractionError as exc:
        emit("E", json.dumps({"code": exc.code, "message": exc.message}))
        return 0
    except MemoryError:
        emit("E", json.dumps({"code": "extraction_out_of_memory",
                              "message": "The PDF needs more memory than the extraction limit allows."}))
        return 0
    emit("R", json.dumps({
        "title": ex.title, "text": ex.text, "language": ex.language, "metadata": ex.metadata,
        "source_published_at": ex.source_published_at.isoformat() if ex.source_published_at else None,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
