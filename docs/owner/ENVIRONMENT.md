# Environment variables

Generated from the code by `scripts/env_inventory.py`; do not edit by hand. 180 variables of the **API service**. Whether a value is set on
Render cannot be seen from here: check with `python -m app.cli doctor` (prints "set" or "not set", never a value) or in the dashboard.

After changing a variable on Render the service restarts by itself (choose *Save, rebuild and deploy* only for the web variables).

## Web service (Render → sch-hub-web → Environment)

All three are **public**: they are built into the pages. Never put a secret here. After a change: *Manual Deploy → Clear build cache & deploy*.

| Variable | Required | Get it | Verify |
|---|---|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | yes | Supabase → Project Settings → API → Project URL | sign-in page works |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | yes | the **publishable / anon** key, never the secret key | `doctor` fails if it is the secret key |
| `NEXT_PUBLIC_API_URL` | yes | address of the API service without `/api/v1` | the Knowledge Center shows documents |

## GitHub (Settings → Secrets and variables → Actions)

| Name | Kind | Required | Purpose | Verify |
|---|---|---|---|---|
| `RENDER_DEPLOY_HOOK_API`, `RENDER_DEPLOY_HOOK_WEB` | SECRET | for automatic deploys | Render → service → Settings → Deploy Hook | Actions → Deploy to Render → log |
| `CRON_SECRET` | SECRET | for daily imports | same value as on the API service | Actions → Scheduled knowledge sync → log |
| `SCH_API_URL` | variable | no | address of the API | same |

## University GPU computer (`~/.config/sch-gpu-worker/env`, see GPU-SETUP.md)

