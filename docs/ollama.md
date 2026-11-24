# Local models with Ollama (university server)

Ollama is an optional provider for development. Production configuration is not affected: with the new variables
unset, every service uses the same provider and model as before.

## Start the development backend

No Supabase project, `.env` file or API key is needed. From the repository root:

```bash
git branch --show-current                  # feature/school-ollama-integration
curl -s http://127.0.0.1:11434/api/tags    # qwen2.5:7b-instruct must be listed
cd backend
uv venv --python 3.11 .venv                # first time only (the system Python 3.10 is too old)
uv pip install --python .venv/bin/python -r requirements-dev.txt     # first time only
LLM_PROVIDER=ollama .venv/bin/python -m app.cli check-llm --generate
.venv/bin/python ../scripts/dev_ollama_backend.py
```

| Option | Effect |
|---|---|
| `--translation-only` | Qwen for drafts and agent tasks; the assistant quotes passages without a model |
| `--embedding hash` | no embedding model download (search is keyword-like, not multilingual) |
| `--port 8001` | another port (always on 127.0.0.1) |

The script uses the existing services with the in-memory store and synthetic data. It reads no `.env` file, refuses
to start when a Supabase variable is set, disables website fetching, and keeps scheduled agents, automatic translation
and public machine translations off. Data is lost when it stops. It prints `export …_TOKEN=` lines for the test users
and the id of a synthetic announcement; paste the lines into a second terminal:

```bash
# grounded answer (id, vi, ko, en, zh-CN)
curl -s http://127.0.0.1:8000/api/v1/assistant/chat -H 'content-type: application/json' \
  -d '{"message":"Gia hạn lưu trú D-2 cần giấy tờ gì?","language":"vi"}'

# announcement draft: queue, wait a few seconds, read
curl -s -X POST http://127.0.0.1:8000/api/v1/admin/announcements/$ANNOUNCEMENT_ID/translations/id/machine-translate \
  -H "Authorization: Bearer $ADMIN_TOKEN"
curl -s http://127.0.0.1:8000/api/v1/admin/announcements/$ANNOUNCEMENT_ID/translations/id \
  -H "Authorization: Bearer $SUPER_ADMIN_TOKEN"

# model latency and token usage (no content)
curl -s http://127.0.0.1:8000/api/v1/admin/system/llm-usage -H "Authorization: Bearer $ADMIN_TOKEN"
```

`uvicorn app.main:app` also accepts the variables below, but it reads `.env` and connects to the Supabase project
configured there. Do not use it here with production values. From your own computer, use an SSH tunnel
(`ssh -L 8000:127.0.0.1:8000 …`); do not bind to `0.0.0.0`.

## Choosing the provider

| Goal | `LLM_PROVIDER` | `BACKGROUND_LLM_PROVIDER` |
|---|---|---|
| Production today | unchanged | unset |
| Local drafts and agent tasks, Gemini answers | `gemini` | `ollama` |
| Local drafts only, no generated answers | `none` | `ollama` |
| Everything local | `ollama` | unset |

`LLM_PROVIDER` covers the assistant (query rewriting, answers, support handoff summary). `BACKGROUND_LLM_PROVIDER`
covers translation drafts, the `summarize_document` and `translate_text` agent tools and discovery summaries. There is
no fallback between providers: text given to the local model is never sent to a cloud service after a failure.

Background calls still count against `LLM_BACKGROUND_DAILY_ATTEMPTS` (150 per day; one per call for Ollama).
`TRANSLATION_MODEL` is for Gemini only.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | loopback only; anything else is refused at startup |
| `OLLAMA_MODEL` | `qwen2.5:7b-instruct` | |
| `OLLAMA_NUM_CTX` | `16384` | context window; Ollama reported about 5.6 GB of GPU memory with it |
| `OLLAMA_MAX_OUTPUT_TOKENS` | `8192` | per call, at most half of the context |
| `OLLAMA_TEMPERATURE` / `OLLAMA_KEEP_ALIVE` | `0.2` / `10m` | |
| `OLLAMA_MAX_CONCURRENCY` | `1` | simultaneous requests of this process, all features together |
| `OLLAMA_CONNECT_TIMEOUT_SECONDS` | `3` | |
| `OLLAMA_REQUEST_TIMEOUT_SECONDS` / `OLLAMA_JOB_TIMEOUT_SECONDS` / `OLLAMA_FAST_TIMEOUT_SECONDS` | `90` / `180` / `30` | one attempt: interactive / job / query rewrite |
| `OLLAMA_QUEUE_TIMEOUT_SECONDS` / `OLLAMA_JOB_QUEUE_TIMEOUT_SECONDS` | `30` / `300` | waiting for a free slot |
| `OLLAMA_REQUEST_DEADLINE_SECONDS` | `120` | interactive calls: no retry starts after this |
| `LLM_MAX_ATTEMPTS_PER_MODEL`, `LLM_RETRY_BASE_SECONDS`, `LLM_RETRY_MAX_DELAY_SECONDS` | existing | retries |
| `TRANSLATION_CHUNK_CHARS` | `6000` | `3000` is better for a 7B model (the script sets it) |

