"""Command-line entrypoints for scheduled work (Render Cron Job / GitHub Actions / local cron).

    python -m app.cli run-due      # fetch website sources whose daily/weekly sync is due
    python -m app.cli recover      # mark jobs left 'running' by a dead process as failed
    python -m app.cli prefetch-model     # download the embedding model at build time (no DB needed)
    python -m app.cli reindex-approved   # re-embed approved current versions after an embedding-model change
    python -m app.cli purge-expired      # delete AI conversations / resolved tickets past the retention period

Free web services sleep, so scheduled syncs are NOT run by the API process; trigger this from an external
scheduler instead. New content still lands in 'pending_review' (never auto-published).
"""
from __future__ import annotations

import argparse
import logging
import sys

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.repositories.supabase_store import SupabaseFileStorage, SupabaseStore
from app.services.container import build_services
from app.services.embeddings.factory import build_embedding_provider
from app.services.llm.base import build_llm_provider

log = logging.getLogger("app.cli")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli")
    parser.add_argument("command", choices=["run-due", "recover", "prefetch-model", "reindex-approved", "purge-expired"])
    args = parser.parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level)
    if args.command == "prefetch-model":
        emb = build_embedding_provider(settings)
        if hasattr(emb, "download"):
            paths = emb.download()
            print(f"cached {emb.model_id}: {', '.join(paths)}")
        else:
            print(f"{emb.model_id}: nothing to prefetch")
        return 0
    if not settings.supabase_configured:
        print("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are not set; nothing to do.", file=sys.stderr)
        return 2
    store = SupabaseStore(settings)
    svc = build_services(settings, store, SupabaseFileStorage(store, settings.source_files_bucket),
                         build_embedding_provider(settings), build_llm_provider(settings.llm_provider, settings.llm_api_key,
                                                                       settings.llm_model, settings.llm_effort, settings.llm_timeout_seconds))
    if args.command == "purge-expired":
        print(f"purged: {svc.support.purge_expired()}")
        return 0
    if args.command == "reindex-approved":
        from app.repositories.base import Query

        docs, _ = store.select("source_documents", Query(is_null={"current_version_id": False}, cols="id,current_version_id"))
        n = 0
        for d in docs:
            stats = svc.indexer.index_version(d["current_version_id"])
            n += 1
            print(f"- {d['current_version_id']}: {stats['embedded_chunks']}/{stats['chunk_count']} chunks with {stats['embedding_model']}"
                  + (f" ERROR {stats['embedding_error']}" if stats["embedding_error"] else ""))
        print(f"re-indexed {n} approved version(s)")
        return 0
    if args.command == "recover":
        print(f"recovered {svc.ingestion.recover_interrupted_jobs()} interrupted job(s)")
        return 0
    due = svc.ingestion.due_sources()
    print(f"{len(due)} source(s) due")
    failed = 0
    for source in due:
        job = svc.ingestion.create_job(source, "schedule", None)
        done = svc.ingestion.run_job(job["id"])
        print(f"- {source['title']}: {done['status']} {done.get('outcome') or done.get('error_code') or ''}")
        failed += done["status"] == "failed"
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
