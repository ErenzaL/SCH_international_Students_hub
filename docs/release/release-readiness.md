# Release readiness (2026-11-24)

**Nothing has been pushed, merged, deployed, migrated or enabled.** Details: [Release A](release-a-plan.md) ·
[Release B](release-b-plan.md) · [GPU worker assessment](gpu-worker-readiness.md) · [retention proposal](retention-proposal.md) ·
[review guide](../review/README.md)

| | Release A: approved-source safety | Release B: GPU worker |
|---|---|---|
| Purpose | unapproved text and titles stay private | drafts from the university GPU, off by default |
| Branch | `release/a-approved-source` | `release/b-gpu-worker` (contains A) |
| Migration | **none** | `20261124000016_gpu_worker.sql` |
| Settings | none | `GPU_WORKER_*`, all off |
| Web build | not needed | not needed |
| Ready to deploy | **yes, after approvals** | **no** |
| Can be deployed without the other | yes | no, needs A |

## Proposed commits

Release A, on `main` `eca1d71`: `cb1f350`, `7246ff2`, `4461644`, `31bdbf3`, `a55a89e`.
Release B, on Release A: `66e7c89`, `3da80c2`, `62c98be`, `2e2a495`, `3b9e238`, `0c74ea6`, `df97422`, `8575ee5`, `e6d857e`, `0ed3a74`, `2e28ac5`
and the documentation commit that contains this file.
The title fix alone, on `main`: `df9075f` (`fix/document-title-approval`).
The earlier branch `feature/school-gpu-worker` (`87d3ccf`) is unchanged and is replaced by these two branches.

## Author identity

All commits here and all 49 commits of the repository have one author and committer: `Lin Erenza
<199873971+ErenzaL@users.noreply.github.com>`. The owner in the remote URL is `ErenzaL`. There is no `.mailmap`, no CODEOWNERS file and no
Git identity configured on this server; the values were taken from the history. Commits are unsigned, like the existing ones.
To confirm before pushing: GitHub → Settings → Emails shows the same no-reply address. No existing commit was rewritten.

## Tests

| Check | Release A | Release B |
|---|---|---|
| Mocked suite | 633 passed, 37 skipped | 823 passed, 44 skipped |
| Every code commit on its own | yes | yes |
| PostgreSQL + PostgREST without 0016 | 29 passed, 9 skipped | 86 passed, 9 skipped (feature off) |
| PostgreSQL + PostgREST with 0016 | 29 passed, 9 skipped | 91 passed, 9 skipped |
| Roll back to `main` on the same data | 27 passed, 9 skipped | 27 passed, 9 skipped |
| Real GPU end to end | — | 20 of 20 |
| Model prompts compared with `main` (22: chat in 5 languages, translations, summary, agent task) | byte-identical | byte-identical |
| Browser tests, hosted Supabase, Render, live Gemini | **not run** | **not run** |

## Blockers

| # | Blocker | A | B |
|---|---|---|---|
| 1 | Your authorization to push, merge and deploy | ✔ | ✔ |
| 2 | Author identity confirmed by you | ✔ | ✔ |
| 3 | Review of the code by a second person | ✔ | ✔ |
| 4 | Checks on the live system after deploying (chat, search, upload, one Gemini draft) | ✔ | ✔ |
| 5 | Backup of production | recommended | ✔ |
| 6 | Migration 0016 | – | ✔ |
| 7 | University IT approval | – | ✔ |
| 8 | Term list confirmed by native speakers ([sheets](../review/)) | – | ✔ |
| 9 | Native review of drafts, pilot evaluated | – | ✔ |
| 10 | Retention decision (R1–R4) | – | before regular use |

## Open findings

1. **Attachments of re-imported board notices become public before approval** (same cause as the title, existing behaviour, not fixed).
2. Public titles that are already wrong stay until reviewed; a read-only query finds them (Release A plan).
3. Machine drafts that pass every check can still be wrong; students are protected only by the human review.
4. No purge exists for drafts and job history.
