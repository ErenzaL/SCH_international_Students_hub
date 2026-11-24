# Retention proposal R1–R4: GPU job history and translation drafts

**Status (2026-11-24): NOT APPROVED. Nothing is deleted. No deletion or clean-up code exists.** This version replaces the first one, which
contained two mistakes (marked ⚠).

## What exists today

| Table | Rows per draft | Bytes per draft (measured) | Deleted today | Cascades |
|---|---|---|---|---|
| `translation_revisions` / `document_translation_revisions` | 1 per generation or edit, with the **whole text** | 1,812 | never | deleted with the translation row |
| `announcement_translations` / `document_translations` | 1 (announcements: one per language, reused; documents: one per version and language) | 1,733 | never | — |
| `ingestion_jobs` | 1 | 1,024 | never | its events are deleted with it |
| `ingestion_events` | 3 | 630 | never | — |
| `audit_log` | 2 | 551 | **cannot be**: the database trigger `audit_log_append_only` refuses update and delete | — |
| `user_notifications` | 1–2 | 473 | never | — |
| **Total** | | **6,223** | | |
| `gpu_workers` | 1 per credential | small | never | — |

Measured with 104 drafts of real notices on PostgreSQL 17, including indexes. 80 drafts a month (20 announcements × 4 languages):
**0.5 MB a month, 6.0 MB a year**. Production had 23 MB. Storage is not a reason to hurry.

## R1: periods

| # | Data | Table (rows) | Proposed | After that |
|---|---|---|---|---|
| R1.1 | approved translations | both translation tables, `human_approved` | unlimited | — |
| R1.2 | all revisions of a translation that was **ever approved or edited by a person** | both revision tables | unlimited | — |
| R1.3 | current drafts (`needs_review`, `machine_draft`) | both translation tables | unlimited; reminder after 30 days | — |
| R1.4 | **outdated document drafts**, GPU-made, never approved, never edited | `document_translations` (`is_outdated`, `provider = 'ollama'`) | 180 days after `outdated_at` | delete row (its revisions follow) |
| R1.5 | **announcement** translation rows | `announcement_translations` | unlimited ⚠ | — (the row is also the translators' task; deleting it would remove the task) |
| R1.6 | replaced machine texts | both revision tables, `action = 'generate'`, not the newest, translation never approved or edited | 180 days | delete row |
| R1.7 | finished GPU jobs, succeeded | `ingestion_jobs` (`executor = 'gpu'`) | 90 days after `completed_at` | delete row (its events follow) |
| R1.8 | finished GPU jobs, failed or cancelled | same | 180 days | delete row (its events follow) |
| R1.9 | open GPU jobs | same, `queued` / `running` | never by retention | 48-hour rule |
| R1.10 | revoked GPU credentials | `gpu_workers`, `revoked` | 365 days after `revoked_at` | delete row |
| R1.11 | worker log | university server, not a table | 30 days | `journalctl` / logrotate |
| R1.12 | benchmark texts | university server, `backend/.eval-cache` | until the pilot is evaluated | delete folder by hand |

Everything made by Gemini or by people, all other job types, conversations, tickets, agent tasks: **not affected**.

## R2: rejected drafts

| | |
|---|---|
| First proposal | delete the text after 365 days, keep the row ⚠ **not possible**: the tables require a text unless the status is `todo` |
| New proposal | **keep** rejected rows unlimited (they are few and show why). Machine revisions of them follow R1.6 |
| Alternative | delete rejected **document** rows after 365 days; loses the reviewer's reason |

## R3: audit and notifications

| | Proposal | Implication |
|---|---|---|
| `audit_log` | not touched | append-only by design; a deletion would need a migration that weakens that protection. Not proposed |
| `user_notifications`, `admin_notifications` | not touched | one policy for all notifications, decided separately |
| Owner of that decision | project owner with the university's data-protection contact | |

## R4: when

**After** the pilot is evaluated, as its own release with its own approval. Until then the counts below are enough.

## Storage impact

Assumptions for one year with 960 drafts: 30 % are regenerated or never approved, 10 % become outdated, 5 % of the jobs fail. Estimates.

| Rule | Kept without deletion (year 1) | Kept with the rule | Saved per year from year 2 |
|---|---|---|---|
| R1.6 replaced machine texts | 0.52 MB | 0.26 MB | 0.5 MB |
| R1.4 outdated document drafts (if all were documents) | 0.34 MB | 0.17 MB | 0.3 MB |
| R1.7 + R1.8 jobs and events | 1.59 MB | 0.41 MB | 1.6 MB |
| not deletable or kept (approved texts, audit, notifications, current drafts) | 3.5 MB | 3.5 MB | 0 |
| **Total** | **6.0 MB** | **4.3 MB** | **about 2.4 MB a year** |

PostgreSQL reuses the space; the database file shrinks only after maintenance (`VACUUM FULL`, not proposed).

## Audit implications

| Question | Today | With R1–R2 |
|---|---|---|
| Who approved, rejected or edited a translation, and when? | revisions + `audit_log` | **unchanged** |
| What exactly did the person approve? | revision with the text | **unchanged** |
| What did the machine write before a person corrected it? | revision `generate` | **unchanged** for texts that were approved or edited (R1.2) |
| What did the machine write in a draft nobody used? | revision `generate` | gone after 180 days; `audit_log` still has date, language, model, number of warnings |
| Who requested a machine translation? | `ingestion_jobs.requested_by` + `audit_log` | `audit_log` **stays**; its `job_id` points to a deleted job |
| Why did a job fail? | job + events | 180 days |
| Which worker made a draft? | `ingestion_jobs.statistics` | 90 days; after that only provider and model |
| Which credentials existed? | `gpu_workers` + `audit_log` | `audit_log` **stays** |
| Link from a new to an outdated draft (`previous_translation_id`) | yes | becomes empty when the old draft is deleted |

Personal data affected: ids of the person who requested a job, earlier than today (90/180 days instead of unlimited). All other ids stay.

## Conditions for an implementation (if approved later)

1. Off by default; dry run that only counts; the counts are approved before the first deletion; backup first.
2. Small batches inside the existing clean-up call; each run written to `audit_log` as counts.
3. Tests for every "unlimited" above; a second run deletes nothing.
4. A translation that has **any** revision by a person is never touched, because deleting its row would delete those revisions too.

## Counts before deciding (read-only, needs migration 0016)

```sql
begin transaction read only;
select status, count(*), min(created_at), max(created_at) from public.ingestion_jobs where executor = 'gpu' group by 1;
select translation_status, is_outdated, count(*) from public.announcement_translations where provider = 'ollama' group by 1, 2;
select translation_status, is_outdated, count(*) from public.document_translations where provider = 'ollama' group by 1, 2;
select count(*), pg_size_pretty(sum(length(body))::bigint) from public.translation_revisions where action = 'generate';
rollback;
```

## Please decide

| # | Options |
|---|---|
| R1 | approve all · approve single lines · change periods · reject |
| R2 | keep rejected drafts (proposed) · delete document rows after 365 days |
| R3 | confirm: audit log and notifications untouched |
| R4 | after the pilot (proposed) · earlier · never |
