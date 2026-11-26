"""Prepare a SEPARATE, free Supabase project as staging: schema, seed, made-up accounts, and an info file for the tests.

    export STAGING_REF=abcd... PRODUCTION_REF=wxyz... STAGING_SUPABASE_URL=https://$STAGING_REF.supabase.co
    export STAGING_API=https://sch-hub-api-staging.onrender.com STAGING_WEB=https://sch-hub-web-staging.onrender.com
    python3 scripts/staging_bootstrap.py all --info ~/staging.json      # asks for the database connection string and the keys

Steps: schema (all migrations in order, each in one transaction; they are written to be re-run), seed, users, info, doctor.
Refuses, before any write: a connection string or URL that names PRODUCTION_REF, or does not name STAGING_REF; equal refs; a project
that already holds more than 50 profiles (a real project, not a fresh staging one). Secrets are read from the environment or typed;
they are never printed or written anywhere except the info file (mode 600: passwords and tokens of the MADE-UP staging accounts).
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import secrets
import shlex
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
#: an object each migration creates (the newest it depends on is enough): a migration whose marker exists is not run again
MARKERS = {
    "0001": "to_regclass('public.profiles')", "0002": "to_regclass('public.document_versions')", "0003": "to_regclass('public.announcements')",
    "0004": "to_regproc('public.approve_document_version')", "0005": "(select id from storage.buckets where id = 'source-files')",
    "0006": "(select 1 from information_schema.columns where table_name = 'knowledge_sources' and column_name = 'stale_after_days')",
    "0007": "(select 1 from information_schema.columns where table_name = 'document_versions' and column_name = 'activation_note')",
    "0008": "to_regclass('public.support_tickets')", "0009": "to_regclass('public.document_suppressions')",
    "0010": "(select 1 from information_schema.columns where table_name = 'knowledge_sources' and column_name = 'archived_at')",
    "0011": "to_regclass('public.document_translations')", "0012": "to_regclass('public.ingestion_jobs_active_source_uniq')",
    "0013": "(select 1 from information_schema.columns where table_name = 'announcement_translations' and column_name = 'provider')",
    "0014": "to_regclass('public.agent_tasks')", "0015": "to_regclass('public.discovered_items')", "0016": "to_regclass('public.gpu_workers')",
    "0017": "to_regclass('public.agent_controls')"}
PEOPLE = [("super_admin", "super_admin", None), ("admin", "admin", None), ("supporter_vi", "supporter", "vi"), ("reviewer_id", "supporter", "id"),
          ("student", "student", None), ("student2", "student", None)]


def stop(msg: str) -> None:
    sys.exit(f"REFUSED (nothing was written): {msg}")


def secret(name: str, prompt: str) -> str:
    return os.environ.get(name) or getpass.getpass(prompt)


class Staging:
    def __init__(self, a: argparse.Namespace):
        self.a = a
        self.local = a.local
        self.ref, self.prod = os.environ.get("STAGING_REF", ""), os.environ.get("PRODUCTION_REF", "")
        self.url = os.environ.get("STAGING_SUPABASE_URL", "").rstrip("/")
        self.db = os.environ.get("STAGING_PSQL", "") if self.local else ""

    # ------------------------------------------------------------------ guards
    def guard(self) -> None:
        if self.local:
            if "supabase" in self.db or not os.environ.get("STAGING_PSQL"):
                stop("--local is only for a scratch database (scripts/scratch_db.sh)")
            return
        if not self.ref or not self.prod or self.ref == self.prod:
            stop("set STAGING_REF and PRODUCTION_REF (two different projects)")
        if self.url != f"https://{self.ref}.supabase.co":
            stop("STAGING_SUPABASE_URL is not the project named by STAGING_REF")
        conn = secret("STAGING_DB_URL", "STAGING connection string (Supabase → Connect → Session pooler or direct): ")
        if self.prod in conn or self.ref not in conn:
            stop("the connection string does not belong to the staging project")
        self.db = "psql " + shlex.quote(conn)

    def psql(self, *args: str, check: bool = True) -> str:
        cmd = shlex.split(self.db) + ["-q", "-t", "-A", "-v", "ON_ERROR_STOP=1", *args]
        r = subprocess.run(cmd, capture_output=True, text=True, env=dict(os.environ, PGOPTIONS="-c client_min_messages=warning"))
        if check and r.returncode:
            raise SystemExit(f"psql failed: {r.stderr.strip()[-600:]}")
        return r.stdout.strip()

    def fresh_enough(self) -> None:
        if not self.psql("-c", "select to_regclass('public.profiles')"):
            return
        n = self.psql("-c", "select count(*) from public.profiles")
        if int(n or 0) > 50:
            stop(f"this project already has {n} accounts: it looks like a real project, not a fresh staging one")

    # ------------------------------------------------------------------ steps
    def schema(self) -> None:
        if self.local:
            self.psql("-f", str(ROOT / "scripts/local_supabase_shim.sql"))
        for f in sorted((ROOT / "supabase/migrations").glob("*.sql")):
            number = f.name[10:14]
            marker = MARKERS.get(number)
            if marker is None:
                raise SystemExit(f"{f.name}: no marker known; add one to MARKERS before running")
            if self.psql("-c", f"select coalesce(({marker})::text, '')"):
                print(f"  {f.name}: already applied")
                continue
            t = time.time()
            self.psql("-1", "-f", str(f))
            print(f"  applied {f.name} ({time.time() - t:.1f} s)")

    def seed(self) -> None:
        self.psql("-1", "-f", str(ROOT / "supabase/seed.sql"))
        print("  seed: categories and labelled sample rows")

    def users(self) -> dict[str, str]:
        password = secrets.token_urlsafe(18)
        ids: dict[str, str] = {}
        domain = self.a.email_domain
        key = "" if self.local else secret("STAGING_SERVICE_KEY", "STAGING secret / service_role key: ")
        for name, role, lang in PEOPLE:
            email = f"{name}@{domain}"
            if self.local:
                uid = self.psql("-c", f"select id from auth.users where email = '{email}'") or str(uuid.uuid4())
                self.psql("-c", f"insert into auth.users (id, email) values ('{uid}', '{email}') on conflict do nothing")
            else:
                r = httpx.post(f"{self.url}/auth/v1/admin/users", headers={"apikey": key, "Authorization": f"Bearer {key}"},
                               json=dict(email=email, password=password, email_confirm=True), timeout=30)
                if r.status_code == 422 and "already" in r.text:
                    found = httpx.get(f"{self.url}/auth/v1/admin/users", params={"per_page": 200}, headers={"apikey": key, "Authorization": f"Bearer {key}"}, timeout=30).json()
                    u = next(x for x in found.get("users", []) if x["email"] == email)
                    httpx.put(f"{self.url}/auth/v1/admin/users/{u['id']}", headers={"apikey": key, "Authorization": f"Bearer {key}"}, json=dict(password=password), timeout=30)
                    uid = u["id"]
                elif r.status_code in (200, 201):
                    uid = r.json()["id"]
                else:
                    raise SystemExit(f"creating {email} failed: HTTP {r.status_code}")
            ids[name] = uid
            self.psql("-c", f"update public.profiles set role = '{role}', display_name = '{name}', preferred_language_confirmed = true where id = '{uid}'")
            if lang:
                self.psql("-c", f"insert into public.supporter_languages (supporter_id, language_code, can_support, can_review_translations) values ('{uid}', '{lang}', true, true) "
                                "on conflict do nothing")
        print(f"  {len(ids)} made-up accounts @{domain}, one random password (in the info file only)")
        self.password = password
        return ids

    def info(self, ids: dict[str, str]) -> None:
        tokens: dict[str, str] = {}
        if not self.local:
            anon = secret("STAGING_ANON_KEY", "STAGING publishable / anon key: ")
            for name in ids:
                r = httpx.post(f"{self.url}/auth/v1/token", params={"grant_type": "password"}, headers={"apikey": anon},
                               json=dict(email=f"{name}@{self.a.email_domain}", password=self.password), timeout=30)
                if r.status_code != 200:
                    raise SystemExit(f"sign-in of {name} failed: HTTP {r.status_code}")
                tokens[name] = r.json()["access_token"]
        data = dict(staging=True, api=os.environ.get("STAGING_API", "").rstrip("/"), web=os.environ.get("STAGING_WEB", "").rstrip("/"), auth=self.url,
                    password=self.password, users=ids, tokens=tokens, email_domain=self.a.email_domain, cron=os.environ.get("STAGING_CRON_SECRET", ""),
                    schedules=bool(os.environ.get("STAGING_CRON_SECRET")), production_ref=self.prod, staging_ref=self.ref)
        fd = os.open(self.a.info, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        print(f"  info file {self.a.info} (mode 600). Tokens expire after about an hour: run 'info' again before a test")

    def doctor(self) -> None:
        env = dict(os.environ, SUPABASE_URL=self.url, SUPABASE_SERVICE_ROLE_KEY=secret("STAGING_SERVICE_KEY", "STAGING secret key: "),
                   SUPABASE_ANON_KEY=secret("STAGING_ANON_KEY", "STAGING anon key: "))
        args = ["-m", "app.cli", "doctor"] + (["--api", os.environ["STAGING_API"]] if os.environ.get("STAGING_API") else []) + \
            (["--web", os.environ["STAGING_WEB"]] if os.environ.get("STAGING_WEB") else [])
        subprocess.run([sys.executable, *args], cwd=ROOT / "backend", env=env)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["all", "schema", "seed", "users", "info", "doctor"])
    ap.add_argument("--info", type=Path, default=Path.home() / "sch-staging.json")
    ap.add_argument("--email-domain", default="sch-staging.example.com")
    ap.add_argument("--local", action="store_true", help="a scratch database of scripts/scratch_db.sh (tests of this script)")
    a = ap.parse_args()
    st = Staging(a)
    st.guard()
    st.fresh_enough()
    if a.step in ("all", "schema"):
        st.schema()
    if a.step in ("all", "seed"):
        st.seed()
    if a.step in ("all", "users", "info"):
        st.info(st.users())
    if a.step in ("all", "doctor") and not a.local:
        st.doctor()


if __name__ == "__main__":
    main()
