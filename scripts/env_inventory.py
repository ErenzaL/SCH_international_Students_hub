"""Writes docs/owner/ENVIRONMENT.md and docs/owner/SOURCES.md from the code (so that nothing is invented or forgotten).

    cd backend && .venv/bin/python ../scripts/env_inventory.py [--check]
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.core.config import Settings  # noqa: E402

SECRET = {"SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_JWT_SECRET", "LLM_API_KEY", "CRON_SECRET", "OCR_SPACE_API_KEY", "SARAMIN_ACCESS_KEY", "DATA_GO_KR_SERVICE_KEY", "TRANSLATION_API_KEY", "WORK24_AUTH_KEY"}
REQUIRED = {"SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "CORS_ORIGINS"}
PROD = {"JOB_EXECUTION", "EMBEDDING_PROVIDER", "EMBEDDING_CACHE_DIR", "RETRIEVAL_MIN_SIMILARITY", "LLM_PROVIDER", "LLM_API_KEY", "GEMINI_PRIMARY_MODEL", "GEMINI_FALLBACK_MODEL", "CRON_SECRET",
        "SUPABASE_JWT_SECRET"}
HOW = {"SUPABASE_URL": "Supabase → Project Settings → API → Project URL", "SUPABASE_SERVICE_ROLE_KEY": "Supabase → Project Settings → API Keys → secret / service_role key. Never in the web service",
       "SUPABASE_JWT_SECRET": "Supabase → Project Settings → JWT Keys → legacy secret. Only when the project signs with HS256", "CORS_ORIGINS": "the exact web address, e.g. https://sch-international-students-hub.onrender.com",
       "LLM_API_KEY": "https://aistudio.google.com/apikey", "CRON_SECRET": "make one: `openssl rand -base64 32`; the same value as GitHub → Settings → Secrets → Actions → CRON_SECRET",
       "OCR_SPACE_API_KEY": "https://ocr.space/ocrapi (free key; images go to that service)", "SARAMIN_ACCESS_KEY": "https://oapi.saramin.co.kr/join (approval needed)",
       "DATA_GO_KR_SERVICE_KEY": "https://www.data.go.kr/data/15125273/openapi.do → 활용신청",
       "WORK24_AUTH_KEY": "https://www.work24.go.kr → OPEN-API → 채용정보 API 신청 (terms and limits: confirm on that page)"}


def comments() -> dict[str, str]:
    """field -> the comment beside it or directly above it"""
    out, above = {}, ""
    for ln in (ROOT / "backend/app/core/config.py").read_text().split("\n"):
        m = re.match(r"    ([a-z][a-z0-9_]+):\s*[^=]+=\s*[^#]*(?:#\s*(.*))?$", ln)
        c = re.match(r"    #\s?(.*)", ln)
        if m:
            out[m[1].upper()] = (m[2] or above).strip()
            above = ""
        elif c:
            t = c[1].strip()
            above = "" if t.startswith("---") else f"{above} {t}".strip()
        elif not ln.strip():
            above = ""
    return out


def environment() -> str:
    render = (ROOT / "render.yaml").read_text()
    example = (ROOT / ".env.example").read_text()
    com = comments()
    rows = []
    for name, f in Settings.model_fields.items():
        n = "CORS_ORIGINS" if name == "cors_allowed_origins" else name.upper()
        d = f.default
        default = "—" if d in ("", None) else f"`{str(d)[:60]}`" if not isinstance(d, str) or len(d) < 60 else "(list)"
        need = "**required**" if n in REQUIRED else "production" if n in PROD else "optional"
        tpl = ", ".join(x for x, t in (("render.yaml", render), (".env.example", example)) if re.search(rf"\b{n}\b", t)) or "—"
        why = (com.get(name.upper(), "") or "").replace("|", "/")[:170]
        how = f"<br>**Get it:** {HOW[n]}" if n in HOW else ""
        rows.append((0 if n in REQUIRED else 1 if n in PROD else 2, f"| `{n}` | {'SECRET' if n in SECRET else 'setting'} | {need} | {default} | {tpl} | {why}{how} |"))
    rows.sort(key=lambda r: r[0])
    return f"""# Environment variables

Generated from the code by `scripts/env_inventory.py`; do not edit by hand. {len(rows)} variables of the **API service**. Whether a value is set on
Render cannot be seen from here: check with `python -m app.cli doctor` (prints "set" or "not set", never a value) or in the dashboard.

After changing a variable on Render the service restarts by itself (choose *Save, rebuild and deploy* only for the web variables).

## Web service (Render → sch-hub-web → Environment)

All three are **public**: they are built into the pages. Never put a secret here. After a change: *Manual Deploy → Clear build cache & deploy*.

| Variable | Required | Get it | Verify |
|---|---|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | yes | Supabase → Project Settings → API → Project URL | sign-in page works |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | yes | the **publishable / anon** key, never the secret key | `doctor` fails if it is the secret key |
| `NEXT_PUBLIC_API_URL` | yes | address of the API service without `/api/v1` | the Knowledge Center shows documents |

## GitHub (Settings → Secrets and variables → Actions)

