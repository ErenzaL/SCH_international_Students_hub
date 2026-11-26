# Security and privacy review (candidate)

Method: code reading, automated tests, browser tests with six accounts, SQL behaviour tests as `anon` / `authenticated`, `doctor`. No external penetration test.

| Area | Finding | Evidence |
|---|---|---|
| Sign-in | tokens verified (HS256 secret or JWKS, audience, expiry); role always from the database | `test_auth`, browser: unauthenticated → login |
| Authorization | every admin route checks the role on the server; supporters by language; GPU tokens open only four worker routes | `test_rbac_integration`, browser: 7 refusals, 403 for another language |
| RLS | on for all 33 tables; private tables have no policy; new `agent_controls`, `storage_overview()` service role only | `behavior_test_*.sql` (13), `doctor` (22 tables with the public key) |
| Agents | tool list per agent, parameters validated, writes need confirmation or staff role, delegation depth 2, no loops | `test_agents`, `test_agent_operations` |
| Student privacy | administrators see task metadata only; staff queue without subject or text; no private text goes to the GPU worker or to a benchmark | tests with `SECRET-…` markers, browser `PRIVATE-WORDS` |
| Prompt injection | sources, conversation and question are data in tags; **new:** a source cannot open or close a tag or contain the assessment marker; links only from evidence; figures must be in evidence; injected document in the benchmark obeyed 0 of 5 | `test_families_and_notes`, benchmark "injection" 100 % |
| Model as proof | model text never changes state; tools are called by code, not by the model | code |
| SSRF | allowlist, DNS check, redirects re-checked, size and time limits, robots.txt; job APIs have fixed https hosts and refuse foreign links | `test_fetcher`, `test_url_guard`, `test_job_apis` |
| Secrets | none in 38 commits (pattern scan; four matches are placeholders in tests and documents; **gitleaks was not run**); keys never in logs, errors, database or URLs shown | scan, `test_job_apis`, `test_doctor` |
| Dependencies | identical to `main`; `pip-audit` and `npm audit` found nothing | 2026-11-24 |
| Draft / approved separation | unreviewed items invisible to students in every path (page, API, search, public key, agents) | Release A tests, browser, staging script |
| Rate limits, quotas | per client, user, day; model budgets | `test_rate_limits_and_budgets` |
| CORS | only listed origins | live check PASS |
| GPU worker | outbound only, hashed expiring tokens, leases, results always `needs_review` | `test_gpu_worker`, e2e 20/20 |
| Ollama | loopback only; provider refuses other addresses | `doctor`, tests |

## Open

| Risk | Level | Note |
|---|---|---|
| Repository is public, `main` unprotected | medium | owner: ruleset |
| Gemini free tier may use content to improve products | medium (privacy) | never paste personal data into the chat; owner decides; paid tier is **not** required |
| Local shared GPU computer | medium | only public approved content leaves the Hub; IT consent open |
| Hosted Supabase sign-in, Storage, Realtime untested here | – | staging |
| No external review | – | second-person review |

## 2026-11-27 (branch `school/rc-2026-11-27`): what changed and how it was checked

| Area | Change | Evidence |
|---|---|---|
| New tables (0018) | `llm_daily_counters`, `llm_usage_daily`, `app_runtime_flags`: RLS on, no policy, grants only to `service_role`; functions `llm_counter_take`, `llm_usage_add` executable only by `service_role` | `behavior_test_llm_usage_controls.sql` (anon and student refused for read, write and execute) |
| New admin endpoint | `POST /admin/system/ai-background-stop`: admin role on the server, audited (`ai.background_stop` / `ai.background_resume`), stops only background AI | `test_admins_flip_the_stop_switch_and_it_is_audited` (supporter and student 403) |
| Usage data | only provider, model, lane, purpose, outcome, token counts, estimated cost; no prompt, answer, student id or IP is stored | `usage.py`, `test_usage_rows_reach_the_database_without_blocking` |
| Budgets fail closed | background AI is refused when the counter table exists but cannot be read; chat falls back to the in-process count | `test_background_fails_closed_when_the_counter_cannot_be_read_but_chat_does_not` |
| Work24 XML | fixed https host, GET, key never in logs/DB/URLs shown, documents with DOCTYPE/ENTITY refused before parsing (no entity expansion), links to other hosts replaced by the official home page | `test_work24_*` (4 bad-answer cases) |
| Relevance | a posting is relevant only by its own title / type / requirements, not by the employer's name | `test_work24_postings_become_private_candidates_with_honest_deadlines` |
| Opportunities | status computed when read (Korea time); a passed deadline hides the item at once; "recruiting" without a date is never "open" | `test_opportunity_expiry.py` |
| Announcement translations | unreviewed machine drafts never public, whatever `PUBLIC_MACHINE_TRANSLATIONS` says; machine drafts only in ko/en/id; vi/zh supporters get no draft button for announcements | `test_release1_translation_scope.py` (8), integration tests on PostgreSQL |
| Third-party job sites | JobKorea (robots.txt blocks AI crawlers), Linkareer, Buddies Korea: no automated access; plain links, marked "not connected" | catalogue, `careers.tsx`, browser check |
| Secrets | pattern scan of every line added on this branch: no key, token, private key or credentialed URL (one match: the public Supabase CLI default `postgres:postgres@127.0.0.1:54322` in a local staging script) | scan 2026-11-27 |
| Dependencies | web `npm audit --omit=dev`: **0 vulnerabilities** (2026-11-27); Python dependencies unchanged since 2026-11-24 (`pip-audit` clean that day); `pip-audit` not re-run today (not installed; a tool download was declined on 2026-11-24) | – |
| Credentials on the school PC | none (no `.env` files); the GPU worker refuses to start with Supabase/Gemini/cron secrets in its environment | `Config.from_env`, `test_gpu_worker` |
| Gemini privacy | paid tier is assumed for the owner's key; on a free-tier key Google may use content to improve products — the Hub sends the student's question, recent conversation turns and approved public passages, so whatever a student types reaches Google; background jobs send only approved public text | owner decision (paid tier recommended) |
