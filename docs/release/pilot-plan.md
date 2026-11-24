# SCH AI Support Office: pilot release plan (2026-11-24)

**Pilot release candidate:** branch `release/ai-office-pilot`, based on production main `671824c`. Nothing has
been pushed, deployed, migrated, purchased, published or scheduled. Every production action below waits for
explicit approval.

## 1. Integrated pilot release candidate

`release/ai-office-pilot` = release candidate `release/ai-office-rc` (`cb5a6ba`) + the three workspace commits +
the pilot hardening commit:

| Commit | Content |
|---|---|
| `44224d8` | Original document viewer, citation navigation, Korean–English machine translation |
| `9800ae3` … `d9de520` | AI Office Phases 1–3 (office, agents, durable tasks, official-source discovery) |
| `cb5a6ba` | Release-candidate hardening (verified SCH sources, extraction, monitoring alerts) |
| `bbba133`, `444eed3`, `0afba42` | Role-specific workspaces and their production hardening |
| `6bf4bcb` | Pilot hardening: chatbot quota reserve, agent-task worker thread, one official-source check at a time |

The branch adds no migrations beyond 0013–0015 (identical to the validated release candidate) and contains no
research files.

**Verification on this branch.** Local stack: production web build, release-candidate API in worker mode, fresh
scratch PostgreSQL + PostgREST databases.

| Check | Result |
|---|---|
| Backend tests | 604 passed |
| Ruff | clean |
| Real-database tests | 27/27 on a fresh database and 27/27 on a reused one |
| Live SCH source tests | 3/3 |
| Web tests | 230 passed; lint, typecheck and production build clean |
| Translation + document-viewer suite (fresh database) | 12/12 — nothing translates automatically, drafts wait for language-team review, originals unchanged, a chat citation opens the PDF at the cited page |
| Phase 4 end-to-end browser suite (fresh database) | 21/21 — office, RAG chatbot with citations, delegation, live official-source discovery, admin review, publication only after approval, PDF/DOCX viewers |
| Workspace browser suite, desktop + phone | 29/29, no page errors |
| Support requests (Sumin) | covered by the workspace suite and end-to-end scenario 9–10: nothing is sent before confirmation |

## 2. Remaining deployment risks

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| 1 | **Production has no database backup.** `supabase backups list` returns none, PITR is off, consistent with the Supabase Free plan ("Automatic backups: Not included"). | **High** | Take a manual `pg_dump` before migrating (section 7, step 1), or move to Supabase Pro (daily backups kept 7 days). |
| 2 | **The API may not fit in 512 MB during uploads** (section 3). | High for uploads | Upgrade the API instance to 2 GB before staff upload large PDFs; until then, upload large files outside peak hours. |
| 3 | **Render Free hours.** 750 instance hours per workspace per month. An API and a web service kept awake all month need about 1,488 h; Render then suspends all free services until the next month. | High during a busy pilot | Paid instances for the pilot period, or accept that idle services sleep (about 1 min cold start). |
| 4 | **Primary Gemini model fails with the production key** (2026-11-23 smoke test: every answer came from the fallback). | Medium | Pin the verified working model (section 6) and run the admin AI model check after deploy. |
| 5 | **Gemini free tier uses submitted content to improve Google's products** (official pricing page). | Medium (privacy) | Use a billing-enabled project for the pilot (about $3–16 a month at pilot volumes; section 3). |
| 6 | **Content gaps:** no TOPIK content; leave of absence, graduation and current career notices missing. | Medium (usefulness) | Admin review list (section 5). |
| 7 | Admin review console approval was tested through its API locally; the console needs Supabase Auth. | Low | Step 7 of the deployment test. |
| 8 | Render's plan, RAM and environment variables could not be read here (no Render API access). | — | Confirm them in the dashboard (section 3). |

## 3. Actual hosting requirements

**What could be observed** (read-only):
- The production API answers `/health` in 0.5–0.9 s, with `embedding_model = intfloat/multilingual-e5-small#qint8`
  (int8 ONNX).
- Answer generation is enabled.
- The database is 23 MB (26 documents, 767 chunks) on PostgreSQL 17.12, region ap-northeast-1. There are no
  backups.
