# Release candidate plan

Branch `integration/release-candidate`, local only. Release A (`af2a766`) and B (`2e3acd4`) are unchanged ancestors.

## Proposed pull requests (small enough to review, in order)

| # | Content | Branch / commits | Migration | Deploys | Can be switched off |
|---|---|---|---|---|---|
| 1 | **Release A** | `release/a-approved-source` `af2a766` | none | API | revert |
| 2 | **Release B** | `release/b-gpu-worker` rebased by merge on A | 0016 | API | `GPU_WORKER_ENABLED=false` (default) |
| 3 | **RAG** | `488469f`, `f471aa5` | none | API | `RETRIEVAL_BRIDGE_WEIGHT=0` and revert |
| 4 | **Agents backend** | `86319ef`, summaries, job APIs, catalogue, notice parser, doctor | 0017 | API | schedules off, no sources = no effect |
| 5 | **Web** | desk tabs, admin pages | none | web | revert |
| 6 | Tests, scripts, documents | rest | none | none | – |

`git cherry-pick` the commits onto a branch from the then current `main`, or merge the whole branch after 1 and 2. Every step: suite, second-person review, approval.

## Migrations

| | Before | Apply | Verify | Undo |
|---|---|---|---|---|
| 0016 | backup | whole file | `doctor` | `supabase/rollback/20261124000016_gpu_worker_down.sql` |
| 0017 | backup | whole file | `doctor`, Admin → Agents → Storage | `supabase/rollback/20261125000017_agent_operations_down.sql` |

Order free; code first or migration first both work (tested). Old code runs on the new schema (tested).

## Order on the day

1. `doctor` (no FAIL) → 2. backup → 3. migration → 4. `doctor` → 5. merge (= deploy) → 6. live check 15 min → 7. read-only checks → 8. write down.
Switch on later, one at a time: sources → manual checks → one schedule → GPU pilot.

## Rollback

Render → previous deploy; disable *Deploy to Render*; `git revert -m 1 <merge>`; database: nothing (rollback SQL only if a migration itself is the problem).
Schedules and GPU: the two switches, at once.

## Approvals still needed

Push, each merge, each migration, each schedule, GPU worker, every production data change. Retention R1–R4 stays unapproved and is not implemented.
