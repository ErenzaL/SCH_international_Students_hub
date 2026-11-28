# Activating the university GPU translation worker in production

Who does what: **you** (the owner) do every production step below. Nothing here was done to production: no push, no
deploy, no migration, no setting, no credential. Background: `docs/final-release/ANNOUNCEMENT-TRANSLATION.md`.

```
University workstation (RTX 4070)                         Render (API)                         Supabase
  Ollama 127.0.0.1:11434 (never exposed)                   sch-hub-api.onrender.com             (service role:
  translategemma:12b                                        /api/v1/gpu/* (worker token only)    only the API)
  python -m app.gpu_worker  ── outbound HTTPS only ──────▶  claim / heartbeat / complete / fail
  token file (600), no Supabase or Gemini key               Gemini: chat + agents only
```

## 0. What must be true first

| # | Item | Status on 2026-11-28 |
|---|---|---|
| 0.1 | University IT approves the use described in §7 of ANNOUNCEMENT-TRANSLATION.md (GPU use, outbound HTTPS to `sch-hub-api.onrender.com`, a revocable credential on the workstation, public text only) | **open** (you) |
| 0.2 | Branch `feature/announcement-auto-translation` is merged into `main`: production `main` (1fe8cb7) does **not** have TranslateGemma-only routing, the model check, the expiry policy or the publication language choice | **open** (you, after review) |
| 0.3 | Migration 0016 on production | **unknown**: run the readiness SQL (step A2) |
| 0.4 | Native reviewers assigned for English and Indonesian (Admin → Language teams) | open |

## Step A: code and database (worker still off)

A1. **Backup** on your own computer (never on the school server). Use the connection string from Supabase → Project
Settings → Database. Prefer the session pooler on port 5432, and use a `pg_dump` at least as new as the server:

```bash
pg_dump "<connection string>" -Fc -f sch-hub-before-0016-$(date +%F).dump
pg_restore --list sch-hub-before-0016-*.dump | head        # proof the file is readable
```

A2. **Readiness, read-only.** In Supabase → SQL Editor, run `docs/owner/sql/check-gpu-worker-readiness.sql`.
- All 20 rows `true` → 0016 is complete; skip A3.
- Rows `false` → apply A3.

A3. **Apply 0016** in one transaction (it is additive and idempotent: it was applied twice on a 0015 copy here and
passed the integration suite, 112 passed / 0 failed). Either:
- `psql "<connection string>" --single-transaction -v ON_ERROR_STOP=1 -f supabase/migrations/20261124000016_gpu_worker.sql`
- or, in the SQL Editor, type `begin;`, paste the **whole** file, type `commit;`, and run.

Then run A2 again: 20 × `true`. Rollback: `supabase/rollback/20261124000016_gpu_worker_down.sql` (read its header first).

A4. **Merge** the branch (GitHub → pull request → *Create a merge commit*). This deploys the API and the website. Leave
`GPU_WORKER_ENABLED` unset or `false` for now. Check that a published announcement still opens, and that its
Machine-translate panel says the GPU worker is switched off.

## Step B: credential and connection test (nothing is routed yet)

B1. **Render → sch-hub-api → Environment**:

| Variable | Value |
|---|---|
| `GPU_WORKER_ENABLED` | `true` |
| `GPU_WORKER_JOB_TYPES` | *(empty: no job is routed to the worker in this step)* |
| `ANNOUNCEMENT_TRANSLATION_MODEL` | `translategemma:12b` |
| `TRANSLATION_FALLBACK_TO_GEMINI` | `false` |
| `GPU_WORKER_MODELS` | `translategemma:12b` |
| `GPU_WORKER_MAX_RUNNING` | `1` |
| `GPU_WORKER_ANNOUNCEMENT_MAX_WAIT_HOURS` | `168` (7 days; `0` = wait however long) |
| `GPU_WORKER_ON_EXPIRY` | `fail` |
| leave unchanged | `LLM_PROVIDER=gemini`, `LLM_API_KEY`, `GEMINI_*`, `TRANSLATION_MODEL` (documents only) |

Save → Render restarts the API (about a minute).

B2. **Workstation, one-time setup** (your account; no root, no open port):

```bash
cd ~/projects/SCH_international_Students_hub && git fetch && git checkout main && git pull   # the merged code
uv venv --python 3.11 ~/sch-gpu/venv                       # the worker needs Python 3.11+ (the system python3 is 3.10)
uv pip install --python ~/sch-gpu/venv/bin/python -r backend/requirements-gpu-worker.txt       # httpx only
install -d -m 700 ~/.config/sch-gpu-worker
install -m 600 backend/gpu-worker.env.example ~/.config/sch-gpu-worker/env
nano ~/.config/sch-gpu-worker/env          # set GPU_WORKER_TOKEN_FILE=/home/<you>/.config/sch-gpu-worker/token
```

Contents of `~/.config/sch-gpu-worker/env`. Mode must be 600; no token and no Supabase or Gemini value in it:

