# Setup

## 1. Requirements

* Node.js 20+ and npm
* Python 3.11+
* A Supabase project (https://supabase.com, free tier) – or skip it to explore the unconfigured states
* Optional: ~1 GB disk for PyTorch (CPU) + the E5 model (~470 MB, downloaded on first embedding)

## 2. Install and run locally

```bash
cd backend
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pip install -r requirements-ml.txt      # skip to run with EMBEDDING_PROVIDER=hash (lexical, dev only)
uvicorn app.main:app --reload --port 8000
```
```bash
cd apps/web
npm install
npm run dev
```

The API loads the embedding model **lazily** (first ingestion/search), never at startup, and `/health` never touches it.

## 3. Create the Supabase project and apply the migrations

1. Supabase dashboard → New project. Save the DB password somewhere safe.
2. Project Settings → API: copy the **Project URL**, the **publishable/anon key**, and the **secret/service-role key**.
3. Apply the SQL, in order, from `supabase/migrations/` (SQL Editor, or `supabase link --project-ref … && supabase db push`):
   `20260101000001_core_profiles.sql` … `20260101000005_rls_and_grants.sql`.
   They enable `vector` and `pg_trgm`, create tables, triggers, RLS and the private `source-files` bucket.
4. Optional dev data: run `supabase/seed.sql` (categories, six *candidate* source registrations – nothing fetched –,
   one sample announcement and one sample pending document, both labelled TEST DATA). Categories are required;
   the sample rows are optional and can be deleted.
5. Authentication → Providers: enable Email. For local testing you may disable "Confirm email".

> The migrations were validated on PostgreSQL 18 + pgvector 0.8 with a Supabase shim, **not** on a hosted
> Supabase project (none was available while building). Run them on a fresh project and report any difference.

## 4. Configure environment variables

Copy `.env.example`. Backend (server only): `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_SECRET`
(only for legacy HS256 projects), `CORS_ORIGINS` (alias `CORS_ALLOWED_ORIGINS`), `ALLOWED_SOURCE_DOMAINS`, `EMBEDDING_*`, `LLM_*`.
Web (`apps/web/.env.local`): `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `NEXT_PUBLIC_API_URL`.
The service-role key must never appear in a `NEXT_PUBLIC_*` variable.

## 5. Bootstrap the first super_admin (manual, secure)

New users are always `student`; nobody becomes admin automatically and the browser cannot change roles
(trigger + column grants + RLS). Sign up through `/login`, then in the Supabase **SQL Editor** (which runs as a
privileged role, not as an end user):

```sql
update public.profiles set role = 'super_admin'
where id = (select id from auth.users where email = 'you@example.com');
```

Sign in again and open `/admin`. Super admins can then promote others in *Users & Roles*. Assign supporters their
languages there too (needed for translation review).

## 6. Register a website source, ingest, approve, search

1. `/admin/sources` → **Add Source**: type *website*, the exact official URL (must be on the allowlist), category, scope.
2. **Fetch Now** → a job id is returned immediately; the page polls it. Real results/errors are shown
   (robots.txt, HTTP 403, empty extraction, …). If a site blocks automation use **Submit text** or **Upload** instead.
3. **View Extracted Content** / `/admin/documents/<id>` shows the proposed version, the diff to the approved one,
   the chunks and their embedding state. **Approve** (or Reject with a reason). Approval embeds missing chunks first.
4. Test retrieval (only approved, current, in-window content is returned):
   ```bash
   curl -s localhost:8000/api/v1/knowledge/search -H 'content-type: application/json' \
     -d '{"query":"D-2 visa extension","top_k":5}' | python -m json.tool
   ```
5. Manual SCH notices: `/admin/announcements/new` → Save draft → Submit → an admin Approves.

## 7. Verify things yourself

```bash
cd backend && pytest && ruff check .
python scripts/check_sources.py              # tests the six candidate URLs one by one (network)
EMBEDDING_PROVIDER=e5 python scripts/demo_pipeline.py   # offline demo with real network + real E5
./scripts/run_sql_tests.sh scratch_db        # needs a scratch PostgreSQL with pgvector; DROPS that database
```

**Integration test (real SupabaseStore → PostgREST → PostgreSQL)** – optional, no Docker needed:
install `postgresql@18`, `pgvector`, `postgrest` (Homebrew), load `scripts/local_supabase_shim.sql`, the migrations
and seed into a scratch DB, start PostgREST with the same JWT secret as the test, run
`python scripts/dev_rest_proxy.py`, then
`SCH_IT_REST_URL=http://127.0.0.1:54331 SCH_IT_PSQL="psql -h localhost -p 54329 -U postgres -d hub -q -t -A" pytest tests/integration`.

## 8. Deploy to Render (not done automatically)

`render.yaml` defines two web services. I have **not** deployed anything; this needs your Render account.

1. Push the repo to GitHub. Render → New → Blueprint → pick the repo → apply.
2. Backend `sch-hub-api`: set `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_SECRET` (if HS256),
   `CORS_ORIGINS=https://<web-service>.onrender.com`. Build: `pip install -r requirements.txt -r requirements-ml.txt`.
   Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers`. Health: `/health`.
3. Web `sch-hub-web`: set the three `NEXT_PUBLIC_*` variables (`NEXT_PUBLIC_API_URL` = the API URL from step 2, without `/api/v1`). These are inlined at build time, so use *Manual Deploy → Clear build cache & deploy* after changing them; a restart is not enough. Build `npm ci && npm run build`
   (no model download). Start `npm run start`.
4. Supabase → Authentication → URL configuration: add the web URL to Site URL / redirect URLs.
5. **Memory:** Render free web services have 512 MB. PyTorch + E5-small can exceed that when loaded.
   Options: use a paid instance for the API, or set `EMBEDDING_PROVIDER=hash` (not semantic; lexical only), or
   run ingestion locally against the same Supabase project and keep the API on keyword search (automatic
   fallback with an explicit warning). A hosted/ONNX embedding provider can be added behind the same interface.
6. Free instances sleep: the first request after idle is slow, and background ingestion tasks can be lost if the
   instance stops mid-job – such jobs are marked `failed: interrupted` on restart and can be retried. Scheduled
   syncs must come from an external scheduler (`python -m app.cli run-due`, see the commented cron in `render.yaml`).


## Phase 2 setup

1. Apply `supabase/migrations/20261122000006_knowledge_intake.sql` (additive; review it first):
   `supabase db push` from a linked project, or paste it into the SQL editor.
2. Backend environment (Render > sch-hub-api > Environment): `JOB_EXECUTION=worker`, `CRON_SECRET=<long random>`,
   optionally `OCR_PROVIDER=ocr_space` + `OCR_SPACE_API_KEY`. Redeploy.
3. GitHub > Settings > Secrets and variables > Actions: add `CRON_SECRET` (same value) for scheduled syncs.
4. Local OCR (optional): `brew install tesseract` and download `kor.traineddata` (tessdata_best) into a tessdata
   folder; run the backend with `OCR_PROVIDER=tesseract TESSDATA_PREFIX=<folder>`.
5. End-to-end check against a local stack: `scripts/e2e_phase2.py` (see its docstring).
