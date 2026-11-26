# Staging at zero cost, without a third Supabase project

**Constraint (2026-11-26):** the Supabase account already has its two active Free projects (먹어보조 and the production project
`sch_international_student`). Neither is paused, deleted, transferred or changed, and nothing is upgraded. So there is **no hosted staging
database**. Staging is split into tiers that together cover what a hosted copy would, and the guide says for every check which tier proved it.

**Nothing in this guide touches production.** Production data, the production Render services and the production Supabase project are only
ever *read* (the existing `doctor` GET checks). Steps that publish or create something are marked **approval**.

## 1. Architecture

| Tier | Where | What runs | Proves | Cannot prove |
|---|---|---|---|---|
| **L1 – scratch stack** | university workstation (this server, now) | PostgreSQL 17 + pgvector and real **PostgREST** on private sockets (`scripts/scratch_db.sh`), all migrations, the Supabase roles and RLS (`scripts/local_supabase_shim.sql`), the real API with its worker, the production web build, a stand-in sign-in service (signed tokens, same claims as Supabase), **Qwen 2.5 7B on the local GPU**, the GPU worker as its own process, the synthetic official websites (`scripts/synthetic_web.py`) | schema, migrations, RLS and SQL rules, every API path, all browser journeys incl. the 14 agents, PDF ingestion, translations, GPU drafts | Supabase's own Auth (GoTrue), Storage service and gateway |
| **L2 – local Supabase stack** | your MacBook | the **real Supabase stack** from the Supabase CLI in Docker (Postgres, Auth, PostgREST, Storage, gateway, Studio), bound to 127.0.0.1 only, with the same migrations, synthetic seed, made-up accounts and synthetic websites (`scripts/local_supabase.sh`) | real e-mail/password sign-in and the Auth admin API, Storage uploads and bucket rules, RLS through the real gateway, the staging bootstrap path, integration tests against real Supabase services | Render's limits, the hosted project's dashboard settings |
| **R – Render memory probe** | one free Render web service, **no database** | the real API code in production mode (worker thread, model, PDF child process) with an in-memory store (`backend/app/memory_probe.py`); refuses every Supabase or production credential; answers only requests with its random key | the real **512 MB / 0.1 CPU** limit: peak memory, out-of-memory kills, restarts, responsiveness, recovery, stuck work | database latency (in-memory store); it holds chunks and vectors in memory, so a pass is conservative |
| **H – hosted Supabase** | production project, **read-only** | `python -m app.cli doctor --api … --web …` (GET only, as before) and you looking at the dashboard | that production is configured as documented | anything that writes; that is verified at release time with your approvals (`docs/release/release-a-approvals.md`) |

**Why no hosted staging API with a database.** A Render service needs a database reachable from the internet. The options were checked and
rejected: a tunnel to a local database (Cloudflare Tunnel, ngrok, Tailscale Funnel) would publish a database or API of a personal computer to
the internet; Render's free PostgreSQL is not Supabase (no Auth, Storage or PostgREST; it would need more public services and expires);
Supabase branching is paid; a second account to get more free projects would sidestep the provider's limit. The safe zero-cost split is:
database features locally (L1, L2), Render's limits with the probe (R), and production read-only (H).

**Qwen.** The GPU worker connects only to development and staging task systems: it refuses the production API unless
`GPU_WORKER_PRODUCTION_HOST` is set to exactly that host, which belongs to the Release B sign-off. Production keeps `GPU_WORKER_ENABLED`
off, so its worker endpoints do not exist. Ollama stays on 127.0.0.1.

## 2. Every staging tool refuses production

