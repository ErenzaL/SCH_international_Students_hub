# Supabase setup

Free plan is enough: 500 MB database (production held 23 MB on 2026-11-24). The free plan makes **no automatic backups** and pauses a project after a
week without use. Production and staging are **separate projects**. Never run a production step with a staging key or the other way round.

## 1. Which project

Dashboard → the project whose address is `SUPABASE_URL` of the Render API service. Write down its reference (`Settings → General`).

| Look at | Must be |
|---|---|
| Project Settings → API | URL, publishable/anon key (public), secret/service_role key (secret) |
| Project Settings → JWT Keys | asymmetric keys: nothing to copy. Legacy HS256: copy to `SUPABASE_JWT_SECRET` |
| Authentication → URL Configuration | Site URL and redirect URLs = the website |
| Authentication → Providers | Email on |
| Storage | bucket `source-files`, **private** (migration 0005 creates it; no storage policies are needed, the API streams files) |
| Database → Extensions | `vector`, `pg_trgm` (migrations enable them). **`pg_cron` is not used** |

## 2. Migrations, in this order

| Migration | State of production (read-only check 2026-11-24) | Needed for |
|---|---|---|
| 0001 … 0015 | 0001–0015 expected; confirm with `doctor` | Release A and the current site |
| `20261124000016_gpu_worker.sql` | **not applied** | Release B (GPU worker) |
| `20261125000017_agent_operations.sql` | **not applied** | monitoring of five more desks, pause, storage page, job APIs |

0016 and 0017 are additive and independent of each other; the code runs without both. Each has a tested rollback in `supabase/rollback/`.
Tested: 0001→0015, →0016, →0017, rollback and forward again, and the old code (`main`) on the new schema.

**Check (read-only):**
```bash
cd backend && SUPABASE_URL=… SUPABASE_SERVICE_ROLE_KEY=… SUPABASE_ANON_KEY=… python -m app.cli doctor
```
It only sends GET requests and never prints a key. Every migration must be `PASS` (0016/0017 may be `NOT TESTED` until you apply them).

**Apply (changes the schema; needs your approval; backup first):** SQL Editor → paste the **whole** file → Run → `Success`. Or
`psql "$DB" -v ON_ERROR_STOP=1 -f supabase/migrations/<file>`. Then run `doctor` again. If it fails: nothing is half applied when you use
`psql -1`; otherwise run the file in `supabase/rollback/` of the same number.

| SQL | Kind |
|---|---|
| `supabase/checks/*.sql` | read-only, one SELECT each |
| `supabase/migrations/*.sql` | **changes the schema** |
| `supabase/rollback/*.sql` | **changes and deletes** what the migration added |
| `supabase/seed.sql` | **writes** categories and sample rows (staging; production already has categories) |
| `supabase/tests/*.sql` | only on a scratch database |

## 3. First super administrator (writes one row)

Sign up on the website, then SQL Editor:
```sql
update public.profiles set role = 'super_admin' where id = (select id from auth.users where email = 'YOUR-ADDRESS');
```
Verify: sign in → *Admin* appears. Everybody else is managed in the interface ([ROLES-AND-REVIEWERS.md](ROLES-AND-REVIEWERS.md)).

## 4. How the data flows

| Question | Answer |
|---|---|
| Knowledge Center → RAG | an approval starts an `index_version` job: chunks + vectors → `searchable_chunks` view (approved, current, not withdrawn, inside its dates) → `search_knowledge_v2` |
| Announcements → RAG | publishing an announcement approves its document version; the same path |
| Agent tasks | `agent_tasks` + `agent_task_events`; schedules in `agent_schedules` (all off); pauses in `agent_controls` (0017) |
| Discovered items | `discovery_sources`, `discovered_items`: candidates, never searched |
| Jobs and the GPU queue | `ingestion_jobs` (`executor` = `local` or `gpu`, 0016); credentials as hashes in `gpu_workers` |
| Row level security | on for every table; browser keys read only published content and their own rows. Private tables have no policy at all. `doctor` with `SUPABASE_ANON_KEY` proves it |

## 5. Usage, backup, restore

- Size: Admin → Agents → Storage (needs 0017), or Dashboard → Reports. Measured: about **35 KB of database per 1,000 characters** of indexed text (vectors and
  their index are most of it); 27 documents = 13 MB.
- **Backup** (your own computer, before every migration and release):
  `pg_dump "$DB" -Fc --no-owner -f sch_$(date +%Y%m%d).dump`, encrypted, not on the university server. Check it: `pg_restore -l file | head`.
- **Restore drill** into a *new* project: `pg_restore --no-owner -d "$NEW_DB" file`. Never restore over production for a code problem.
- Files in Storage are not in the dump: download the bucket separately.

## Staging

A second free project: [release-a-staging.md](../release/release-a-staging.md). Use all migrations there, then run `doctor`, `scripts/staging_smoke.py` and the
checks. It costs nothing; the free plan allows two active projects.
