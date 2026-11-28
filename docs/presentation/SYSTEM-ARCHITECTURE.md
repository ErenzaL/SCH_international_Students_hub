# System architecture

```
 Student / staff browser (ko · en · id · vi · zh-CN)
        │  HTTPS
        ▼
 Next.js web (Render free) ── Supabase Auth (sign-in, JWT)
        │  REST + streaming
        ▼
 FastAPI API (Render free, 512 MB) ─────────────────────────────┐
   ├─ Public: Knowledge Center, announcements, categories       │
   ├─ Assistant: rewrite → retrieve → select → screens → answer │── Gemini API (3.6 Flash answers,
   ├─ AI Office: 14 desks, tasks, tools (server-defined)        │    3.5 Flash-Lite fallback / rewrite;
   ├─ Review: documents, announcements, translations, sources   │    daily caps, bounded retries)
   ├─ Admin: users, roles, sources, agents, AI usage            │
   └─ Worker (in-process queue): ingestion, indexing, discovery │── Official websites (allowlist, robots.txt)
        │ service role only                                     │
        ▼                                                       │
 Supabase PostgreSQL + pgvector + Storage ◄─────────────────────┘
   documents → versions (review states) → chunks (vector(384) + full text)
   searchable_chunks view: approved ∧ current ∧ not cancelled / archived ∧ source active ∧ valid now
   RLS on every table; search function callable by the service role only

 Optional, OFF in production: GPU worker on the school RTX 4070 (TranslateGemma 12B drafts, outbound-only)
```

## RAG pipeline (one chat turn)

| Step | What happens | Safety |
|---|---|---|
| 1 rewrite | Gemini Flash-Lite writes the question as a standalone question plus English and Korean variants (≤ 4 queries) | variants that change a visa code are dropped |
| 2 retrieve | per query: dense (multilingual-e5-small int8, pgvector HNSW) + full-text + glossary bridge, weighted fusion; reciprocal-rank fusion across queries | only the `searchable_chunks` view |
| 3 select | ≤ 4 documents × 3 passages, ≤ 9,000 characters; newest edition of a notice; visa-code filter | expired passages dropped |
| 4 screens (release) | sentences giving orders to the model removed; evidence gate decision recorded (log) | prompt-injection defence |
| 5 answer | Gemini 3.6 Flash with numbered sources | the prompt treats sources as data |
| 6 checks | invalid citations and unknown links removed; sentences with figures in no source removed; figures re-attributed to the citing source (release); wrong language → retry / fallback | never an invented figure from outside the sources |
| 7 fallback | model unavailable or over budget → short message + approved sources | no invented answer |

## Data flow for content

official page / PDF / notice → ingestion (fetch with allowlist, PDF in a child process) → draft version → **human review** →
approved current version → chunks + embeddings → searchable. Translations: approved original → draft (Gemini or the optional
GPU worker) → automatic checks → **reviewer** → published in that language.

## Hosting and cost

| Part | Plan | Cost |
|---|---|---|
| web, API | Render free | 0 (sleeps when idle; cold start ≈ 45 s) |
| database, auth, storage | Supabase free (500 MB) | 0 (no automatic backups) |
| Gemini | pay per token | ≈ US$0.012 per answer at standard prices; daily caps |
| school GPU | not used in production | 0 |
