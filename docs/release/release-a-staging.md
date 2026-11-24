# Release A: staging smoke test

There is no staging environment. Two stages; the second needs the owner's approval because it creates a project.

| Stage | Where | Cost | State |
|---|---|---|---|
| 1 | local database, real API, real web build | 0 | **done**: 14 of 14 (script), 23 of 23 (browser), 30 (integration) |
| 2 | a separate **free** Supabase project, API and web app on the owner's computer | 0 | **not done** |

Render is not part of staging: free instance hours are shared by all services of a workspace, so a second service could use up those of
production. Render is checked by the production checks right after the deployment.

Stage 2 answers what stage 1 cannot: hosted login, hosted access rules, hosted API gateway.

## Stage 2 (about 60 minutes)

**Rules.** Synthetic users and text only; the only real content is a few public notices. A new password and keys of *this* project only. No
copy of production data. No `LLM_API_KEY`: `LLM_PROVIDER=none`. Not on the university server. If the free plan has no room for another
project, **stop**: do not pause or delete a project for it, and do not upgrade.

1. Supabase → new project `sch-hub-staging`, free plan. Write down its reference (`STAGING_REF`) and the production one (`PROD_REF`).
2. Use a **fresh clone** with `release/a-approved-source` checked out: the API reads `backend/.env` *and* `.env`, the web app `.env.local`, and in the
   working copy these can point to production. `ls -a . backend apps/web | grep -E '^\.env'` must print `.env.example` only. Create the tables (bash):
   ```bash
   ls supabase/migrations | wc -l          # 15, the last one ends with 0015_official_source_discovery.sql
   read -rs -p 'STAGING connection string: ' DB; echo
   case "$DB" in *"$STAGING_REF"*) ;; *) echo "not staging, stop"; DB=;; esac
   for f in supabase/migrations/*.sql supabase/seed.sql; do psql "${DB:?}" -q -v ON_ERROR_STOP=1 -f "$f" || break; done
   unset DB
   ```
3. Authentication → add the user `admin@example.test` (auto-confirm). SQL editor of **staging**:
   `update public.profiles set role = 'super_admin' where id = (select id from auth.users where email = 'admin@example.test');`
4. API, in a new terminal of that clone (values are typed, no `.env` file):
   ```bash
   cd backend && python3.11 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
   export SUPABASE_URL=https://$STAGING_REF.supabase.co LLM_PROVIDER=none EMBEDDING_PROVIDER=hash JOB_EXECUTION=worker
   export CORS_ORIGINS=http://localhost:3000
   read -rs -p 'STAGING service key: ' SUPABASE_SERVICE_ROLE_KEY; export SUPABASE_SERVICE_ROLE_KEY
   # only if the project signs with a shared secret (Settings → JWT):  read -rs SUPABASE_JWT_SECRET; export SUPABASE_JWT_SECRET
   .venv/bin/uvicorn app.main:app --port 8000
   ```
5. The script, in another terminal. It refuses a remote API, the production project, and a project with other public documents:
   ```bash
   read -r -p 'STAGING anon key: ' STAGING_ANON_KEY; export STAGING_ANON_KEY
   export STAGING_API=http://127.0.0.1:8000 STAGING_SUPABASE_URL=https://$STAGING_REF.supabase.co STAGING_ADMIN_EMAIL=admin@example.test
   backend/.venv/bin/python scripts/staging_smoke.py --ref "$STAGING_REF" --production-ref "$PROD_REF" \
     --board 'https://sgee.sch.ac.kr/notice/notice01.php?table_name=noti_fore'
   ```
   It prints two SQL statements to run in the **staging** SQL editor. Expected: `14/14 passed`. "no notice has attachments": another official board.
6. Both checks from `supabase/checks/` in the staging SQL editor: they run, and the attachment check lists the row the script names.
7. Browser (`cd apps/web && npm ci`, with `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY` of staging and
   `NEXT_PUBLIC_API_URL=http://localhost:8000`, then `npm run dev`): sign in as admin; open the review queue; submit a text, approve it, open the
   public page; sign out; the admin pages ask for a login. Korean and English; once at phone width.
8. **Rollback rehearsal:** stop the API, `git switch --detach eca1d71`, start it, open the same documents and approve one; switch back, start, run
   step 5 again. Expected: no error in either direction.
9. Write down: date, name, head commit, result of every step. Then stop the API, close the terminals (keys), delete
   the clone. Deleting the staging project is a separate decision of the owner.

**Stop** and do not merge when a check fails, when an unapproved title, text or attachment is visible anywhere, or when a step needs
production data or keys.

Not covered by stage 2: Render's start and memory, the production embedding model, a real Gemini request, real data volume.