- The repository blueprint (`render.yaml`) declares `plan: free` for both services, one `uvicorn` process,
  `JOB_EXECUTION=worker`. The services were created by hand, so **confirm in the Render dashboard:** instance
  type, RAM, and the environment variables listed in section 7.

**Measured memory of the API process tree** (local, release-candidate code, real 9 MB Korean guidebook PDF;
macOS RSS, so treat it as an estimate of Linux usage):

| Moment | Peak |
|---|---|
| Startup (model not loaded yet) | 106–120 MB |
| First chat / search (loads the e5 embedding model) | **460–477 MB** |
| Approving the guidebook (embedding + indexing 174 chunks in 10.4 s) with an official-source check running at the same time | **474 MB** |
| PDF extraction child process (runs during uploads) | **+~140 MB** on top of the API |
| Settled after the burst | 276–377 MB |

On a 512 MB instance the model alone leaves about 35–50 MB of headroom. A PDF upload while the model is loaded
(about 600 MB) is likely to be killed for exceeding memory.

**Worker concurrency and queue behaviour:**
- **Process:** one `uvicorn` process; request handlers run in its thread pool.
- **Ingestion worker thread:** ingestion, indexing and translation jobs, one at a time, using the persistent queue
  (`claim_ingestion_job`, `FOR UPDATE SKIP LOCKED`).
- **Agent-task worker thread** (new, `AGENT_TASK_WORKER=true`): agent tasks, one at a time.
- **Recovery:** jobs and tasks survive restarts; stale ones are re-queued.

**Gemini quota configuration:**
- **Chat budgets (in-process, reset at midnight KST):** `AI_DAILY_LIMIT_GLOBAL` 1,500 answers/day,
  `AI_DAILY_LIMIT_PER_USER` 150, `AI_DAILY_LIMIT_PER_CLIENT` 40.
- **Background reserve (new):** `LLM_BACKGROUND_DAILY_ATTEMPTS` 150; `TRANSLATION_DAILY_JOB_LIMIT` 60.
- **Provider limit:** the provider's requests-per-day limit is only shown in AI Studio (aistudio.google.com/rate-limit).
- **Rule:** set `2 × AI_DAILY_LIMIT_GLOBAL + LLM_BACKGROUND_DAILY_ATTEMPTS` at or below about 90% of that limit for
  the chat model.

**Can the current configuration support a small pilot?**
- **Chat, browsing and workspaces for 20–40 students:** yes on 512 MB once the model is loaded, with cold starts
  when idle.
- **Uploads of large PDFs and approvals during the pilot:** not safely.
- **Recommended for the pilot:**

| Service | Plan | Price | Reason |
|---|---|---|---|
| Render API | 1 CPU / 2 GB (`1c-2g`, legacy "Standard") | $25/month * | Uploads and indexing fit with headroom |
| Render web | 0.5 CPU / 512 MB (`0.5c-512mb`, "Starter") | $7/month * | Next.js measured at about 98 MB; avoids free-hour suspension |
| Supabase | Pro | $25/month (official) | Daily backups kept 7 days, no inactivity pausing; includes $10 compute credit (Micro, 1 GB) |
| Gemini | billing-enabled project | usage-based | Paid content is not used to improve Google's products |

Gemini prices (official pricing page):
- `gemini-3.5-flash-lite`: $0.30 input / $2.50 output per 1M tokens (thinking billed as output).
- `gemini-3.6-flash`: $0.75 / $3.75 until 2026-12-31, then $1.50 / $7.50.

\* Render's plan specifications come from its official compute-plans page. Its price table did not render for
automated reading; the $7 / $25 figures come from Render's pricing page as cached by search. **Confirm on
render.com/pricing before purchasing.**

Pilot model cost (measured 6.1k input + 0.5k output tokens per chat question, Flash-Lite):

| Students | Questions | Model cost |
|---|---|---|
| 30 | 300 | about $0.93 |
| 100 | 1,000 | about $3.10 |

Even the heavy case (25 questions per student) stays under $10 a month. Total pilot cost with the recommended
hosting: about **$58–60/month**.

