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
