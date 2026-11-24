# Configuration inventory

Status = what could be verified from here on 2026-11-25. "?" = only visible in your dashboard: `doctor` answers it.

## Secrets

| Service | Setting | Required | Status | Obtain | Configure | Verify | Blocks |
|---|---|---|---|---|---|---|---|
| Render API | `SUPABASE_SERVICE_ROLE_KEY` | yes | in use (`/health`: database configured) | Supabase → API | Render → API → Environment | `doctor` | everything |
| Render API | `SUPABASE_JWT_SECRET` | only HS256 projects | ? | Supabase → JWT Keys | same | sign in | sign-in |
| Render API | `LLM_API_KEY` | for answers | ? (answers were enabled on 2026-11-24) | [AI Studio](https://aistudio.google.com/apikey) | same | Admin → Settings → Test AI models | chat answers |
| Render API + GitHub | `CRON_SECRET` | daily imports | ? (the workflow ran successfully) | make it | both, same value | Actions log | daily imports |
| GitHub | `RENDER_DEPLOY_HOOK_API/WEB` | deploys | ? (workflow succeeds) | Render → Settings → Deploy Hook | GitHub → Secrets → Actions | Actions log | automatic deploy |
| Render API | `DATA_GO_KR_SERVICE_KEY` | no | **missing** | [EXTERNAL-APIS.md](EXTERNAL-APIS.md) | Render | Daniel → Check now | public-institution jobs |
| Render API | `SARAMIN_ACCESS_KEY` | no | **missing** | same | Render | same | Saramin jobs |
| GPU computer | worker token | Release B | **does not exist** | Admin → GPU worker | token file, mode 600 | `--check`, Admin → GPU worker | Qwen drafts in production |
| Render API | `OCR_SPACE_API_KEY` | no | ? | ocr.space | Render | upload a screenshot | OCR of screenshots |

## Not secret

| Service | Setting | Required | Status | Configure | Verify | Blocks |
|---|---|---|---|---|---|---|
| Render API | `SUPABASE_URL`, `CORS_ORIGINS` | yes | work (checked live) | Render | `doctor --api --web` | everything |
| Render API | `LLM_PROVIDER=gemini`, model names | for answers | ? | Render | Admin → Settings | chat answers |
| Render API | `JOB_EXECUTION=worker`, `EMBEDDING_PROVIDER=e5_onnx`, `RETRIEVAL_MIN_SIMILARITY=0.80` | yes | in render.yaml; live model is e5 qint8 | Render | `doctor` | search quality |
| Render API | `AGENT_SCHEDULES_ENABLED` | no | off (default) | Render | `doctor` | automatic checks |
| Render API | `GPU_WORKER_ENABLED` | Release B | off (not in production code yet) | Render | `doctor` | Qwen drafts |
| Render web | `NEXT_PUBLIC_SUPABASE_URL/ANON_KEY`, `NEXT_PUBLIC_API_URL` | yes | work (site loads) | Render, rebuild | open the site | site |
| Render | Pull Request Previews off, Auto-Deploy | yes | ? | Render → Settings | look | accidental deploys |
| GitHub | protection of `main` | recommended | **off** | Rulesets | push is refused | accidental deploys |
| GitHub | commit address is yours | before push | **to confirm** | Settings → Emails | look | push |
| Supabase | migrations 0016, 0017 | Release B / agents | **not applied** | SQL Editor | `doctor` | GPU worker / five desks |
| Supabase | backup | before every release | **none exists** | `pg_dump` | `pg_restore -l` | release |
| Supabase | Auth URLs | yes | ? | Authentication → URL Configuration | sign in | sign-in |
| Admin | official sources | for agents | **0 of 25 added** (production has none) | Admin → Agents → Sources | status ok | Robo, Leo, Daniel, Mia, Yuna, Joon, Seo |
| Admin | reviewers for 5 languages | for translations | ? | Language teams | `doctor` | translations |
| Admin | human supporters | for Sumin | ? | Language teams | `doctor` | human support |
| Admin | approved content for TOPIK, leave, graduation, scholarships | usefulness | **missing** (2026-11-24: 0 TOPIK, 0 scholarships) | Knowledge Sources, Review | Knowledge Center | Seo, Joon, Leo |
| University | consent of IT and the international office | Release B / sources | **open** | letter | – | GPU in production |

## What is missing and what it stops

| Feature or agent | Missing manual action | Impact if missing | Development can continue | Production can activate |
|---|---|---|---|---|
| Release A (safety) | author check, second reviewer, staging, backup, push and merge approval | old behaviour stays | yes | **no** |
| Better RAG (editions, bridge, checks) | review and merge of this candidate | old retrieval | yes | no |
| Hana, Minji, Alex, Sari, Minh, Mei: chat | Gemini key (exists) | – | yes | yes |
| their review queues | reviewers per language | drafts wait forever | yes | partly |
| Yuna, Joon, Seo, Mia, Daniel: monitoring | migration 0017, sources | desks answer, but watch nothing | yes | no |
| Robo, Leo: monitoring | sources (0015 exists) | nothing is discovered | yes | after adding sources |
| automatic checks | `AGENT_SCHEDULES_ENABLED` and each schedule | checks start by hand | yes | after your approval |
| Daniel: job APIs | two keys | only SCH and Study in Korea postings | yes | without them |
| JobKorea, Buddies | application / address | not connected | yes | without them |
| Qwen drafts in production | 0016, flag, token, IT consent, reviewers | Gemini drafts on request | yes | no |
| Sumin | human supporters available | requests wait | yes | partly |
| Gemini comparison | a free key as `GEMINI_LAB_KEY` on your computer | no measured comparison | yes | – |
| Quality claims for languages | native reviewers (`docs/review/`) | no claim may be made | yes | – |
