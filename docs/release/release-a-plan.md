# Release A: approved-source safety fixes

Branch `release/a-approved-source`, based on `main` `eca1d71`. **No migration. No new setting. No web change. No GPU code.**
Not pushed, not deployed.

| Commit | Content | Runtime code |
|---|---|---|
| `cb1f350` | Translations (Gemini and every other provider) are made from the approved, public source only | yes |
| `7246ff2` | A published document title belongs to its approved version (also alone on `fix/document-title-approval`, `df9075f`) | yes |
| `4461644` | Test databases: private sockets and per-run keys only | no (tests, test scripts, docs/setup.md) |
| `31bdbf3` | Real-database tests of both fixes | no |
| (this plan) | Plan and the read-only title check | no |

The two fixes are independent: either can be released alone.

## Can it be deployed without migration 0016?

**Yes.** It needs no migration at all. Tested on a database with migrations 0001–0015 only, and on one where 0016 is already
applied, so its order relative to Release B does not matter. The title is kept in the existing column
`document_versions.extraction_meta`.

## What changes for people

| Who | Before | Now |
|---|---|---|
| Students | a re-imported page could show a new title before anybody approved it | title, text, search and citations change together, at approval |
| Students | — | nothing else changes; chat, search and translations already approved stay as they are |
| Translators, reviewers | saw (and Gemini translated) an edit that waits for approval | see the approved text; are told and the translation is marked outdated when the edit is approved |
| Administrators | — | review pending edits as before; the review page adds "The title changes from … to …" |
| Supporters | a draft could change a public title | it cannot |
| Jobs | — | new failure codes `source_not_public`, `source_unapproved`; a forced regeneration never replaces later human work |

Announcements that are not published yet are prepared from their draft, as before.

## Tests

| Check | Result |
|---|---|
| Mocked suite on this branch | 633 passed, 37 skipped (`main`: 604 passed, 37 skipped) |
| Each runtime commit alone on `main` | 618 (`cb1f350`), 619 (`df9075f`) passed |
| New tests against the old code | 12 of 14 and 13 of 15 fail, so they detect the bugs |
| PostgreSQL + PostgREST, 0001–0015 | 29 passed, 9 skipped (live services) |
| PostgreSQL + PostgREST, 0016 already applied | 29 passed, 9 skipped |
| Rollback: `main`'s code on a database Release A wrote to | 27 passed, 9 skipped |
| Not run | browser tests (no Node here), hosted Supabase, Render, live Gemini |

Review of pending edits is covered by tests: see and compare, edit, send back, submit, reject, approve; approving a translation
while an edit waits; documents and announcements.

## Before deploying

1. Approvals: merge, push, deploy (project owner). Author identity confirmed.
2. A second person reviews the two commits.
3. Backup: not technically required (no migration), recommended because production has no automatic backup.
4. Run [titles_to_review.sql](../../supabase/checks/titles_to_review.sql) in the Supabase SQL editor (**read-only**) and keep the result.
   Release A stops new cases; titles that are **already** wrong stay until somebody decides:
   - waiting version → review it; approving makes title and text consistent;
   - rejected or replaced version → if the public title is wrong, correct that one row by hand. This is a production data change
     and needs its own approval; it is not part of this release.
   Waiting versions from before the release have no recorded title and keep the title that is public now.

## Deploy

1. Merge to `main`, deploy the API. The web service does not need a new build. No environment change.
2. Check: `/health`; one chat answer with citations (Gemini); search; one agent task; `AGENT_SCHEDULES_ENABLED` and `AUTO_TRANSLATE_*` as before.
3. Check the fix with a test source: publish a page, change its title and text, re-import → the public title stays; the review page shows
   the change; approve → title and text change together.
4. Request one Gemini translation draft of a published announcement.
5. Watch the logs for 30 minutes: no new errors, no unexpected `source_unapproved` / `source_not_public`.

## Roll back

Redeploy `main` `eca1d71`. Nothing to undo in the database; the old code ignores the recorded titles (and has the old behaviour again).

## Known limits

- **Attachments have the same problem and are not fixed here:** re-importing a board notice updates `source_documents.metadata`
  (attachment list) before approval, and the public page shows it. Found while fixing the title; needs a decision.
- Between the version switch and the title update there are a few milliseconds in which the new text has the old approved title. If
  the API stops in between, the job is repeated and the title follows. An unapproved title is never shown.
- Versions replaced before this release have no recorded title; rolling back to one keeps the current public title.
- A title-only change of a published manual text (same ID, same text) is ignored and logged.