## 4. Worker bottleneck: decision and result

**Problem:** one worker thread ran everything. A live official-source check occupies it for about 90 s, so a
document upload or approval waited behind it. The reverse also happened: student tasks waited behind long PDFs.

**Implemented (smallest safe change), commit `6bf4bcb`:**
1. **Priority separation by a second thread.** Agent tasks run on their own worker thread in the same process
   (`AGENT_TASK_WORKER`, default on; off restores the previous single worker). Ingestion, indexing and
   translation never wait behind a discovery check. At most one job and one agent task run at the same time, and
   there's no extra memory for models (the embedding model is shared). Discovery mostly waits on the network
   (1.5 s politeness delay), so the second thread costs little CPU.
   - Measured with real threads: a document ingestion queued during a long agent task waited **0 s with the lane
     versus the full task duration without it** (test `test_document_ingestion_does_not_wait_behind_a_long_agent_task`).
2. **No duplicate scans.** One official-source check per agent at a time (a double click or a second admin gets
   `409 check_running`). The existing 10-minute per-source throttle still applies.
3. **Schedule only with capacity.** A due scheduled check (still disabled) is postponed by 15 minutes while
   documents are being ingested or wait for the worker.

**Not done, and why:**
- **Splitting discovery into resumable per-source jobs:** unnecessary once indexing has its own thread; it would
  change progress tracking for no pilot benefit.
- **A separate worker service:** another paid instance and a second copy of the embedding model. Not justified at
  pilot volume. Reconsider at about 2,000 students or if checks run frequently.
- **Automatic checks:** stay disabled (`AGENT_SCHEDULES_ENABLED` off, every schedule off).

## 5. Missing-content review list (for admin review; nothing was published)

**How this list was made:**
- Production's Knowledge Center and announcements were read with read-only queries.
- Only **list pages** of the allowlisted official boards were read (titles, dates, URLs), with the
  robots-respecting fetcher.
- No document was created, imported or published.

**What production has today:**
- Approved documents: academic-life 5 (including 수강신청 안내, 수강신청 주의사항), employment-internships 1,
  part-time-employment 2, topik-korean **0**, scholarships **0**.
- 4 published announcements: dormitory ×2, health day, illegal-work warning.

**Proposed additions.** Add each through **Sources → add a website source** (or, after deployment, Robo's / Leo's
discovery and **Send to review**). Use the proposed category, then approve in the normal review.