| Tool | Refuses |
|---|---|
| `scripts/staging_bootstrap.py` | production references, keys of other projects, production addresses, real e-mail domains, projects with real users; with `--supabase-local` anything that is not on this computer or that names a hosted project |
| `scripts/local_supabase.sh` | a checkout linked to a hosted project (`supabase/.temp/project-ref`), hosted addresses from the stack, containers published on all interfaces; never runs `link`, `db push` or `--linked`; unsets `SUPABASE_ACCESS_TOKEN` |
| `scripts/local_api.py` | a `SUPABASE_URL` that is not on this computer, any hosted or production value, Gemini and OCR keys |
| `backend/app/memory_probe.py` | to start when any Supabase, Gemini, OCR, cron or database credential is set; requests without its key |
| `scripts/memory_probe_info.py`, `scripts/staging_memory_check.py`, `scripts/e2e_full.mjs` | production addresses; the password only goes to loopback or the staging project |
| GPU worker | production secrets on the GPU computer (as before) and now the production API |
| the API as the tools start it | `.env` files: started from an empty directory, production-sensitive variables set empty |

Checked by `backend/tests/test_staging_tools.py`, `test_staging_doc.py` and `test_runtime_and_slots.py`.

## 3. L2 on your MacBook: software (all free)

| Software | Install | Note |
|---|---|---|
| Homebrew | brew.sh | – |
| Colima + Docker CLI | `brew install colima docker` | open-source container engine. Docker Desktop is free only for personal use, education and small companies; Colima avoids the question. OrbStack is free for personal use. |
| Supabase CLI | `brew install supabase/tap/supabase` | runs the stack; never logged in or linked for this |
| psql | `brew install libpq && brew link --force libpq` | SQL tests and the bootstrap |
| Python 3.11 | `brew install python@3.11` | backend |
| Node 22 | `brew install node@22` | web app and browser tests (Playwright downloads Chromium itself) |
| Ollama + Qwen (optional) | ollama.com, then `ollama pull qwen2.5:7b-instruct` (about 4.7 GB) | for the chat, translation and GPU journeys; Apple silicon runs it on its GPU |

Disk: about 15 GB (stack images, model files, Qwen). Memory: give Colima 4 CPUs and 8 GB.

## 4. L2: exact commands

The code reaches the MacBook without a push: on the university server `git bundle create ~/sch-local-first.bundle staging/local-first`, copy
the file to the MacBook (for example with `scp`), then `git clone sch-local-first.bundle sch-hub-local`. Use **a fresh clone**, never one
that was linked to a Supabase project.

```bash
cd sch-hub-local
colima start --cpu 4 --memory 8 --disk 40
cd backend && python3.11 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt && cd ..
scripts/local_supabase.sh check          # software, engine, not linked
scripts/local_supabase.sh up             # stack on 127.0.0.1, migrations + synthetic seed, six made-up accounts, ~/.sch-local/sch-local.json
scripts/local_supabase.sh api            # terminal 2 (with Qwen: LLM_PROVIDER=ollama scripts/local_supabase.sh api)
scripts/local_supabase.sh web            # terminal 3; then open http://127.0.0.1:3000 (yellow staging banner)
scripts/local_supabase.sh test           # 13 SQL behaviour tests + backend integration tests against the real stack
scripts/local_supabase.sh e2e            # browser journeys (with Qwen: LLM_PROVIDER=ollama scripts/local_supabase.sh e2e)
scripts/local_supabase.sh memory         # the hosted memory check against the local API (not Render's limits)
scripts/local_supabase.sh down           # stop, data kept;  down --wipe  deletes it
```

