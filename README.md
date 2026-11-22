# SCH International Student Hub

A multilingual information and support platform for international students at Soonchunhyang University (SCH), South Korea. It combines SCH notices, general Korean-government information relevant to international students, announcements from SCH Global Supporters, and verified PDF/DOCX/website content, with a retrieval layer (RAG-ready) and a human review workflow.

> Unofficial student-support project. It does not use SCH branding. Sample data is labelled `TEST DATA`; nothing in the repo is an official announcement or regulation. **No content is ever published without an administrator's approval.**

## What is in Phase 1

| Area | Status |
|---|---|
| Next.js student site (Home, Announcements, Knowledge Center, AI Assistant shell, Student Support), 5 UI languages | built |
| Protected `/admin` (Overview, Knowledge Sources, Documents + review page, Announcements, Translations, Review Queue, Users & Roles, Settings) | built |
| FastAPI backend: 44 endpoints, Supabase JWT verification, role checks, structured errors, rate limits | built |
| Ingestion: guarded website fetch (SSRF-safe, robots.txt), HTML/PDF/DOCX/manual extractors, versioning, chunking, E5 embeddings | built |
| Supabase schema: 5 migrations, RLS, transactional approve/reject/rollback functions, hybrid search RPC (pgvector + FTS, RRF) | built and verified on local PostgreSQL |
| Answer generation (LLM) | **not enabled** (abstraction only). The assistant shows retrieved, cited passages |
| Automatic translation | not enabled (human flow + schema ready) |
| OCR for scanned PDFs | not enabled (scans are flagged `needs_ocr`) |

## Layout

```
apps/web/        Next.js 16 (App Router, TypeScript, Tailwind v4, next-intl)
backend/         FastAPI (app/api, core, models, schemas, security, repositories, services/*), tests/
supabase/        migrations/ (versioned SQL), seed.sql, tests/behavior_test.sql
docs/            setup.md, architecture.md, database.md, ingestion.md, api-contract.md
scripts/         check_sources.py, demo_pipeline.py, run_sql_tests.sh, dev_rest_proxy.py, local_supabase_shim.sql
render.yaml      Render blueprint (web + api)
.env.example
```

## Quick start (local)

Requirements: Node 20+ (tested on 26), Python 3.11+, a Supabase project (free tier is enough).

```bash
# 1) Backend
cd backend
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt          # API + tests
pip install -r requirements-ml.txt           # optional: local multilingual-e5-small (torch, ~1 GB)
cp ../.env.example ../.env                   # then fill in the Supabase values
uvicorn app.main:app --reload --port 8000    # http://localhost:8000/docs

# 2) Web (second terminal)
cd apps/web
npm install
cp ../../.env.example .env.local             # keep only the NEXT_PUBLIC_* lines
npm run dev                                  # http://localhost:3000
```

Without Supabase configured, everything still starts: data pages show setup instructions or a clear
"Supabase is not configured" state, never fake data. Apply the migrations, create the first super_admin and
follow [docs/setup.md](docs/setup.md) for the full walkthrough (register a source, ingest, approve, search, deploy).

## Checks

```bash
cd backend  && pytest                         # 171 tests (+1 integration test, see docs/setup.md)
cd backend  && ruff check .
cd apps/web && npm run typecheck && npm run lint && npm test && npm run build
./scripts/run_sql_tests.sh scratch_db         # SQL behaviour/RLS tests on a scratch local Postgres + pgvector
python scripts/check_sources.py               # live access + extraction test of the six candidate sources
```

## Documentation

* [docs/setup.md](docs/setup.md) – install, Supabase, first admin, ingestion walkthrough, Render deployment
* [docs/architecture.md](docs/architecture.md) – components, trust boundaries, security model
* [docs/database.md](docs/database.md) – tables, lifecycle, RLS, functions
* [docs/ingestion.md](docs/ingestion.md) – pipeline, SSRF rules, source registry and verified access results
* [docs/api-contract.md](docs/api-contract.md) – every endpoint
