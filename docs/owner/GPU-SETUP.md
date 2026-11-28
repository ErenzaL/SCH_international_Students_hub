# University GPU computer

**Production activation, step by step: [GPU-ACTIVATION.md](GPU-ACTIVATION.md)** (token via `scripts/gpu_worker_token.sh`, start via `scripts/gpu_worker.sh`).

Only outbound HTTPS. Ollama listens on this computer only. **Nothing runs by itself**: no service, no cron. Ask university IT before using the machine for
production content.

## Check

| What | Command | Good |
|---|---|---|
| Ollama, models | `curl -s 127.0.0.1:11434/api/tags` | `translategemma:12b` in the list (announcement translation; checked 2026-11-28: digest `3189e9a01b8a`, Q4_K_M, 7.7 GB), else `ollama pull translategemma:12b` |
| Not exposed | `ss -ltn 'sport = :11434'` | `127.0.0.1:11434` (never `0.0.0.0` or `*`) |
| GPU, VRAM | `nvidia-smi` | RTX 4070 (12.2 GB); TranslateGemma 12B needs about 8–10 GB while it translates |
| Inference | `ollama run translategemma:12b "Translate into English: 안녕하세요"` | answer in seconds |
| All of it | `cd backend && .venv/bin/python -m app.cli doctor` | PASS in "models" |

## Worker (after Release B is live and 0016 is applied)

1. **API service:** `GPU_WORKER_ENABLED=true` (needs migration 0016). Announcement translations then always go to this worker (`ANNOUNCEMENT_TRANSLATION_MODEL=translategemma:12b`); while it is offline they **wait** - Gemini is not used for them unless `TRANSLATION_FALLBACK_TO_GEMINI=true` (default `false`). Chat and agents keep using Gemini.
2. **Token:** Admin → GPU worker → name `school-gpu` → Create. It is shown **once**.
3. **On this computer:**
   ```bash
   uv venv --python 3.11 ~/sch-gpu/venv && uv pip install --python ~/sch-gpu/venv/bin/python -r backend/requirements-gpu-worker.txt
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
| Computer is off | announcement tasks wait ("Waiting for the GPU worker") for up to 7 days (`GPU_WORKER_ANNOUNCEMENT_MAX_WAIT_HOURS`) and start when it is back; after that they end visibly and can be requested again; admins get one alert a day; no paid model is used; publication and chat are not affected. Document tasks still end after 48 h |
| Failed task | Admin → Translations → request again |
| Pause / stop for good | Admin → GPU worker → Pause / Revoke (at once) |
| Rotate | Admin → GPU worker → New token (the old one works 10 more minutes) → replace the file; no restart |
| Switch the whole feature off | `GPU_WORKER_ENABLED=false`: waiting tasks end ("GPU worker switched off"); new announcement requests are refused with that reason (reviewers translate by hand); only with `TRANSLATION_FALLBACK_TO_GEMINI=true` would Gemini take over |

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