`up` creates a Docker network whose published ports bind to 127.0.0.1 only (Supabase's documented way for untrusted networks) and stops
again if any container is published on all interfaces. Accounts: `super_admin`, `admin`, `supporter_vi`, `reviewer_id`, `student`,
`student2` `@sch-staging.example.com`, one random password in `~/.sch-local/sch-local.json` (mode 600). Studio runs at
`http://127.0.0.1:54323`. **Not on a shared server:** other accounts there could reach the stack's database with its well-known local password.

**Not yet run:** this server gives no Docker access, and the CLI's experimental native runtime is not used here for the same shared-server
reason. The parts the script reuses (bootstrap, launcher, synthetic websites, journeys, checks) are tested on L1; the first `up` on the
MacBook is the test of the script itself.

## 5. R: the Render memory probe (needs approval: a branch push and one free service)

| | Action |
|---|---|
| 1 | **Approval:** push the branch for Render to build: `git push origin staging/local-first:refs/heads/hub-staging` (only `main` deploys anything) |
| 2 | Make two random values on your computer: `python3 -c 'import secrets;print(secrets.token_urlsafe(32))'`, twice → `PROBE_KEY`, `PROBE_JWT_SECRET` |
| 3 | **Approval:** Render → New → Web Service → this repository, name `sch-hub-staging-probe`, branch `hub-staging`, root `backend`, Python 3, Free, Auto-Deploy off, previews off, health check `/health` |
| 4 | Build: `pip install -r requirements.txt && python -m app.cli prefetch-model` · Start: `uvicorn app.memory_probe:app --host 0.0.0.0 --port $PORT` |
| 5 | Environment, only these: `PYTHON_VERSION=3.11.9`, `MALLOC_ARENA_MAX=2`, `EMBEDDING_PROVIDER=e5_onnx`, `EMBEDDING_CACHE_DIR=.model-cache`, `EMBEDDING_MODEL=intfloat/multilingual-e5-small`, `INGESTION_MAX_CONCURRENT_JOBS=1`, `PROBE_KEY`, `PROBE_JWT_SECRET`. No `SUPABASE_*`, no keys: the probe refuses to start with them |
| 6 | On your computer: `PROBE_KEY=… PROBE_JWT_SECRET=… backend/.venv/bin/python scripts/memory_probe_info.py --api https://sch-hub-staging-probe.onrender.com --out ~/sch-probe.json` |
| 7 | `backend/.venv/bin/python scripts/staging_memory_check.py ~/sch-probe.json --report ~/probe-memory.json` (60–90 minutes), meanwhile Render → the service → **Metrics → Memory** and **Events** |
| 8 | Afterwards: Render → the service → **Suspend** (or Delete); `git push origin --delete hub-staging` (approval) |

The probe's data lives only in its memory and is gone with every restart; the uploads are the synthetic PDFs and texts of
`scripts/synthetic_docs.py`. A test uses about 1.5 of the 750 free monthly hours. Send me `~/probe-memory.json`: numbers and synthetic titles only.

## 6. Verification procedure

| Area | L1 (this server) | L2 (MacBook) | R (Render probe) | H (production, read-only) |
|---|---|---|---|---|
| migrations, RLS, SQL rules | 13 SQL behaviour tests, integration tests | `local_supabase.sh test` | – | `doctor` |
| login | stand-in sign-in service, all roles | **real Supabase Auth** (password, admin API) | probe token | – |
| RAG (search, answers with sources) | journeys `setup`, `announcement`, `pdf`, `visa`, `chats` with Qwen | `e2e` | search during load | – |
| 14 agents | journeys `office` (all 14), `announcement`, `career`, `scholarship`, `autonomy`, `escalation` (synthetic websites) | `e2e` | – | – |
| admin | journey `admin` (every page, roles, pause, storage) | `e2e` | – | – |
| translations | journey `gpu` (draft → language review → public) | `e2e` with Ollama | – | – |
| PDF ingestion | journey `pdf` (browser upload → worker extraction → review → approval → search → answer) | `e2e` (real Storage) | `staging_memory_check` (3 + 9 MB) | – |
| GPU processing | journey `gpu` (worker process, real Qwen) | `e2e` with Ollama | – | `GPU_WORKER_ENABLED` stays off |
| 512 MB / 0.1 CPU | `scripts/render_like.py` approximation | – | **real** | – |
| production configuration | – | – | – | `doctor` 10 of 10 (GET only) |

Results of L1 and of the local probe run are in [TEST-RESULTS.md](../development/TEST-RESULTS.md) and
[RENDER-MEMORY.md](../development/RENDER-MEMORY.md). L2 and R are waiting for the steps above.

## 7. If a free Supabase slot ever becomes available

`scripts/staging_bootstrap.py all` (without `--supabase-local`) prepares a separate hosted project with the same guards: it refuses
production keys and addresses, real e-mail domains and projects with real users, and writes only synthetic data. Required API variables for
such a copy: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `CORS_ORIGINS`, plus the probe's values of step 5 without `PROBE_*`.
