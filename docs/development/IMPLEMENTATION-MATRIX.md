# Implementation matrix

**V** implemented and verified here · **P** partly · **B** blocked outside · tests in `backend/tests`, `apps/web/src/**/*.test.tsx`, `scripts/e2e_*.mjs`.

| Requirement | State | Code | Evidence |
|---|---|---|---|
| Approved version only (titles, text, attachments, translations) | V | Release A | Release A tests, staging script 14/14, browser 23/23 |
| GPU worker, leases, recovery, rotation | V | `services/gpu_worker.py`, `gpu_worker/` | unit, PostgreSQL, real GPU 20/20, browser |
| Hybrid multilingual retrieval | V | `services/retrieval/` | pilot + held-out |
| Cross-language without a model call | V | `retrieval/bridge.py` | held-out MRR 0.657 → 0.729 |
| Editions, copies, passed deadlines, conflicts | V | `retrieval/families.py`, `assistant/engine.py` | `test_families_and_notes` |
| Grounded answers, citations, refusal, language | V | `assistant/engine.py` | benchmark, browser |
| Reranking | P | `retrieval/rerank.py` | exists, off: memory of the free plan |
| Human-checked benchmark | B | `docs/review` | reviewers |
| Gemini comparison | B | `scripts/rag_lab.py` | key |
| 14 agents with jobs, tools, states | V | `services/agents/` | [AGENT-MATRIX](AGENT-MATRIX.md) |
| Monitoring for seven desks | V | `services/discovery/` | live, scheduled run in development |
| Schedules, retries, leases, cancel, pause, rerun, health, dedupe | V | `agents/tasks.py`, `operations.py`, 0014/0017 | unit, SQL, PostgreSQL, browser |
| Admin approval of everything found | V | discovery → review | browser |
| Official sources managed in the interface | V | Admin → Agents → Sources | browser |
| Job APIs | B | `discovery/job_apis.py` | fixtures; keys |
| JobKorea, Buddies | B | – | access |
| Reviewed translations and summaries by Qwen | V | queue + `request_translation_draft` | browser, GPU |
| Structured extraction / categories by Qwen | P | measured, rules kept | [GPU-EVALUATION](GPU-EVALUATION.md) |
| Interactive Qwen RAG on the workstation | V | `rag_lab.py`, `dev_stack.py` | [DEMO](DEMO.md) |
| Admin: agents, schedules, sources, storage, GPU, jobs | V | `features/admin` | browser, 16 pages |
| Moderator role | – | admin covers it | [roles](../owner/ROLES-AND-REVIEWERS.md) |
| Storage overview and warnings | V | `storage_overview()`, alerts | tests |
| Retention deletion R1–R4 | not implemented | – | by instruction |
| Five languages, phone, keyboard | V | messages | browser |
| `doctor` | V | `app/doctor.py` | tests, live read-only 10/10 |
| Hosted staging, Render run of this candidate, mobile Safari, screen readers | not tested | – | owner |
