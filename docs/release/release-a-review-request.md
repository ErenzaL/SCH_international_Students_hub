# Request: second-person code review of Release A

**To:** a developer who did not write this code. **Time:** about 60–90 minutes. **Not yet sent to anybody**: the branch is not pushed, and
choosing the reviewer is up to the project owner.

## What to review

`main` `eca1d71` … `release/a-approved-source`. 11 runtime files, about 220 changed lines; the rest is tests, scripts, documents.

| Commit | Question |
|---|---|
| `cb1f350` approved source | Can any text reach the model, or be stored, that students cannot see right now? |
| `7246ff2` titles | Is there any way left to change a public title without an approval? |
| `a7a7035` attachments | The same for attachments, in the API **and** in the row that the public key can read |

Without access to the server: `release-a.patch` (all changes) and `release-a-runtime.patch` (runtime only), or the bundle:
`git fetch release-a.bundle release/a-approved-source:release/a-approved-source` in a clone of the repository.

## Please look hardest at

1. `pipeline.py` `_run_index`: order of *remember title → switch → apply title → apply details*; a crash at each point; the "already active" branch
2. `pipeline.py` `_find_or_create_document`: what may still change on a **published** document (pinned only)
3. `document_attachments.public_details`: is the approved version always the source? What if nothing is recorded?
4. `auto.py` / `document_translations.py`: both checks (before generating **and** before storing); can a new failure code leave a job in a bad state?
5. `review.py` `rollback`: two updates after the database function; what if the second one fails?
6. `_announcement_changed`: runs inside the activation job and may queue translations if automatic translation is on
7. `indexing.py`: embeddings now use the version's own title. Effect on re-used embeddings?
8. Who can still write `source_documents.title` or `.metadata`? (`grep -rn '"source_documents"' backend/app | grep update`)

## Run it

```bash
cd backend && python3.11 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/ruff check . && .venv/bin/python -m pytest -q          # 674 passed, 40 skipped
.venv/bin/python -m pytest -q tests/test_approved_source.py tests/test_document_titles.py tests/test_document_attachments.py tests/test_gemini_source_path.py
```
Then break something on purpose (for example remove `apply_details` from `_run_index`) and see whether a test notices.

## Answer

| | |
|---|---|
| Reviewer, date | |
| Findings (blocking / not blocking) | |
| Read the runtime code completely | yes / no |
| Ran the tests | yes / no |
| Decision | approve / approve with changes / reject |
