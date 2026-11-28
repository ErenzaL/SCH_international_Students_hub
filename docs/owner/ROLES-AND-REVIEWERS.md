# Roles and reviewers

The Hub has four roles. A separate "moderator" role does not exist; the admin role covers it.

| Role | May | May not |
|---|---|---|
| super_admin | everything, incl. roles, languages, GPU tokens, permanent deletion | – |
| admin ("moderator", "source approver") | sources, imports, **approve / reject / roll back** documents and announcements, desks, schedules, pause | roles, languages, GPU tokens; translations or support of a language without an assignment |
| supporter | only assigned languages: support requests, translations; own submissions | approve documents; other languages; admin pages |
| student | own requests, tasks, conversations | everything else |

Language permissions per person and language: **support** (requests), **review** (approve translations), **lead** (whole language queue).

## Assign

| Step | Where | Good |
|---|---|---|
| 1. Person signs up on the website | /login | appears in Users & Roles |
| 2. Role | Admin → Users & Roles → role → Supporter / Admin (super administrators only) | person sees *Admin* after signing in again |
| 3. Languages | Admin → Language teams → person → tick support / review / lead | `doctor`: "translation reviewer per language: all five" |
| 4. Availability | the supporter: Admin → Support inbox → available | new requests are routed |

**Needed: one native-level reviewer and one human supporter for each of ko, en, id, vi, zh-CN, and one document approver who is not the author.**

Verified by tests and in the browser: a supporter cannot open admin pages, approve documents, or approve another language's translation; a reviewer of
Indonesian gets 403 for Vietnamese; students cannot see candidates, other students' requests or task data; administrators see agent tasks without a student's words.

| Needs a person | Runs by itself |
|---|---|
| approving documents, announcements, translations, discovered items | import of sources with a sync frequency (result waits for review) |
| sending a support request (the student confirms) | indexing after an approval, search, chat |
| switching on schedules, sources, the GPU worker | retry, recovery, notifications, expiry of private data per existing policy |
| correcting production data | nothing |
