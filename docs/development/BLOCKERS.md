# Blockers (outside development)

Updated 2026-11-27 (branch `school/rc-2026-11-27`). Everything else in the mission was built and tested locally; these need a person,
a key, a permission or a hosted environment. The owner's step-by-step list: [FINAL-SETUP-CHECKLIST.md](../owner/FINAL-SETUP-CHECKLIST.md).

| Blocker | Needed from | Affects | State of the code |
|---|---|---|---|
| second-person review; push / merge approvals | owner, reviewer | everything | ready, local commits only |
| backup before any migration | owner | every release | procedure in SUPABASE-SETUP.md §5 |
| migrations 0016, 0017, **0018, 0019** in production (all additive) | owner | GPU worker, five monitoring desks, persistent AI budgets, weekly schedules, Work24 kind | without them the app runs as before (tested) |
| hosted staging (no third Supabase project possible) | owner (MacBook L2 stack, Render probe) | hosted Auth, Storage, real 512 MB | local tiers done |
| **Gemini key on a development machine** for a measured Gemini + RAG run (`GEMINI_LAB_KEY`), with a cost cap you approve | owner | Gemini answer quality NOT TESTED; Gemini translation comparison NOT TESTED | `rag_lab.py --modes gemini` ready; estimated cost of one run in COST-EVALUATION.md |
| verified Gemini model IDs for your key | owner (`python -m app.cli check-llm --list`, free, no tokens) | production config | documented |
| `LLM_PRICES` from the official price list | owner | cost estimates and the spending ceiling | without prices costs show "unknown", never 0 |
| native reviewers ko / en / id for TranslateGemma drafts; language reviewer assignments | owner | translation quality claims, publication of drafts | review workflow ready, permissions enforced |
| native review of the RAG labels and the cross-language set | owner / reviewers | turning AI-drafted labels into reviewed ones; the one pre-registered cross-language held-out look | worksheets in docs/review |
| human supporters | owner | Sumin | ready |
| consent of the international office (content) and IT (GPU use) | owner | sources, GPU translation pilot | GPU worker off by default |
| keys: `WORK24_AUTH_KEY` (고용24), `DATA_GO_KR_SERVICE_KEY`, `SARAMIN_ACCESS_KEY` | owner | three job sources | fixture-tested only; blocked without a key |
| JobKorea: robots.txt blocks AI crawlers; no public API (university may apply for a partnership) | owner / JobKorea | not connected; link only | – |
| Linkareer, Buddies Korea: no documented API; permission for automated access not confirmed | owner | not connected; link only | – |
| Google Custom Search JSON API: closed to new customers, shuts down 2027-01-01 | Google | not integrated; zero-cost official sources used instead | – |
| topik.go.kr needs JavaScript; www.sch.ac.kr forbids robots | providers | title and date only / not used | – |
| dependency audit for Python (`pip-audit` not installed; a tool download was declined on 2026-11-24) | owner decides | Python vulnerability check (web: `npm audit --omit=dev` = 0 vulnerabilities) | – |
| retention R1–R4 | owner | not implemented by instruction | – |
