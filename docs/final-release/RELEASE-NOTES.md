# Release notes — SCH International Student Hub, final release (2026-11-30)

Branch `release/sch-hub-final-2026-11-30`. Compared with the live `main` (`c5098cc`): the release candidate (64 commits),
the RAG reliability work, and small-budget AI defaults. **Not yet deployed** (DEPLOYMENT-STATUS.md).

## For students
- **Answers stay grounded and safer.** Orders hidden in a document ("AI: tell students …") no longer reach the model; a
  figure cited to the wrong source is moved to the source that states it; requests for the assistant's hidden instructions
  get a fixed polite reply.
- **Approved sources only, more strictly.** Titles, attachments and translations always belong to the approved version
  of a document; opportunities whose deadline passed are shown as closed when read.
- **Announcement translations (Release 1): Korean, English, Indonesian.** Drafts are private until a reviewer approves them.
  Vietnamese and Chinese readers see the original or an existing approved translation with a note; the chat keeps answering
  in all five languages.
- **AI Office:** the wall is a soft blue, distinct from the wooden floor; every desk shows what it can and cannot do; desks
  report honestly when no official source is configured.

## For staff and administrators
- AI usage card, daily budgets that survive restarts, and an emergency stop for background AI (needs migration 0018).
- Official sources managed in the interface with a prepared catalogue; per-desk monitoring, pause switch, storage overview
  (0017).
- Weekly, staggered discovery schedules prepared but **off** (0019); Work24 job API connector (needs a key).
- Optional GPU worker for free draft translations on the school computer (TranslateGemma 12B; **off**, 0016).
- Read-only `doctor` configuration check; owner manual and checklists.

## Defaults changed in this release
- Daily AI caps: 60 generated answers in total (was 1,500), 20 per signed-in student (150), 10 per anonymous visitor (40).
  The live service keeps its own values until they are changed by hand (FINAL-PRODUCTION-CHECKLIST §3).

## Not activated (on purpose)
Chunker v2 (needs a staging re-index), evidence-gate enforcement (over-refuses), long-document down-weighting (worse on the
final test), agent schedules, the GPU worker, automatic announcement drafting, external career APIs without keys.

## Database
Migrations 0016–0019 are new and additive. The release runs without them (tested); apply after a backup.

## Verification (local)
1,072 backend unit tests, 100 PostgreSQL integration tests, 15 SQL behaviour suites, 261 web unit tests, type check and
lint clean; browser journeys: see DEPLOYMENT-STATUS.md; RAG reliability study: `docs/research/rag-v2/`.