| Variable | Required | Meaning |
|---|---|---|
| `GPU_WORKER_HUB_URL` | yes | `https://` address of the API, no path |
| `GPU_WORKER_PRODUCTION_HOST` | no | leave unset: the worker refuses the production API. Only after the Release B sign-off: exactly `sch-hub-api.onrender.com` |
| `GPU_WORKER_TOKEN_FILE` | yes | file with the token, mode 600 (the token itself is **not** a variable) |
| `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `OLLAMA_NUM_CTX`, `OLLAMA_JOB_TIMEOUT_SECONDS` | no | defaults: loopback, `qwen2.5:7b-instruct`, 16384, 180 |
| `GPU_WORKER_IDLE_MIN_SECONDS`, `GPU_WORKER_IDLE_MAX_SECONDS`, `GPU_WORKER_ACTIVE_HOURS`, `GPU_WORKER_LOCK_FILE` | no | continuous mode only |

The worker refuses to start when a Supabase, Gemini or cron secret is set on that computer.

## API service (Render → sch-hub-api → Environment)

| Variable | Kind | Needed | Default | In template | Purpose |
|---|---|---|---|---|---|
| `SUPABASE_URL` | setting | **required** | — | render.yaml, .env.example | <br>**Get it:** Supabase → Project Settings → API → Project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | SECRET | **required** | — | render.yaml, .env.example | <br>**Get it:** Supabase → Project Settings → API Keys → secret / service_role key. Never in the web service |
| `CORS_ORIGINS` | setting | **required** | `http://localhost:3000` | render.yaml, .env.example | Comma-separated. Read from CORS_ORIGINS or CORS_ALLOWED_ORIGINS (first one set wins).<br>**Get it:** the exact web address, e.g. https://sch-international-students-hub.onrender.com |
| `SUPABASE_JWT_SECRET` | SECRET | production | — | render.yaml, .env.example | Legacy HS256 projects: JWT secret. Projects using asymmetric signing keys are verified through the JWKS endpoint derived from SUPABASE_URL (no secret needed).<br>**Get it:** Supabase → Project Settings → JWT Keys → legacy secret. Only when the project signs with HS256 |
| `EMBEDDING_PROVIDER` | setting | production | `e5` | render.yaml, .env.example | "e5" (sentence-transformers) / "hash" (dev/test only, NOT semantic) |
| `EMBEDDING_CACHE_DIR` | setting | production | — | render.yaml | model files cache (default: Hugging Face cache); set to a path inside |
| `RETRIEVAL_MIN_SIMILARITY` | setting | production | `0.0` | render.yaml, .env.example | Vector-only matches below this cosine similarity are dropped unless they also match a keyword. |
| `JOB_EXECUTION` | setting | production | `worker` | render.yaml, .env.example | "worker": persisted queue claimed by an in-process worker thread (survives restarts: queued jobs are picked up again, stale running jobs are re-queued). "inline": run in  |
| `CRON_SECRET` | SECRET | production | — | render.yaml, .env.example | Shared secret for POST /api/v1/internal/sync/run-due (external scheduler). Empty = endpoint disabled.<br>**Get it:** make one: `openssl rand -base64 32`; the same value as GitHub → Settings → Secrets → Actions → CRON_SECRET |
| `LLM_PROVIDER` | setting | production | `none` | render.yaml, .env.example | none / anthropic / gemini / ollama |
| `LLM_API_KEY` | SECRET | production | — | render.yaml, .env.example | server-side secret; empty = the SDK reads its own variable (ANTHROPIC_API_KEY / GEMINI_API_KEY)<br>**Get it:** https://aistudio.google.com/apikey |
| `GEMINI_PRIMARY_MODEL` | setting | production | `gemini-3.6-flash` | render.yaml, .env.example | Gemini (LLM_PROVIDER=gemini). gemini-3.5-flash is deprecated and routed by Google to gemini-3.6-flash, so the stable successor is the default primary (verify with `python |
| `GEMINI_FALLBACK_MODEL` | setting | production | `gemini-3.5-flash-lite` | render.yaml, .env.example | empty = no fallback model |
| `APP_VERSION` | setting | optional | `0.1.0` | — |  |
| `ENVIRONMENT` | setting | optional | `development` | — |  |
| `LOG_LEVEL` | setting | optional | `INFO` | .env.example |  |
| `SUPABASE_JWT_AUDIENCE` | setting | optional | `authenticated` | — |  |
| `SOURCE_FILES_BUCKET` | setting | optional | `source-files` | — |  |
| `MAX_REQUEST_BODY_MB` | setting | optional | `12` | — |  |
| `ALLOWED_SOURCE_DOMAINS` | setting | optional | (list) | .env.example |  |
| `FETCH_TIMEOUT_SECONDS` | setting | optional | `20.0` | — |  |
| `MAX_RESPONSE_MB` | setting | optional | `5` | .env.example |  |
| `MAX_UPLOAD_MB` | setting | optional | `10` | .env.example |  |
| `MAX_REDIRECTS` | setting | optional | `4` | — |  |
| `RESPECT_ROBOTS_TXT` | setting | optional | `True` | — |  |
| `FETCH_USER_AGENT` | setting | optional | (list) | — |  |
| `MIN_EXTRACTED_CHARS` | setting | optional | `40` | — |  |
| `CHUNK_TARGET_TOKENS` | setting | optional | `320` | — |  |
| `CHUNK_MAX_TOKENS` | setting | optional | `420` | — |  |
| `CHUNK_OVERLAP_TOKENS` | setting | optional | `48` | — |  |
| `EMBEDDING_MODEL` | setting | optional | `intfloat/multilingual-e5-small` | render.yaml, .env.example |  |
| `EMBEDDING_DIMENSIONS` | setting | optional | `384` | .env.example |  |
| `EMBEDDING_BATCH_SIZE` | setting | optional | `16` | — |  |
| `EMBEDDING_ONNX_VARIANT` | setting | optional | `qint8` | — | e5_onnx: qint8 (~118 MB, default) / fp32 / o4 |
| `EMBEDDING_ONNX_BATCH_SIZE` | setting | optional | `1` | — | e5_onnx: 1 keeps peak memory lowest on 512 MB instances |
| `EMBEDDING_THREADS` | setting | optional | `0` | — | e5_onnx: 0 = min(2, CPUs) |
| `RETRIEVAL_FUSION` | setting | optional | `weighted` | .env.example | "weighted" (default): dense and keyword candidates are fetched separately and fused in the application with semantic relevance weighted above keyword overlap (keyword evi |
| `RETRIEVAL_VECTOR_WEIGHT` | setting | optional | `1.0` | — |  |
| `RETRIEVAL_KEYWORD_WEIGHT` | setting | optional | `0.35` | — |  |
| `RETRIEVAL_BRIDGE_WEIGHT` | setting | optional | `0.75` | .env.example | extra Korean/English concept queries (retrieval/bridge.py); 0 = off |
| `RETRIEVAL_CROSS_SCRIPT_WEIGHT` | setting | optional | `0.0` | — | off: helped the development sets, not the blind set (KOREAN-RETRIEVAL.md) |
| `RETRIEVAL_HUB_BETA` | setting | optional | `0.0` | — | long documents (many chunks) are scaled down by (typical/n)**beta; 0 = off |
| `RETRIEVAL_CANDIDATE_POOL` | setting | optional | `30` | — | candidates fetched per leg before fusion |
| `RETRIEVAL_MAX_CHUNKS_PER_DOCUMENT` | setting | optional | `3` | — |  |
| `RETRIEVAL_CODE_MISMATCH_PENALTY` | setting | optional | `0.5` | — | a passage that names a different visa/status code (E-7, F-2-R ...) but not the one asked about is demoted |
| `BOARD_MAX_ITEMS` | setting | optional | `5` | .env.example | notices imported per sync unless the source config says otherwise |
| `BOARD_MAX_ITEMS_CAP` | setting | optional | `30` | — | hard upper bound per sync (polite crawling) |
| `BOARD_MAX_PAGES` | setting | optional | `1` | — |  |
| `BOARD_REQUEST_DELAY_SECONDS` | setting | optional | `1.0` | — |  |
| `OCR_PROVIDER` | setting | optional | `none` | render.yaml, .env.example | "none" (manual transcription), "tesseract" (local binary; Docker/dev), "ocr_space" (hosted free tier) |
| `OCR_LANGUAGES` | setting | optional | `kor+eng` | .env.example | tesseract language codes |
| `OCR_SPACE_API_KEY` | SECRET | optional | — | render.yaml, .env.example | <br>**Get it:** https://ocr.space/ocrapi (free key; images go to that service) |
| `OCR_SPACE_LANGUAGE` | setting | optional | `kor` | — |  |
| `OCR_SPACE_ENGINE` | setting | optional | `1` | — |  |
| `OCR_TIMEOUT_SECONDS` | setting | optional | `60.0` | — |  |
| `OCR_MAX_PDF_PAGES` | setting | optional | `10` | — |  |
| `MAX_IMAGE_MB` | setting | optional | `8` | — |  |
| `EMBED_ON_INGEST` | setting | optional | `False` | — | Pre-review content is chunked but NOT embedded; embeddings are generated by the index job after approval. |
| `JOB_RETRY_BASE_SECONDS` | setting | optional | `30` | — |  |
| `CONVERSATION_RETENTION_DAYS` | setting | optional | `365` | — | AI conversations deleted after this many days without activity |
| `SUPPORT_RETENTION_DAYS` | setting | optional | `365` | — | resolved support tickets (and their threads) deleted after this   # transient failures re-queue after 30 s, 60 s, 120 s ... (max_attempts) |
| `JOB_POLL_SECONDS` | setting | optional | `10.0` | — |  |
| `AGENT_TASK_WORKER` | setting | optional | `True` | — | A second worker thread only for agent tasks (digests, checklists, official-source checks): document ingestion, indexing and translation never wait behind a ~90 s official |
| `INGESTION_MAX_CONCURRENT_JOBS` | setting | optional | `1` | — | ingestion jobs executing at the same time in one process (worker thread, inline background tasks, CLI); 1 on 512 MB |
| `JOB_HEARTBEAT_SECONDS` | setting | optional | `15.0` | — | running jobs heartbeat every job_heartbeat_seconds (a background ticker, also during long extractions); a job without a heartbeat for job_stale_seconds belongs to a dead  |
| `JOB_STALE_SECONDS` | setting | optional | `180` | — |  |
| `JOB_STARTUP_STALE_SECONDS` | setting | optional | `90` | — |  |
| `JOB_MAX_RUNTIME_SECONDS` | setting | optional | `1800` | — | heartbeats stop after this, so a hung job goes stale and is recovered |
| `ASSISTANT_STRONG_SIMILARITY` | setting | optional | `0.84` | — | without an LLM: passages at/above this similarity (or keyword/exact matches) count as sufficient evidence |
| `ASSISTANT_ANONYMOUS_CHAT` | setting | optional | `True` | — | visitors who are not signed in can chat (no history, no handoff) |
| `ASSISTANT_HISTORY_TURNS` | setting | optional | `6` | — | earlier messages given to rewriting and generation |
| `ASSISTANT_PROMPT_VERSION` | setting | optional | `system_v2` | render.yaml, .env.example | behavioral specification: app/services/assistant/prompts/<version>.txt (recorded with every answer) |
| `ASSISTANT_FOLLOW_UP_SUGGESTIONS` | setting | optional | `False` | — | follow-up suggestion chips under answers (off: answers end when they are complete) |
| `ASSISTANT_MAX_SOURCES` | setting | optional | `4` | — | distinct source documents given to the model per answer |
| `ASSISTANT_MAX_PASSAGES_PER_SOURCE` | setting | optional | `3` | — |  |
| `ASSISTANT_CONTEXT_CHARS` | setting | optional | `9000` | — | total passage text sent to the model |
| `ASSISTANT_VERIFY_LOCAL` | setting | optional | `True` | .env.example | a short second look at answers with figures, small local models only |
| `ASSISTANT_EVIDENCE_CHECK` | setting | optional | `False` | — |  |
| `ASSISTANT_EVIDENCE_ADJACENT` | setting | optional | `True` | — |  |
| `ASSISTANT_EVIDENCE_SECOND_SEARCH` | setting | optional | `True` | — |  |
| `ASSISTANT_EVIDENCE_MAX_ADDED_PASSAGES` | setting | optional | `4` | — |  |
| `ASSISTANT_EVIDENCE_MAX_ADDED_CHARS` | setting | optional | `3000` | — |  |
| `RERANK_PROVIDER` | setting | optional | `none` | — | none / onnx |
| `RERANK_MODEL_PATH` | setting | optional | — | — | e.g. /models/mminilm/model_int8.onnx |
| `RERANK_TOKENIZER_PATH` | setting | optional | — | — | its sentencepiece.bpe.model |
| `RERANK_TOP_N` | setting | optional | `20` | — | first-stage passages scored by the cross-encoder |
| `RERANK_BATCH_SIZE` | setting | optional | `4` | — | pairs per forward pass (activation memory grows with it) |
| `RERANK_THREADS` | setting | optional | `1` | — |  |
| `RERANK_MAX_LENGTH` | setting | optional | `512` | — |  |
| `PDF_EXTRACTION_ISOLATION` | setting | optional | `subprocess` | — | subprocess / inline (tests) |
| `PDF_EXTRACT_TIMEOUT_SECONDS` | setting | optional | `300.0` | — |  |
| `PDF_EXTRACT_MEMORY_MB` | setting | optional | `0` | — | address-space cap for the child (Linux); 0 = no extra cap |
| `PDF_TABLE_DETECTION` | setting | optional | `off` | — | off / auto (find_tables() costs ~230 MB; enable only on larger plans) |
| `PDF_MAX_TABLE_ITEMS` | setting | optional | `1500` | — | auto mode: skip table detection on pages with more drawing operations |
| `PDF_MAX_PAGES` | setting | optional | `300` | — |  |
| `SOURCE_REVIEW_AGE_DAYS` | setting | optional | `1095` | — | new versions whose publication date / declared edition is older than this get a reviewer warning to verify time-sensitive guidance (nothing is changed or hidden automatic |
| `BACKGROUND_LLM_PROVIDER` | setting | optional | — | .env.example | background work only (translation drafts, agent summaries / translations, discovery summaries): none / anthropic / gemini / ollama. Empty = LLM_PROVIDER (the existing beh |
| `LLM_MODEL` | setting | optional | `claude-opus-5-5` | — | anthropic only |
| `LLM_EFFORT` | setting | optional | `medium` | — | low / medium / high / xhigh / max |
| `LLM_TIMEOUT_SECONDS` | setting | optional | `120.0` | — |  |
| `GEMINI_THINKING_LEVEL` | setting | optional | `low` | render.yaml, .env.example | minimal / low / medium / high ("" = model default) |
| `OLLAMA_BASE_URL` | setting | optional | `http://127.0.0.1:11434` | .env.example | Ollama (local models, university server only; see docs/ollama.md). Loopback addresses only. |
| `OLLAMA_MODEL` | setting | optional | `qwen2.5:7b-instruct` | .env.example |  |
| `OLLAMA_NUM_CTX` | setting | optional | `16384` | — | a prompt that does not fit is an error, never cut silently |
| `OLLAMA_MAX_OUTPUT_TOKENS` | setting | optional | `8192` | — | per call (at most half of the context) |
| `OLLAMA_TEMPERATURE` | setting | optional | `0.2` | — |  |
| `OLLAMA_KEEP_ALIVE` | setting | optional | `10m` | — | how long the model stays in GPU memory when idle |
| `OLLAMA_MAX_CONCURRENCY` | setting | optional | `1` | — | requests sent at the same time, all features together (one GPU) |
| `OLLAMA_CONNECT_TIMEOUT_SECONDS` | setting | optional | `3.0` | — |  |
| `OLLAMA_REQUEST_TIMEOUT_SECONDS` | setting | optional | `90.0` | — | one attempt, interactive calls |
| `OLLAMA_JOB_TIMEOUT_SECONDS` | setting | optional | `180.0` | — | one attempt, translation jobs |
| `OLLAMA_FAST_TIMEOUT_SECONDS` | setting | optional | `30.0` | — | query rewriting (may include loading the model) |
| `OLLAMA_QUEUE_TIMEOUT_SECONDS` | setting | optional | `30.0` | — | waiting for a free slot, interactive calls |
| `OLLAMA_JOB_QUEUE_TIMEOUT_SECONDS` | setting | optional | `300.0` | — | ... jobs |
| `OLLAMA_REQUEST_DEADLINE_SECONDS` | setting | optional | `120.0` | — | interactive calls: no retry starts after this much time |
| `GPU_WORKER_ENABLED` | setting | optional | `False` | .env.example | GPU worker on the university server (docs/gpu-worker.md). OFF: no endpoint exists and nothing is routed to it. When on, these translation jobs wait for the worker instead |
| `GPU_WORKER_JOB_TYPES` | setting | optional | `translate_announcement,translate_document` | — |  |
| `GPU_WORKER_MODELS` | setting | optional | `qwen2.5:7b-instruct` | — | models whose results are accepted |
| `GPU_WORKER_MAX_RUNNING` | setting | optional | `1` | — | jobs leased at the same time, all workers together |
| `GPU_WORKER_LEASE_SECONDS` | setting | optional | `180` | — | renewed by the worker; a lost worker's job is re-queued after this |
| `GPU_WORKER_JOB_MAX_SECONDS` | setting | optional | `1800` | — | a lease is not renewed beyond this |
| `GPU_WORKER_CHUNK_CHARS` | setting | optional | `1200` | — |  |
| `GPU_WORKER_MAX_SOURCE_CHARS` | setting | optional | `12000` | — | text a summary is made from (longer: partial, labelled) |
| `GPU_WORKER_ONLINE_HOURS` | setting | optional | `24` | — | no contact for this long: new requests use the server's own model |
| `GPU_WORKER_MAX_QUEUE_HOURS` | setting | optional | `48` | — | a job that waited this long is not left waiting ... |
| `GPU_WORKER_ON_EXPIRY` | setting | optional | `fail` | — | ... "fail": visible failure + alert / "local": server's own model |
| `GPU_WORKER_TOKEN_DAYS` | setting | optional | `90` | — | validity of a new or rotated credential |
| `LLM_TEMPERATURE` | setting | optional | — | .env.example | None = the model's default (recommended for Gemini 3 models) |
| `LLM_ANSWER_MAX_TOKENS` | setting | optional | `2048` | — | answer generation output cap (thinking tokens count separately) |
| `LLM_REQUEST_TIMEOUT_SECONDS` | setting | optional | `30.0` | render.yaml, .env.example | per attempt (assistant answers); translation jobs use llm_timeout |
| `LLM_MAX_ATTEMPTS_PER_MODEL` | setting | optional | `2` | render.yaml, .env.example | primary: 1 try + 1 retry on retryable errors; fallback: same bound |
| `LLM_RETRY_BASE_SECONDS` | setting | optional | `0.8` | — | exponential backoff with full jitter |
| `LLM_RETRY_MAX_DELAY_SECONDS` | setting | optional | `8.0` | — | a server-requested delay above this is not waited for (fail over) |
| `LLM_REQUEST_DEADLINE_SECONDS` | setting | optional | `45.0` | — | interactive calls: no new attempt starts after this much time |
| `LLM_FAST_TIMEOUT_SECONDS` | setting | optional | `12.0` | — | query rewriting: one quick attempt (fast model first) |
| `AI_DAILY_LIMIT_PER_CLIENT` | setting | optional | `40` | render.yaml, .env.example | anonymous visitors, per client IP |
| `AI_DAILY_LIMIT_PER_USER` | setting | optional | `150` | render.yaml, .env.example | signed-in students |
| `AI_DAILY_LIMIT_GLOBAL` | setting | optional | `1500` | render.yaml, .env.example | all generated answers; beyond it answers degrade, never fail open |
| `TRANSLATION_CHUNK_CHARS` | setting | optional | `6000` | — | translation drafts: documents are translated in chunks of about this many characters (one job per language) |
| `AUTO_TRANSLATE_DOCUMENTS` | setting | optional | `False` | — | create AI drafts automatically when a new original version is approved (needs an LLM provider) |
| `PUBLIC_MACHINE_TRANSLATIONS` | setting | optional | `False` | — | show unreviewed machine drafts to students (clearly labelled as machine translation). Off = original only. |
| `AUTO_TRANSLATE_ANNOUNCEMENTS` | setting | optional | `False` | — | queue machine translations when an announcement is published |
| `AUTO_TRANSLATE_LANGUAGES` | setting | optional | `ko,en,id` | — | target languages generated automatically (others: by request) |
| `ANNOUNCEMENT_MACHINE_LANGUAGES` | setting | optional | `ko,en,id` | — | Release 1: machine drafts of ANNOUNCEMENTS only in these languages (automatic and on request). Existing approved translations in other languages stay visible; the chatbot |
| `TRANSLATION_MODEL` | setting | optional | — | — | Gemini model for translation jobs ("" = the assistant's models) |
| `TRANSLATION_FULL_MAX_CHARS` | setting | optional | `12000` | — | longer documents: title + AI summary only (labelled as summary) |
| `TRANSLATION_SUMMARY_SOURCE_CHARS` | setting | optional | `40000` | — | text given to the summarizer (plus all section headings) |
| `TRANSLATION_MAX_REQUESTS_PER_JOB` | setting | optional | `6` | — | model calls per job (title + parts); longer -> human translation |
| `TRANSLATION_DAILY_JOB_LIMIT` | setting | optional | `60` | — | translation jobs started per UTC day; more wait until tomorrow |
| `LLM_BACKGROUND_DAILY_ATTEMPTS` | setting | optional | `150` | — | Reserve for the chatbot: every model ATTEMPT made by background work (translation jobs, AI summaries, discovery summaries; retries and fallbacks included) counts against  |
| `AI_BACKGROUND_STOP` | setting | optional | `False` | — | Emergency stop for ALL background AI (translations, summaries, discovery); the chatbot keeps working. An administrator can also switch it in the admin system page (needs  |
| `LLM_PRICES` | setting | optional | — | — | Prices for cost ESTIMATES, USD per million tokens: "model=input/output,model2=input/output" (copy them from the provider's official price list; thinking tokens are priced |
| `LLM_BACKGROUND_DAILY_USD_LIMIT` | setting | optional | `0.0` | — | Optional ceiling on today's (KST) estimated background cost in USD; 0 = off. With a ceiling, a model without a price in LLM_PRICES gets no background attempts (unknown co |
| `AI_BUDGET_PERSISTENT` | setting | optional | `True` | — | Daily AI budgets (background attempts, generated chat answers) in the database (migration 0018), so restarts do not reopen them. Without the migration they stay in-proces |
| `TRANSLATION_QUOTA_RETRY_SECONDS` | setting | optional | `3600` | — | provider quota exhausted: try the job again after this long |
| `TRANSLATION_MAX_DEFERRALS` | setting | optional | `24` | — | ... at most this many times, then the job fails visibly |
| `MACHINE_TRANSLATION_HIGH_RISK` | setting | optional | `label` | — | unreviewed machine translations of immigration / employment / insurance / fee / legal content: 'label' = shown with a prominent "unverified" label; 'review' = hidden unti |
| `AGENT_TASKS_ENABLED` | setting | optional | `True` | — | background agent tasks (read-only tools work regardless) |
| `AGENT_MAX_ACTIVE_TASKS_PER_USER` | setting | optional | `5` | — | queued + running + awaiting approval |
| `AGENT_DAILY_TASKS_PER_USER` | setting | optional | `30` | — | tasks created per user per KST day |
| `AGENT_TOOL_RUNS_PER_MINUTE` | setting | optional | `30` | — | instant tool runs per user / client IP |
| `AGENT_TASK_TIMEOUT_SECONDS` | setting | optional | `180` | — | a task that runs longer fails (checked between steps) |
| `AGENT_TASK_RETENTION_DAYS` | setting | optional | `30` | — | finished tasks (and their step log) are deleted afterwards |
| `DATABASE_LIMIT_MB` | setting | optional | `500` | .env.example | size limit of the database plan (free plan: 500 MB); only for the admin storage warnings |
| `AGENT_SCHEDULES_ENABLED` | setting | optional | `False` | — | master switch for scheduled agents. Even when true, each schedule runs only after an admin enables it. |
| `DISCOVERY_WEEKLY_ANCHOR` | setting | optional | `mon 03:00` | — | weekly schedules (interval 10080) run at this slot, Korea time, plus their own stagger (params.stagger_minutes): "<mon/tue/wed/thu/fri/sat/sun> HH:MM" |
| `SARAMIN_ACCESS_KEY` | SECRET | optional | — | .env.example | official-source discovery (Phase 3): polite, bounded checks of admin-configured official pages official recruitment APIs (app/services/discovery/job_apis.py); empty = the<br>**Get it:** https://oapi.saramin.co.kr/join (approval needed) |
| `DATA_GO_KR_SERVICE_KEY` | SECRET | optional | — | .env.example | <br>**Get it:** https://www.data.go.kr/data/15125273/openapi.do → 활용신청 |
| `WORK24_AUTH_KEY` | SECRET | optional | — | — | 고용24 Open API (job postings): the key from work24.go.kr -> OPEN-API. Without it the source is shown as blocked.<br>**Get it:** https://www.work24.go.kr → OPEN-API → 채용정보 API 신청 (terms and limits: confirm on that page) |
| `DISCOVERY_MAX_ITEMS` | setting | optional | `10` | — | items read per source per check (hard cap 30) |
| `DISCOVERY_MAX_SOURCES` | setting | optional | `10` | — | sources per task |
| `DISCOVERY_MIN_CHECK_INTERVAL_SECONDS` | setting | optional | `600` | — | a manual re-check sooner than this reuses the last results |
| `RATE_LIMIT_SEARCH_PER_MINUTE` | setting | optional | `30` | — |  |
| `RATE_LIMIT_INGEST_PER_MINUTE` | setting | optional | `20` | — |  |
| `RATE_LIMIT_PUBLIC_PER_MINUTE` | setting | optional | `120` | — |  |
| `RATE_LIMIT_CHAT_USER_PER_MINUTE` | setting | optional | `12` | — | signed-in assistant turns, per user id |
| `RATE_LIMIT_CHAT_ANONYMOUS_PER_MINUTE` | setting | optional | `6` | — | anonymous assistant turns per client IP |
| `RATE_LIMIT_CHAT_ANONYMOUS_GLOBAL_PER_MINUTE` | setting | optional | `60` | — | all anonymous assistant turns together (spoof-proof cap) |
| `CLIENT_IP_HEADER` | setting | optional | — | render.yaml, .env.example | Client IP resolution behind proxies. X-Forwarded-For is read from the RIGHT: the entry appended by the outermost of `trusted_proxy_hops` trusted proxies (0 = ignore X-For |
| `TRUSTED_PROXY_HOPS` | setting | optional | `1` | render.yaml, .env.example |  |
