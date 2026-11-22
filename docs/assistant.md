# SCH Assistant (floating RAG chatbot)

A chat launcher sits at the bottom-right of every student-facing page (hidden on `/admin`, `/login` and the full
`/assistant` page; `…#chat` opens it). It answers from the approved knowledge base first and offers a Global
Supporter only when that is genuinely needed — and only sends anything after the student confirms.

## Request flow

```
Student message ──► POST /api/v1/conversations/{id}/messages/stream   (signed in, persisted history)
                └─► POST /api/v1/assistant/chat/stream                  (visitor: stateless, last turns sent by browser)
   AssistantEngine.respond (backend/app/services/assistant/engine.py)
   1. reply language: the language the student writes in (Hangul / Han / Vietnamese diacritics / id-en words),
      otherwise the site language
   2. greetings / thanks → friendly reply, no search, never an escalation
   3. retrieval queries: follow-ups rewritten into a standalone question using the conversation; with an LLM also
      English + Korean variants (the corpus is mostly ko/en originals — cross-language retrieval was the weak spot
      in docs/multilingual.md); without an LLM short follow-ups are merged with the previous question
   4. hybrid retrieval (multilingual E5 vectors + full text, search_knowledge_v2) for every query, reciprocal-rank
      fusion, top 6 — only approved, current, active originals (searchable_chunks excludes drafts, superseded,
      withdrawn, archived, deleted and inactive sources; translations are never indexed)
   5. generation (LLM_PROVIDER=anthropic): streamed answer in the reply language, [n] citations, short by default;
      a hidden META block reports evidence = sufficient | partial | conflicting | none, individual, wants_human,
      follow-up suggestions. Without an LLM: the approved passages with a localized framing sentence, graded from
      retrieval signals that must agree (multilingual-E5 gives unrelated text ~0.79-0.81 similarity in production):
      sufficient = exact identifier, or keyword + similarity >= 0.83, or similarity >= 0.86; partial = keyword +
      >= 0.80 or similarity >= 0.84; otherwise "closest information - may not answer your question" (no escalation)
   6. validation: answers without a valid citation are discarded (fallback to passages); [n] outside the evidence
      removed; links not present in the evidence replaced by "[link removed]"; the model cannot create requests
   7. escalation offer only for: explicit request for a person, a reported wrong answer, an individual decision,
      no reliable evidence, conflicting evidence — phrased as a question
   SSE events: status {searching|writing} → delta {text}… → done {message} | error {code, message}
Offer accepted ──► POST /conversations/{id}/handoff-draft  (summary + messages + sources, personal data redacted,
                   nothing sent) ──► student edits, selects messages, ticks consent ──► POST /support/tickets
                   (existing endpoint, consent=true) → routed to the team of the student's preferred language
                   (route_support_ticket) → confirmation message with the request number/status in the chat
```

Messages store `metadata.evidence_level`, `handoff_reasons`, `follow_ups`, `retrieval_mode`, `answer_generation`,
`model`, `latency_ms`. Each turn logs one logfmt line (`assistant turn lang=… evidence=… hits=… queries=… mode=…
generation=… offer=… reasons=… latency_ms=…`) — never message content. Responses carry `x-request-id`.

## Safety

* Passages and student text go to the model inside tags as data; the system prompt says to ignore instructions in
  them. Answers may only link to URLs that appear in the evidence; Markdown is rendered client-side into React
  nodes only (no HTML), and only http(s) links are clickable.
* LLM keys stay on the backend (`LLM_API_KEY`); the browser never talks to the model.
* Visitors: no history is stored on the server; supporter help requires signing in.

## Limits and client identity

* Every assistant turn: the per-IP `search` bucket, plus a per-account limit for signed-in students
  (`RATE_LIMIT_CHAT_USER_PER_MINUTE`) or a GLOBAL anonymous cap (`RATE_LIMIT_CHAT_ANONYMOUS_GLOBAL_PER_MINUTE`)
  that no header spoofing can get around.
* With an LLM configured, AI-generated turns also count against daily budgets (KST day): per client IP
  (`AI_DAILY_LIMIT_PER_CLIENT`) / per account (`AI_DAILY_LIMIT_PER_USER`) -> HTTP 429 `daily_limit`; and a global
  budget (`AI_DAILY_LIMIT_GLOBAL`) -> answers degrade to the localized "can't generate right now" reply with the
  matching sources (the model is not called). Counters are in-process (one instance; reset on restart/sleep). A
  persistent counter needs a database table (an approval-gated migration).
* Client IP: `CLIENT_IP_HEADER` (default `true-client-ip`, set by Cloudflare in front of Render) is trusted first;
  otherwise `X-Forwarded-For` is read from the right (`TRUSTED_PROXY_HOPS`). The left-most `X-Forwarded-For` entry
  is client-controlled and never used. **Verify on the deployment** with `GET /api/v1/admin/system/client-ip` (admin):
  call it normally and with a made-up `True-Client-IP: 1.2.3.4` header; `resolved_client_ip` must stay your real IP.
  If the made-up value appears, set `CLIENT_IP_HEADER=` (empty) and use `TRUSTED_PROXY_HOPS`.

