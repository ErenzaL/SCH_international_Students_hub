# Hosted staging at zero cost

Read on the providers' pages on 2026-11-26: Supabase Free allows **2 active projects** (500 MB each, no backups, paused after 1 week without use).
Render gives **750 free instance hours per workspace and month**, free instances have **0.1 CPU / 512 MB**, sleep after 15 minutes without requests and use no
hours while asleep. The Hobby workspace (one per account) costs $0 plus compute; free compute is $0.

So staging = **a second free Supabase project + two more free Render services in the same workspace**. Asleep they cost nothing; a two-hour test
session uses about 4 of the 750 hours (two services). Never keep staging awake (no uptime pings, no continuous GPU worker): production shares the hours.

**Nothing below touches production.** Two steps publish or create something and need your approval: **pushing the branch `hub-staging`** (step 2) and
**creating the two services** (step 4). Everything else only reads or writes the new staging project. Every variable name below is checked against the
code by a test (`backend/tests/test_staging_doc.py`): a name that the API, the web app, Render or the staging scripts do not read fails the test.

**Which commit.** `staging/zero-cost-rag-memory` at `68d6ee0` is the accepted candidate and stays unchanged. `staging/hosted-checks` = `68d6ee0` plus
what decisions 7–9 asked for: the hardened bootstrap (production keys refused, synthetic data only), the ingestion concurrency limit, the read-only
runtime endpoint and the hosted memory check. **Recommended: deploy `staging/hosted-checks`.** If you prefer to deploy exactly `68d6ee0`, push it as
`hub-staging` and also push `staging/hosted-checks` (no service builds from it) as `hub-staging-tools` to run the tools of steps 3 and 5 from it; then memory, restarts and
concurrency are read by hand in Render (step 5d).

## 1. Supabase staging project (10 minutes, you)

| | Action | Check |
|---|---|---|
| 1 | supabase.com → **New project** → name `sch-hub-staging`, region **Northeast Asia (Tokyo)**, Free plan, a new database password (keep it in your password manager) | the project page opens |
| 2 | Project Settings → General → copy the **Project ID** = `STAGING_REF`. Your production project's ID = `PRODUCTION_REF` | they differ |
| 3 | Authentication → Sign In / Providers → **Email** on. *Confirm email* off is fine for staging (the made-up accounts are confirmed by the script) | – |
| 4 | Project Settings → **API Keys**: the **publishable** key and the **secret** key of *this* project. Do not use a production key: the script refuses it | – |
| 5 | **Connect** (top bar) → *Session pooler* → copy the connection string, put the database password into it | starts with `postgresql://postgres.<STAGING_REF>:` |

## 2. Push the branch `hub-staging` (needs your approval)

The branches exist only on the university server so far. There, after you confirm the commit author shown by
`git log -1 --format='%an <%ae>' staging/hosted-checks` (`Lin Erenza` with the GitHub no-reply address), run, or tell me to run:
```bash
git push origin staging/hosted-checks:refs/heads/hub-staging                       # recommended: one branch, services and tools
# alternative: git push origin 68d6ee0:refs/heads/hub-staging staging/hosted-checks:refs/heads/hub-staging-tools
```
(Not named `staging`: a branch `staging` cannot exist next to the `staging/…` branches.)
Only `main` triggers *Deploy to Render* (`.github/workflows/render-deploy.yml`), so this deploys nothing. No other workflow reacts to it.

## 3. Schema, synthetic data, made-up accounts (one command, on your computer, 5 minutes)

Not on the university server (no Supabase secrets there).

```bash
git fetch origin hub-staging && git switch --detach FETCH_HEAD    # alternative path: hub-staging-tools
cd backend && python3.11 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt && cd ..
export STAGING_REF=<staging project id> PRODUCTION_REF=<production project id>
export STAGING_SUPABASE_URL=https://$STAGING_REF.supabase.co
export STAGING_API=https://sch-hub-api-staging.onrender.com STAGING_WEB=https://sch-hub-web-staging.onrender.com
backend/.venv/bin/python scripts/staging_bootstrap.py all --info ~/sch-staging.json
```

