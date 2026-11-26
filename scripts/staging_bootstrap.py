"""Prepare a SEPARATE, free Supabase project as staging: schema, seed, made-up accounts, and an info file for the tests.

    export STAGING_REF=abcd... PRODUCTION_REF=wxyz... STAGING_SUPABASE_URL=https://$STAGING_REF.supabase.co
    export STAGING_API=https://sch-hub-api-staging.onrender.com STAGING_WEB=https://sch-hub-web-staging.onrender.com
    python3 scripts/staging_bootstrap.py all --info ~/staging.json      # asks for the database connection string and the keys

Steps: schema (all migrations in order, each in one transaction; they are written to be re-run), seed, users, info, doctor.
Refuses, before any write: equal refs; a URL or connection string that names PRODUCTION_REF or does not name STAGING_REF; an API key
of another project (legacy keys name their project; new sb_ keys are tried once, read-only, against the staging project and must be
accepted there); a secret key in the publishable slot or the reverse; STAGING_API / STAGING_WEB that are production addresses or not
https; an account domain that is not a reserved example domain (example.com/.net/.org, *.example, *.test, *.invalid); a project with
more than 50 profiles or more than 5 accounts outside that domain (a real project, not a fresh staging one).
Only synthetic data is written: the seed's labelled samples and categories, made-up accounts; the seed's candidate official sources
are registered but switched off (nothing on staging fetches a real website unless an administrator enables a source).
Secrets are read from the environment or typed; they are never printed or written anywhere except the info file (mode 600: passwords
and tokens of the MADE-UP staging accounts).
"""
from __future__ import annotations

import argparse
import base64
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
from typing import Any
from urllib.parse import urlparse

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
PRODUCTION_HOSTS = ("sch-hub-api.onrender.com", "sch-international-students-hub.onrender.com")
RESERVED = ("example.com", "example.net", "example.org")
PEOPLE = [("super_admin", "super_admin", None), ("admin", "admin", None), ("supporter_vi", "supporter", "vi"), ("reviewer_id", "supporter", "id"),
          ("student", "student", None), ("student2", "student", None)]


def stop(msg: str) -> None:
    sys.exit(f"REFUSED (nothing was written): {msg}")


def secret(name: str, prompt: str) -> str:
    return os.environ.get(name) or getpass.getpass(prompt)


def reserved_domain(domain: str) -> bool:
    d = domain.lower().strip(".")
    return d in RESERVED or d.endswith(tuple("." + r for r in RESERVED)) or d.endswith((".example", ".test", ".invalid"))


def jwt_claims(key: str) -> dict | None:  # type: ignore[type-arg]
    """Claims of a legacy Supabase key (a JWT naming its project as 'ref'); None for the new sb_... keys."""
    parts = key.split(".")
    if len(parts) != 3:
        return None
    try:
        claims = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
    except (ValueError, json.JSONDecodeError):
        return None
    return claims if isinstance(claims, dict) else None


