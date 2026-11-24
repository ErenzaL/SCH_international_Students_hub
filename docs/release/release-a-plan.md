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
| `7f7bd13`, `b0d07f8` | This plan, checklists, review request | no |
| (last commit) | Pull request text, staging test, approval boundaries | no |

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
| **Gemini path**: the real provider class with a recording client, 14 tests | no pending text, title or attachment in any request |
| Trial merge into Release B (not kept; before the last commit) | no conflict, 864 passed, 45 skipped |
| **Staging script** on a local database: real API with its job worker, public key, board import | 14 of 14; the same script on `main`: 5 of 14 |
| Merge into `main` and `git revert -m 1` (not kept) | same files as Release A, then same files as `main` |
| Dependency files; `pip-audit`; `npm audit` | identical to `main`; no known vulnerabilities in either |
| Secret patterns in every added line and commit message | none (own pattern scan; gitleaks was not run) |
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

**Approvals**: [boundaries before pushing and before merging](release-a-approvals.md)

**Before**
- [ ] Production runs `main` `eca1d71` (Render → Deploys); write down the deploy to return to
- [ ] Backup (`pg_dump`), recommended, stored off the university server
- [ ] [Both read-only checks](release-a-production-checks.md) run and saved
- [ ] No import or approval in progress (the daily import starts hours later than its planned 05:00 KST); administrators do not approve for 30 minutes
- [ ] Render environment noted; **no variable changes**

**Deploy**
- [ ] Merge, watch the **API** deploy to the end (the web service needs no new build; a rebuild is harmless)
- [ ] `/health` answers; the log shows a clean start, no migration step

**Check (15 minutes)**
- [ ] Chat: one answer with sources, in Korean and in English (Gemini)
- [ ] Search finds a known guide; its page opens with title, text and attachments
- [ ] Announcements open; an approved translation is still shown
- [ ] Admin: the review queue opens; a document with a waiting version shows both versions and the new warnings
- [ ] Choose one `differs` row of the attachment check: the public page shows the approved list
- [ ] One Gemini draft of a published announcement: created, not public
- [ ] One agent task works; scheduled agents are still off; `AUTO_TRANSLATE_*` unchanged

**Check the fix**: in [staging](release-a-staging.md), not in production (it needs test documents). In production only look: the next notice that
really changes keeps its public title and attachments until somebody approves it.

**Afterwards**
- [ ] Both read-only checks again: no new rows
- [ ] Logs for 30 minutes, then after 24 hours: no new errors; `source_unapproved` / `source_not_public` only where explainable
- [ ] Tell translators and reviewers: they see the approved text; they are told when an edit is approved

# Rollback

Steps and reasons: [approvals and rollback](release-a-approvals.md#production-rollback). **Database: nothing to undo.**

# Known risks

The owner accepts these in writing before the merge.

## Historical titles (known, not repaired)

| | |
|---|---|
| What | Before this release an import could replace a public title without approval. **Titles already replaced stay** |
| Seen by | everybody, until corrected |
| Find | `supabase/checks/titles_to_review.sql` (read-only; may also list harmless differences) |
| Correct | separate approval, one row at a time, after a backup. Or: the next approval of that document sets its title |
| Also | versions replaced before this release have **no recorded title**: a rollback to one restores the text and keeps the current title. The reviewer checks the title after a rollback |

## Attachment lists (known, partly repaired)

| Case | Pages and API | Row that the public key can read | Handling |
|---|---|---|---|
| list in the row already wrong, approved list recorded | **approved list** | wrong until the next approval | `attachments_to_review.sql`; nothing to change |
| very old import, no recorded list | stored list | stored list | compare with the approved text by hand |
| reviewer removes an attachment only from the **text** of a waiting version | still listed (as before) | still listed | reject instead; the warning names every attachment |
| import and approval of the same notice in the same second | approved list | previous **approved** list | corrected by the next approval |
| file behind an approved link is exchanged on the official site | the link is the same | the same | not detectable; as before |

## Other

| Risk | Likelihood | Effect | Handling |
|---|---|---|---|
| Not tested on hosted Supabase, Render, live Gemini | — | unknown differences | checks above; rollback takes minutes |
| A stop between the version switch and the title update | very low | old approved title for up to about a minute | the job repeats and corrects it |
| Translators no longer see edits in advance | certain | a little later start | they are told at approval |
| External official pages (discovery) are still summarised before review | existing | for administrators only | not part of this release |
| `main` has no branch protection | certain | a merge by mistake deploys | [boundaries](release-a-approvals.md); optional: a protection rule |
| `4461644` changes how test databases are started | certain | test commands differ | docs/setup.md |
