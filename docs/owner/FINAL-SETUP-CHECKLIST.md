# Final setup checklist (before the production release)

Prepared 2026-11-27 for the owner. Branch `school/rc-2026-11-27` on the school PC, **local only**. Nothing was pushed, deployed or changed in
production. **Who:** *You* = only you can do it (account, key, approval, people). *Claude* = Claude Code can do it once you say so.
Never paste a key into a chat, a commit or a document; every key goes only into the Render dashboard or a 0600 file on your own computer.

Earlier, still valid detail: [SETUP-CHECKLIST.md](SETUP-CHECKLIST.md) (sections A–F), [ENVIRONMENT.md](ENVIRONMENT.md) (every variable),
[SUPABASE-SETUP.md](SUPABASE-SETUP.md), [RENDER-SETUP.md](RENDER-SETUP.md), [GPU-SETUP.md](GPU-SETUP.md), [EXTERNAL-APIS.md](EXTERNAL-APIS.md).

## 0. Decide first (You)

| # | Decision | Recommendation | Why |
|---|---|---|---|
| 0.1 | Release order | A → B → this candidate, one per day ([RELEASE-CANDIDATE.md](../development/RELEASE-CANDIDATE.md)), each after a backup | small reviews, easy rollback |
| 0.2 | Push the branch | `git push origin school/rc-2026-11-27` **only after** a second person has looked at it; never push to `main` directly | `main` deploys the API |
| 0.3 | Paid Gemini test | approve or refuse a capped live run (≈ US$0.20, §1.4) | Gemini answer quality is **not measured** yet |
| 0.4 | Translation model for drafts | TranslateGemma 12B on the school PC (selected by the benchmark), reviewed by people; production keeps the school PC optional | [TRANSLATION-EVALUATION.md](../research/TRANSLATION-EVALUATION.md) |

## 1. Gemini (You)

| # | Action | Where / command | Verify |
|---|---|---|---|
| 1.1 | Check which models your key can use (free, sends no prompt) | on **your** computer: `cd backend && LLM_PROVIDER=gemini LLM_API_KEY=… .venv/bin/python -m app.cli check-llm --list` | `gemini-3.6-flash` and `gemini-3.5-flash-lite` (or what you choose) are listed |
| 1.2 | Set the models on Render (API service → Environment) | `GEMINI_PRIMARY_MODEL`, `GEMINI_FALLBACK_MODEL`, `GEMINI_THINKING_LEVEL=low` | Admin → Settings → "Check AI models": both OK |
| 1.3 | Set prices for cost estimates (from the official page, today) | `LLM_PRICES=gemini-3.6-flash=0.75/3.75,gemini-3.5-flash-lite=0.30/2.50` — **from 2027-01-01 3.6 Flash is 1.50/7.50: update it then** | Admin → Settings → AI usage: "Prices configured for …" |
| 1.4 | Optional measured comparison | `GEMINI_LAB_KEY=… .venv/bin/python ../scripts/rag_lab.py --modes gemini --langs en,ko,id,vi,zh-CN` on your computer: 95 answers ≈ 0.5 M input + 0.04 M output tokens ≈ **US$0.20 with 3.6 Flash** (estimate, COST-EVALUATION §2) | a `gemini` row in the results file; send it to Claude for the report |
| 1.5 | Spending safety (all free to set) | `AI_DAILY_LIMIT_GLOBAL` (default 1500 answers/day), `LLM_BACKGROUND_DAILY_ATTEMPTS` (150), `TRANSLATION_DAILY_JOB_LIMIT` (60), optional `LLM_BACKGROUND_DAILY_USD_LIMIT=0.50` | Admin → Settings → AI usage shows the limits |
| 1.6 | Set a budget alert at Google | Google Cloud console → Billing → Budgets & alerts (the project of the key) | an e-mail alert at e.g. 5,000 KRW. **The app's limits are estimates; only Google's billing is the real cap.** Your earlier KRW 8,000 payment is not a spending limit |
| 1.7 | Emergency stop, if costs look wrong | Admin → Settings → AI usage → "Stop background AI" (needs 0018), or `AI_BACKGROUND_STOP=true` on Render | background jobs wait; the chatbot keeps answering |

## 2. Supabase (You; Claude can prepare the SQL and read the output)