class Staging:
    def __init__(self, a: argparse.Namespace, http: Any = httpx):
        self.a = a
        self.http = http
        self.service_key = self.anon_key = ""
        self.local = a.local
        self.ref, self.prod = os.environ.get("STAGING_REF", ""), os.environ.get("PRODUCTION_REF", "")
        self.url = os.environ.get("STAGING_SUPABASE_URL", "").rstrip("/")
        self.db = os.environ.get("STAGING_PSQL", "") if self.local else ""

    # ------------------------------------------------------------------ guards
    def guard(self) -> None:
        if not reserved_domain(self.a.email_domain):
            stop(f"--email-domain {self.a.email_domain}: use a reserved example domain, so no made-up account can reach a real mailbox")
        if self.local:
            if "supabase" in self.db or not os.environ.get("STAGING_PSQL"):
                stop("--local is only for a scratch database (scripts/scratch_db.sh)")
            return
        if not self.ref or not self.prod or self.ref == self.prod:
            stop("set STAGING_REF and PRODUCTION_REF (two different projects)")
        if self.url != f"https://{self.ref}.supabase.co":
            stop("STAGING_SUPABASE_URL is not the project named by STAGING_REF")
        for name in ("STAGING_API", "STAGING_WEB"):
            u = os.environ.get(name, "")
            host = urlparse(u).hostname or ""
            if u and (host in PRODUCTION_HOSTS or self.prod in u or not u.startswith("https://")):
                stop(f"{name} must be the https address of a staging service, not production")
        conn = secret("STAGING_DB_URL", "STAGING connection string (Supabase → Connect → Session pooler or direct): ")
        if self.prod in conn or self.ref not in conn:
            stop("the connection string does not belong to the staging project")
        if self.a.step in ("all", "users", "info", "doctor"):
            self.service_key = self.check_key(secret("STAGING_SERVICE_KEY", "STAGING secret / service_role key: "), "secret")
        if self.a.step in ("all", "info", "doctor"):
            self.anon_key = self.check_key(secret("STAGING_ANON_KEY", "STAGING publishable / anon key: "), "publishable")
        self.db = "psql " + shlex.quote(conn)

    def check_key(self, key: str, kind: str) -> str:
        """The key must belong to the staging project. Read-only; nothing is written with it before this passed."""
        key = key.strip()
        if not key:
            stop(f"no {kind} key")
        claims = jwt_claims(key)
        if claims is not None:                                   # legacy JWT key: names its project and role
            if claims.get("ref") == self.prod:
                stop(f"the {kind} key is a PRODUCTION key")
            if claims.get("ref") != self.ref:
                stop(f"the {kind} key belongs to another project")
            if (claims.get("role") == "service_role") != (kind == "secret"):
                stop(f"the {kind} key has role {claims.get('role')!r}")
            return key
        if key.startswith("sb_secret_") != (kind == "secret") or not key.startswith(("sb_secret_", "sb_publishable_")):
            stop(f"that is not a {kind} key")
        headers = {"apikey": key} | ({"Authorization": f"Bearer {key}"} if kind == "secret" else {})
        path = "/auth/v1/admin/users?per_page=1" if kind == "secret" else "/auth/v1/settings"
        try:
            r = self.http.get(self.url + path, headers=headers, timeout=30)
        except httpx.HTTPError as exc:
            stop(f"could not reach the staging project to check the {kind} key: {type(exc).__name__}")
        if r.status_code != 200:
            stop(f"the staging project does not accept this {kind} key (HTTP {r.status_code}): it belongs to another project")
        return key

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
        domain = self.a.email_domain.replace("'", "")
        other = self.psql("-c", f"select count(*) from public.profiles where coalesce(email, '') not like '%@{domain}'", check=False)
        if other.isdigit() and int(other) > 5:
            stop(f"{other} accounts outside @{domain}: real people use this project, so it is not a staging copy")

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
        # the seed registers candidate official sources (real public websites): on staging they stay switched off
        off = self.psql("-c", "with u as (update public.knowledge_sources set is_active = false where coalesce(is_test_data, false) = false "
                              "and is_active returning 1) select count(*) from u")
        print(f"  seed: categories and labelled sample rows; {off or 0} candidate official sources switched off (no fetching on staging)")

    def users(self) -> dict[str, str]:
        password = secrets.token_urlsafe(18)
        ids: dict[str, str] = {}
        domain = self.a.email_domain
        key = self.service_key
        for name, role, lang in PEOPLE:
            email = f"{name}@{domain}"
            if self.local:
                uid = self.psql("-c", f"select id from auth.users where email = '{email}'") or str(uuid.uuid4())
                self.psql("-c", f"insert into auth.users (id, email) values ('{uid}', '{email}') on conflict do nothing")
            else:
                r = self.http.post(f"{self.url}/auth/v1/admin/users", headers={"apikey": key, "Authorization": f"Bearer {key}"},
                               json=dict(email=email, password=password, email_confirm=True), timeout=30)
                if r.status_code == 422 and "already" in r.text:
                    found = self.http.get(f"{self.url}/auth/v1/admin/users", params={"per_page": 200}, headers={"apikey": key, "Authorization": f"Bearer {key}"}, timeout=30).json()
                    u = next(x for x in found.get("users", []) if x["email"] == email)
                    self.http.put(f"{self.url}/auth/v1/admin/users/{u['id']}", headers={"apikey": key, "Authorization": f"Bearer {key}"}, json=dict(password=password), timeout=30)
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
            anon = self.anon_key
            for name in ids:
                r = self.http.post(f"{self.url}/auth/v1/token", params={"grant_type": "password"}, headers={"apikey": anon},
                               json=dict(email=f"{name}@{self.a.email_domain}", password=self.password), timeout=30)
                if r.status_code != 200:
                    raise SystemExit(f"sign-in of {name} failed: HTTP {r.status_code}")
                tokens[name] = r.json()["access_token"]
        data = dict(staging=True, api=os.environ.get("STAGING_API", "").rstrip("/"), web=os.environ.get("STAGING_WEB", "").rstrip("/"), auth=self.url,
                    password=self.password, users=ids, tokens=tokens, email_domain=self.a.email_domain, cron=os.environ.get("STAGING_CRON_SECRET", ""),
                    schedules=bool(os.environ.get("STAGING_CRON_SECRET")), production_ref=self.prod, staging_ref=self.ref,
                    # the publishable key is public by design (the web build contains it); with the password it lets long tests sign in again
                    anon_key=self.anon_key)
        fd = os.open(self.a.info, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        print(f"  info file {self.a.info} (mode 600). Tokens expire after about an hour: run 'info' again before a test")

    def doctor(self) -> None:
        env = dict(os.environ, SUPABASE_URL=self.url, SUPABASE_SERVICE_ROLE_KEY=self.service_key, SUPABASE_ANON_KEY=self.anon_key)
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