| Desk | Published | Title (original) | Source board | Proposed category | Why / status | URL |
|---|---|---|---|---|---|---|
| Joon | 2026-07-06 | [학사팀] 2026학년도 2학기 정기 휴학·복학 신청기간 안내 | 순천향대학교 학사공지 | academic-life | Leave / return procedure (2026-2 period passed; the procedure text stays useful; watch for the 2027-1 notice) | https://home.sch.ac.kr/sch/06/010200.jsp?mode=view&article_no=20260706171420330058&board_wrapper=%2Fsch%2F06%2F010200.jsp&board_no=20090724142539399571 |
| Joon | 2026-09-15 | [학사팀] 2027년 2월 <졸업연장> 및 <능력별 조기졸업> 신청안내 | 순천향대학교 학사공지 | academic-life | Graduation: extension and early graduation (applications for Feb 2027) | https://home.sch.ac.kr/sch/06/010200.jsp?mode=view&article_no=20260915170155465036&board_wrapper=%2Fsch%2F06%2F010200.jsp&board_no=20090724142539399571 |
| Joon | 2026-07-15 | 2026년 8월 졸업대상자 학사학위 취득유예(졸업유예) 신청 안내 | 순천향대학교 학사공지 | academic-life | Graduation deferral (Aug 2026 cycle passed; procedure reference) | https://home.sch.ac.kr/sch/06/010200.jsp?mode=view&article_no=20260715112051532039&board_wrapper=%2Fsch%2F06%2F010200.jsp&board_no=20090724142539399571 |
| Joon | 2026-11-05 | [학사팀] 2027학년도 1학기 전과 신청 안내 (11/09~11/13) | 순천향대학교 학사공지 | academic-life | Change of major (period passed; procedure reference) | https://home.sch.ac.kr/sch/06/010200.jsp?mode=view&article_no=20261105150749338081&board_wrapper=%2Fsch%2F06%2F010200.jsp&board_no=20090724142539399571 |
| Joon | 2026-11-13 | [본교] 2026학년도 동계 계절학기 수강신청 안내 [수강기간 12월 23일(수) ~ 27년 1월 14일(목)] | 순천향대학교 학사공지 | academic-life | **Current:** winter session course registration (12/23 – 1/14) | https://home.sch.ac.kr/sch/06/010200.jsp?mode=view&article_no=20261113092633418088&board_wrapper=%2Fsch%2F06%2F010200.jsp&board_no=20090724142539399571 |
| Joon | 2026-07-24 | [수강신청] 2026학년도 2학기 수강신청 및 수업시간표 조회 안내 | 순천향대학교 학사공지 | academic-life | Course registration and timetable (compare with 수강신청 안내 already in the Hub) | https://home.sch.ac.kr/sch/06/010200.jsp?mode=view&article_no=20260724105901681037&board_wrapper=%2Fsch%2F06%2F010200.jsp&board_no=20090724142539399571 |
| Joon | 2026-11-04 | [OCU수강] 2027학년도 1학기 OCU 교과목 수강 안내 | 순천향대학교 학사공지 | academic-life | OCU online courses for 2027-1 | https://home.sch.ac.kr/sch/06/010200.jsp?mode=view&article_no=20261104101351798091&board_wrapper=%2Fsch%2F06%2F010200.jsp&board_no=20090724142539399571 |
| Joon | 2026-11-16 | [학생기업학부] SC전공(복수전공) 설명회 개최 안내 | 순천향대학교 공지사항 | academic-life | Double-major session (optional, lower priority) | https://home.sch.ac.kr/sch/06/010100.jsp?mode=view&article_no=20261116134321559011&board_wrapper=%2Fsch%2F06%2F010100.jsp&board_no=20090723152156588979 |
| Seo | 2026-09-01 | 도서관 홈페이지 TOPIK 무료 동영상강좌 이용 안내 | SCH 국제교육교류처 유학생 공지사항 | topik-korean | Free TOPIK video lectures through the library | https://sgee.sch.ac.kr/notice/notice01.php?admin_mode=read&no=6007&table_name=noti_fore |
| Seo | (page, undated) | 언어 능력 기준 및 TOPIK | Study in Korea (official, allowlisted; fetch verified) | topik-korean | Official explanation of language requirements and TOPIK | https://www.studyinkorea.go.kr/ko/plan/examAndKoreanStudy.do |
| Seo | 2013-12-23 | TOPIK GUIDE (**already in production**, filed under academic-life) | existing Hub document | topik-korean | Re-categorise and check whether it is outdated (2013) | (existing document) |
| Daniel | 2026-06-04 | [인턴십 공지] 2026년 천안시 외국인 유학생 인턴 모집 안내 | SCH 국제교육교류처 취업·아르바이트 공지 | employment-internships | International-student internship programme (check for a 2027 round) | https://sgee.sch.ac.kr/notice/notice01.php?admin_mode=read&no=6582&table_name=over_sea |
| Daniel | 2026-11-24 | [채용] (주)정수이앤씨 인도네시아어 통역 인력 채용 | SCH 국제교육교류처 취업·아르바이트 공지 | employment-internships | **Current** posting for Indonesian interpreters | https://sgee.sch.ac.kr/notice/notice01.php?admin_mode=read&no=6711&table_name=over_sea |
| Daniel | 2026-08-06 | [모집] 2026년 8월 졸업 외국인 유학생 취업비자(E-7) 변경 수수료 지원 안내 | SCH 국제교육교류처 취업·아르바이트 공지 | employment-internships | E-7 work-visa change fee support for graduates | https://sgee.sch.ac.kr/notice/notice01.php?admin_mode=read&no=6618&table_name=over_sea |
| Daniel | 2026-11-23 | [G-LAMP] 2026학년도 동계 Lab-Connect 인턴십 참여 학생 모집 안내(~12.8) | 순천향대학교 공지사항 | employment-internships | **Current:** winter internship (until 12/8; all students) | https://home.sch.ac.kr/sch/06/010100.jsp?mode=view&article_no=20261123113713894004&board_wrapper=%2Fsch%2F06%2F010100.jsp&board_no=20090723152156588979 |
| Daniel | 2026-11-20 | [순천향대학교] 해외취업연수과정 연수생 모집(~12/4) | 순천향대학교 공지사항 | employment-internships | **Current:** overseas employment training (until 12/4) | https://home.sch.ac.kr/sch/06/010100.jsp?mode=view&article_no=20261120142352829080&board_wrapper=%2Fsch%2F06%2F010100.jsp&board_no=20090723152156588979 |
| Daniel | 2026-10-29 | [홍보] 2026년 충청남도 일자리 박람회 개최 안내 | SCH 국제교육교류처 유학생 공지사항 | employment-internships | Chungnam job fair (2026-10) | https://sgee.sch.ac.kr/notice/notice01.php?admin_mode=read&no=6695&table_name=noti_fore |
| Daniel | 2026-08-06 | [채용] 2026년 충남형 일학습병행제 참여기업 채용 안내 (외국인 유학생·졸업생 대상)- 제조업 | SCH 국제교육교류처 취업·아르바이트 공지 | employment-internships | Work-study hiring for international students / graduates | https://sgee.sch.ac.kr/notice/notice01.php?admin_mode=read&no=6616&table_name=over_sea |
| Daniel | (2022-01-01) | 외국인유학생 취업제도 | Study in Korea (official, allowlisted; fetch verified) | part-time-employment | Official rules for part-time work while studying and work after graduation | https://www.studyinkorea.go.kr/ko/work/aboutForeignerEmploymentSystem.do |
| Daniel | 2026-11-10 | [롯데그룹] 2027 롯데그룹 외국인 유학생 채용연계형 Winter Internship (~11/17) | SCH 국제교육교류처 취업·아르바이트 공지 | employment-internships | Closed (11/17): example of the employer-linked internships on this board; skip unless a new round opens | https://sgee.sch.ac.kr/notice/notice01.php?admin_mode=read&no=6701&table_name=over_sea |