It asks for `STAGING_DB_URL` (the connection string), `STAGING_SERVICE_KEY` (secret key) and `STAGING_ANON_KEY` (publishable key), never prints them.
**Before it writes anything it refuses:** equal references; a URL or connection string that names `PRODUCTION_REF`; a key of another project (legacy
keys name their project; new `sb_` keys are tried once, read-only, against the staging project); a secret key in the publishable slot or the reverse;
`STAGING_API` / `STAGING_WEB` that are production addresses; an account domain that is not a reserved example domain; a project with more than 50
profiles or more than 5 accounts outside `@sch-staging.example.com`.

**What it writes, all synthetic:** the 17 migrations (skips applied ones; safe to repeat), the seed (categories and two rows labelled *SAMPLE – TEST
DATA*), six made-up accounts `super_admin`, `admin`, `supporter_vi`, `reviewer_id`, `student`, `student2` `@sch-staging.example.com` with one random
password, kept only in `~/sch-staging.json` (mode 600). The seed's candidate official sources are registered but **switched off**, so staging fetches no
real website. Its last step, `doctor`, cannot reach the services yet; that is expected (step 5a repeats it).
Run `scripts/staging_bootstrap.py info --info ~/sch-staging.json` again before each test: sign-in tokens last about an hour.

## 4. Two Render services (15 minutes, needs your approval)

Render → **New → Web Service** → this repository, twice. Set the variables **before** the first build (the web app bakes `NEXT_PUBLIC_*` into the build).

| Field | `sch-hub-api-staging` | `sch-hub-web-staging` |
|---|---|---|
| Branch | `hub-staging` | `hub-staging` |
| Root directory | `backend` | `apps/web` |
| Runtime | Python 3 | Node |
| Build command | `pip install -r requirements.txt && python -m app.cli prefetch-model` | `npm ci && npm run build` |
| Start command | `uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips="*"` | `npm run start` |
| Instance type | **Free** | **Free** |
| Health check path | `/health` | `/` |
| Auto-Deploy | **Off** (Settings → Build & Deploy) | **Off** |
| Pull Request Previews | Off | Off |

**API environment** (copy exactly; values in angle brackets are yours):

| Variable | Value | Why |
|---|---|---|
| `ENVIRONMENT` | `staging` | shown by `doctor`; on Render the production rules still apply |
| `PYTHON_VERSION` | `3.11.9` | Render's Python version, as in `render.yaml` |
| `MALLOC_ARENA_MAX` | `2` | memory on 0.1 CPU ([RENDER-MEMORY.md](../development/RENDER-MEMORY.md)) |
| `SUPABASE_URL` | `https://<STAGING_REF>.supabase.co` | the staging project |
| `SUPABASE_SERVICE_ROLE_KEY` | `<staging secret key>` | server only |
| `CORS_ORIGINS` | `https://sch-hub-web-staging.onrender.com` | exact web address |
| `JOB_EXECUTION` | `worker` | durable queue, as in production |
| `INGESTION_MAX_CONCURRENT_JOBS` | `1` | one ingestion job at a time (the default; `staging/hosted-checks` only) |
| `EMBEDDING_PROVIDER` | `e5_onnx` | as in production |
| `EMBEDDING_CACHE_DIR` | `.model-cache` | model baked in at build time |
| `EMBEDDING_MODEL` | `intfloat/multilingual-e5-small` | as in production |
| `RETRIEVAL_MIN_SIMILARITY` | `0.80` | as in production |
| `LLM_PROVIDER` | `none` | no answers generated, no key needed. Later, for chat tests only: `gemini` with **a separate free key** in `LLM_API_KEY` |

Not set on staging (all off by default; each would bring real data or outside traffic in): `SUPABASE_JWT_SECRET` (new projects sign in with keys
the API reads from the project itself), `CRON_SECRET`, `AGENT_SCHEDULES_ENABLED`, `GPU_WORKER_ENABLED`, `AUTO_TRANSLATE_ANNOUNCEMENTS`,
`AUTO_TRANSLATE_DOCUMENTS`, `PUBLIC_MACHINE_TRANSLATIONS`. Never copy a value from the production services.

**Web environment:** `NEXT_PUBLIC_SITE_ENV=staging` (yellow banner on every page, no search indexing), `NEXT_PUBLIC_SUPABASE_URL=https://<STAGING_REF>.supabase.co`,
`NEXT_PUBLIC_SUPABASE_ANON_KEY=<staging publishable key>`, `NEXT_PUBLIC_API_URL=https://sch-hub-api-staging.onrender.com`.