## Gemini (LLM_PROVIDER=gemini)

* Official `google-genai` SDK, synchronous calls (FastAPI runs these endpoints in its worker thread pool and the
  SSE stream in its own thread, so the event loop is never blocked; every caller keeps one interface).
* Models (checked 2026-11-23 against ai.google.dev, now served from aistudio.google.com/docs): `gemini-3.5-flash` is
  deprecated and Google routes its requests to `gemini-3.6-flash`, so the default primary is `gemini-3.6-flash`;
  fallback `gemini-3.5-flash-lite` (stable). Validate for your key: `python -m app.cli check-llm` (Models API:
  existence + `generateContent`), `--generate` adds one tiny call per model.
* Policy per request: at most `LLM_MAX_ATTEMPTS_PER_MODEL` tries on the primary, then the same bound on the fallback.
  Retried: 429 (unless a per-day quota), 5xx, timeouts, network errors, empty/malformed output - exponential backoff
  with jitter, or the server's `RetryInfo` delay (a delay above `LLM_RETRY_MAX_DELAY_SECONDS` is not waited for; the
  request fails over). Failed over: those errors, a per-day quota and an unknown model (404). Never retried or failed
  over: 400 invalid request, 401/403 and invalid keys, safety blocks, truncated output. A fallback that shares the
  exhausted quota fails once, and that is final.
* Streaming: once text has reached the student nothing is retried; the final `done` event carries a clean localized
  message that replaces the partial text (`metadata.partial_stream_discarded`).
* When both models fail: "I'm having trouble generating an answer right now…" in the student's language plus at most
  three distinct source documents - never raw passages.
* Usage: one logfmt line per attempt (`llm_attempt provider model role purpose attempt outcome error latency_ms
  input_tokens output_tokens thinking_tokens total_tokens`) - token counts only as reported by the API, no content,
  no keys, no cost estimate. Aggregates: `GET /api/v1/admin/system/llm-usage` (admin; in-process since restart).

## Retrieval (weighted hybrid)

See `app/services/retrieval/service.py` and `query_analysis.py`. Dense and keyword candidates are fetched separately
from `search_knowledge_v2` (no schema change) and fused in the application: semantic rank counts fully, keyword rank
counts in proportion to the rarity-weighted share of query terms a passage covers (so "visa" alone is not evidence);
visa codes are normalized (D2 = D 2 = D-2) and a passage about a different code (E-7, F-2-R) than the one asked is
demoted; a small multilingual glossary links equivalent terms (ARC / residence card / 외국인등록증, dormitory / 생활관
...); overlapping chunks are dropped and each document contributes at most 3 passages. `mode=hybrid_legacy` keeps the
original SQL fusion for benchmarking; `RETRIEVAL_FUSION=sql_rrf` switches the default back.
Benchmark: `scripts/eval_retrieval_benchmark.py` (real public corpus, `scripts/benchmarks/retrieval_pilot_v0.1.json`).

## Configuration

| Variable | Default | |
|---|---|---|
| `LLM_PROVIDER` / `LLM_API_KEY` | `none` / – | `gemini` or `anthropic`; without a provider the assistant shows approved passages |
| `GEMINI_PRIMARY_MODEL` / `GEMINI_FALLBACK_MODEL` | `gemini-3.6-flash` / `gemini-3.5-flash-lite` | fallback empty = none |
| `GEMINI_THINKING_LEVEL` / `LLM_TEMPERATURE` | `low` / model default | |
| `LLM_REQUEST_TIMEOUT_SECONDS` / `LLM_TIMEOUT_SECONDS` | `30` / `120` | per attempt: interactive calls / translation jobs |
| `LLM_MAX_ATTEMPTS_PER_MODEL` / `LLM_RETRY_BASE_SECONDS` / `LLM_RETRY_MAX_DELAY_SECONDS` | `2` / `0.8` / `8` | |
| `LLM_ANSWER_MAX_TOKENS` | `2048` | visible answer cap (thinking headroom is added) |
| `LLM_MODEL` / `LLM_EFFORT` | `claude-opus-5-5` / `medium` | Anthropic only |
| `AI_DAILY_LIMIT_PER_CLIENT` / `_PER_USER` / `_GLOBAL` | `40` / `150` / `1500` | 0 = unlimited |
| `RATE_LIMIT_CHAT_USER_PER_MINUTE` / `RATE_LIMIT_CHAT_ANONYMOUS_GLOBAL_PER_MINUTE` | `12` / `60` | |
| `CLIENT_IP_HEADER` / `TRUSTED_PROXY_HOPS` | `true-client-ip` / `1` | see "Limits and client identity" |
| `RETRIEVAL_FUSION` and `RETRIEVAL_*` weights | `weighted` | see "Retrieval" |
| `ASSISTANT_ANONYMOUS_CHAT` | `true` | allow visitors who are not signed in |
| `ASSISTANT_STRONG_SIMILARITY` | `0.84` | evidence level for passage-only replies |
| `ASSISTANT_HISTORY_TURNS` | `6` | earlier messages used for rewriting / generation |

No database migration: conversations, messages and support tickets use the existing tables.