```
GPU_WORKER_HUB_URL=https://sch-hub-api.onrender.com
GPU_WORKER_PRODUCTION_HOST=sch-hub-api.onrender.com
GPU_WORKER_TOKEN_FILE=/home/<you>/.config/sch-gpu-worker/token
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=translategemma:12b
GPU_WORKER_PROMPT_STYLE=auto
GPU_WORKER_MIN_FREE_VRAM_MB=9500
GPU_WORKER_IDLE_MIN_SECONDS=300
GPU_WORKER_IDLE_MAX_SECONDS=3600
# GPU_WORKER_ACTIVE_HOURS=9-18
```

B3. **Register the worker. The token is shown once; it must never go into a chat, an e-mail, a ticket or a
repository.**
1. In your browser, signed in as a **super administrator**: Admin → **GPU worker** → name `school-gpu` → **Create**.
2. Copy the token from that page once.
3. In a terminal **on the workstation** (your own SSH or VS Code session), run `scripts/gpu_worker_token.sh` and paste
   the token when asked. Input is hidden; it writes `~/.config/sch-gpu-worker/token` with mode 600 and refuses
   anything that is not a worker token.
4. Back in the browser, press **Hide**. Clear the clipboard.

The token only opens the four `/api/v1/gpu/*` calls of this worker. It is stored on the server as a SHA-256 hash,
expires after 90 days, and can be paused, revoked or rotated in the same page.

B4. **Connection test** (no content can flow; there are no job types yet):

```bash
cd ~/projects/SCH_international_Students_hub
scripts/gpu_worker.sh --check     # Ollama, model, token file, GPU memory; contacts nothing else
scripts/gpu_worker.sh --once      # contacts the API over HTTPS: expect "idle", exit 0
```

Admin → GPU worker should now show `school-gpu` with *last contact: just now*. If `--once` exits with **77**, the
token was rejected; with **78**, the configuration is wrong (the message says what).

## Step C: authorized end-to-end test in production (needs 0.1 and 0.4)

C1. Render: `GPU_WORKER_JOB_TYPES=translate_announcement`. **Not** `translate_document`: document translation stays
off the GPU.

C2. Admin → Announcements → an already **published** announcement → Translations → **Bahasa Indonesia** → **Machine-translate**.
The panel shows *Queued for translategemma:12b on the university GPU*.

C3. On the workstation: `scripts/gpu_worker.sh --once`. The log shows `claimed ko->id` and `status=succeeded`. The panel
shows **Needs review**, with the draft loaded.

C4. The Indonesian reviewer compares it with the original and checks dates, times, fees, links and contacts.
- Only if it is correct: tick *I verified…* → **Approve & publish**. The student page in Indonesian shows it.
- Otherwise: reject or edit. Nothing has reached students.

C5. Write down the result (date, announcement, time, reviewer). That is the authorized end-to-end test. **Only now** go
on to D.

## Step D: everyday use

| Task | Command / place |
|---|---|
| Translate everything waiting, then stop (recommended) | `scripts/gpu_worker.sh --drain` |
| One job | `scripts/gpu_worker.sh --once` |
| Continuous, only after IT approved it | `scripts/gpu_worker.sh` inside `GPU_WORKER_ACTIVE_HOURS`; or the systemd **user** unit `backend/gpu-worker.service.example` (instructions inside). It keeps the free Render instance awake while it polls. |
| New announcement | Admin → Announcements → New → **Automatic translation**: tick English / Indonesian (the original is excluded) → submit → after **Approve & publish** the drafts are queued |
| Existing announcements | the announcement's *Automatic translation* card → *Save and translate missing*; or Admin → Translations → *Missing translations* → Preview → Queue (at most 50) |
| Stop | Ctrl+C (the job is handed back) · Admin → GPU worker → Pause / Revoke (immediate) · Render `GPU_WORKER_ENABLED=false` |
| Rotate the token | Admin → GPU worker → New token → `scripts/gpu_worker_token.sh` (no restart) |

## When the worker is offline (explicit policy)

- Jobs stay **queued**. The panel says *Waiting for the GPU worker* and gives the last contact. Admins get one alert a
  day. Publication, the website and chat are not affected.
- **No paid model is used** (`TRANSLATION_FALLBACK_TO_GEMINI=false`): this is enforced at routing, in the sweep and in
  the API's job runner.
- After `GPU_WORKER_ANNOUNCEMENT_MAX_WAIT_HOURS` (7 days) a waiting job ends visibly ("not fetched in time"), and
  **Translate again** queues a new one.
- **Worker crash:** the lease ends after 3 minutes and the job is queued again; a late result is discarded.
- **GPU busy** (another user holds the memory): the worker takes no job and uses no attempt.
- **Model error or out of memory:** retried with backoff, at most 3 attempts, then *Failed – retry available*.
- **Token expired or revoked:** the worker stops (exit 77) and takes nothing.

## Rollback

1. Render `GPU_WORKER_JOB_TYPES=` (empty) or `GPU_WORKER_ENABLED=false`. New requests are refused with the reason;
   waiting jobs end with the next sweep (within the hour).
2. Admin → GPU worker → **Revoke**. On the workstation, delete `~/.config/sch-gpu-worker/token`.
3. Code: redeploy the previous `main` commit in Render. Database: 0016 can stay (additive); to remove it, use
   `supabase/rollback/20261124000016_gpu_worker_down.sql`, after the backup from A1.
