# Deployment status — final release (2026-11-28)

**Verdict: the release is built, tested and committed locally. It is NOT pushed and NOT deployed.** The school workstation
has no GitHub credential (no token, no SSH key, no `gh`), and no Render or production-database access. Pushing needs one
command from the owner (FINAL-PRODUCTION-CHECKLIST §1). Render deploys from `main`, so the release goes live when it is
merged into `main` on GitHub.

## 1. Repository

| Item | Value |
|---|---|
| release branch | `release/sch-hub-final-2026-11-30` (worktree `~/projects/sch-hub-final`) |
| base | `school/rc-2026-11-27` @ `8fd791b` (release candidate: 64 commits on top of `origin/main` `c5098cc`) |
| integrated | `research/rag-reliability-v2` @ `110b03d` (merge `bb73e79`), small-budget AI defaults (`b61e0cf`), release documents |
| relation to `origin/main` | `origin/main` is an ancestor: merging is a fast-forward, no history is rewritten |
| push | **not done** (blocked: credential); dry run fails at "could not read Username" |
| backups | tags `backup/2026-11-27/*`, `backup/2026-11-28/school-rc-2026-11-27`, `backup/2026-11-28/research-rag-reliability-v2`; bundle `~/backups/sch-hub-2026-11-27/` |
| other branches | all preserved locally, none deleted |

## 2. What is live now (read-only checks, 2026-11-28, no login)

| Check | Result |
|---|---|
| API `/health` | 200, `supabase: configured`, embedding `intfloat/multilingual-e5-small#qint8` (first request after sleep: 42.6 s, then < 1 s) |
| `/api/v1/assistant/status` | answer generation **enabled**, retrieval available |
| Knowledge Center | 21 documents, 11 categories |
| announcements | 7 published |
| frontend `/`, `/knowledge`, `/announcements`, `/ai-office`, `/login`, `/support`, `/account`, `/?lang=ko` | 200; `/assistant` and `/admin` redirect (not signed in) |
| one RAG question (Korean, residence-card fee) | correct ("35,000원, since 1 January 2025"), answered in Korean, cited "Resident Card in South Korea"; 27.6 s |

The live commit cannot be read from the service (no revision endpoint). It is presumably the last `main` deploy. Its code
has the 14 agents and ko / en automatic translation, but not this release's changes.

## 3. Database (Supabase)

Production schema: presumed at migration **0015** (`main`). Not verified: no database access from this workstation.

| Migration | Required for this release? | Verified here |
|---|---|---|
| 0016 GPU worker | no (feature off) | additive; tested on scratch PostgreSQL |
| 0017 agent operations (desk sources, pause switch, storage overview) | recommended | additive; without it the new desks have no sources |
| 0018 AI usage controls (persistent budgets, usage table, emergency stop) | **recommended before heavy use** | additive; without it budgets stay in-process (reset on restart) |
| 0019 weekly discovery | no (schedules off) | additive; only re-times untouched, disabled schedules |

**Compatibility test** (release code against a scratch database built with migrations up to 0015 only): integration suite
93 passed, 0 failed, 16 skipped (the 7 extra skips are the 0016 / 0017 feature tests); all 42 parameter-free GET endpoints
called as anonymous, student, supporter, admin and super-admin: 0 server errors. **The release can be deployed before the
migrations;** the features that need them stay unavailable until they are applied.

No migration was applied to production.

## 4. Render

No Render access from here. The production services' environment differs from `render.yaml` (for example
`EMBEDDING_PROVIDER` is `e5` live and `e5_onnx` in the blueprint). Values were set by hand, so **a deploy changes the code
only, not the environment variables.** Settings to change by hand: FINAL-PRODUCTION-CHECKLIST §3.

## 5. Local tests of the release

Backend 1,082 passed / 0 failed; frontend 261 passed, type check and lint clean; PostgreSQL integration 104 passed (all
migrations) and 97 passed (schema 0015 only); SQL suites 15 / 15; browser journeys 114 / 115 (one 60-second timeout of the
local model on the Chinese desk), re-run of the chat journey 15 / 15. Details: TEST-REPORT.md.

## 6. Hosted smoke tests after the deploy

Not run (nothing deployed). The checklist §4 lists them, and the read-only part can be repeated from any computer.