**Not available through approved sources:**
- **TOPIK test dates.** The official TOPIK site (topik.go.kr, allowlisted) renders its content with JavaScript, so
  it can't be ingested automatically. An admin should enter the 2027 TOPIK schedule as a manual announcement with
  the official page as evidence. No URL is guessed here.
- **Excluded:** the 순천향대학교 취업정보 board mostly lists general public-sector hiring, not aimed at
  international students.

## 6. Gemini status (verified)

**Model IDs**, checked on Google's official model list (aistudio.google.com/docs/models; ai.google.dev redirects
there):

| Model ID | Status | Notes |
|---|---|---|
| `gemini-3.5-flash-lite` | Stable | "fastest, most cost-effective 3.5 model". **Verified working with the production key** (2026-11-23 smoke test: every answer, 5 languages) |
| `gemini-3.6-flash` | Stable | "previous-generation Flash". **Failed for the production key** in that smoke test. The cause is unknown (permission, quota or project tier) |
| `gemini-3.8-flash` | Stable | Newest Flash. Not tested with this project |
| `gemini-3.5-flash` | Not on the current model list | Configuration comments call it deprecated; not used |

**Recommendation for the pilot:**
- Set `GEMINI_PRIMARY_MODEL=gemini-3.5-flash-lite` and `GEMINI_FALLBACK_MODEL=` (empty).
- This is the only model verified both as a valid stable ID and as working with this key. It's also the cheapest,
  and it avoids spending a failed primary attempt (latency and quota) on every question.
- After deployment, run **Admin → Settings → AI model check** (4 tiny requests). If `gemini-3.6-flash` or
  `gemini-3.8-flash` pass, compare them with Flash-Lite in the quality pilot (research plan, 40 answers) before
  switching.

**Reserve for the chatbot:**
- **Background attempt cap.** Translation jobs, AI summaries and discovery summaries now share a per-day cap of
  model attempts (`LLM_BACKGROUND_DAILY_ATTEMPTS`, default 150). The cap is checked before every request,
  including retries and fallbacks.
