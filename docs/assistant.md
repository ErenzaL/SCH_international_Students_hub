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
* Visitors: no history is stored on the server; supporter help requires signing in. Rate limit: the `search` bucket.

## Configuration

| Variable | Default | |
|---|---|---|
| `LLM_PROVIDER` / `LLM_API_KEY` / `LLM_MODEL` / `LLM_EFFORT` | `none` / – / `claude-opus-5-5` / `medium` | without a provider the assistant shows approved passages (no rewriting, no streaming tokens) |
| `ASSISTANT_ANONYMOUS_CHAT` | `true` | allow visitors who are not signed in |
| `ASSISTANT_STRONG_SIMILARITY` | `0.84` | evidence level for passage-only replies |
| `ASSISTANT_HISTORY_TURNS` | `6` | earlier messages used for rewriting / generation |

No database migration: conversations, messages and support tickets use the existing tables.
