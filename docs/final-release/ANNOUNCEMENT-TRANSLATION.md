# Announcement translation: TranslateGemma on the GPU worker, Gemini for chat and agents

Branch `feature/announcement-auto-translation` (from production `main` 1fe8cb7). **Not pushed, not deployed.**
Production data was not read or changed from the workstation.

## 1. Model routing (implemented and enforced in code)

| Work | Model | Where it runs | Enforced by |
|---|---|---|---|
| Student RAG chat, Hana and the other desks, AI Office reasoning | Gemini (`GEMINI_PRIMARY_MODEL` / `GEMINI_FALLBACK_MODEL`) | Render API | unchanged |
| Announcement translation drafts (ko ↔ en ↔ id), manual and automatic | **TranslateGemma 12B** (`translategemma:12b`) | university GPU worker (outbound HTTPS only) | `gpu_routing.announcement_route`; the server hands announcement jobs only to a worker that reports this model (`/gpu/claim` with `model`) and refuses drafts of any other model (`model_not_allowed`) |
| Announcement translation with the paid Gemini | only if `TRANSLATION_FALLBACK_TO_GEMINI=true` (default **false**) | Render API | refused in three places: routing, the GPU sweep (never reroutes), and the API's own job runner (`translation_fallback_disabled`, before any model call), so jobs queued earlier never reach Gemini either |
| Knowledge-document translation (unchanged) | GPU worker when it is online, else `TRANSLATION_MODEL` | as before | as before; now never the chat fallback model |

**Confirmed model:** Ollama on this workstation, `translategemma:12b`, digest `3189e9a01b8a`, 12.2 B parameters,
Q4_K_M, 7.7 GB. This is the model chosen in `docs/research/TRANSLATION-EVALUATION.md`. On 72 real notices, with the
Hub's prompts, it kept every date, amount and link and had 1 detectable fact error, against 6 for Qwen 2.5 7B. That
evaluation is historical evidence only: no native speaker has rated the drafts, so human review stays mandatory.

## 2. Why tasks showed "To do · Queued" with a disabled Machine-translate button

Reproduced on the unchanged code with production defaults (`AUTO_TRANSLATE_ANNOUNCEMENTS` unset):

1. Publishing an announcement creates a "To do" task per language. With automatic translation off, **no job is
   created**: the queue had zero `translate_announcement` jobs.
2. The panel mapped "To do without a job" to the state `pending`, labelled **"Queued"**, and treated `pending` as
   running, so the button was **disabled**. Its label "Machine-translate" (rather than "Translate again") is the sign
   that no job existed. Nothing was stuck in a queue: nobody could start a job.
3. Had a job existed, it would have run on the server's Gemini (`TRANSLATION_MODEL`) whenever no GPU worker was
   online, because the old routing fell back silently. That fallback is now opt-in.

To confirm on production (read-only): `docs/owner/sql/diagnose-translation-queue.sql`. Query 1 should show "To do"
tasks with `jobs_for_these_tasks = 0`.

## 3. What changed

**Backend**
- States an admin can act on: `ready`, `pending`, `waiting_worker` (the GPU worker is offline: the job waits, and the
  panel says so), `processing`, `stalled` (with a safe "Check again"), `quota`, `retrying`, `needs_review`,
  `completed`, `failed` (retry available), `outdated`, `approved`, `human_draft`, and `manual` (Release 1 has no
  machine drafts for vi / zh-CN).
- A request that cannot run says why: not published, original language, out of scope, worker switched off, or
  approved and protected.
- Languages chosen while writing or publishing: `translation_targets` on create / edit, and
  `PUT /admin/announcements/{id}/translation-targets`. They are stored in `source_documents.metadata`, so **no
  migration** is needed, and they survive reject → edit → resubmit. Jobs are created only when the approved version
  is published. Saving the languages of a published announcement queues the missing drafts at once.
- **No duplicates:** one open job per translation (unique index), plus the content-hash cache. Asking again for an
  unchanged draft returns the existing job with no new job and no inference. Repeated publication events queue
  nothing.