## Behaviour

- **Async and sync:** `acomplete` / `astream` for coroutines; `complete` / `stream` for the existing services.
- **Errors:** `llm_unavailable`, `llm_timeout`, `llm_rate_limited`, `llm_empty` and `llm_malformed` are retried.
  `llm_model`, `llm_bad_request`, `llm_context` and `llm_truncated` are not. Nothing is retried after streamed text
  was delivered.
- **Long prompts:** by default Ollama drops part of a prompt that does not fit and still answers 200. The provider
  turns this off (`truncate: false`), so the result is an `llm_context` error. Texts for summaries are cut to the
  context size and marked partial.
- **Drafts:** stored as `machine_draft`, or `needs_review` when a check flags them. Drafts from Ollama get extra checks:
  Chinese characters in other languages, Korean left untranslated, wrong language for id / vi / zh-CN.
- **Answers:** the assistant repeats its format rules after the question for Ollama only. All citation and grounding
  checks apply unchanged; an answer that fails them is replaced by the matching sources.
- **Logs:** one `llm_attempt` line per attempt with model, outcome, latency, tokens, queue time, load time and speed.
  Prompts, answers and Ollama's error texts are never logged.

## Tests and benchmark

```bash
cd backend
.venv/bin/python -m pytest -q tests/test_ollama_provider.py tests/integration/test_ollama_integration.py   # mocked
.venv/bin/python -m pytest -q && .venv/bin/ruff check .
.venv/bin/python ../scripts/bench_ollama_translation.py --out ../scripts/benchmarks/results/ollama_translation_qwen2.5-7b.json
```

Result of 2026-11-24 (qwen2.5:7b-instruct Q4_K_M, RTX 4070, two synthetic notices in all 20 directions, model already
loaded):

| Target | chrF | Median | Slowest | No check flagged |
|---|---|---|---|---|
| ko | 66.9 | 1.6 s | 1.8 s | 3/8 |
| en | 70.2 | 1.0 s | 1.4 s | 5/8 |
| id | 66.2 | 1.7 s | 2.2 s | 6/8 |
| vi | 61.2 | 1.5 s | 1.8 s | 8/8 |
| zh-CN | 51.8 | 1.1 s | 1.5 s | 1/8 |

How to read it:

- The references were written by an AI assistant and not checked by native speakers; chrF is not comparable between
  target languages, and two short notices are a small sample. "No check flagged" is not proof of a correct translation.
- Real errors found: zh-CN→en left out the whole application period; zh-CN→id kept a Chinese phrase; vi→ko had a
  Chinese title. The checks caught all three.
- Many other flags come from the existing checks, mostly for zh-CN and ko: dates rewritten as `12月1日`
  or `December 1`, text directly after a URL without a space, and a length ratio not calibrated for Chinese. The checks
  are shared with Gemini and were left unchanged.
- The checks cannot see wrong words. In the RAG trial, 재학증명서 became "bukti rencana studi" (proof of a study plan)
  in Indonesian. A person must review every draft.

## Limits

- Ollama has no authentication: every account on the server can use `127.0.0.1:11434`, and the development backend's
  port. Keep Ollama on loopback, and use synthetic or approved data only.
- The concurrency limit is per process; other users of the GPU can still slow requests down.
- `llm_timeout` is not in the job queue's list of retryable codes (existing behaviour), so a translation job that times
  out twice fails and must be requested again.
