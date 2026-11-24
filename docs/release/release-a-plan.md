# Release A: approved-source safety fixes

Branch `release/a-approved-source`, based on `main` `eca1d71`. **No migration. No new setting. No web change. No GPU code.**
Not pushed, not deployed.

| Commit | Content | Runtime code |
|---|---|---|
| `cb1f350` | Translations (Gemini and every other provider) are made from the approved, public source only | yes |
| `7246ff2` | A published document title belongs to its approved version (also alone on `fix/document-title-approval`, `df9075f`) | yes |
| `a7a7035` | Public attachments of a notice belong to its approved version | yes |
| `4461644` | Test databases: private sockets and per-run keys only | no |
| `31bdbf3` | Real-database tests | no |
| `a55a89e` | First version of this plan and of the title check | no |
| `945797b` | Verification: Gemini source path, browser review workflow, read-only production checks | no |
| (last commit) | This plan, checklists, review request | no |

The three fixes are separate commits. `7246ff2` and `cb1f350` work alone on `main`; `a7a7035` needs `7246ff2`.

## Can it be deployed without migration 0016?

**Yes.** It needs no migration at all. Tested on a database with migrations 0001–0015 only, and on one where 0016 is already
applied, so its order relative to Release B does not matter. Title and attachments are kept in the existing column
`document_versions.extraction_meta`; every board version ever imported already records its attachments there.

## What changes for people

| Who | Before | Now |
|---|---|---|
| Students | a re-imported page could show a new title before anybody approved it | title, text, search and citations change together, at approval |
| Students | a re-imported notice could show new attachments before anybody approved them | the attachments of the approved version, also where the stored list is already wrong |
| Students | — | nothing else changes; chat, search and translations already approved stay as they are |
| Translators, reviewers | saw (and Gemini translated) an edit that waits for approval | see the approved text; are told and the translation is marked outdated when the edit is approved |
| Administrators | — | review pending edits as before; the review page adds "The title changes from … to …", "New attachment …" and "Attachment removed …" |
| Supporters | a draft could change a public title | it cannot |
| Jobs | — | new failure codes `source_not_public`, `source_unapproved`; a forced regeneration never replaces later human work |

Announcements that are not published yet are prepared from their draft, as before.

## Tests

| Check | Result |
|---|---|
| Mocked suite | **674 passed, 40 skipped** (`main`: 604 passed, 37 skipped) |
| Suite after each runtime commit | 618 (`cb1f350`), 633 (`7246ff2`), 657 (`a7a7035`) passed |
| New tests against the old code | fail as they should: 12 of 14 (source), 13 of 15 (titles), 16 of 24 (attachments) |
| PostgreSQL + PostgREST, **old schema** (0001–0015), twice | 30 passed, 9 skipped (live services) |
| PostgreSQL + PostgREST, **new schema** (with 0016) | 30 passed, 9 skipped |
| Roll back: `main` on a database Release A wrote to | 27 passed, 9 skipped |
| Forward again: Release A on a database `main` wrote to | 30 passed, 9 skipped |
| Attachment read with the **public key** through PostgREST | approved list only |
| Web app (identical to `main`): unit tests, typecheck, lint, production build | 240 passed, clean, clean, builds |
| **Browser** (Chromium, production web build, real API, stand-in login), twice | 23 of 23; the same test fails against `main` |
| **Gemini path**: the real provider class with a recording client, 13 tests | no pending text, title or attachment in any request |
| Trial merge into Release B (not kept) | no conflict, 864 passed, 45 skipped |
| Not run | hosted Supabase, Render, a real Gemini request, mobile browsers, languages other than English in the admin pages |

Attachment cases: added, replaced, removed; approval; rejection and the same import again; send-back, edit, resubmission; import after
send-back; repeated imports; several replacements before one approval; return to the approved state; rollback in both directions and
while a version waits; failed indexing; stop between the version switch and the update; withdrawn, archived, unpublished notices; wrong lists
already stored; versions without a recorded list.

## Nothing of Release B is included

