"""Configuration check:  python -m app.cli doctor [--api https://...] [--web https://...] [--json]

READ-ONLY. Only GET requests; nothing is created, changed, generated or queued, also not in a test way. Values of secrets are
never printed: only "set", "not set" and, where it matters, the kind. Reads the same environment / .env as the API.

PASS | FAIL | WARNING | NOT TESTED | REQUIRES OWNER ACTION
"""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.core.config import Settings

PASS, FAIL, WARN, SKIP, OWNER = "PASS", "FAIL", "WARNING", "NOT TESTED", "REQUIRES OWNER ACTION"
ROOT = Path(__file__).resolve().parents[2]
# migration -> (table, column) that only exists after it
MIGRATIONS = [("0001", "profiles", "role"), ("0002", "document_chunks", "embedding"), ("0003", "announcements", "publication_status"),
              ("0006", "ingestion_events", "step"), ("0007", "admin_notifications", "kind"), ("0008", "support_tickets", "ticket_number"),
              ("0009", "document_suppressions", "reason"), ("0010", "knowledge_sources", "archived_at"),
              ("0011", "document_translations", "human_edited"), ("0013", "announcement_translations", "provider"),
              ("0014", "agent_tasks", "idempotency_key"), ("0015", "discovered_items", "opportunity_kind"),
              ("0016", "gpu_workers", "token_hash"), ("0017", "agent_controls", "paused")]
REQUIRED_UP_TO = "0015"
FUNCTIONS = ("search_knowledge_v2", "claim_ingestion_job", "claim_agent_task", "replace_version_chunks", "rollback_document_version")
#: a browser with the public key must never get a row from these
PRIVATE = ("profiles", "agent_tasks", "agent_task_events", "agent_schedules", "discovery_sources", "discovered_items", "gpu_workers",
           "agent_controls", "ingestion_jobs", "ingestion_events", "audit_log", "support_tickets", "support_ticket_messages",
           "support_ticket_assignments", "ai_conversations", "ai_messages", "user_notifications", "admin_notifications",
           "supporter_languages", "translation_revisions", "document_translation_revisions", "allowed_source_domains")
LANGS = ("ko", "en", "id", "vi", "zh-CN")


@dataclass
class Check:
    area: str
    name: str
    state: str
    detail: str = ""
    fix: str = ""