Then Supabase staging → Authentication → **URL Configuration** → Site URL = `https://sch-hub-web-staging.onrender.com`.

If Render gives the services other addresses, use those everywhere above and in `STAGING_API` / `STAGING_WEB`; they must contain `staging`.

## 5. Verify (on your computer)

```bash
export STAGING_REF=… PRODUCTION_REF=… STAGING_SUPABASE_URL=https://$STAGING_REF.supabase.co STAGING_API=… STAGING_WEB=…
```

| | Command or action | Pass |
|---|---|---|
| a | `backend/.venv/bin/python scripts/staging_bootstrap.py doctor` (read-only) | no FAIL; it names the staging project |
| b | Open `STAGING_WEB` in a browser; sign in as `admin@sch-staging.example.com` with the password from `~/sch-staging.json` | yellow staging banner; admin pages open |
| c | `backend/.venv/bin/python scripts/staging_bootstrap.py info --info ~/sch-staging.json` then `backend/.venv/bin/python scripts/staging_memory_check.py ~/sch-staging.json --report ~/staging-memory.json` (about 60–90 minutes; keep the computer awake) | exit code 0, no FAIL; see below |
| d | Meanwhile in Render → `sch-hub-api-staging` → **Metrics → Memory** and **Events** | stays under about 470 MB; no "Out of memory", no unplanned restart |
| e | Browser journeys, optional: `ONLY=staging,setup,visa,admin,office node scripts/e2e_full.mjs ~/sch-staging.json ./out backend/.venv/bin/python backend` (needs Playwright; refuses production addresses). Not `announcement` or `career`: they read the live university board, which would bring real notices into staging | all PASS |

**What the memory check does** (only invented data, `scripts/synthetic_docs.py`): wakes the API, loads the model, uploads a 3 MB and a 9 MB synthetic
Korean PDF and 12 synthetic text documents (3,000–150,000 characters) at once, approves them so the indexing runs too, and every 20 seconds
measures `/health`, a search and `/api/v1/admin/system/runtime`. It signs in again by itself when the hour-long token expires.

| Check | Pass |
|---|---|
| uploads are asynchronous | every PDF upload answered within 30 s with 202; the work waits in the queue |
| all jobs succeeded | every extraction and indexing job `succeeded` |
| ingestion concurrency within the limit | never more running jobs than `INGESTION_MAX_CONCURRENT_JOBS` |
| API stays responsive / search usable | no failed `/health`; p95 ≤ 5 s; searches p95 ≤ 20 s |
| no restart | the instance id never changes (a restart after an out-of-memory kill would change it) |
| no out-of-memory kill | the container's `oom_kill` counter does not grow (also catches a killed PDF child process); SKIP if Render does not expose it: then step d |
| peak memory | ≤ 470 MB PASS, ≤ 512 WARN, above FAIL |
| memory recovers | after 3 minutes idle at least half of the rise is given back and ≤ 420 MB |
| nothing stuck | no running job without a heartbeat, no stuck queue, nothing unfinished, worker thread alive |
| `MALLOC_ARENA_MAX=2` is set | read back from the process |

Send me `~/staging-memory.json` (it holds no secret and no personal data: numbers, synthetic titles, job ids). With `68d6ee0` the memory, restart
and concurrency rows say SKIP: take them from step d.

**If a check fails:** a FAIL on memory, restarts or out-of-memory kills is the trigger for the fallback in
[INDEXING-OFFLOAD.md](../development/INDEXING-OFFLOAD.md); nothing changes in production either way.

## 6. Afterwards

Nothing to switch off: the services sleep. The synthetic documents stay on staging (titled "Synthetic test …"). To end staging for good: Render → each
staging service → Settings → Delete; Supabase → project → Pause (keeps the data) or Delete; `git push origin --delete hub-staging` (approval).

| Risk | Handling |
|---|---|
| a production value in a staging variable | `bootstrap`, `staging_memory_check` and `e2e_full` refuse production references, keys and addresses; `doctor` shows which project is used |
| real data in staging | only synthetic documents and made-up accounts; candidate official sources switched off; schedules, cron and GPU worker not set |
| staging found by search engines | banner and `noindex` |
| staging uses production's free hours | Auto-Deploy off, no pings, sleep after 15 minutes; a full memory test uses about 3 hours (two services) |
| test data mistaken for real | every page says "Staging copy for tests" |
