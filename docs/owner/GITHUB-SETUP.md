# GitHub setup

Facts read on 2026-11-25: the repository is **public**, `main` is **not protected**, there are no pull requests.

| Question | Answer |
|---|---|
| What deploys production | a push to `main` (workflow *Deploy to Render*, deploy hooks in secrets); API only for `backend/` or `render.yaml`, web only for `apps/web/` or `render.yaml` |
| Pushing another branch / opening a pull request | starts no workflow |
| Scheduled | *Scheduled knowledge sync*: planned 05:00 KST, GitHub starts it hours late (09:44 and 13:41 on the last two days). It calls `/api/v1/internal/sync/run-due`: due imports (new content waits for review), clean-up of expired private data, queue checks; agent schedules only when both switches are on |
| What can change production | *Deploy to Render* (code), *Scheduled knowledge sync* (imports, notifications). Nothing else |
| Secrets | `RENDER_DEPLOY_HOOK_API`, `RENDER_DEPLOY_HOOK_WEB`, `CRON_SECRET` |
| Previews | none in GitHub; check Render and other connected apps |

## Protect `main` (recommended, free)

Settings → Rules → Rulesets → New branch ruleset → target `main` → *Require a pull request before merging* (1 approval), *Block force pushes*, *Restrict deletions*
→ Create. Verify: `git push origin main` is refused.

## Reviewable pull requests

1. Push one branch, never `--all`, `--mirror` or `--force`.
2. Open as draft, paste the prepared text, request the reviewer.
3. Verify the commit: `git rev-parse <branch>` = the commit shown on the pull request = the one in the approval.
4. Merge with *Create a merge commit* (one revert undoes it).

## Stop or undo a deployment

| Situation | Do |
|---|---|
| Deploy is running | Render → Deploys → Cancel deploy |
| Deployed and broken | Render → Rollback; Actions → *Deploy to Render* → Disable workflow; then revert in Git |
| Imports misbehave | Actions → *Scheduled knowledge sync* → Disable workflow |
| A secret was pushed | rotate it **first** (Supabase / Google / Render), then clean up |