Checked against `main`: 11 runtime files changed, all in `backend/app/services`. No migration, no setting, no new dependency, no change in
`apps/`, `render.yaml`, `.github/`, `main.py`, `config.py`, `jobs.py`, the LLM providers, the assistant, retrieval or agents. No commit of
Release B is an ancestor. The words gpu, ollama, qwen, executor and lease do not occur in the changed runtime lines.

# Release checklist

Every box needs a name and a time. **Stop** at the first problem.

**Approvals**
- [ ] Git author checked by the owner (GitHub → Settings → Emails)
- [ ] Second-person review done ([request](release-a-review-request.md)); findings resolved
- [ ] Owner approves: push `release/a-approved-source`
- [ ] Owner approves: merge to `main`
- [ ] Owner approves: deploy (merging to `main` **triggers the deployment** through `render-deploy.yml`, if its secrets are set)

**Before**
- [ ] Production runs `main` `eca1d71` (Render → Deploys); write down the deploy to return to
- [ ] Backup (`pg_dump`), recommended, stored off the university server
- [ ] [Both read-only checks](release-a-production-checks.md) run and saved
- [ ] No import or approval in progress; tell administrators not to approve for 30 minutes
- [ ] Render environment noted; **no variable changes**

**Deploy**
- [ ] Push, merge, watch the **API** deploy to the end (the web service needs no new build; a rebuild is harmless)
- [ ] `/health` answers; the log shows a clean start, no migration step

**Check (15 minutes)**
- [ ] Chat: one answer with sources, in Korean and in English (Gemini)
- [ ] Search finds a known guide; its page opens with title, text and attachments
- [ ] Announcements open; an approved translation is still shown
- [ ] Admin: the review queue opens; a document with a waiting version shows both versions and the new warnings
- [ ] Choose one `differs` row of the attachment check: the public page shows the approved list
- [ ] One Gemini draft of a published announcement: created, not public
- [ ] One agent task works; scheduled agents are still off; `AUTO_TRANSLATE_*` unchanged

**Check the fix (with a test source, 10 minutes)**
- [ ] Publish a test page; change its title and text; import again → public page unchanged, review page shows the changes
- [ ] Reject → unchanged. Import again, approve → title and text change together
- [ ] Roll back → the old title returns. Archive the test page

**Afterwards**
- [ ] Both read-only checks again: no new rows
- [ ] Logs for 30 minutes, then after 24 hours: no new errors; `source_unapproved` / `source_not_public` only where explainable
- [ ] Tell translators and reviewers: they see the approved text; they are told when an edit is approved

# Rollback checklist

Roll back when: chat, search, sign-in or approvals fail; approved content disappears; errors repeat. Not for single explainable job failures.

- [ ] Render → API → Deploys → the deploy noted above → **Rollback** (about 3 minutes). Automatic deploys off until the cause is known
- [ ] `/health`, chat, search, one approval
- [ ] **Database: nothing to do.** No migration; `main` ignores the recorded titles and reads the same rows
- [ ] Until a fixed release: unapproved titles and attachments can become public again. **Pause scheduled imports** or review before importing
- [ ] Approvals made meanwhile stay valid. Run both read-only checks and note new rows
- [ ] In Git: `git revert` of the merge, with a new review. No force-push

# Remaining risks

| Risk | Likelihood | Effect | Handling |
|---|---|---|---|
| Not tested on hosted Supabase, Render, live Gemini | — | unknown differences | checks above; rollback takes minutes |
| Titles that are already wrong stay | possible | one wrong title until corrected | read-only check, separate approval |
| A reviewer deletes an attachment only from the **text** of a waiting version | low | it is still in the attachment list (as before) | reject instead; the warning names every attachment |
| An import and an approval of the same notice in the same second | very low | the stored row keeps the previous **approved** list; the page is right | corrected by the next approval |
| A stop between the version switch and the title update | very low | old approved title for up to about a minute | the job repeats and corrects it |
| Versions replaced before this release have no recorded title | certain, harmless | a rollback to one keeps the current title | reviewer checks the title after a rollback |
| Translators no longer see edits in advance | certain | a little later start | they are told at approval |
| External official pages (discovery) are still summarised before review | existing | for administrators only | not part of this release |
| `4461644` changes how test databases are started | certain | test commands differ | docs/setup.md |
