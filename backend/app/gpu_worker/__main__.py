"""python -m app.gpu_worker [--check | --once | --drain]   (default: run until stopped)"""
from __future__ import annotations

import argparse
import fcntl
import logging
import signal
import sys

from app.gpu_worker.config import Config, ConfigError, read_token
from app.gpu_worker.hub import CredentialRejected
from app.gpu_worker.runner import EXIT_CONFIG, EXIT_CREDENTIAL, EXIT_OK, Worker
from app.services.llm.ollama import OllamaProvider

log = logging.getLogger("gpu_worker")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="app.gpu_worker")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true", help="check configuration, token file and Ollama; contact nothing else")
    g.add_argument("--once", action="store_true", help="run at most one job")
    g.add_argument("--drain", action="store_true", help="run until the queue is empty")
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
    try:
        c = Config.from_env()
        read_token(c.token_file)
        # one request at a time
        llm = OllamaProvider(c.model, base_url=c.ollama_url, num_ctx=c.num_ctx, max_concurrency=1, max_attempts=2,
                             request_timeout=c.model_timeout, job_timeout=c.model_timeout, deadline=c.model_timeout * 2)
    except (ConfigError, ValueError) as exc:
        print(f"configuration: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    w = Worker(c, llm)
    if a.check:
        ok = w.model_ready()
        free = w.free_vram_mb()
        gpu = "unknown" if free is None else f"{free}MiB free (need {c.min_free_vram_mb})"
        gpu += ", ready" if w.gpu_ready() else ", BUSY (no job would be taken now)"
        print(f"hub={c.hub_url} model={c.model} token_file=ok ollama={'ok' if ok else 'NOT READY'} gpu={gpu}")
        llm.close()
        return EXIT_OK if ok else 1
    c.lock_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = open(c.lock_file, "w")  # noqa: SIM115 - held until the process ends
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("Another GPU worker is already running for this account.", file=sys.stderr)
        return EXIT_CONFIG
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: w.request_stop())
    try:
        return w.run("once" if a.once else "drain" if a.drain else "service")
    except CredentialRejected:
        log.error("the credential was rejected (revoked, rotated or expired); stopping")
        return EXIT_CREDENTIAL
    except ConfigError as exc:
        log.error("configuration: %s", exc)
        return EXIT_CONFIG
    finally:
        llm.close()
        w.hub.close()


if __name__ == "__main__":
    raise SystemExit(main())