- **Own provider.** Background work has its own provider and circuit breaker, so its errors never pause the
  chatbot's model.
- **Optional quota isolation.** A separate `TRANSLATION_MODEL` puts translation on its own quota bucket and never
  falls back onto the chatbot's models.
- **No AI for workspaces.** Workspaces make no model calls (enforced by a test).

**Translation controls** (verified in the 12/12 suite):
- `PUBLIC_MACHINE_TRANSLATIONS=false`, `AUTO_TRANSLATE_DOCUMENTS=false` and `AUTO_TRANSLATE_ANNOUNCEMENTS=false`
  remain the defaults. Confirm these are not set to true in the Render dashboard.
- Machine translations become public only after a real-model quality pilot passes.

## 7. Migration and deployment checklist

Every step below needs your approval. **Stop if any check fails** and use section 8.

1. **Backup (required; none exists today).** Run from a machine you control; the password never goes into the
   repo, logs or chat:
   `pg_dump "postgresql://postgres.<ref>:<password>@<pooler-host>:5432/postgres" -Fc --no-owner -f sch_prod_$(date +%Y%m%d).dump`.
   - Use the connection string from Supabase → Connect (session pooler, port 5432). pg_dump 18 can dump the
     server's PostgreSQL 17.12.
   - Verify with `pg_restore --list sch_prod_*.dump | head`, and keep the file off-site.
   - Alternative: upgrade to Supabase Pro first (daily backups) and confirm one backup is listed by
     `supabase backups list`.
2. **Migrations pending and safe.** Checked today, read-only:
   - production is at `20261122000012`; 0013, 0014 and 0015 are pending;
   - the production schema catalog is identical to the one validated in Phase 4 (upgrade, re-run and rollback on
     a production-shaped copy; existing data unchanged);
   - the migration files are unchanged since that validation.

   Then run `supabase db push --remote --dry-run` (expect exactly 0013–0015), then
   `supabase db push --remote --yes`.
3. **Prepare the production merge.** `git switch main && git merge --ff-only release/ai-office-pilot`. Confirm main
   now points at the tip of `release/ai-office-pilot` (`git rev-parse main release/ai-office-pilot` prints the same
   hash twice).
4. **Deploy.** `git push origin main`. The GitHub workflow calls both Render deploy hooks. Before pushing, set in
   the Render dashboard (API service):
   - `GEMINI_PRIMARY_MODEL=gemini-3.5-flash-lite` and `GEMINI_FALLBACK_MODEL=` (section 6);
   - **confirm:** `PUBLIC_MACHINE_TRANSLATIONS`, `AUTO_TRANSLATE_*` and `AGENT_SCHEDULES_ENABLED` unset or false;
   - **optional:** `LLM_BACKGROUND_DAILY_ATTEMPTS`, sized per section 3.

   No new environment variable is required: the new settings have safe defaults.
5. **Memory and health.**
   - `/health` returns `status=ok` and the qint8 embedding model.
   - Render Metrics → memory after a search, and after one PDF upload. If memory stays above about 85% of the plan,
     apply the API upgrade before continuing.
   - Logs show both `job worker … started` and `agent task worker … started`.
6. **AI Office with authorized accounts** (one student, one Global Supporter, one admin):
   - every character opens its workspace;
   - the student sees no admin tabs;
   - the student's Tasks tab only shows their own tasks.
7. **Admin approval through the actual UI:** Admin → Review → open a pending document → **Approve and index**.
   The document then becomes public in the Knowledge Center.
8. **Source discovery, manually.**
   - Configure the approved sources from `docs/release/sch-sources-proposal.json` (admin API, after approval).
   - Run one **Check official websites** in Robo's Sources tab.
   - A second click shows "already running". Candidates appear in Review, not to students.
9. **Multilingual chatbot.** Ask the same question to Hana (English) and to Minji / Sari / Minh / Mei.
   - Each answers in its language with citations.
   - Admin → Settings → LLM usage shows the model's answers and the background budget.
10. **Original documents and citations.** A citation opens the PDF viewer at the cited page, and a DOCX shows its
    preview. The original bytes download unchanged.
