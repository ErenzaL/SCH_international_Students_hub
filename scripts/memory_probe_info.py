"""Info file for the Render memory probe (backend/app/memory_probe.py), read by scripts/staging_memory_check.py.

    python3 scripts/memory_probe_info.py --api https://sch-hub-staging-probe.onrender.com --out ~/sch-probe.json
    python3 scripts/memory_probe_info.py --api http://127.0.0.1:8191 --out /tmp/probe.json        # a local probe

Asks for PROBE_KEY and PROBE_JWT_SECRET (or reads them from the environment) and writes, mode 600: the address, the probe key and a
sign-in token of the probe's made-up super_admin, valid for 8 hours. Refuses the production addresses. Nothing is sent anywhere.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import time
from pathlib import Path
from urllib.parse import urlparse

import jwt

PRODUCTION = ("sch-hub-api.onrender.com", "sch-international-students-hub.onrender.com")
ADMIN_ID = "00000000-0000-4000-8000-00000000a001"          # app/memory_probe.py
ADMIN_EMAIL = "probe-admin@memory-probe.example.com"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--hours", type=int, default=8)
    a = ap.parse_args()
    api = a.api.rstrip("/")
    host = urlparse(api).hostname or ""
    if host in PRODUCTION or not (api.startswith("http://127.0.0.1:") or (api.startswith("https://") and "staging" in host)):
        raise SystemExit("REFUSED: a local probe (http://127.0.0.1:…) or a hosted one whose address contains 'staging' only")
    key = os.environ.get("PROBE_KEY") or getpass.getpass("PROBE_KEY: ")
    secret = os.environ.get("PROBE_JWT_SECRET") or getpass.getpass("PROBE_JWT_SECRET: ")
    token = jwt.encode({"sub": ADMIN_ID, "aud": "authenticated", "role": "authenticated", "email": ADMIN_EMAIL,
                        "exp": int(time.time()) + a.hours * 3600}, secret, algorithm="HS256")
    data = dict(staging=True, probe=True, api=api, probe_key=key, tokens=dict(super_admin=token), users=dict(super_admin=ADMIN_ID))
    fd = os.open(a.out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
    print(f"written {a.out} (mode 600; the token is valid for {a.hours} hours)")


if __name__ == "__main__":
    main()