class Doctor:
    def __init__(self, settings: Settings, *, api: str | None = None, web: str | None = None, env: dict[str, str] | None = None,
                 http: httpx.Client | None = None):
        self.s = settings
        self.api, self.web = (api or "").rstrip("/"), (web or "").rstrip("/")
        self.env = dict(os.environ if env is None else env)
        self.http = http or httpx.Client(timeout=60, trust_env=False, follow_redirects=False)
        self.out: list[Check] = []
        self.applied: set[str] = set()

    def add(self, area: str, name: str, state: str, detail: str = "", fix: str = "") -> None:
        self.out.append(Check(area, name, state, detail, fix))

    def run(self) -> list[Check]:
        for part in (self.environment, self.exposure, self.database, self.rls, self.people, self.content, self.models, self.gpu_worker,
                     self.background, self.deployment, self.live):
            try:
                part()
            except Exception as exc:  # noqa: BLE001 - one failing part never hides the others, and never shows a value
                self.add(part.__name__, "check could not finish", FAIL, type(exc).__name__)
        return self.out

    # ------------------------------------------------------------------ environment
    def environment(self) -> None:
        s = self.s
        a = "environment"
        for name, value, why in (("SUPABASE_URL", s.supabase_url, "database"), ("SUPABASE_SERVICE_ROLE_KEY", s.supabase_service_role_key, "database")):
            self.add(a, name, PASS if value else OWNER, "set" if value else "not set",
                     "" if value else f"{why}: Supabase → Project Settings → API → Render → API service → Environment")
        self.add(a, "SUPABASE_JWT_SECRET", PASS if s.supabase_jwt_secret else WARN, "set" if s.supabase_jwt_secret else
                 "not set: sign-in uses the project's JWKS (right for projects with asymmetric keys)")
        prod = s.environment.lower() == "production" or bool(self.env.get("RENDER"))
        origins = [o.strip() for o in s.cors_allowed_origins.split(",") if o.strip()]
        bad = [o for o in origins if o == "*" or not re.match(r"https?://[^/]+$", o)]
        local = [o for o in origins if "localhost" in o or "127.0.0.1" in o]
        self.add(a, "CORS_ORIGINS", FAIL if bad else WARN if prod and local else PASS, f"{len(origins)} origin(s)" + (", contains localhost" if local else ""),
                 "exact web address without a path, no *" if bad or (prod and local) else "")
        self.add(a, "JOB_EXECUTION", PASS if s.job_execution == "worker" else WARN, s.job_execution,
                 "" if s.job_execution == "worker" else "production needs JOB_EXECUTION=worker (durable queue)")
        self.add(a, "EMBEDDING_PROVIDER", FAIL if prod and s.embedding_provider == "hash" else WARN if s.embedding_provider == "hash" else PASS, s.embedding_provider,
                 "hash is not semantic: use e5_onnx" if s.embedding_provider == "hash" else "")
        if s.cron_secret:
            self.add(a, "CRON_SECRET", PASS if len(s.cron_secret) >= 24 else WARN, "set" if len(s.cron_secret) >= 24 else "set, but short",
                     "" if len(s.cron_secret) >= 24 else "use at least 24 random characters, the same value in GitHub → Actions secrets")
        else:
            self.add(a, "CRON_SECRET", WARN, "not set: the scheduled import endpoint is off", "only needed for daily imports")
        for flag, on, text in (("AGENT_SCHEDULES_ENABLED", s.agent_schedules_enabled, "agents may run on schedules an administrator enabled"),
                               ("GPU_WORKER_ENABLED", s.gpu_worker_enabled, "translation jobs may wait for a GPU worker"),
                               ("AUTO_TRANSLATE_ANNOUNCEMENTS", s.auto_translate_announcements, "announcements are machine-translated at publication"),
                               ("AUTO_TRANSLATE_DOCUMENTS", s.auto_translate_documents, "documents are machine-translated at approval"),
                               ("PUBLIC_MACHINE_TRANSLATIONS", s.public_machine_translations, "students may see machine translations")):
            self.add(a, flag, WARN if on else PASS, "on: " + text if on else "off")

    def exposure(self) -> None:
        a = "secrets"
        leaked = [k for k, v in self.env.items() if k.startswith("NEXT_PUBLIC_") and _role(v) == "service_role"]
        leaked += [k for k, v in self.env.items() if k.startswith("NEXT_PUBLIC_") and v.startswith("sb_secret_")]
        self.add(a, "no secret key in NEXT_PUBLIC_*", FAIL if leaked else PASS, ", ".join(leaked), "rotate the key at once" if leaked else "")
        if self.s.supabase_service_role_key and (_role(self.s.supabase_service_role_key) == "anon" or self.s.supabase_service_role_key.startswith("sb_publishable_")):
            self.add(a, "SUPABASE_SERVICE_ROLE_KEY is the secret key", FAIL, "it is the public key", "use the service-role / secret key")
        try:
            files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, timeout=20).stdout.split("\n")
            tracked = [f for f in files if re.search(r"(^|/)\.env($|\.)", f) and not f.endswith(".example")] + [f for f in files if f.endswith((".pem", ".p12"))]
            self.add(a, "no secret file in Git", FAIL if tracked else PASS, ", ".join(tracked), "remove it and rotate every key in it" if tracked else "")
        except (OSError, subprocess.SubprocessError):
            self.add(a, "no secret file in Git", SKIP, "git is not available here")

    # ------------------------------------------------------------------ database
    def _get(self, path: str, key: str, **params: str) -> httpx.Response:
        headers = {"apikey": key}
        if key.count(".") == 2:
            headers["Authorization"] = f"Bearer {key}"
        return self.http.get(f"{self.s.supabase_url.rstrip('/')}{path}", params=params, headers=headers)

    def database(self) -> None:
        a, key = "database", self.s.supabase_service_role_key
        if not self.s.supabase_configured:
            self.add(a, "connection", SKIP, "SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are not set")
            return
        try:
            r = self._get("/rest/v1/categories", key, select="slug", limit="50")
        except httpx.HTTPError as exc:
            self.add(a, "connection", FAIL, type(exc).__name__, "is SUPABASE_URL right, is the project paused?")
            return
        if r.status_code != 200:
            self.add(a, "connection", FAIL, f"HTTP {r.status_code}", "check the key and that the project is not paused")
            return
        self.add(a, "connection", PASS, "")
        self.add(a, "categories (seed.sql)", PASS if len(r.json()) >= 11 else OWNER, f"{len(r.json())} of 11", "" if len(r.json()) >= 11 else "run supabase/seed.sql (its sample rows are optional)")
        for mig, table, col in MIGRATIONS:
            ok = self._get(f"/rest/v1/{table}", key, select=col, limit="0").status_code == 200
            if ok:
                self.applied.add(mig)
            optional = mig > REQUIRED_UP_TO
            self.add(a, f"migration {mig}", PASS if ok else SKIP if optional else FAIL, "" if ok else "not applied" + (" (optional until its release)" if optional else ""),
                     "" if ok or optional else "apply supabase/migrations in order, after a backup")
        spec = self._get("/rest/v1/", key)
        paths = set(spec.json().get("paths") or {}) if spec.status_code == 200 and "json" in spec.headers.get("content-type", "") else None
        for f in FUNCTIONS:
            self.add(a, f"function {f}", SKIP if paths is None else PASS if f"/rpc/{f}" in paths else FAIL, "API description not readable" if paths is None else "")
        if self.s.gpu_worker_enabled and "0016" not in self.applied:
            self.add(a, "GPU_WORKER_ENABLED needs migration 0016", FAIL, "", "set GPU_WORKER_ENABLED=false or apply 0016")
        b = self._get(f"/storage/v1/bucket/{self.s.source_files_bucket}", key)
        if b.status_code == 200 and "json" in b.headers.get("content-type", ""):
            public = bool(b.json().get("public"))
            self.add(a, f"storage bucket {self.s.source_files_bucket}", FAIL if public else PASS, "PUBLIC" if public else "private", "make the bucket private" if public else "")
        else:
            self.add(a, f"storage bucket {self.s.source_files_bucket}", FAIL if b.status_code in (400, 404) else SKIP, f"HTTP {b.status_code}", "migration 0005 creates it")

    def rls(self) -> None:
        a = "access rules"
        anon = self.env.get("SUPABASE_ANON_KEY") or self.env.get("NEXT_PUBLIC_SUPABASE_ANON_KEY") or ""
        if not self.s.supabase_url or not anon:
            self.add(a, "public key sees no private rows", SKIP, "set SUPABASE_ANON_KEY for this check (the public key, not a secret)")
            return
        open_, unreadable = [], 0
        for t in PRIVATE:
            r = self._get(f"/rest/v1/{t}", anon, select="*", limit="1")
            if r.status_code == 200 and r.json():
                open_.append(t)
            elif r.status_code == 404:
                unreadable += 1
        self.add(a, "public key sees no private rows", FAIL if open_ else PASS, ", ".join(open_) or f"{len(PRIVATE)} tables", "check the RLS policies of these tables at once" if open_ else "")
        r = self._get("/rest/v1/document_versions", anon, select="id", verification_status="neq.approved", limit="1")
        self.add(a, "unapproved versions are hidden", FAIL if r.status_code == 200 and r.json() else PASS)
        r = self._get("/rest/v1/announcements", anon, select="id", publication_status="neq.published", limit="1")
        self.add(a, "unpublished announcements are hidden", FAIL if r.status_code == 200 and r.json() else PASS)

    # ------------------------------------------------------------------ people, content
    def _rows(self, table: str, **params: str) -> list[dict[str, Any]] | None:
        r = self._get(f"/rest/v1/{table}", self.s.supabase_service_role_key, **params)
        return r.json() if r.status_code == 200 else None

    def people(self) -> None:
        a = "people"
        if "0008" not in self.applied:
            self.add(a, "roles", SKIP, "no database")
            return
        admins = self._rows("profiles", select="role", role="in.(admin,super_admin,supporter)") or []
        n = {r: sum(x["role"] == r for x in admins) for r in ("super_admin", "admin", "supporter")}
        self.add(a, "super administrator", PASS if n["super_admin"] else OWNER, f"{n['super_admin']}", "" if n["super_admin"] else "docs/owner/SUPABASE-SETUP.md, first super administrator")
        self.add(a, "administrators / supporters", PASS if n["admin"] + n["supporter"] else OWNER, f"{n['admin']} / {n['supporter']}", "" if n["admin"] + n["supporter"] else "Admin → Users & Roles")
        langs = self._rows("supporter_languages", select="language_code,can_support,can_review_translations") or []
        for what, col in (("translation reviewer", "can_review_translations"), ("human supporter", "can_support")):
            missing = [x for x in LANGS if not any(r["language_code"] == x and r.get(col) for r in langs)]
            self.add(a, f"{what} per language", OWNER if missing else PASS, "missing: " + ", ".join(missing) if missing else "all five", "Admin → Language teams" if missing else "")

    def content(self) -> None:
        a = "content"
        if "0002" not in self.applied:
            self.add(a, "approved documents", SKIP, "no database")
            return
        r = self._get("/rest/v1/source_documents", self.s.supabase_service_role_key, select="id", current_version_id="not.is.null", limit="2000")
        self.add(a, "approved documents", PASS if r.status_code == 200 and r.json() else OWNER, f"{len(r.json()) if r.status_code == 200 else '?'}", "" if r.status_code == 200 and r.json() else "Admin → Knowledge Sources, then Review")
        if "0015" in self.applied:
            src = self._rows("discovery_sources", select="agent_id,enabled,last_status,consecutive_failures") or []
            for agent, name in (("announcement", "Robo"), ("scholarship", "Leo"), ("career", "Daniel"), ("events", "Mia"), ("immigration", "Yuna"), ("academic", "Joon"), ("topik", "Seo")):
                mine = [x for x in src if x["agent_id"] == agent and x["enabled"]]
                bad = [x for x in mine if x["consecutive_failures"] or x["last_status"] in ("failed", "blocked")]
                self.add(a, f"official sources of {name}", OWNER if not mine else WARN if bad else PASS, f"{len(mine)} enabled" + (f", {len(bad)} failing" if bad else ""),
                         "" if mine and not bad else "docs/owner/SOURCES.md")
        if "0014" in self.applied:
            on = [x for x in self._rows("agent_schedules", select="agent_id,enabled") or [] if x["enabled"]]
            self.add(a, "agent schedules", WARN if on else PASS, f"{len(on)} enabled" if on else "all off")

    # ------------------------------------------------------------------ models
    def models(self) -> None:
        a, s = "models", self.s
        p = (s.llm_provider or "none").lower()
        if p == "none":
            self.add(a, "live chat provider", OWNER, "LLM_PROVIDER=none: the chat shows excerpts", "LLM_PROVIDER=gemini and LLM_API_KEY (docs/owner/SETUP-CHECKLIST.md)")
        elif p in ("gemini", "anthropic"):
            self.add(a, "live chat provider", PASS if s.llm_api_key else OWNER, f"{p}, key {'set' if s.llm_api_key else 'not set'}")
            self.add(a, f"{p} models answer", SKIP, "", "python -m app.cli check-llm (free: lists models), or Admin → Settings → Test AI models")
        else:
            self.add(a, "live chat provider", WARN if p == "ollama" else FAIL, p, "Ollama is for development on the GPU computer only" if p == "ollama" else "unknown provider")
        uses_local = "ollama" in (p, (s.background_llm_provider or "").lower())
        try:
            r = self.http.get(f"{s.ollama_base_url.rstrip('/')}/api/tags", timeout=3)
            names = [m["name"] for m in r.json().get("models", [])]
            self.add(a, f"Ollama model {s.ollama_model}", PASS if s.ollama_model in names else OWNER if uses_local else WARN, f"{len(names)} model(s) installed", "" if s.ollama_model in names else f"ollama pull {s.ollama_model}")
            exposed = _listens_everywhere(11434)
            self.add(a, "Ollama listens on this computer only", FAIL if exposed else PASS if exposed is not None else SKIP, "reachable from the network" if exposed else "",
                     "OLLAMA_HOST=127.0.0.1" if exposed else "")
        except (httpx.HTTPError, ValueError):
            self.add(a, "Ollama", FAIL if uses_local else SKIP, "not running on this computer", "only needed on the GPU computer")

        for name, v in (("SARAMIN_ACCESS_KEY", s.saramin_access_key), ("DATA_GO_KR_SERVICE_KEY", s.data_go_kr_service_key)):
            self.add("recruitment APIs (optional)", name, PASS if v else OWNER, "set" if v else "not set: this source stays blocked", "" if v else "docs/owner/EXTERNAL-APIS.md")

    def gpu_worker(self) -> None:
        a = "GPU worker (this computer)"
        if not self.env.get("GPU_WORKER_HUB_URL"):
            self.add(a, "worker configuration", SKIP, "GPU_WORKER_HUB_URL is not set here", "only on the university GPU computer: docs/owner/GPU-SETUP.md")
            return
        from app.gpu_worker.config import Config, ConfigError, read_token

        try:
            c = Config.from_env(self.env)
            self.add(a, "worker configuration", PASS, urlsplit(c.hub_url).hostname or "")
            read_token(c.token_file)
            self.add(a, "worker token file", PASS, "readable by this account only")
        except ConfigError as exc:
            self.add(a, "worker configuration", FAIL, str(exc)[:160])

    def background(self) -> None:
        a = "background work"
        if "0006" not in self.applied:
            self.add(a, "queues", SKIP, "no database")
            return
        for table, extra in (("ingestion_jobs", {}), ("agent_tasks", {})):
            if table == "agent_tasks" and "0014" not in self.applied:
                continue
            rows = self._rows(table, select="id,created_at,run_after", status="eq.queued", order="created_at.asc", limit="100", **extra) or []
            from datetime import UTC, datetime, timedelta

            old = [r for r in rows if datetime.fromisoformat(r["run_after"]) < datetime.now(UTC) - timedelta(hours=2)]
            self.add(a, f"{table} queue", WARN if old else PASS, f"{len(rows)} waiting" + (f", {len(old)} for more than 2 hours" if old else ""), "is the API running with JOB_EXECUTION=worker?" if old else "")

    # ------------------------------------------------------------------ deployment files, live service
    def deployment(self) -> None:
        a = "deployment files"
        y = (ROOT / "render.yaml").read_text() if (ROOT / "render.yaml").is_file() else ""
        names = set(re.findall(r"key:\s*([A-Z][A-Z0-9_]+)", y))
        known = {f.upper() for f in Settings.model_fields} | {"CORS_ORIGINS", "CORS_ALLOWED_ORIGINS", "NEXT_PUBLIC_SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_ANON_KEY", "NEXT_PUBLIC_API_URL", "PYTHON_VERSION", "NODE_VERSION"}
        unknown = sorted(names - known)
        self.add(a, "render.yaml uses variables the code knows", WARN if unknown else PASS if names else SKIP, ", ".join(unknown))
        wf = ROOT / ".github" / "workflows" / "render-deploy.yml"
        if wf.is_file():
            t = wf.read_text()
            self.add(a, "GitHub: what deploys", WARN if "branches: [main]" in t else PASS, "a push to main that touches backend/ or apps/web/ deploys it" if "branches: [main]" in t else "", "protect main: docs/owner/GITHUB-SETUP.md")

    def live(self) -> None:
        a = "live service"
        if not self.api:
            self.add(a, "API", SKIP, "", "--api https://your-api.onrender.com")
            return
        h = self.http.get(f"{self.api}/health")
        ok = h.status_code == 200 and "json" in h.headers.get("content-type", "")
        self.add(a, "API /health", PASS if ok else FAIL, f"HTTP {h.status_code}" + (f", database {h.json().get('supabase')}, {h.json().get('embedding_model')}" if ok else ""))
        for path, want in (("/api/v1/categories", (200,)), ("/api/v1/agents", (200,)), ("/api/v1/admin/overview", (401, 403)), ("/api/v1/admin/agent-operations", (401, 403, 404)),
                           ("/api/v1/me", (401,)), ("/api/v1/agent-tasks", (401,))):
            code = self.http.get(self.api + path).status_code
            self.add(a, f"GET {path} without sign-in", PASS if code in want else FAIL, f"HTTP {code}")
        r = self.http.get(f"{self.api}/api/v1/categories", headers={"Origin": "https://not-allowed.example"})
        allow = r.headers.get("access-control-allow-origin")
        self.add(a, "CORS refuses unknown websites", FAIL if allow in ("*", "https://not-allowed.example") else PASS, allow or "no header")
        if self.web:
            w = self.http.get(self.web)
            self.add(a, "website", PASS if w.status_code in (200, 307, 308) else FAIL, f"HTTP {w.status_code}")
            r = self.http.get(f"{self.api}/api/v1/categories", headers={"Origin": self.web})
            self.add(a, "CORS allows the website", PASS if r.headers.get("access-control-allow-origin") == self.web else FAIL, "", "CORS_ORIGINS on the API service")


