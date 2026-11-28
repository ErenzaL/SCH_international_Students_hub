# My setup checklist

In order. **You** = only you can do it. **Claude** = Claude Code can do it after you say so. Nothing needs a payment.
Details: [Supabase](SUPABASE-SETUP.md) · [Render](RENDER-SETUP.md) · [GitHub](GITHUB-SETUP.md) · [GPU](GPU-SETUP.md) · [External APIs](EXTERNAL-APIS.md) ·
[Sources](SOURCES.md) · [Roles](ROLES-AND-REVIEWERS.md) · [All variables](ENVIRONMENT.md) · [Inventory](CONFIGURATION-INVENTORY.md)

Already done (evidence): Release A and B integrated and tested locally; 25 sources prepared, 23 read live; `doctor` on the live services 10/10 PASS (read-only);
schedules, GPU worker and automatic translation are off by default; the worker, the database and both site services are free.

## A. Now

| # | Action | Why | Where / command | Who | Permission | Expected → verify | Risk if skipped |
|---|---|---|---|---|---|---|---|
| A1 | Confirm the commit address | commits become public | GitHub → Settings → Emails: `199873971+ErenzaL@users.noreply.github.com` | You | account | address listed | commits under a foreign identity |
| A2 | Run `doctor` against production (read-only) | shows every missing setting | `cd backend && SUPABASE_URL=… SUPABASE_SERVICE_ROLE_KEY=… SUPABASE_ANON_KEY=… .venv/bin/python -m app.cli doctor --api https://sch-hub-api.onrender.com --web https://sch-international-students-hub.onrender.com` on **your** computer | You | keys | no FAIL | hidden problems |
| A3 | Switch off pull-request previews, note Auto-Deploy | a branch must not deploy | Render → both services → Settings | You | Render | off | accidental deploy |
| A4 | Protect `main` | one wrong push deploys | [GITHUB-SETUP.md](GITHUB-SETUP.md) | You | GitHub admin | push refused | accidental deploy |
| A5 | Name a second reviewer, send `~/release-a-review/` | nobody has reviewed the code | e-mail | You | – | answer sheet returned | no independent check |
| A6 | Name reviewers and supporters for 5 languages | drafts and requests wait for people | [ROLES-AND-REVIEWERS.md](ROLES-AND-REVIEWERS.md) | You | super admin | `doctor`: people PASS | no translations, no human support |
| A7 | Make a backup and test that it can be read | none exists | [SUPABASE-SETUP.md](SUPABASE-SETUP.md) §5 | You | DB password | `pg_restore -l` lists tables | no way back after data loss |
| A8 | Ask the international office (content) and IT (GPU computer) for consent | their material, their machine | letter; [gpu-gateway-assessment.md](../gpu-gateway-assessment.md) | You | – | written answer | conflict with the university |

## B. Staging without a third Supabase project (zero cost; full runbook: [STAGING.md](STAGING.md))

| # | Action | Why | Where / command | Who | Permission | Expected → verify | Risk if skipped |
|---|---|---|---|---|---|---|---|
| B1 | Nothing to create in Supabase: both free projects stay as they are (no pause, delete, transfer or upgrade) | the account has its two free projects | – | – | – | production untouched | – |
| B2 | On your MacBook: install Colima, Docker CLI, Supabase CLI, psql, Python 3.11, Node 22 (and optionally Ollama + Qwen) | real Supabase Auth, Storage and RLS locally (tier L2) | STAGING.md §3 | You | your computer | `scripts/local_supabase.sh check` says ok | Auth/Storage only tested with stand-ins |
| B3 | Copy the code as a git bundle, then `local_supabase.sh up`, `api`, `web`, `test`, `e2e` | the full local staging on the real Supabase stack, loopback only | STAGING.md §4 | You (Claude can interpret the output) | your computer only | no FAIL; send the outputs | – |
| B4 | **Approval:** push `hub-staging` and create the free Render service `sch-hub-staging-probe` (no database, no secrets) | the real 512 MB / 0.1 CPU limit (tier R) | STAGING.md §5 | You, or Claude after your approval | **your written approval** | the probe answers `/health` | a 512 MB problem shows up first in production |
| B5 | `memory_probe_info.py` + `staging_memory_check.py` against the probe; Render Metrics and Events | memory, restarts, out-of-memory kills, responsiveness on real Render | STAGING.md §5 | You | probe key | no FAIL; memory under about 470 MB; no restart | – |