| # | Action | Where / command | Verify |
|---|---|---|---|
| 2.1 | Backup before anything | `pg_dump "$DB" -Fc --no-owner -f sch_$(date +%Y%m%d).dump` on your computer; `pg_restore -l file \| head` | tables listed |
| 2.2 | Read-only check of the current state | `python -m app.cli doctor` with your keys on your computer | every applied migration PASS |
| 2.3 | Apply the migrations **in order**, each after its release: `…0016_gpu_worker`, `…0017_agent_operations`, `…0018_llm_usage_controls`, `…0019_weekly_discovery` | SQL Editor → paste the whole file → Run, or `psql -1 -v ON_ERROR_STOP=1 -f supabase/migrations/<file>` | `doctor` PASS; Admin → Settings → AI usage: "Budgets are stored in the database" |
| 2.4 | If a migration must go back | `supabase/rollback/<same number>_down.sql` (0018 deletes the usage history and an active stop switch; 0019 restores the old intervals and removes Work24 sources) — tested here | `doctor` |
| 2.5 | Auth | unchanged; confirm Site URL and redirect URLs are the production web address | sign-in works |
| 2.6 | RLS | every new table (0018: `llm_daily_counters`, `llm_usage_daily`, `app_runtime_flags`) has RLS on and no policy: browser roles see nothing (tested: `behavior_test_llm_usage_controls.sql`) | `select relname, relrowsecurity from pg_class where relname like 'llm_%' or relname = 'app_runtime_flags';` → all `t` |
| 2.7 | Size | Admin → Agents → Storage; free plan 500 MB; ~35 KB per 1,000 indexed characters | below 400 MB |

## 3. Render (You)

| # | Action | Value | Verify |
|---|---|---|---|
| 3.1 | Memory | `MALLOC_ARENA_MAX=2` on the API service (first on the staging probe, STAGING.md §5) | re-measured 2026-11-27, PERFORMANCE.md |
| 3.2 | Announcement translation scope | `ANNOUNCEMENT_MACHINE_LANGUAGES=ko,en,id` (default), `AUTO_TRANSLATE_LANGUAGES=ko,en,id` (default) | Admin → Announcements → a Korean notice offers drafts only for English and Indonesian |
| 3.3 | Keep automation off until reviewers exist | `AUTO_TRANSLATE_ANNOUNCEMENTS=false`, `AUTO_TRANSLATE_DOCUMENTS=false`, `PUBLIC_MACHINE_TRANSLATIONS=false` | students see only reviewed translations (announcements: always, whatever this says) |
| 3.4 | Schedules stay off | `AGENT_SCHEDULES_ENABLED=false` (default); `DISCOVERY_WEEKLY_ANCHOR=mon 03:00` (Korea time) | Admin → Agents → Schedules: "globally off" |
| 3.5 | Keys of job APIs, only if you obtain them | `WORK24_AUTH_KEY`, `DATA_GO_KR_SERVICE_KEY`, `SARAMIN_ACCESS_KEY` | Admin → Agents → Sources: the source is "ready" |
| 3.6 | Deployment safety | pull-request previews off; `main` protected (GITHUB-SETUP.md) | a push to `main` is refused |
| 3.7 | Rollback of a deploy | Render → API → Events → previous deploy → "Rollback"; database: §2.4 | `/health` 200, `doctor` PASS |

## 4. University school PC / GPU (You for consent and accounts; Claude can run the commands with you)

