"""Command-line entrypoints for scheduled work (Render Cron Job / GitHub Actions / local cron).

    python -m app.cli run-due      # fetch website sources whose daily/weekly sync is due
    python -m app.cli recover      # mark jobs left 'running' by a dead process as failed
    python -m app.cli prefetch-model     # download the embedding model at build time (no DB needed)
    python -m app.cli reindex-approved   # re-embed approved current versions after an embedding-model change
    python -m app.cli purge-expired      # delete AI conversations / resolved tickets past the retention period
    python -m app.cli check-llm          # verify the configured LLM models exist for this API key (no DB needed)
    python -m app.cli check-llm --generate   # ... and run one tiny generation per model (uses a few tokens)
    python -m app.cli check-rag          # is every published document searchable? (read-only report)
    python -m app.cli check-rag --notify # ... and alert admins about documents that are not (also part of run-due)
    python -m app.cli reextract <version_id>          # DRY RUN: re-extract the stored original, compare, write nothing
    python -m app.cli reextract <version_id> --apply  # ... and create a new 'pending_review' version (live one unchanged)
    python -m app.cli translate-backfill              # DRY RUN: what needs machine translation + estimated usage
    python -m app.cli translate-backfill --apply --limit 10   # queue at most 10 jobs (the API worker runs them)

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
from app.services.llm.base import build_llm_from_settings

log = logging.getLogger("app.cli")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli")
    parser.add_argument("command", choices=["run-due", "recover", "prefetch-model", "reindex-approved", "purge-expired",
                                            "check-llm", "check-rag", "reextract", "translate-backfill"])
    parser.add_argument("version_id", nargs="?", help="reextract: the version whose stored original is re-extracted")
    parser.add_argument("--apply", action="store_true", help="reextract: create the new pending version (default: dry run)")
    parser.add_argument("--generate", action="store_true", help="check-llm: also run one tiny generation per model")
    parser.add_argument("--list", action="store_true", help="check-llm: list every Gemini model this key can use")
    parser.add_argument("--notify", action="store_true", help="check-rag: store admin alerts for unsearchable documents")
    parser.add_argument("--limit", type=int, default=10, help="translate-backfill --apply: jobs to queue (default 10)")
    parser.add_argument("--languages", default="", help="translate-backfill: e.g. ko,en (default AUTO_TRANSLATE_LANGUAGES)")
    parser.add_argument("--json", action="store_true", help="translate-backfill: print the full plan as JSON")
    args = parser.parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level)
    if args.command == "check-llm":
        return check_llm(settings, generate=args.generate, list_models=args.list)
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
                         build_embedding_provider(settings), build_llm_from_settings(settings))
    if args.command == "purge-expired":
        print(f"purged: {svc.support.purge_expired() | {'agent_tasks': svc.agents.purge_expired()}}")
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
    if args.command == "check-rag":
        return check_rag(svc, notify=args.notify)
    if args.command == "reextract":
        if not args.version_id:
            parser.error("reextract needs a version_id")
        return reextract(svc, args.version_id, apply=args.apply)
    if args.command == "translate-backfill":
        langs = [x.strip() for x in args.languages.split(",") if x.strip()] or None
        return translate_backfill(svc, apply=args.apply, limit=args.limit, languages=langs, as_json=args.json)
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
    # scheduled agents: queued for the API worker; does nothing unless AGENT_SCHEDULES_ENABLED and an admin enabled one
    print(f"agent schedules: {svc.agents.run_due_schedules()}")
    try:   # the scheduled run also verifies that every published document is still searchable (alerts, no changes)
        check_rag(svc, notify=True)
    except Exception:  # noqa: BLE001 - a failed check must not fail the sync run
        log.exception("searchability check failed")
    return 1 if failed else 0


def reextract_preview(svc, version_id: str) -> dict:  # type: ignore[no-untyped-def,type-arg]
    """Re-extract a version's stored original with the CURRENT extractor and compare it with the stored text.

    Read-only (``IngestionService.reextraction_preview``): downloads the original from private storage, extracts and
    chunks it in memory, writes nothing."""
    from app.core.errors import AppError

    try:
        return svc.ingestion.reextraction_preview(version_id)  # type: ignore[no-any-return]
    except AppError as exc:
        raise SystemExit(exc.message) from exc


def reextract(svc, version_id: str, *, apply: bool) -> int:  # type: ignore[no-untyped-def]
    import json

    preview = reextract_preview(svc, version_id)
    print(json.dumps(preview, ensure_ascii=False, indent=1))
    if preview["unchanged"]:
        print("The current extractor produces the stored text; nothing to do.")
        return 0
    if not apply:
        print("DRY RUN: nothing was written. Re-run with --apply to create a new version waiting for review.")
        return 0
    if not preview["can_apply"]:
        print(f"Cannot re-extract now: {preview['blocked_reason']}", file=sys.stderr)
        return 1
    job = svc.ingestion.request_reextraction(version_id, None)
    done = svc.ingestion.run_job(job["id"])
    print(f"job {done['id']}: {done['status']} {done.get('outcome') or done.get('error_code') or ''} "
          f"{(done.get('statistics') or {}).get('chunk_count', '')}")
    return 0 if done["status"] == "succeeded" else 1


def translate_backfill(svc, *, apply: bool, limit: int, languages: list[str] | None,  # type: ignore[no-untyped-def]
                       as_json: bool = False) -> int:
    """Dry run by default: what needs a machine translation and the estimated model usage. --apply queues jobs."""
    import json

    from app.services.translation import backfill

    p = backfill.plan(svc, languages)
    if as_json:
        print(json.dumps(p, ensure_ascii=False, indent=1, default=str))
    else:
        print(f"languages={','.join(p['languages'])} pairs={p['pairs']} (announcements={p['announcements']} "
              f"documents={p['documents']}) already_queued={p['already_queued']}")
        print(f"estimated: requests={p['requests']} input_tokens~{p['input_tokens']} output_tokens~{p['output_tokens']} "
              f"days_at_daily_job_limit={p['days_at_daily_job_limit']}")
        for doc_id, title, chars in p["long_documents_summary_only"]:
            print(f"  long (title + summary only): {title} ({chars} chars) {doc_id}")
        for it in p["too_long_for_automatic"]:
            print(f"  too long for automatic translation: {it['kind']} {it['title']} -> {it['language']}")
    if not apply:
        print("DRY RUN: nothing was queued. Re-run with --apply --limit N to queue N jobs for the API worker.")
        return 0
    if not svc.llm.enabled:
        print("No LLM provider is configured; nothing was queued.", file=sys.stderr)
        return 2
    queued = backfill.apply(svc, limit, languages)
    for q in queued:
        print(f"queued {q['kind']} {q['id']} -> {q['language']} ({q['mode']}) job {q['job_id']}")
    print(f"{len(queued)} job(s) queued; the API worker runs them within the daily translation budget.")
    return 0


def check_rag(svc, *, notify: bool) -> int:  # type: ignore[no-untyped-def]
    """Print the searchability audit; exit 1 when a published document is not (fully) searchable."""
    report = svc.rag_health.audit(notify=notify)
    st = report["statistics"]
    print(f"published={st['published_documents']} searchable={st['searchable_documents']} "
          f"hidden_by_schedule_or_status={st['intentionally_hidden']} problems={st['documents_with_problems']} "
          f"chunks={st['chunks']} embedded={st['embedded_chunks']} searchable_chunks={st['searchable_chunks']} "
          f"model={report['embedding_model']}")
    for r in report["problems"]:
        print(f"- {r.get('document_id')} v{r.get('version_number')} '{(r.get('title') or '')[:60]}': "
              f"{', '.join(r['problems'])} ({r.get('searchable_chunks')}/{r.get('chunks')} searchable)")
    return 1 if report["problems"] else 0


def check_llm(settings, *, generate: bool, list_models: bool = False) -> int:  # type: ignore[no-untyped-def]
    """Validate the configured Gemini models for THIS key (the key is never printed).

    * Models API: does each configured model exist for the key and list ``generateContent``?
    * ``--generate``: one tiny non-streaming AND one tiny streaming call per model, separately, with the same
      configuration production uses (thinking level, output limit) - reports ok / error category / HTTP status /
      Google's (non-secret) message / latency / tokens.
    * ``--list``: every Gemini model this key can call with generateContent."""
    if settings.llm_provider.strip().lower() not in ("gemini", "google"):
        print(f"LLM_PROVIDER={settings.llm_provider!r}: check-llm validates Gemini models only.")
        return 0
    from google import genai
    from google.genai import errors

    try:
        client = genai.Client(api_key=settings.llm_api_key or None)
    except ValueError:
        print("No Gemini API key: set LLM_API_KEY (or GEMINI_API_KEY).", file=sys.stderr)
        return 2
    ok = True
    if list_models:
        try:
            names = []
            for m in client.models.list():
                actions = list(getattr(m, "supported_actions", None) or [])
                if "gemini" in (m.name or "") and "generateContent" in actions:
                    names.append(f"  {m.name.removeprefix('models/'):40} {getattr(m, 'display_name', '') or ''}")
            print(f"models with generateContent for this key ({len(names)}):")
            print("\n".join(sorted(names)) or "  (none)")
        except errors.APIError as exc:
            if "API_KEY_INVALID" in str(exc.details) or "API key not valid" in str(exc.message):
                print("The Gemini API key was rejected (invalid key). Nothing else can be checked.", file=sys.stderr)
            else:
                print(f"listing models failed: {exc.code} {exc.status} {str(exc.message or '')[:200]}", file=sys.stderr)
            return 2
    for role, model in (("primary", settings.gemini_primary_model), ("fallback", settings.gemini_fallback_model)):
        if not model:
            print(f"{role}: (not configured)")
            continue
        try:
            info = client.models.get(model=model)
        except errors.APIError as exc:
            if "API_KEY_INVALID" in str(exc.details) or "API key not valid" in str(exc.message):
                print("The Gemini API key was rejected (invalid key). Nothing else can be checked.", file=sys.stderr)
                return 2
            print(f"{role}: {model} -> NOT AVAILABLE ({exc.code} {exc.status}) {str(exc.message or '')[:200]}")
            ok = False
            continue
        actions = list(getattr(info, "supported_actions", None) or [])
        gen = "generateContent" in actions
        print(f"{role}: {model} -> {getattr(info, 'name', model)} | input_limit={getattr(info, 'input_token_limit', '?')} "
              f"output_limit={getattr(info, 'output_token_limit', '?')} | generateContent={'yes' if gen else 'NO'}")
        ok = ok and gen
    if generate:
        llm = build_llm_from_settings(settings)
        for role, model in (("primary", settings.gemini_primary_model), ("fallback", settings.gemini_fallback_model)):
            if not model:
                continue
            for row in llm.probe(model):  # type: ignore[attr-defined]
                status = "OK" if row.get("ok") else f"FAILED error={row.get('error')} http={row.get('http')} " \
                                                     f"status={row.get('status')} quota={row.get('quota_id')}"
                print(f"  {role} {model} {row['call']:8} {status} latency_ms={row['latency_ms']} "
                      f"served_by={row.get('served_by')} tokens={row.get('total_tokens')}"
                      + (f"\n      detail: {row['detail']}" if row.get("detail") else ""))
                ok = ok and bool(row.get("ok"))
    return 0 if ok else 1

if __name__ == "__main__":
    raise SystemExit(main())
