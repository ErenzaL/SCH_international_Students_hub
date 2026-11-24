# GPU worker: production readiness (2026-11-24)

Branch `feature/school-gpu-worker`, based on `main` `eca1d71`. **Nothing has been pushed, deployed, migrated or enabled.**
Operation and installation: [docs/gpu-worker.md](../gpu-worker.md).

## 1. Verdict

| Question | Answer |
|---|---|
| Deploy the backend with the feature **off**? | Technically ready, after approvals A1–A4 |
| **Enable** the worker for one manual pilot translation? | Not yet: B1–B4 are open |
| Use drafts without a native reviewer? | **No** (section 4) |
| Real-time Qwen chat | Not in scope, not recommended ([assessment](../gpu-gateway-assessment.md)) |

### Blockers

| # | Blocker | Blocks | Who |
|---|---|---|---|
| B1 | University IT has not confirmed that this account may run an outbound worker that uses the GPU | enabling | IT |
| B2 | No native speaker has reviewed drafts. Drafts that pass every check contain serious wording errors (section 4) | enabling beyond the pilot | reviewers for en, id, vi, zh-CN |
| B3 | The term list ([glossary.py](../../backend/app/gpu_worker/glossary.py)) was written by an AI assistant and is unconfirmed | enabling beyond the pilot | reviewers, international office |
| B4 | Production has no automatic backup (pilot plan, risk 1). Migration 0016 needs a manual `pg_dump` first | migrating | project owner |
| B5 | Not verified here: hosted Supabase, Render, the web frontend (no Node on this server), live Gemini | deploying | project owner |
| B6 | Branch not reviewed by a second person | merging | project owner |

### Approvals needed

| # | Approval | From |
|---|---|---|
| A1 | Merge and push the branch | project owner |
| A2 | Backup taken and stored off the university server; apply migration 0016 | project owner |
| A3 | Deploy with `GPU_WORKER_ENABLED` unset | project owner |
| A4 | Accept the Gemini behaviour change in section 5 | project owner |
| A5 | Outbound worker on the university account and GPU | university IT |
| A6 | Create a worker credential; set `GPU_WORKER_ENABLED=true` for the pilot | project owner (super admin) |
| A7 | The pilot announcement, the language and its reviewer | announcement owner, reviewer |
| A8 | Anything persistent (service, timer, more jobs) after the pilot | project owner and IT |

## 2. Test results

| Check | Result |
|---|---|
| Backend tests (mocked; each code commit of the first series was tested separately) | see section 11 |
| Integration tests on a fresh PostgreSQL 17 + PostgREST, migration 0016 applied | 89 passed, 9 skipped (live services) |
| **Old code** (`main`) on the **new** schema | 27 passed, 9 skipped |
| **New code, feature off, on the old schema** (0016 not applied) | 84 passed, 9 skipped |
| SQL behaviour tests | 12 of 12 files |
| End to end: real GPU, separate worker process, synthetic data | 20 of 20 |

Not run: browser tests, hosted Supabase, Render, live Gemini.

## 3. Why only 5 of 8 drafts passed

The three failures were reproduced exactly. **None changed a fact.**

| Draft | Flag | Cause | Where |
|---|---|---|---|
| scholarship → en | `number 12` missing | `2026-12-01` became "December 01, 2026" | model ignores "copy dates exactly" + rule cannot read month names |
| scholarship → id | `number 12` missing | the same ("01 Desember 2026") | model + rule |
| scholarship → zh-CN | `url_added` | Chinese text directly after a URL was read as part of it | parsing in the validation rule |

The same 8 drafts with 5 seeds (40 drafts): 24 passed. Of the 16 flagged, 15 were validation rules only and 1 was a real language error.

On **real** notices the picture is worse in both directions. Of 104 drafts, 69 were flagged (44 without any measured
error), and 3 of the 35 that passed contained measured errors:

| Cause (a draft can have several) | Drafts | Kind |
|---|---|---|
| dates, amounts, times in another form | 44 | validation rule |
| model added Markdown headings | 33 | prompt not followed; harmless |
| numbers lost, changed or added | 12 + 9 | model |
| table rows changed | 7 | model; often harmless |
| blank lines merged | 7 | validation rule |
| Chinese or Korean left in the draft | 7 | model |
| list items dropped | 3 | model |
| URL text added or changed | 3 + 2 | parsing and model |
| instructions repeated as content | 1 flagged (4 drafts in all) | prompt |
| **wrong weekday** | 16 drafts, not checked at all | model; missing rule |

Worst real errors in the first version: the section with the fines missing from the illegal-work notice (id, vi), an
"English" draft in Chinese, an invented deadline (23:59 instead of 18:00), 31 of 43 Vietnamese weekdays wrong, "hotel" for
dormitory.

