# Incident: "no pending version (ref 9cdb45f3bd55)" when approving an announcement

Reported 2026-11-28 on production, announcement `5597d191-b38a-401c-9c29-210550a6a2d6`, shown as **Pending approval**.
Fixed on `release/sch-hub-final-2026-11-30` (application code only, no migration). Not pushed or deployed.
Production data was not read or changed from the workstation (no production credentials there).

## 1. What happens

`ref 9cdb45f3bd55` is the request id of the failed `POST /api/v1/admin/announcements/{id}/approve`. In the Render API log
the same request appears as `rid=9cdb45f3bd55`. The message comes from the database function `approve_announcement`
(`supabase/migrations/20260101000004_functions.sql`):

```sql
select id into v_version from public.document_versions
 where document_id = a.document_id and verification_status = 'pending_review';
if v_version is null then raise exception 'invalid_state: no pending version' ...
```

So the announcement is `pending_approval`, but **none of its text versions is `pending_review`**.

## 2. Root cause: two review paths for the same text

An announcement's text is stored as a document (`source_documents.document_type = 'announcement'`) with versions.
Submitting the announcement moves both: announcement → `pending_approval`, its text version → `pending_review`.

**Admin → Review** (`review-queue-page.tsx`) lists two things: pending announcements (from `/admin/announcements`) and every
document with a `pending_review` version (from `/admin/documents`). The second list included the announcement's own
document, so the same announcement showed up twice. The document actions (Approve, Reject, Request changes →
`approve_document_version`, `reject_document_version`, `request_version_changes`) move **only the version**. They don't
know about the announcement, and neither the service nor the SQL refused them. After one of them:

| State | Text version | Effect in production |
|---|---|---|
| **A** | `approved`, current | Approve fails ("no pending version"). **The text is already searchable in the chat** while the announcement looks unpublished. Reject "works", but the text stays searchable under a rejected announcement. |
| **B** | `draft` (sent back) | Approve fails. Reject works and is the right way out. |
| **C** | `rejected` | Approve fails. Reject works and is the right way out. |

This is **not** legacy data, not a missing migration and not an API/schema mismatch. It is a workflow inconsistency that has
been present since the review queue began listing documents. The release as frozen at `a271b25` did **not** fix it.

## 3. The fix (commit on the release branch)

| Where | Change |
|---|---|
| `backend/app/api/admin_documents.py` | The document review queue leaves out documents whose announcement is `draft`, `pending_approval` or `rejected`: each announcement is listed once. Pending **edits of published** announcements stay in the queue (Release A, approved source). |
| `backend/app/services/review.py` | Approve, reject, request changes and submit for such a version return **409** "review it under Admin → Announcements" (`code=announcement_text`), even if called directly. |
| `backend/app/services/announcements.py` `approve` | Stuck state **A**: publishes the announcement on top of the existing text approval. Version, approver and approval time are untouched; the audit entry `announcement.approve` records `text_already_approved`, the version id and who approved the text. States **B/C**: 409 that says what happened (with the reviewer's note) and how to continue. Nothing is changed by the refusal. |
| `backend/app/services/announcements.py` `reject` | State **A**: 409 "already approved and searchable: Approve, or Cancel to withdraw it". Rejecting would leave the text in the chat. |
| `apps/web/.../announcement-admin-detail.tsx` | **Cancel** is offered for pending announcements too (the database function already allowed it); cancelling removes the text from search. |

Nothing is approved automatically: every outcome needs an administrator's click. No content or approval history is
altered.

## 4. Tests

| Suite | Result |
|---|---|
| `backend/tests/test_announcement_review_consistency.py` (new): reproduces the exact `no pending version` at the database function; recovery of A, B, C; the guard; the queue; the boundary for published-announcement edits; normal workflow unchanged | **9 / 9** |
| Backend unit, whole suite | **1,082 passed**, 0 failed, 57 skipped (the skips are the opt-in integration and live tests) |
| `backend/tests/integration/test_announcement_review_integration.py` (new, real PostgreSQL + PostgREST): guard, stuck state A reproduced and recovered, sent-back text, Cancel withdraws a live text | **4 / 4** on both schemas |
| PostgreSQL integration, full schema (0001–0019) | **104 passed**, 0 failed, 9 skipped |
| PostgreSQL integration, **production schema (0001–0015)** | **97 passed**, 0 failed, 16 skipped (the 0016 / 0017 feature tests) |
| SQL behaviour suites (run by the scratch stack) | all passed |
| Web unit (vitest), type check, lint | **261 / 261**, clean, clean |

**Production schema compatibility:** the fix adds no migration and uses only columns and functions that exist at 0015.
The release still runs on the production schema without 0016–0019 (row above).

## 5. Production data: diagnose (read-only), then repair through the app

**Step 1, diagnose.** Run `docs/owner/sql/diagnose-no-pending-version.sql` in the Supabase SQL editor. Every query is a
`SELECT` in a `READ ONLY` transaction (a write is refused). The queries cover:

1. the announcement, its document, its newest version and a **diagnosis** A / B / C;
2. all its versions (no text, only length and hash);
3. the audit trail. The expected sequence is `announcement.submit`, then `version.approve` / `version.request_changes` / `version.reject`, and no `announcement.approve`;
4. **every** announcement in the same state;
5. the migration level. This query needs `supabase_migrations`; skip it if that schema does not exist.

It was checked on a scratch database at schema 0015 seeded with states A, B and C, and the diagnosis was correct for each.

**Step 2, repair: recommended path, no SQL.**

| Diagnosis | Before the release is deployed | After the release is deployed |
|---|---|---|
| A: text approved, searchable | Wait for the deploy (Reject would leave the text searchable), or use the last-resort SQL below | Admin → Announcements → **Approve** (publishes it; translation tasks are created as usual) or **Cancel** (withdraws the text) |
| B: text sent back | **Reject** with the reviewer's note; the author revises and resubmits; approve as usual | the same (the Approve message now explains it) |
| C: text rejected | **Reject** with the reason; the author submits a new text | the same |

**Last resort for A only:** `docs/owner/sql/repair-no-pending-version-state-a.sql`. It runs in one transaction and acts
only if the row is still in state A; otherwise 0 rows are changed. It changes one announcement row and writes one audit
row that holds the previous values. An **UNDO** block restores those values and logs the undo. Before running it, take a
backup (checklist §2). Unlike the app, it does **not** create the translation tasks or notify the reviewers, which is why
the app path is preferred. It was tested on a scratch 0015 database: repair published the announcement and made it
visible to anonymous readers; undo restored `pending_approval` and the empty approver; the repair changed nothing on a
state B row. **It has not been run on production.**
