# Proposal: how long to keep GPU job history and translation drafts

**Status: proposal. Nothing is deleted, and no deletion code exists.** Every step needs its own approval.

## Today

Nothing in these tables is ever deleted. (Retention exists for conversations and tickets, 365 days; agent tasks, 30 days;
discovered items.)

| Table | Per draft | Personal data |
|---|---|---|
| `announcement_translations` / `document_translations` | 1 row (replaced on regeneration) | ids of reviewer and editor |
| `translation_revisions` / `document_translation_revisions` | 1 row with the **whole text** per generation or edit | id of the person |
| `ingestion_jobs` (`executor = 'gpu'`) | 1 row | id of the person who asked |
| `ingestion_events` | 3 rows | none |
| `audit_log` | 2 rows | id of the person |
| `user_notifications` | 1–2 rows | recipient |
| `gpu_workers` | 1 row per credential | id of the creator; hashes only |

Measured: 6.2 KB per draft in total. 20 announcements a month in 4 languages: about 0.5 MB a month, 6 MB a year. The production
database had 23 MB. **Space is not the reason to delete**; tidiness and personal data are.

## Proposed periods

| Data | Keep | Then | Why |
|---|---|---|---|
| Approved translations | while the original is published | unchanged | students use them |
| Revisions of approved translations | as long as the translation | unchanged | proof of who approved what |
| Current drafts (`needs_review`, `machine_draft`) | while the original is current | reminder to reviewers after 30 days; no deletion | somebody's open work |
| **Outdated** drafts never touched by a person | 180 days after they became outdated | delete the row and its revisions | no value; the original changed |
| Rejected drafts | 365 days | delete the text, keep the row | learn from mistakes first |
| Revisions with action `generate`, replaced, never approved | 180 days | delete | largest share of the space |
| GPU jobs, succeeded | 90 days | delete with their events | metrics need weeks, not years |
| GPU jobs, failed or cancelled | 180 days | delete with their events | to find patterns |
| Open GPU jobs (queued, running) | never deleted by retention | — | handled by the 48-hour rule |
| `audit_log` | not changed by this proposal | — | the university decides for all audit data together |
| Notifications about drafts | not changed by this proposal | — | same for all notifications |
| Revoked credentials | 365 days after revocation | delete the row | the audit log keeps the events |
| Worker log on the school server | 30 days (`journalctl` / logrotate) | delete | ids, codes and durations only |
| Benchmark texts (`backend/.eval-cache`) | until the pilot is evaluated | delete the folder by hand | public notices, local only |

## Rules for a later implementation

1. Off by default (`GPU_RETENTION_ENABLED=false`), days as settings, dry run first that prints counts per table.
2. Only rows with `executor = 'gpu'` and drafts with `provider = 'ollama'`; nothing made by Gemini or by people.
3. Never: approved translations and their revisions, anything a person edited, anything of a current original, open jobs, `audit_log`.
4. In small batches, inside the existing clean-up call (`run-due`), logged and written to `audit_log` as counts.
5. A backup before the first run. Tests: every "never" above, and a second run deletes nothing.

## Count before deciding (read-only)

```sql
begin transaction read only;
select status, count(*), min(created_at), max(created_at) from public.ingestion_jobs where executor = 'gpu' group by 1;
select translation_status, is_outdated, count(*) from public.announcement_translations where provider = 'ollama' group by 1, 2;
select translation_status, is_outdated, count(*) from public.document_translations where provider = 'ollama' group by 1, 2;
select count(*), pg_size_pretty(sum(length(body))::bigint) from public.translation_revisions where action = 'generate';
rollback;
```
(Needs migration 0016.)

## Decisions needed

| # | Question | Proposal |
|---|---|---|
| R1 | Periods in the table above | accept |
| R2 | May texts of rejected drafts be deleted after a year? | yes |
| R3 | Who owns the retention of `audit_log` and notifications? | university / project owner, separately |
| R4 | Implement now or after the pilot? | **after** the pilot: at 0.5 MB a month there is no hurry |