11. **Translation stays controlled.**
    - No machine translation is visible to students.
    - A requested AI draft waits for a language-team reviewer.
    - The LLM usage view shows background attempts counted against the cap.
12. **Schedules stay disabled.** Robo's Sources tab shows every schedule "Automatic checks off". The server switch
    stays off.

## 8. Rollback

| Situation | Action |
|---|---|
| Frontend or API problem after deploy | Re-deploy the previous release: `git revert` the merge range on main, or force-push main back to `671824c` **with approval**, and push. Or use Render → service → Deploys → "Rollback" to the previous deploy (no database change needed: 0013–0015 are additive and the old code ignores the new tables and columns; validated in Phase 4). |
| Agent-task worker misbehaves | Set `AGENT_TASK_WORKER=false` on the API service (single worker, previous behaviour) and restart. |
| Background AI uses too much quota | Set `LLM_BACKGROUND_DAILY_ATTEMPTS=0` (no background AI) and restart. The chatbot is unaffected. |
| Migration must be undone | Run the rollback scripts in reverse order (`supabase/rollback/…0015_down.sql`, `0014`, `0013`) inside a transaction, **after** rolling back the code. Validated in Phase 4: they restore the identical 0012 schema. They delete the agent/discovery data created since. |
| Data loss or corruption | `pg_restore --clean --if-exists --no-owner -d "<connection>" sch_prod_YYYYMMDD.dump` from step 1 (or a Supabase Pro daily backup). Rehearse on a scratch database first. |

## 9. Pilot evaluation plan

**Participants and duration:**
- 15–25 international students, recruited through the International Office, across the five site languages.
- 3–5 authorized Global Supporters and 1–2 admins.
- 2 weeks.
- Informed consent: the pilot uses the live Hub; answers can be wrong; personal data must not be entered.
- Participants get codes (P01…), never names, in any pilot notes.

**Tasks** (each student, in their language, on their own device):

| # | Task | Desk | Success = |
|---|---|---|---|
| 1 | Find the steps to extend your D-2 visa | Yuna | a checklist step opened at its source |
| 2 | Find when winter course registration happens | Joon / Hana | correct dates, with source opened |
| 3 | Find a scholarship you could apply for now | Leo | an approved item with deadline and official link |
| 4 | Find an upcoming campus event | Mia | event detail opened |
| 5 | Find official rules for part-time work | Daniel / chat | answer with a citation to an approved guide |
| 6 | Ask a question in your language and open a citation | supporter | the cited page opens at the right place |
| 7 | Ask a person for help | Sumin | request confirmed and visible in "My requests" |

**Measures:**
- **Facilitator sheet, per task:** completed (yes/partly/no), time to useful result (stopwatch), whether the
  citation was opened and landed on the right page, errors seen.
- **Short questionnaire:** satisfaction 1–5 per task, plus three open questions.
- **Server-side aggregates** (`docs/release/pilot-metrics.sql`; no message text, no user ids, groups under 5
  suppressed): answers, model-generated share, fallback share, citation share, insufficient-evidence share,
  handoff offers, latency p50/p90, tokens, agent-task completion and failure codes, support requests by language.
- **Admin:** LLM usage (successes, errors, background attempts), Render Metrics (memory and CPU peaks), and number
  of 429 / 5xx responses in Render logs.

**Derived:**

| Measure | Definition |
|---|---|
| Task completion rate | completed tasks / attempted |
| Time to useful result | median and p90 seconds |
| Citation navigation success | citations opened at the right place / citations opened |
| Gemini generation success | model answers / answers needing the model |
| Cost per successful task | (Gemini spend from the billing console + pro-rated hosting for the 2 weeks) / completed tasks |

**Success criteria** (proposed; agree before starting):
- task completion ≥ 80%;
- median time to useful result ≤ 90 s;
- citation navigation ≥ 90%;
- satisfaction median ≥ 4;
- Gemini generation success ≥ 95%;
- no data-protection incident;
- API memory under 85% of the plan.

**Reporting:** aggregates only, with the measured numbers. Results are not estimated or filled in before the
pilot runs.