- **Approved translations are protected:** machine output never replaces a reviewer-approved translation of the
  current text, even when forced.
- **Bounded backfill** for existing announcements: `POST /admin/translations/backfill` (admins; preview first; at
  most 50 per call; skips approved, current and human work).
- **GPU sweep:** while the worker is offline, announcement jobs keep waiting (one admin alert a day) up to an explicit
  limit, `GPU_WORKER_ANNOUNCEMENT_MAX_WAIT_HOURS` (default 7 days, 0 = no limit); then they fail visibly and can be
  requested again. They are never sent to Gemini. Lost leases are re-queued.
- Each server-run job records its usage (`statistics.usage`: model, input and output tokens, model calls, estimated
  cost). GPU jobs record worker metrics.
- The translations list shows, per task: machine state, model, last attempt and error.
- The `doctor` check reports where announcement translations run.
- The background Gemini instance no longer fails over onto the chat fallback model.

**GPU worker:** it reports its model when claiming. Its default model is now `translategemma:12b`.

**Web**
- An "Automatic translation" section in the announcement form, with checkboxes ko / en / id; the original
  language is disabled and removed. The form also gets an original-language choice (ko / en / id).
- An "Automatic translation" card on the announcement page.
- A rebuilt machine-translation panel: honest state, explanation, model and route, worker online or offline, job
  line, refresh while work is under way, regenerate with confirmation (reviewers), and blocked reasons instead of a
  disabled button.
- In the list: a machine column and the backfill panel (admins).
- All new strings exist in ko, en, id, vi and zh-CN.

## 4. Tests (local, school workstation; mocked models except where stated)

| Suite | Result |
|---|---|
| Backend unit (whole suite) | **1,116 passed**, 0 failed (63 skipped: opt-in integration and live tests) |
| New `tests/test_announcement_translation_routing.py`, covering the test list A–T plus expiry and staged activation | 28 / 28 |
| Real worker program against the API with a stand-in Ollama (`tests/integration/test_gpu_worker_integration.py`), incl. busy GPU, out of memory, wrong model, expired token | 40 / 40 |
| PostgreSQL + PostgREST, full schema 0001–0019 | **114 passed**, 0 failed, 9 skipped |
| PostgreSQL + PostgREST, **production schema 0001–0015** | **99 passed**, 0 failed, 19 skipped (0016 / 0017 features); with 0016 added: **112 passed**, 0 failed |
| SQL behaviour suites | all passed |
| Web unit tests, type check, lint | **268 / 268**, clean, clean |
| Browser journeys `gpu` + `autotr` + `gpuops` on the local stack with the **real worker program and TranslateGemma 12B on this GPU** | 32 / 32 and **34 / 34** (`gpuops`: API down, wrong model, busy GPU, duplicate, offline, expired / rotated / revoked token, source change, cancellation, `kill -9` + lease recovery); log `evidence/gpu-worker-e2e-2026-11-28.log` |
| Peak memory, the same 40-translation workload on `main` and on this branch | 104–105 MB on both (94 MB baseline); no new dependency |

The test list maps to the tests as follows:

| Items | Covered by |
|---|---|
| A–F | manual request → TranslateGemma draft → private `needs_review` → reviewer edits and approves → students |
| G–J | languages chosen while writing, queued once after approval, never the original language, no duplicates |
| K, L | Gemini down or out of budget does not matter for announcements |
| M, N | dead worker hands the job back; offline worker → jobs wait, then run |
| O | cancelled original is not translated |
| P | approved translations protected |
| Q | language-scoped approval |
| R | document translation suites unchanged and passing |
| S | no GPU worker: site works, nothing charged, clear reason |
| T | memory |

**No Gemini tokens were used.** Every Gemini test uses a recording fake that asserts zero calls.

## 5. Production configuration (Render, API service)