| # | Action | Command / fact | Verify |
|---|---|---|---|
| 4.1 | Ask university IT for consent to use the GPU for translation drafts of public notices | letter: [gpu-gateway-assessment.md](../gpu-gateway-assessment.md) | written answer |
| 4.2 | Ollama | already installed (snap, 0.40.2), listens on `127.0.0.1:11434` only | `ss -ltn 'sport = :11434'` → `127.0.0.1` |
| 4.3 | Model | `translategemma:12b` already downloaded (8.1 GB; `translategemma:4b` 3.3 GB and `qwen2.5:7b-instruct` 4.7 GB also present). Pull command if missing: `curl -s 127.0.0.1:11434/api/pull -d '{"model":"translategemma:12b","stream":false}'` | `curl -s 127.0.0.1:11434/api/tags` lists it |
| 4.4 | Resources | GPU memory 9.7 GB while translating (RTX 4070 has 12 GB); RAM < 2 GB for the worker; disk: root is 91 % full, ~39 GB free — do not pull more models there | `nvidia-smi`, `df -h /` |
| 4.5 | Worker environment | `~/.config/sch-gpu-worker/env` (0600): `GPU_WORKER_HUB_URL=…`, `OLLAMA_MODEL=translategemma:12b`, `GPU_WORKER_PROMPT_STYLE=auto` (= the Hub's prompts; measured better), token in `~/.config/sch-gpu-worker/token` (0600). **Never** put Supabase or Gemini keys there (the worker refuses to start) | `python -m app.gpu_worker --check` |
| 4.6 | Batch run (manual, bounded) | `… -m app.gpu_worker --drain` (everything that waits, then stops) or `--once` | Admin → GPU worker: results; Admin → Translations: drafts `needs_review` |
| 4.7 | Start / stop | start: the command above; stop: Ctrl+C (the task is handed back) | – |
| 4.8 | Failure recovery | computer off → tasks wait (48 h), then the server's model or a visible failure; worker dies → lease expires, task re-queued | Admin → GPU worker |
| 4.9 | Privacy | only approved public announcement text is sent to the worker; no student data, no service-role key on this machine | `doctor` on the worker: no forbidden variables |

## 5. External sources (You)

| Source | Official provider / docs | Credential | Free? | Where the key goes | Without it |
|---|---|---|---|---|---|
| 고용24 (Work24) job postings | www.work24.go.kr → OPEN-API → 채용정보 (`callOpenApiSvcInfo210L01`) | `authKey` | registration; confirm terms and limits on that page | Render `WORK24_AUTH_KEY` | blocked, link only on Daniel's desk |
| 공공기관 채용정보 | https://www.data.go.kr/data/15125273/openapi.do → 활용신청 | service key | yes | `DATA_GO_KR_SERVICE_KEY` | blocked |
| 사람인 (Saramin) | https://oapi.saramin.co.kr (approval needed; 500 calls/day) | access key | yes, after approval | `SARAMIN_ACCESS_KEY` | blocked |
| 잡코리아 (JobKorea) | no public API; robots.txt blocks AI crawlers; the university may apply for a partnership | – | – | – | **not connected**, link only |
| 링커리어 (Linkareer) | no documented API or feed | – | – | – | **not connected**, link only |
| Buddies Korea | publishes a job sitemap, but no API and no confirmed permission | – | – | – | **not connected**, link only; ask Buddies before any automation |
| Google Search | Custom Search JSON API is closed to new customers and ends 2027-01-01 | – | – | – | not integrated; the official sources are used instead |
| SCH boards, Study in Korea, HiKorea | public pages, allowlisted, robots.txt respected | none | yes | – | prepared in the catalogue (Admin → Agents → Sources → add) |

Verification for any source: Admin → Agents → Sources → "Check now" → candidates appear in review; nothing is ever published without approval.

## 6. People and admin (You)

| # | Action | Where | Verify |
|---|---|---|---|
| 6.1 | Staff reviewers (approve sources, discoveries) | Admin → Users → role `admin` / `moderator` | they see Admin → Review |
| 6.2 | Language reviewers **ko, en, id** (announcement drafts of Release 1) and supporters vi, zh-CN (chat desks) | Admin → Language teams → assign `can_review` per language | a Korean notice's Indonesian draft appears in the Indonesian reviewer's queue only |
| 6.3 | First translation review | one TranslateGemma draft (4.6) reviewed side by side with the original by a native reviewer; record the outcome in `docs/review` | approved draft visible in that language; others still show the original |
| 6.4 | Add sources | Admin → Agents → Sources → catalogue → add (career: Work24 after 3.5) | "Check now" → candidates |
| 6.5 | First discovery review | AI Office → Robo / Leo / Daniel → Review | an approved item appears for students with source link, deadline, last check |
| 6.6 | Schedule activation (last) | Render `AGENT_SCHEDULES_ENABLED=true`, then Admin → Agents → Schedules → enable **one** (Robo); weekly, first run at its Monday slot | after a week: task "by a schedule", notification |
| 6.7 | Label review for the research numbers | `docs/review` worksheets (RAG labels, cross-language set) | then the one pre-registered held-out look (CROSSLANG-EVAL.md) |

## 7. What Claude Code can do next, after your go-ahead

Push the branch and open a draft pull request (with your written approval) · interpret `doctor`, `check-llm` and staging outputs · run the
capped Gemini comparison on a machine that holds your lab key · re-run every benchmark after the label review · prepare release notes.
