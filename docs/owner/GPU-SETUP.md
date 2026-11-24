# University GPU computer

Only outbound HTTPS. Ollama listens on this computer only. **Nothing runs by itself**: no service, no cron. Ask university IT before using the machine for
production content.

## Check

| What | Command | Good |
|---|---|---|
| Ollama, models | `curl -s 127.0.0.1:11434/api/tags` | `qwen2.5:7b-instruct` in the list, else `ollama pull qwen2.5:7b-instruct` |
| Not exposed | `ss -ltn 'sport = :11434'` | `127.0.0.1:11434` (never `0.0.0.0` or `*`) |
| GPU, VRAM | `nvidia-smi` | RTX 4070, about 5.1 GB used with the model loaded (12.2 GB total) |
| Inference | `ollama run qwen2.5:7b-instruct "Say OK"` | answer in seconds |
| All of it | `cd backend && .venv/bin/python -m app.cli doctor` | PASS in "models" |

## Worker (after Release B is live and 0016 is applied)

1. **API service:** `GPU_WORKER_ENABLED=true`. Nothing else changes; without a connected worker the server's own model is used.
2. **Token:** Admin → GPU worker → name `school-gpu` → Create. It is shown **once**.
3. **On this computer:**
   ```bash
   python3.11 -m venv ~/sch-gpu/venv && ~/sch-gpu/venv/bin/pip install -r backend/requirements-gpu-worker.txt
   mkdir -p ~/.config/sch-gpu-worker && chmod 700 ~/.config/sch-gpu-worker
   install -m 600 /dev/null ~/.config/sch-gpu-worker/token && nano ~/.config/sch-gpu-worker/token    # paste the token
   install -m 600 backend/gpu-worker.env.example ~/.config/sch-gpu-worker/env && nano ~/.config/sch-gpu-worker/env   # set GPU_WORKER_HUB_URL
   ```
4. **Run** (from `backend`, after `set -a; . ~/.config/sch-gpu-worker/env; set +a`):

| Task | Command |
|---|---|
| Diagnose, contacts nothing but Ollama | `~/sch-gpu/venv/bin/python -m app.gpu_worker --check` |
| One task | `… --once` |
| Everything that waits, then stop (recommended) | `… --drain` |
| Continuous | without an option; keeps the free Render service awake, so use `GPU_WORKER_ACTIVE_HOURS` |
| Stop | Ctrl+C or `kill <pid>`: the task is handed back |

5. **See it:** Admin → GPU worker (last contact, queue, results) → Admin → Translations: the draft is `needs_review`. In Supabase (read-only):
   `select job_type, status, error_code, completed_at from ingestion_jobs where executor = 'gpu' order by created_at desc limit 5;`

| Situation | What happens / do |
|---|---|
| Worker dies in a task | the lease ends, the task is queued again (tested) |
| Computer is off | tasks wait; after 48 h without pickup they are handled by the server's own model or reported; chat is not affected |
| Failed task | Admin → Translations → request again |
| Pause / stop for good | Admin → GPU worker → Pause / Revoke (at once) |
| Rotate | Admin → GPU worker → New token (the old one works 10 more minutes) → replace the file; no restart |
| Switch the whole feature off | `GPU_WORKER_ENABLED=false`: waiting tasks return to the server's model |

## Qwen experiments with the Hub's RAG (no production access)

```bash
cd backend
.venv/bin/python ../scripts/rag_lab.py --modes retrieval,qwen,nocontext                      # benchmark, synthetic
.venv/bin/python ../scripts/rag_lab.py --ask "D-2 연장 서류는?" --language ko --modes retrieval,qwen,nocontext
.venv/bin/python ../scripts/eval_retrieval_benchmark.py --fetch-corpus https://sch-hub-api.onrender.com    # public documents only
.venv/bin/python ../scripts/rag_lab.py --corpus .eval-cache/public_corpus.json --ask "…" --modes qwen
GEMINI_LAB_KEY=… .venv/bin/python ../scripts/rag_lab.py --modes qwen,gemini                  # compares with Gemini (free key)
.venv/bin/python ../scripts/bench_qwen_capabilities.py                                        # extraction, tools, summaries, speed
```
The whole site with Qwen on this computer: [DEMO.md](../development/DEMO.md).