Fixed for local models only (Gemini's prompts and checks are unchanged): exact renderings of dates, weekdays and amounts are
given to the model; a term list; 1,200-character parts; prompt examples removed; `<…>` lines neutralised; up to two repairs;
wrong-language drafts refused (`llm_malformed`, retried by the queue); checks for weekdays, list items, leaked instructions.

## 4. Benchmark on real announcements

26 public, non-sensitive SCH notices (each read by the AI assistant, not by a person, before selection) and 10 **held-out**
notices that were not used for tuning. Texts stay in a git-ignored cache; the repository has only URLs and hashes.

```bash
cd backend
.venv/bin/python ../scripts/build_announcement_corpus.py                          # rebuild from the manifest
.venv/bin/python ../scripts/bench_announcements.py --name improved
.venv/bin/python ../scripts/bench_announcements.py --name heldout_improved --set heldout
```

| | before (26) | after (26) | before (held-out) | **after (held-out)** |
|---|---|---|---|---|
| drafts | 104 | 103 + 1 refused | 40 | 39 + 1 refused |
| without any measured error | 76 | 93 | 24 | **36** |
| dates | 274/276 | 272/272 | 102/104 | **101/101** |
| weekdays | 198/237 | 305/305 | 60/77 | **95/95** |
| times | 132/132 | 130/130 | 28/28 | **27/27** |
| money | 44/48 | 48/48 | 16/16 | **16/16** |
| links, mail, phone | 60/60 | 60/60 | 24/24 | **24/24** |
| administrative terms | 142/168 | 164/165 | 23/36 | **33/34** * |
| proper nouns | 105/144 | 135/141 | 16/24 | **23/24** * |
| drafts with missing items | 4 | 3 | 4 | **2** |
| drafts with unsupported numbers / links | 5 / 1 | 5 / 0 | 1 / 0 | **1 / 0** |
| drafts with leaked instructions | 4 | 0 | 1 | **0** |
| drafts with Korean or stray Chinese | 8 | 2 | 3 | **0** |
| measured errors the checks missed | 3 | 0 | 6 | **0** |
| correct drafts flagged | 44 | 16 | 17 | **8** |
| median / p95 / slowest (seconds) | 7.2 / 17.4 / 24.1 | 5.3 / 16.7 / 21.7 | 5.6 / 11.4 / 13.6 | **4.9 / 10.3 / 11.8** |

Per language, after, held-out (without measured error): en 9/9 (+1 refused), id 8/10, vi 10/10, zh-CN 9/10.

\* Circular: the term list is both the help and the measure. Read these two rows as "the list is followed".

GPU: 5.6 GB of 12.3 GB peak, 98 % utilisation, about 199 W while generating.

**What the numbers do not show.** The drafts were not reviewed by native speakers. A reading of seven improved drafts by
the AI assistant found, in drafts that pass every check: "Polda" (police) for the immigration office and a Dutch phrase in the
Indonesian illegal-work notice; an English draft that changes which students are exempt from the health check; "hotel" for
dormitory in a Vietnamese title. One seed was used per configuration. The scorer was written by the same author as the fixes.

## 5. One approved-source rule for both providers

Before: the Gemini path read `document_versions` in state draft / pending of a published announcement, and documents were not
re-checked at run time. Now, for **every** provider, before generating **and** before storing: the announcement is published and
the text equals what students see; the document version is current, approved and public (not archived, withdrawn, inactive or
private); the title did not change meanwhile; a person's later work is never replaced, also with "force".

Behaviour change to accept (A4): reviewers of a published announcement with a waiting edit now see the **approved** text as the
original. Jobs for hidden documents fail with `source_not_public`. Failed announcement translations get their own alert
instead of "Sync failed".

Open and unchanged: re-ingestion updates a document's **title** before the new version is approved (existing behaviour of
`_find_or_create_document`; the public page shows that title too). Decide separately.

## 6. Can a translation be blocked silently?

| Situation | Now |
|---|---|
| no worker, offline > 24 h, paused, revoked, expired | new requests use the server's own model; with none configured the request is refused |
| `queue-missing` without a worker | refused (`gpu_worker_unavailable`) |
| job waits > 48 h | fails visibly + one alert; `GPU_WORKER_ON_EXPIRY=local` gives it to the server's own model instead |
| feature switched off | every open GPU job is released at the next sweep (start-up, then hourly); no manual cancelling needed |
| worker dies, also as the only worker | lease ends (180 s), sweep every 5 min queues the job again, 3 attempts |
| API crashes while storing a result | the same |
| job type removed from `GPU_WORKER_JOB_TYPES` | 48-hour rule |
| credential revoked | its job is freed at once; alert when jobs wait without a worker |
| scheduled agents (if ever enabled) | no longer held back by waiting GPU jobs |

Limit: the sweep runs in the API process. While a free Render instance sleeps nothing is swept; it runs after waking up.
Automatic use of the server's own model means Gemini can still receive requests while the feature is on (public text only).

## 7. Migration 0016

- `claim_ingestion_job`: the only change is `and executor = 'local'`, twice (definition diff). Owner, security definer,
  search path, grants, RLS policies and browser-role grants are identical before and after.
