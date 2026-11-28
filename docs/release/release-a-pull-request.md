# Pull request text for Release A

Title: **Release A: titles, attachments and translations follow the approved version**
Base `main` (`eca1d71`), compare `release/a-approved-source`. Open as **draft**. Everything below the line is the description.

This repository is **public**. Never paste results of the production checks, names, keys, project references or log lines into the pull request.

---

## What this changes

A document that is already published must only change when somebody approves the change. Three places did not follow that rule:

1. **Translations** (`cb1f350`): drafts for a published document or announcement were made from its newest text, even if that text was still waiting for review.
2. **Titles** (`7246ff2`): importing a changed page changed the public title at once.
3. **Attachments** (`a7a7035`): importing a changed notice changed its public attachment list at once.

Title, text, search entry and attachments now change together, at approval, and return together at a rollback. The review page names title and attachment changes before approval.

## Size and scope

11 runtime files, all in `backend/app/services` (226 lines added, 13 removed). The rest is tests, scripts and documents.

**Not included:** migrations, settings or environment variables, dependencies, web app, workflows, `render.yaml`, LLM providers, assistant, retrieval, agents, schedules. No GPU or Ollama code.

## Known risks and limitations

**Historical titles (not repaired by this release).** A public title that was already replaced by an unapproved one stays as it is until it is corrected separately. A read-only query lists candidates. Versions replaced before this release have no recorded title: rolling back to one restores its text but keeps the current title.

**Attachment lists.**
- A list that is already wrong in the stored row stays there until the next approval of that notice. The pages show the approved list; a direct read of the row with the public key still shows the stored one.
- Very old imports without a recorded list keep the stored list.
- If a reviewer removes an attachment only from the *text* of a waiting version, it stays in the attachment list. Reject the version instead.
- An import and an approval of the same notice in the same second can leave the previous approved list in the row until the next approval.

**Other.** Not tested: hosted Supabase, Render, a real Gemini request, mobile browsers. Translators see an edit only once it is approved. A stop between the version switch and the title update shows the old approved title for up to about a minute.

Full list: `docs/release/release-a-plan.md`.

## Tests

| | |
|---|---|
| Mocked suite | 674 passed, 40 skipped (`main`: 604 / 37) |
| Real PostgreSQL + PostgREST, migrations 0001–0015, twice | 30 passed, 9 skipped (live services) |
| `main` on a database this branch wrote to, and back | 27 passed / 30 passed |
| Browser review workflow (Chromium, production web build), twice | 23 of 23; fails on `main` |
| Staging script against a local database | 14 of 14; on `main` 5 of 14 |
| Merge, then `git revert -m 1` of it | same files as `main` |
| `pip-audit`, `npm audit` | no known vulnerabilities; dependency files identical to `main` |
| Secret patterns in all added lines and commit messages | none found (own pattern scan; gitleaks was not run) |

## Deployment and rollback

Merging starts the API deployment (`render-deploy.yml`). No migration, no setting, no web build. Rollback: Render → previous deploy, then revert this merge; nothing to undo in the database. Steps: `docs/release/release-a-approvals.md`.

**Merge with "Create a merge commit"** (no squash, no rebase), and only after the approval below.

## Reviewer checklist

- [ ] I did not write this code, and I read all 11 runtime files completely
- [ ] The head commit I reviewed: `________` (a new commit needs a new review)
- [ ] `git diff --stat main...HEAD`: nothing in `supabase/migrations`, `apps`, `.github`, `render.yaml`, requirements, `app/core`
- [ ] **Translations:** no path lets waiting, rejected or withdrawn text reach a model or be stored (`auto.py`, `document_translations.py`, `translations.py`); checked before generating *and* before storing
- [ ] **Titles:** no path changes a public title without an approval (`pipeline.py`, `document_titles.py`, `indexing.py`)
- [ ] **Attachments:** the same for the API *and* for the row the public key can read (`public.py`, `document_attachments.py`)
- [ ] `_run_index`: a crash at any point leaves the old approved or the new approved state, never an unapproved one
- [ ] `review.py` rollback: acceptable if the update after the database function fails
- [ ] New job failure codes do not leave a job running or retrying forever
- [ ] Embeddings with the version's own title: no unwanted re-embedding
- [ ] Tests run on my computer; I broke one fix on purpose and a test failed
- [ ] The known risks above are acceptable for production
- [ ] Both read-only queries contain one SELECT and nothing else
- [ ] Result: approve / approve with changes / reject; findings written as review comments

🤖 Generated with [Claude Code](https://claude.com/claude-code)
