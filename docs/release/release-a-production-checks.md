# Read-only checks on production (Release A)

Two questions, **no change**: which published titles and which published attachment lists may come from a version nobody approved?
Run both **before** the deployment and again **after** it. Keep both results.

| File | Finds | SHA-256 of the file |
|---|---|---|
| [titles_to_review.sql](../../supabase/checks/titles_to_review.sql) | public title differs from the approved text, or a newer version was never approved | `3154324475a1faa2f796fabf2118635714d66e9a93d3ac8902a1070a4111d6d5` |
| [attachments_to_review.sql](../../supabase/checks/attachments_to_review.sql) | stored attachment list or notice number differs from the approved version | `0a0e22ef2507511423c618bd8ac2b4006cb655dae2d64627fdc91a658b8499ac` |

Each file is **one SELECT**. A test fails if it ever contains anything else. Both were run on a test database that forbids writing.

**Who and where:** the project owner, on their own computer. **Not on the university server** (no production credentials there).

## Way 1: Supabase SQL editor

1. Open the **production** project → SQL Editor → new query.
2. Check the file: `shasum -a 256 supabase/checks/*.sql` must show the values above.
3. Paste the whole file. Read it: the first word that is not a comment is `select`, and there is one semicolon, at the end.
4. Run. Nothing else in the same query tab, no "Explain analyze", do not save it as a function.
5. Export as CSV: `titles_before_<date>.csv`, `attachments_before_<date>.csv`. Store them with the release papers, not in the repository.

The editor works with a powerful role: it is read-only because the query is a SELECT, not because the editor prevents writing. If that is
not enough, use way 2.

## Way 2: psql, with writing forbidden by the server

```bash
read -rs -p 'Connection string: ' DB; echo
for c in titles attachments; do
  PGOPTIONS='-c default_transaction_read_only=on -c statement_timeout=30000' \
    psql "$DB" --csv -v ON_ERROR_STOP=1 -f supabase/checks/${c}_to_review.sql > ${c}_before_$(date +%F).csv
done
unset DB
```
With this option every write ends with `cannot execute … in a read-only transaction`. Use the **direct** connection string; a pooler
may ignore `PGOPTIONS`. Check it first:
`PGOPTIONS='-c default_transaction_read_only=on' psql "$DB" -Atc 'show transaction_read_only'` must print `on`.

## Reading the result

| Result | Meaning | What to do |
|---|---|---|
| no rows | nothing to review | write it down |
| title, `newer_unapproved` has `pending_review` or `draft` | a version waits | review it in the admin pages as usual |
| title, `title differs from the approved text` | the public title may be unapproved. **Not always:** PDFs and edited texts can start with another heading | compare with the official page; list the real cases |
| attachments, `differs` | students may see unapproved attachments **today**; Release A shows the approved ones without any data change | check the linked file; nothing to correct in the data |
| attachments, `not recorded` | very old import without a recorded list | compare with the attachment section of the approved text |

If a title is really wrong, correcting it is a **change of production data** with its own approval, one row at a time, after a backup.
It is not part of Release A. Attachments need no correction: the stored list is replaced with the next approval of that notice.

## After the deployment

Run both again. Expected: no **new** rows. The `attachments` rows stay until the next approval of each notice (the stored row is
untouched), while the public page already shows the approved list; check one of them in the browser.