| Variable | Value | Why |
|---|---|---|
| `GPU_WORKER_ENABLED` | `true` | turns the GPU route on (**needs migration 0016**) |
| `GPU_WORKER_JOB_TYPES` | `translate_announcement` (now the default; documents only if `translate_document` is added on purpose) | jobs the worker may take |
| `ANNOUNCEMENT_TRANSLATION_MODEL` | `translategemma:12b` (default) | the only model accepted for announcements |
| `TRANSLATION_FALLBACK_TO_GEMINI` | `false` (default) | no paid announcement translation |
| `GPU_WORKER_MODELS` | must contain `translategemma:12b` (default does) | accepted results |
| `AUTO_TRANSLATE_ANNOUNCEMENTS` | leave unset | languages are now chosen per announcement; the flag is only for announcements saved before this release |
| `TRANSLATION_MODEL` | unchanged | used only for document translations (and announcements only with the fallback) |
| Gemini variables | unchanged | chat and agents |

**GPU workstation** (`~/.config/sch-gpu-worker/env`, mode 0600):
- `GPU_WORKER_HUB_URL=https://sch-hub-api.onrender.com`
- `GPU_WORKER_PRODUCTION_HOST=sch-hub-api.onrender.com` (the worker refuses the production host without it)
- `OLLAMA_MODEL=translategemma:12b`
- optionally `GPU_WORKER_ACTIVE_HOURS=9-18`

The token goes in `~/.config/sch-gpu-worker/token` (mode 0600). No Supabase or Gemini key may be set there; the worker
refuses to start if one is. Activation step by step: `docs/owner/GPU-ACTIVATION.md`.

## 6. Database

No new migration. **0016 is required** for the GPU route: it adds `ingestion_jobs.executor` and the lease columns,
`gpu_workers`, `claim_gpu_job` and `expire_gpu_leases`. It is additive and tested on scratch PostgreSQL.

Without 0016, keep `GPU_WORKER_ENABLED=false`. The release then runs on 0015 (tested): publication works, the chosen
languages are saved, and Machine-translate explains that the GPU worker is off. Nothing is charged.

## 7. University IT approvals needed before a live worker

- Running a persistent or scheduled process on the RTX 4070 workstation: GPU, CPU, memory and disk policy.
  Translation uses about 8–10 GB VRAM for seconds per notice, one job at a time.
- Outbound HTTPS from the workstation to `sch-hub-api.onrender.com`. No inbound ports, no SSH exposure, and Ollama
  bound to 127.0.0.1 only.
- Storing the revocable worker token on the workstation. It is a worker credential only: no database or user access.
- That only public, approved announcement text is processed there; no student data ever is.

## 8. Safe deployment (each step needs your approval)

1. Backup (checklist §2). Apply **0016** in the Supabase SQL editor, then check with `diagnose-translation-queue.sql`
   query 4.
2. Merge this branch. The API and web deploy, still with `GPU_WORKER_ENABLED=false`: no behaviour change except the
   clearer panel and the language choice.
3. Admin → GPU worker → create `school-gpu` → copy the token once → put it on the workstation.
4. On the workstation, run `python -m app.gpu_worker --check`. **Only after IT approval**, set
   `GPU_WORKER_ENABLED=true` on Render.
5. Run one announcement: choose Indonesian → approve → `--once` on the workstation → the reviewer checks the draft.
   Then `--drain` (recommended) or the service mode inside `GPU_WORKER_ACTIVE_HOURS`.

**Rollback:**
- Set `GPU_WORKER_ENABLED=false`. New requests are refused at once, with the reason. Waiting jobs end with "GPU
  worker switched off" at the next sweep (within the hour, or at once via the daily scheduler call). Reviewers
  translate by hand meanwhile.
- Revoke the worker (Admin → GPU worker).
- Or redeploy the previous `main`. The metadata key `translation_targets` is ignored by older code. 0016 can stay; it
  is additive.

## 9. Remaining blockers

- **Live translation on production is not verified.** No authorized worker has completed a production job. Locally,
  the real worker with TranslateGemma 12B completed the full flow against the local stack.
- Migration 0016 is not yet applied on production (unknown; check with query 4).
- University IT approval for the workstation, plus the worker credential.
- Native reviewers for English and Indonesian: approvals need people.
- `ruff` still reports the pre-existing import-order finding in `citation_check.py`; CI does not run ruff.
