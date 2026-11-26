# Hosted staging at zero cost

Read on the providers' pages on 2026-11-26: Supabase Free allows **2 active projects** (500 MB each, no backups, paused after 1 week without use).
Render gives **750 free instance hours per workspace and month**, free instances have **0.1 CPU / 512 MB**, sleep after 15 minutes without requests and use no
hours while asleep. The Hobby workspace (one per account) costs $0 plus compute; free compute is $0.

So staging = **a second free Supabase project + two more free Render services in the same workspace**. Asleep they cost nothing; a two-hour test
session uses about 4 of the 750 hours (two services). Never keep staging awake (no uptime pings, no continuous GPU worker): production shares the hours.
Render says free instances are meant for testing and hobby projects; production runs on them today too, that is your decision, not a staging question.

Nothing below touches production. Two points need your approval because they publish or create something: **creating the branch `staging` on GitHub**
(a push) and **creating the services**. Everything else in this list only reads or writes the staging project.

## 1. Supabase staging project (10 minutes)

| | Action | Check |
|---|---|---|
| 1 | supabase.com → New project → name `sch-hub-staging`, region **Northeast Asia (Tokyo)**, Free plan, a new password | project page opens |
| 2 | Write down `STAGING_REF` (Settings → General) and your production reference `PRODUCTION_REF` | they differ |
| 3 | Authentication → Providers → Email on; *Confirm email* off is fine for staging | – |
| 4 | Settings → API Keys: publishable key and secret key of **this** project | – |

## 2. Schema, test data, accounts (one command, on your computer)

```bash
git switch staging/zero-cost-rag-memory        # or the branch that is to be tested
cd backend && python3.11 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt && cd ..
export STAGING_REF=… PRODUCTION_REF=… STAGING_SUPABASE_URL=https://$STAGING_REF.supabase.co
backend/.venv/bin/python scripts/staging_bootstrap.py all --info ~/sch-staging.json
```
It asks for the connection string (Supabase → Connect → *Session pooler*) and the two keys, never prints them, and refuses a production reference.
It applies the 17 migrations (skipping applied ones; safe to repeat), the seed, six made-up accounts (`super_admin`, `admin`, `supporter_vi`, `reviewer_id`,
`student`, `student2` `@sch-staging.example.com`, one random password stored only in `~/sch-staging.json`, mode 600), then runs `doctor`.
Tested end to end on a local database, twice. Not yet run against a hosted project.

## 3. Render staging services (15 minutes)

First, with your approval: create the branch `staging` from the commit to test and push it (`git push origin <commit>:refs/heads/staging`). The
*Deploy to Render* workflow only reacts to `main`, so this deploys nothing.

Render → New → **Web Service** → this repository, twice:

| Field | `sch-hub-api-staging` | `sch-hub-web-staging` |
|---|---|---|
| Branch | `staging` | `staging` |
| Root directory | `backend` | `apps/web` |
| Runtime | Python 3 | Node |
| Build command | `pip install -r requirements.txt && python -m app.cli prefetch-model` | `npm ci && npm run build` |
| Start command | `uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips="*"` | `npm run start` |
| Instance type | **Free** | **Free** |
| Health check path | `/health` | `/` |
| Auto-Deploy | **Off** (deploy by hand when testing) | **Off** |
| Pull Request Previews | Off | Off |

API environment: `ENVIRONMENT=staging`, `SUPABASE_URL=https://<STAGING_REF>.supabase.co`, `SUPABASE_SERVICE_ROLE_KEY=<staging secret key>`,
`CORS_ORIGINS=https://sch-hub-web-staging.onrender.com`, `PYTHON_VERSION=3.11.9`, `JOB_EXECUTION=worker`, `EMBEDDING_PROVIDER=e5_onnx`,
`EMBEDDING_CACHE_DIR=.model-cache`, `MALLOC_ARENA_MAX=2` (memory, see below), `RETRIEVAL_MIN_SIMILARITY=0.80`, `LLM_PROVIDER=none` (or `gemini` with **a separate free key**), and to test the agents and the
GPU worker: `AGENT_SCHEDULES_ENABLED=true`, `GPU_WORKER_ENABLED=true`, `CRON_SECRET=<new random value>`. Never a production value.

Web environment: `NEXT_PUBLIC_SITE_ENV=staging` (yellow banner, no search indexing), `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY` (staging publishable key),
`NEXT_PUBLIC_API_URL=https://sch-hub-api-staging.onrender.com`.

Supabase staging → Authentication → URL Configuration → Site URL = the staging web address.

## 4. Test

```bash
export STAGING_API=https://sch-hub-api-staging.onrender.com STAGING_WEB=https://sch-hub-web-staging.onrender.com STAGING_CRON_SECRET=…
backend/.venv/bin/python scripts/staging_bootstrap.py doctor                       # read-only, no FAIL expected
backend/.venv/bin/python scripts/staging_bootstrap.py info --info ~/sch-staging.json  # fresh sign-in tokens (they last about an hour)
backend/.venv/bin/python scripts/staging_smoke.py --ref $STAGING_REF --production-ref $PRODUCTION_REF   # Release A, needs a local API: see release-a-staging.md
cd /path/with/playwright && node <repo>/scripts/e2e_full.mjs ~/sch-staging.json ./out <gpu-python> <repo>/backend   # all journeys
```
`e2e_full.mjs` refuses the production addresses. With `ONLY=staging,setup,announcement,visa,admin,office` it needs no GPU computer. The first request wakes the
services (about a minute). Expect slower times than on the test computer: 0.1 CPU (see [RENDER-MEMORY.md](../development/RENDER-MEMORY.md)).

**Memory check on real Render (the one thing the test computer cannot prove).** Staging has the same 0.1 CPU / 512 MB as production. Write
the synthetic test PDFs (`backend/.venv/bin/python scripts/render_memory_test.py --write-pdfs --pdf-mb 3,9 --pdf-dir ~/sch-test-pdfs`: invented
Korean text, no real data), upload them as an administrator on the staging site (Admin → Knowledge Sources → new source → upload the PDF), approve them, and watch API
service → **Metrics → Memory** until the jobs finish (at 0.1 CPU a 9 MB PDF takes about 25 minutes). Pass: no restart in **Events** ("Out of memory"), memory stays under about 470 MB. Repeat once without
`MALLOC_ARENA_MAX` only if you want to see the difference; it was killed at 512 MB on the test computer.

## 5. Afterwards

Nothing to switch off: the services sleep. To end staging for good: Render → each staging service → Settings → Delete; Supabase → project → Pause (keeps
the data) or Delete. The second free Supabase project slot is free again once it is paused.

| Risk | Handling |
|---|---|
| a production value in a staging variable | `bootstrap` and `e2e_full` refuse production references and addresses; `doctor` shows which project is used |
| staging found by search engines | banner and `noindex` |
| staging uses production's free hours | auto-deploy off, no pings, sleep after 15 minutes |
| test data mistaken for real | every page says "Staging copy for tests" |
