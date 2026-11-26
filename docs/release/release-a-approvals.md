# Release A: approval boundaries and rollback

A boundary is crossed only after the owner writes the approval, naming the **commit**. An approval covers that one step. Finishing a step, a
reviewer's approval, or a green test is not an approval of the next step. `main` has no branch protection: nothing but this page stops a merge.

| | Step | Effect | Who |
|---|---|---|---|
| 0 | Read-only checks on production | reads production data | owner |
| **1** | **Push the branch, open a draft pull request** | **publishes code, documents and commit addresses** (public repository). Cannot be taken back | owner |
| 2 | Create the staging project | a new free project | owner |
| **3** | **Merge** | **starts the production deployment** (API) | owner, after review |
| 4 | Roll back | production returns to the earlier deploy | owner; best decided in advance |
| – | Correct a title or row in production | changes production data | separate, one row at a time |
| – | Migration 0016, GPU worker, Release B; retention R1–R4 | **blocked / not approved**; no part of Release A | – |

## Boundary 1: before pushing

Facts (2026-11-24): no workflow starts on a branch push or pull request; `main` is `eca1d71`; there are no pull requests. Until the deployment,
the public branch describes a weakness that production still has. Its effect is limited (titles and attachment names that were imported but not yet
reviewed), but keep the time between boundary 1 and 3 short: **staging and a first review with the patch files come before the push.**

- [ ] The commit address `199873971+ErenzaL@users.noreply.github.com` is the owner's (GitHub → Settings → Emails)
- [ ] The secret scan was looked at; optional second scan on the owner's computer
- [ ] Render → both services → Settings: **Pull Request Previews off**; Auto-Deploy noted (it must follow `main` only, or be off)
- [ ] Vercel, Netlify or other apps connected to the repository (GitHub → Settings → Integrations): none builds branches
- [ ] Reviewer named, has the patch, and knows the time frame
- [ ] `git rev-parse release/a-approved-source` is the commit in `SHA256SUMS` / the hand-over note
- [ ] Written: "I approve pushing `release/a-approved-source` at `<commit>` and opening a draft pull request."

Push exactly this one branch, without force. Never push `release/b-gpu-worker`, `feature/*`, `--all` or `--mirror`. Do not touch `research/milestone-5`.

## Boundary 3: before merging (= deploying)

- [ ] Second-person review finished on the **current** head; every blocking finding resolved
- [ ] The pull request shows 11 files in `backend/app`, 0 in migrations / apps / workflows / requirements
- [ ] `main` is still `eca1d71`. If not: stop, compare, merge test again, run the suite again, ask the reviewer again
- [ ] Staging stage 2 done, or the owner writes that it is skipped and why
- [ ] Read-only checks "before" saved; backup made; known risks accepted in writing
- [ ] Render → API → Deploys: the live deploy is `eca1d71`; its time is written down (rollback target)
- [ ] Render environment: no variable changes; `GPU_WORKER_ENABLED` does not exist there
- [ ] Admin → jobs: nothing queued or running. GitHub → Actions: "Scheduled knowledge sync" is not running. **It is planned for 05:00 KST but GitHub
      starts it hours late** (23 Nov 09:44, 24 Nov 13:41 KST): look, do not trust the clock. Best after that day's run
- [ ] Two hours without other duties for the person deploying; administrators told not to approve for 30 minutes
- [ ] Written: "I approve merging pull request #`<n>` at `<commit>` into `main`, which deploys the API, and rolling back if needed."

Merge with **Create a merge commit**, not squash or rebase (the three fixes stay separate and one revert undoes all).

## Production rollback

**When:** chat, search, sign-in or approvals fail; approved content disappears; errors repeat; an unapproved text becomes public through the new code.
**Not** for single explainable job failures (`source_unapproved`, `source_not_public`).

1. **Return to the old deploy (about 3 minutes).** Render → API service → Deploys → the deploy of `eca1d71` → **Rollback**. The web service: nothing.
2. **Stop new deployments.** Render → Auto-Deploy off. This is **not enough**: the GitHub workflow calls a deploy hook, so the next push to `main`
   that touches `backend/` would deploy Release A again. GitHub → Actions → "Deploy to Render" → **Disable workflow** until step 5.
3. **Check:** `/health`, one chat answer with sources, a search, sign-in, one approval.
4. **Imports:** the old code shows unapproved titles and attachments at import again. GitHub → Actions → "Scheduled knowledge sync" → **Disable
   workflow**, and import nothing by hand until a fixed release. The owner decides.
5. **Git** (own approval, like any push to `main`). No force-push, no reset:
   ```bash
   git fetch origin && git switch -c revert/release-a origin/main
   git log --merges -1 --format='%h %s'            # must be the merge of Release A
   git revert -m 1 --no-edit <merge commit>
   git diff --stat eca1d71                         # empty, if nothing else was merged meanwhile
   git push origin revert/release-a                # → pull request → merge
   ```
   Then enable "Deploy to Render" again **before** merging it, or deploy by hand in Render. To bring the release back later, revert the revert.
6. **Database: nothing to undo.** No migration; the old code ignores the recorded titles and lists. Approvals made meanwhile stay valid. Do **not**
   restore the backup for a code problem.
7. Both read-only checks again; note new rows. Write down time, reason, log lines (without personal data).

Tested: old code on a database written by the new code and back (27 / 30 tests passed); merge and `git revert -m 1` give exactly the files of `main`.
Not tested: the rollback button of Render.
