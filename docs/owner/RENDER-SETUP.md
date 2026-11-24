# Render setup

Everything runs on the free plan. **Nothing here needs a payment.** (Older documents name paid plans as an option for a busy pilot; they are not required
and nothing depends on them.)

| | `sch-hub-api` | `sch-hub-web` |
|---|---|---|
| Root directory | `backend` | `apps/web` |
| Build | `pip install -r requirements.txt && python -m app.cli prefetch-model` | `npm ci && npm run build` |
| Start | `uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips="*"` | `npm run start` |
| Health check | `/health` | `/` |
| Branch | `main` | `main` |
| Deploys when | GitHub workflow calls the deploy hook after a push to `main` that touches `backend/` or `render.yaml` | the same for `apps/web/` or `render.yaml` |
| Memory | measured 391–410 MB after loading the model (Linux), limit 512 MB | about 100 MB |

## Walk through the dashboard

1. Each service → **Settings**: branch `main`; *Auto-Deploy* off or "On Commit" (not both hook and auto-deploy, or every push deploys twice);
   **Pull Request Previews off**.
2. API → **Environment**: compare with [ENVIRONMENT.md](ENVIRONMENT.md). Required: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `CORS_ORIGINS`. Production:
   `JOB_EXECUTION=worker`, `EMBEDDING_PROVIDER=e5_onnx`, `EMBEDDING_CACHE_DIR=.model-cache`, `RETRIEVAL_MIN_SIMILARITY=0.80`, `LLM_PROVIDER=gemini`, `LLM_API_KEY`.
   Must stay off until you approve them: `GPU_WORKER_ENABLED`, `AGENT_SCHEDULES_ENABLED`, `AUTO_TRANSLATE_ANNOUNCEMENTS`, `AUTO_TRANSLATE_DOCUMENTS`,
   `PUBLIC_MACHINE_TRANSLATIONS`.
3. Web → **Environment**: the three `NEXT_PUBLIC_*` values, all public.
4. **Verify:** `python -m app.cli doctor --api https://sch-hub-api.onrender.com --web https://sch-international-students-hub.onrender.com` (only GET requests).
   On 2026-11-25 this gave 10 of 10 PASS for the running services.

## Limits that matter

- **750 free instance hours a month for the whole workspace.** Services sleep after 15 minutes without requests; the first request then takes about a minute.
  Two services awake all month would need about 1,490 hours: never keep them awake artificially. The GPU worker is started by hand (`--drain`), not continuously.
- One API process with its own worker threads. Queued jobs survive a sleep or restart (durable queue).
- Large PDFs: text extraction needs about 140 MB more and can exceed 512 MB. Upload large PDFs one at a time, outside busy hours; a killed job is repeated.
- Do not add a second service "for staging" in the same workspace: it uses the same hours.

## Deploy and roll back

Deploy: merge to `main` (see [GITHUB-SETUP.md](GITHUB-SETUP.md)); watch Deploys → Logs: no migration runs by itself. Roll back: Deploys → the previous deploy →
**Rollback**, then GitHub → Actions → *Deploy to Render* → Disable workflow (otherwise the next push deploys the bad code again). Details:
[release-a-approvals.md](../release/release-a-approvals.md#production-rollback).
