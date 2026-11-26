# Master plan

Branch `integration/release-candidate` = `main` `eca1d71` + Release A `af2a766` + Release B `2e3acd4` + the work below. Local only.
**Not allowed:** push, merge to `main`, deploy, production data or migrations, production schedules or GPU work, automatic publication, public
Ollama, paid services, retention deletion, other branches (`research/milestone-5` is read only).

How to resume: read [PROGRESS.md](PROGRESS.md) (what is done, next step), [BLOCKERS.md](BLOCKERS.md), [TEST-RESULTS.md](TEST-RESULTS.md).
Worktree `~/projects/sch-hub-rc`; Python `~/projects/SCH_international_Students_hub/backend/.venv`; test database only with `scripts/scratch_db.sh`.

What the audit found: retrieval, the chat engine, the review workflow, durable queues, agents, discovery and the GPU worker exist and are tested.
They are extended, not rebuilt. Work packages:

| # | Package | Acceptance |
|---|---|---|
| R1 | Cross-language retrieval without a model call ("concept bridge"), larger glossary | better on the development set, not worse on the held-out set |
| R2 | Document families, superseded and expired notices, duplicates across sources | old notice never presented as current; provenance kept |
| R3 | Conflicting figures are shown to the model with their dates; untrusted text cannot leave its tag | unit tests, injection tests |
| R4 | Answer language is checked; one bounded retry | unit tests, Qwen benchmark |
| R5 | Evaluation: retrieval (R@k, P@k, MRR, nDCG), answers (faithfulness, citations, refusal, stale), five languages | reproducible scripts, results stored |
| A1 | Official-source monitoring for Yuna, Joon, Seo, Mia, Daniel (Robo, Leo exist) | real task, review candidates, schedule off |
| A2 | Supporter desks: review queue, terminology, translation drafts; Sumin: staff queue; deadline overview | real data, role checks |
| A3 | Admin: all agent tasks, rerun, cancel, pause an agent, health | server-side permissions, audit |
| Q1 | Qwen: RAG lab (Gemini / Qwen / retrieval only / no context), agent language tasks through the GPU queue | real GPU runs |
| U1 | Admin pages: agents, GPU workers, storage; AI Office tabs for the new monitoring desks | browser tests, phone width |
| O1 | `doctor` diagnostics, storage overview, owner manual, checklists, demo script | no secrets printed, no writes |
| T1 | Regression, database old/new schema, browser, GPU, failure recovery | TEST-RESULTS.md |
