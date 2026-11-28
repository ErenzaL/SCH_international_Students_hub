# Demonstration (university LLM project, about 20 minutes)

Everything on the GPU computer: real PostgreSQL, real API, real Qwen, live official websites. Synthetic accounts. No production access, nothing public.

## Start
```bash
export PG_BIN=/path/to/pg/bin POSTGREST=/path/to/postgrest PYTHON=backend/.venv/bin/python     # docs/setup.md §7
scripts/scratch_db.sh start /tmp/demo-db && source /tmp/demo-db/env
(cd backend && .venv/bin/python ../scripts/dev_stack.py --info /tmp/demo.json) &                 # add --schedules for step 6
cd apps/web && NEXT_PUBLIC_API_URL=http://127.0.0.1:8051 NEXT_PUBLIC_SUPABASE_URL=http://127.0.0.1:8052 NEXT_PUBLIC_SUPABASE_ANON_KEY=any npm run build && npx next start -H 127.0.0.1 -p 3051
```
Password: `python3 -c "import json;print(json.load(open('/tmp/demo.json'))['password'])"`. Accounts: `super_admin@`, `admin@`, `supporter_vi@`, `reviewer_id@`,
`student@` `example.test`. From your own computer: `ssh -L 3051:127.0.0.1:3051 -L 8051:127.0.0.1:8051 -L 8052:127.0.0.1:8052 <server>`, then http://127.0.0.1:3051.
Stop: Ctrl+C, `scripts/scratch_db.sh stop /tmp/demo-db`.

## Show

| # | Step | Say |
|---|---|---|
| 1 | AI Office, open a few of the 14 characters, switch languages, phone width | each desk has its own tools; `About` lists what it never does |
| 2 | Admin → Agents → Sources → add "유학생 공지사항"; AI Office → Robo → *Check official sources* | live website, robots.txt, background worker, candidates |
| 3 | Robo → Review → Send to review; Admin → Review → Approve | nothing is public before this click |
| 4 | Sari (as student): ask in Indonesian about that notice; open the citation; ask a follow-up | Korean source, Indonesian answer, Qwen on the RTX 4070 (`nvidia-smi`) |
| 5 | Ask for something no source has ("parking permit") | it says so; the benchmark: unanswerable 100 % refused |
| 6 | Admin → GPU worker → create; `python -m app.gpu_worker --check` / `--drain`; Minh → Queue → Request a draft; Admin → Translations → approve | draft, checks, human review, public |
| 7 | Sumin: request to a person, confirm; supporter's queue shows no private words | privacy |
| 8 | `rag_lab.py --ask "…" --modes retrieval,qwen,nocontext` | same question: excerpts, RAG, and what the model invents without sources (0 % correct) |
| 9 | [RAG-EVALUATION.md](RAG-EVALUATION.md), [GPU-EVALUATION.md](GPU-EVALUATION.md) | before/after, limits, labels not reviewed by people |

The whole sequence runs unattended as a test: `node scripts/e2e_full.mjs /tmp/demo.json OUT WORKER_PYTHON backend` (153 checks).