def _role(token: str) -> str | None:
    try:
        part = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))).get("role")
    except Exception:  # noqa: BLE001 - not a JWT
        return None


def _listens_everywhere(port: int) -> bool | None:
    """True when something on this port accepts connections from other computers (Linux only)."""
    found = None
    for f, anyaddr in (("/proc/net/tcp", {"00000000"}), ("/proc/net/tcp6", {"0" * 32})):
        try:
            lines = Path(f).read_text().split("\n")[1:]
        except OSError:
            continue
        for ln in lines:
            p = ln.split()
            if len(p) > 3 and p[3] == "0A":
                addr, prt = p[1].split(":")
                if int(prt, 16) == port:
                    found = bool(found) or addr in anyaddr
    return found


def main(settings: Settings, *, api: str | None, web: str | None, as_json: bool) -> int:
    checks = Doctor(settings, api=api, web=web).run()
    if as_json:
        print(json.dumps([asdict(c) for c in checks], ensure_ascii=False, indent=1))
    else:
        area = ""
        for c in checks:
            if c.area != area:
                area = c.area
                print(f"\n== {area}")
            print(f"{c.state:22} {c.name}" + (f"  [{c.detail}]" if c.detail else "") + (f"\n{'':22}   → {c.fix}" if c.fix and c.state != PASS else ""))
        n = {s: sum(c.state == s for c in checks) for s in (PASS, WARN, FAIL, SKIP, OWNER)}
        print("\n" + ", ".join(f"{v} {k}" for k, v in n.items()))
    return 1 if any(c.state == FAIL for c in checks) else 0