| Name | Kind | Required | Purpose | Verify |
|---|---|---|---|---|
| `RENDER_DEPLOY_HOOK_API`, `RENDER_DEPLOY_HOOK_WEB` | SECRET | for automatic deploys | Render → service → Settings → Deploy Hook | Actions → Deploy to Render → log |
| `CRON_SECRET` | SECRET | for daily imports | same value as on the API service | Actions → Scheduled knowledge sync → log |
| `SCH_API_URL` | variable | no | address of the API | same |

## University GPU computer (`~/.config/sch-gpu-worker/env`, see GPU-ACTIVATION.md)

| Variable | Required | Meaning |
|---|---|---|
| `GPU_WORKER_HUB_URL` | yes | `https://` address of the API, no path |
| `GPU_WORKER_PRODUCTION_HOST` | for production | unset = the worker refuses the production API. For activation (GPU-ACTIVATION.md): exactly `sch-hub-api.onrender.com` |
| `GPU_WORKER_TOKEN_FILE` | yes | file with the token, mode 600 (the token itself is **not** a variable) |
| `OLLAMA_MODEL` | yes for announcements | `translategemma:12b` (default; the API gives announcement jobs to no other model) |
| `OLLAMA_BASE_URL`, `OLLAMA_NUM_CTX`, `OLLAMA_JOB_TIMEOUT_SECONDS` | no | defaults: loopback, 16384, 180 |
| `GPU_WORKER_MIN_FREE_VRAM_MB` | no | `9500`: no job is taken while less GPU memory is free (shared computer); 0 = no check |
| `GPU_WORKER_IDLE_MIN_SECONDS`, `GPU_WORKER_IDLE_MAX_SECONDS`, `GPU_WORKER_ACTIVE_HOURS`, `GPU_WORKER_LOCK_FILE` | no | continuous mode only |

The worker refuses to start when a Supabase, Gemini or cron secret is set on that computer.

## API service (Render → sch-hub-api → Environment)

| Variable | Kind | Needed | Default | In template | Purpose |
|---|---|---|---|---|---|
""" + "\n".join(r for _k, r in rows) + "\n"


def sources() -> str:
    d = json.loads((ROOT / "backend/app/services/discovery/catalog.json").read_text())["sources"]
    desk = dict(announcement="Robo", scholarship="Leo", career="Daniel", events="Mia", immigration="Yuna", academic="Joon", topik="Seo")
    rows = []
    for e in d:
        v = e.get("validated") or {}
        state = f"works ({v.get('checked')}, {v.get('items_read')} read)" if v.get("status") == "ok" else f"**needs {e['needs']}**" if e.get("needs") else v.get("status", "—")
        rows.append(f"| {desk[e['agent_id']]} | [{e['name']}]({e['url']}) | {e['kind']} | {e['category']} | {state} | {e['recommended_interval_minutes'] // 60} h |")
    return f"""# Official sources

Generated from `backend/app/services/discovery/catalog.json` by `scripts/env_inventory.py`. {len(rows)} prepared sources; **none is active** until an
administrator adds it. "works" = read on the live website with the Hub's own fetcher (allowlist, robots.txt, at least one second between requests).

| Desk | Source | Type | Category | State | Suggested interval |
|---|---|---|---|---|---|
""" + "\n".join(rows) + """

## How to

| Task | Where |
|---|---|
| Add | Admin → Agents → Sources → *Prepared official sources* → Add (or the form below it) |
| Check now | AI Office → the desk → Sources → *Check official sources now* (administrators) |
| Pause one | Admin → Agents → Sources → Turn off. A whole desk: Admin → Agents → Desks → Pause |
| Recognise failures | red "failing" count in Sources; a notification after 3 failures; after 5 the source is skipped until *Reset failures* |
| Review what was found | AI Office → the desk → Review → *Send to review* or *Dismiss*; then Admin → Review Queue → Approve. Only then students and the chat see it |
| Validate again | `cd backend && .venv/bin/python ../scripts/validate_sources.py app/services/discovery/catalog.json --items 2` |
| Switch on a schedule | 1. `AGENT_SCHEDULES_ENABLED=true` on the API service, 2. Admin → Agents → Schedules → on. Both are off |

## Restrictions

- Only domains of *Admin → Settings → Allowed domains* are ever requested; `robots.txt` is respected. `www.sch.ac.kr` forbids automated access and is **not** used.
- Study in Korea lists open their items through a script: only title and date are read (status "unknown"). They are not worked around.
- `topik.go.kr` renders its pages with JavaScript and returns no text: not used. TOPIK information comes from Study in Korea and SCH notices.
- The content belongs to its publisher. The Hub stores text for review and search, quotes it with a link to the original, and keeps the source. If a publisher
  objects, turn the source off and withdraw its documents.
- The same notice found by two desks is stored once (first desk keeps it); events and jobs are shown at Mia's and Daniel's desk whoever found them.
"""


out = {ROOT / "docs/owner/ENVIRONMENT.md": environment(), ROOT / "docs/owner/SOURCES.md": sources()}
bad = [p.name for p, t in out.items() if not p.is_file() or p.read_text() != t]
if "--check" in sys.argv:
    print("out of date: " + ", ".join(bad) if bad else "up to date")
    sys.exit(bool(bad))
for p, t in out.items():
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(t)
print("written", len(Settings.model_fields), "variables")
