"""Command-line entrypoints for scheduled work (Render Cron Job / GitHub Actions / local cron).

    python -m app.cli run-due      # fetch website sources whose daily/weekly sync is due
    python -m app.cli recover      # mark jobs left 'running' by a dead process as failed

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
    parser.add_argument("command", choices=["run-due", "recover"])
    args = parser.parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level)
    if not settings.supabase_configured:
        print("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are not set; nothing to do.", file=sys.stderr)
        return 2
    store = SupabaseStore(settings)
    svc = build_services(settings, store, SupabaseFileStorage(store, settings.source_files_bucket),
                         build_embedding_provider(settings), build_llm_provider(settings.llm_provider, settings.llm_api_key))
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
