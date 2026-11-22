# Architecture

```
Browser (Next.js, anon key only)
   │  Supabase Auth (email/password)  ──────────────► Supabase Auth
   │  Bearer <access token>
   ▼
FastAPI  ── verifies JWT (JWKS / HS256), loads role from public.profiles, enforces roles ──┐
   │ service-role key (server only)                                                        │
   ▼                                                                                       ▼
Supabase PostgreSQL (+pgvector, RLS, SECURITY DEFINER functions)      Private Storage bucket `source-files`
   ▲
   └── ingestion: guarded fetch → extract → hash → version → chunk → embed (E5, lazy) → pending_review
```

## Layers (backend)

| Layer | Path | Responsibility |
|---|---|---|
| API | `app/api/*` | HTTP, validation (Pydantic), dependencies, status codes |
| Security | `app/security` | JWT verification, role dependencies, SSRF guard |
| Services | `app/services/*` | ingestion pipeline, extractors, chunker, embeddings, retrieval, review, announcements, public views |
| Repositories | `app/repositories` | `Store` protocol → `SupabaseStore` (production) / `MemoryStore` (tests only) |
| Database | `supabase/migrations` | constraints, RLS, transactional functions, search RPC |

The embedding provider (`EmbeddingProvider`), LLM provider (`LLMProvider`) and translation provider are
interfaces; Phase 1 ships E5 (+ a lexical `hash` dev provider), a null LLM and a null translator.

## Trust boundaries and authorization (defense in depth)

1. **Frontend** hides admin UI by role, but is never trusted.
2. **Backend** verifies the Supabase JWT on every admin request and reads the role from `public.profiles`
   (token claims are ignored). Role matrix: `admin`/`super_admin` for review/sources/documents; `supporter` for
   creating/submitting announcements and translating their assigned languages; only `super_admin` changes roles
   (and the last super_admin cannot be demoted).
3. **Database**: the service-role key bypasses RLS, so each state-changing SQL function re-checks the actor
   (`assert_admin_actor`) and runs in one transaction. RLS additionally limits anon/authenticated access to
   approved, current, in-window, non-private content; profile role changes by end users are blocked by trigger.
4. **Storage**: bucket is private with no policies; only the backend reads/writes; no public URLs.

Nothing is auto-published: every new extraction is `pending_review`; announcements need an admin approval;
translations are public only when `human_approved`.

## Rate limiting and limits

In-process sliding window per client IP (search 30/min, ingestion 20/min, public reads 120/min; configurable).
It is per instance – use an edge limiter/WAF when scaling out. Request bodies are capped (12 MB), uploads
(10 MB), fetched responses (5 MB), `top_k` ≤ 20, page size ≤ 100.

## Jobs

Ingestion returns `202 {job_id}`. The job row (`ingestion_jobs`) is persisted before execution; FastAPI
`BackgroundTasks` runs it. On startup, jobs still `running` are marked `failed: interrupted` (retryable via
`POST /admin/ingestion-jobs/{id}/retry`). This is deliberately simple because free Render instances may sleep;
`python -m app.cli run-due` is the entry point for an external scheduler. A queue-backed worker is the next step
if volume grows.

## Frontend

Next.js App Router, locale resolved server-side (cookie `NEXT_LOCALE` → `Accept-Language` → `en`), switcher stores
cookie + localStorage; English is deep-merged under every other locale as fallback. UI strings are separate from
knowledge content. Data is fetched client-side from the API so builds never need the backend. `src/proxy.ts`
(Next 16 middleware) redirects unauthenticated `/admin/*` requests when Supabase is configured.