## C. Before Release A

| # | Action | Why | Where / command | Who | Permission | Expected → verify | Risk if skipped |
|---|---|---|---|---|---|---|---|
| C1 | Read-only checks "before" | titles / attachments that may be wrong today | [release-a-production-checks.md](../release/release-a-production-checks.md) | You | DB read | 2 CSV files | unknown starting point |
| C2 | Approve the push in writing, push one branch, draft pull request | publishes | [release-a-approvals.md](../release/release-a-approvals.md) boundary 1 | You | GitHub | draft PR | – |
| C3 | Review finished, risks accepted | quality | same, boundary 3 | reviewer + You | – | approved | bugs |
| C4 | Approve and merge (= deploy API), check 15 minutes | release | [release-a-plan.md](../release/release-a-plan.md) | You | GitHub, Render | checks pass, "after" CSV without new rows | – |

## D. Before Release B and this candidate

| # | Action | Why | Where / command | Who | Permission | Expected → verify | Risk if skipped |
|---|---|---|---|---|---|---|---|
| D1 | Decide the split: B, then RAG, then agents/UI ([RELEASE-CANDIDATE.md](../development/RELEASE-CANDIDATE.md)) | small reviews | – | You | – | order written | too much at once |
| D2 | New backup | before each schema change | as A7 | You | DB | listed | – |
| D3 | Apply 0016, later 0017 | schema for B / agents | [SUPABASE-SETUP.md](SUPABASE-SETUP.md) §2 | You | DB | `doctor` PASS | features show "needs migration" |
| D4 | Merge in order, one per day, watch | deploys | GitHub | You | – | live checks | – |
| D5 | Create the GPU worker, run `--check`, `--once` with one announcement | pilot | [GPU-SETUP.md](GPU-SETUP.md) | You | super admin, GPU account | draft `needs_review` | – |
| D6 | Native reviewers work through the pilot ([docs/review](../review/README.md)) | Qwen makes mistakes | – | reviewers | language permission | sheets filled | wrong information |

## E. Before autonomous agents

| # | Action | Why | Where / command | Who | Permission | Expected → verify | Risk if skipped |
|---|---|---|---|---|---|---|---|
| E1 | Add sources, check each by hand once | agents watch nothing without | Admin → Agents → Sources | You | admin | candidates appear | empty desks |
| E2 | Review the first candidates, approve content for TOPIK, scholarships, leave, graduation | knowledge gaps | AI Office → Review; Admin → Review Queue | You / admin | admin | visible to students | Seo, Leo, Joon have little to say |
| E3 | `AGENT_SCHEDULES_ENABLED=true` | first switch | Render → API → Environment | You | Render | `doctor`: WARNING "on" | checks only by hand |
| E4 | Switch on one schedule (Robo, 24 h); after a week the next | second switch | Admin → Agents → Schedules | You | admin | task "by a schedule", notification | – |
| E5 | Watch queues, storage, failing sources weekly | free limits | Admin → Agents | admin | admin | no red | slow decay |

## F. Optional, later

| # | Action | Why | Where | Who | Verify |
|---|---|---|---|---|---|
| F1 | Key for public-institution jobs | more for Daniel, free licence | [EXTERNAL-APIS.md](EXTERNAL-APIS.md) | You | source status ok |
| F2 | Saramin key, read its cautions | more jobs | same | You | same |
| F3 | JobKorea API through the university | schools may apply | same | You | answer of JobKorea |
| F4 | `GEMINI_LAB_KEY` on your computer | measured Qwen/Gemini comparison | `rag_lab.py --modes qwen,gemini` | You | table with both |
| F5 | Cross-encoder reranking | +7–9 points MRR in the research, needs more memory than the free plan | [RAG-EVALUATION.md](../development/RAG-EVALUATION.md) | Claude | benchmark |
| F6 | Decide on retention R1–R4 | storage | [retention-proposal.md](../release/retention-proposal.md) | You | not implemented today |