- 200,000 existing jobs: 91 ms in total, longest statement 27 ms. `claim` 2.5 ms, `expire` 0.3 ms afterwards.
- Compatible in both directions (section 2), so migrate first, then deploy. Rolling back the code does not need the SQL rollback.
- Worker-mode test on PostgreSQL: ingest, index, document translation and agent task threads finish while GPU jobs wait and
  run; nobody takes the other's jobs. 12 parallel claimers on 80 jobs: every job claimed exactly once.
- Source and document deletion are not blocked by waiting GPU jobs (a running one blocks source deletion until its lease ends).

## 8. Test database exposure

On 2026-11-24 a scratch PostgreSQL was started with `trust` on `127.0.0.1:54329`.

- **Duration:** 20:30:57.1 to 20:31:11.7 KST, 14.6 seconds (server log). Loopback only; not reachable from the network.
- **Content:** synthetic test rows. No production data or credentials exist on this server.
- **Evidence:** connections were not logged, so access by another local account cannot be excluded. Afterwards: only the roles
  the harness creates, no extra databases, extensions, languages or settings. The last login of another account in `last`
  is from 2026-11-16 (services are not covered by that).
- **Worst case:** a local account could have run commands as this account (superuser + `trust`). If that risk matters, rotate this
  account's SSH keys and tokens. No sign of it was found.
- **Prevention:** [scratch_db.sh](../../scripts/scratch_db.sh) (no TCP listener, 0700 directory, per-run keys, 401 without them,
  connections logged); the SQL tests refuse a passwordless TCP server; the integration tests refuse a default secret.

The old cluster has been deleted.

## 9. Plans (after the approvals)

### Deploy with the feature off

1. `pg_dump` (B4). Confirm migrations 0001–0015 are applied and no job is running.
2. Apply `supabase/migrations/20261124000016_gpu_worker.sql`.
3. Check the **running old release**: `/health`, one chat answer, one upload + approval.
4. Merge, deploy. Environment unchanged; `GPU_WORKER_*`, `OLLAMA_*`, `BACKGROUND_LLM_PROVIDER` unset; Render keeps its current
   `LLM_PROVIDER`.
5. Check: `/api/v1/gpu/claim` answers 404; Gemini chat with citations; search; one agent task; one upload and approval;
   one Gemini translation draft; `AGENT_SCHEDULES_ENABLED` and `AUTO_TRANSLATE_*` as before; logs without errors for 30 minutes.
6. Roll back: redeploy the previous release (the schema stays). Only if the schema must go: the SQL in `supabase/rollback/`.

### One manual pilot translation (A5–A7)

1. Choose a short notice without visa, work, money, deadline, insurance or legal content, e.g. the library's TOPIK courses.
   Language: one with an available native reviewer.
2. `GPU_WORKER_ENABLED=true`, `GPU_WORKER_JOB_TYPES=translate_announcement`. Create the worker; install the token; `--check`; `--once`.
3. On the administrator's computer:
   ```bash
   export HUB_URL=https://<api host>
   backend/.venv/bin/python scripts/gpu_pilot.py preflight ANNOUNCEMENT_ID vi
   backend/.venv/bin/python scripts/gpu_pilot.py queue ANNOUNCEMENT_ID vi --authorized "who, when, where recorded"
   ```
4. On the GPU server: `.venv-gpu/bin/python -m app.gpu_worker --once`
5. `scripts/gpu_pilot.py verify ANNOUNCEMENT_ID vi`; the reviewer compares every line with the original and approves or rejects.
6. Revoke the worker, set `GPU_WORKER_ENABLED=false`, check that the status shows no open job. Write down time, errors, review minutes.

Stop at once (revoke + disable) if students can see an unapproved draft, more than one job runs, or the chatbot, RAG or agents
behave differently.

## 10. Size, retention, resources

| | Measured |
|---|---|
| Database per draft (real texts, 104 drafts, all tables and indexes) | 6.2 KB |
| Same request again | 0 new drafts, 0 new rows per language; 1.3 KB of job history |
| Estimate: 20 announcements a month × 4 languages | 0.5 MB a month (production: 23 MB) |
| Retention | drafts, revisions, jobs, events and audit rows are **kept forever** (existing design; no purge exists) |
| Worker process | 35 MiB RAM peak, 1.8 % of one core while generating, 2.2 MB environment |
| GPU | 5.6 GB, about 199 W while generating; the model is unloaded after 10 idle minutes |
| Server disk | 90 % full (44 GB free); the worker stores no content |
| Render hours | two `--drain` runs a day: about 15 h a month |

## 11. Unchanged

Gemini chat, prompts, RAG retrieval, agents, schedules, `render.yaml`, workflows and the web app were not changed on purpose.
Shared code that was touched and why: engine (a reminder sent to local models only), agent task gate (ignores GPU jobs, only
when the feature is on), translation services (section 5), job worker loop (sweep), failure alert of announcement translations.

Final run of the mocked suite on the last commit: **799 passed, 42 skipped** (the skipped ones need a database or live services), ruff clean.
