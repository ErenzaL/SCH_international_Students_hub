# Future improvements — roadmap

Not implemented in this release. Priority: P1 do first · P2 next · P3 later. Limitation IDs refer to CURRENT-LIMITATIONS.md.

## Stage A — Immediate stabilisation (first two weeks after the presentation)

| # | Item | Priority | Depends on | Approach | Expected impact | Risks | Acceptance criteria |
|---|---|---|---|---|---|---|---|
| A1 | Monitor the live application | P1 | the deploy | daily: Render metrics, `/health`, error logs; weekly: the SQL query in PRODUCTION-READINESS §4 | problems seen before students report them | none | one week of checks written down, no unexplained restarts |
| A2 | Fix real user bugs | P1 | A1 | issues from students and staff, each with a test first | trust | regressions | every fix has a failing-then-passing test; regression script exit 0 |
| A3 | Validate Gemini spending | P1 | budget alert (I4) | compare Google billing with the AI-usage card (0018) for 7 days; adjust `AI_DAILY_LIMIT_GLOBAL` (15 for US$5 / month) | no surprise bills | caps too low block students | billing within budget; refusals because of the cap < 5 % of days |
| A4 | Review RAG failure logs | P1 | 0018, A1 | answers with `evidence_gate = insufficient`, fallbacks, `injection_screened > 0` | finds missing documents and broken sources | privacy: aggregates only | a list of missing topics handed to the content team |
| A5 | Database checks | P2 | — | size vs 500 MB, slow queries in Supabase reports, weekly `pg_dump` | no data loss | — | 4 weekly dumps kept; size < 60 % |
| A6 | Operational alerts | P1 | — | Google budget alerts, a free uptime check on `/health` | early warning | alert fatigue | alerts reach the owner by e-mail |

## Stage B — RAG and agent improvements (next semester)

| # | Item | Priority | Depends on | Approach | Expected impact | Risks | Acceptance criteria |
|---|---|---|---|---|---|---|---|
| B1 | Human-labelled evaluation set | P1 | reviewers | HUMAN-REVIEW-CHECKLIST on TEST v0.3 → v0.3.1; regrade DEV / VAL the same way (exhaustive) | defensible numbers | reviewer time | κ ≥ 0.6; changelog of every correction |
| B2 | Gemini answer-quality evaluation | P1 | key, owner approval, B1 helpful | the prepared capped `answer_eval.py --provider gemini` run + human rating sheet | first real accuracy figures | cost ~US$2.5 per 210 questions | figure recall, abstention, citation support reported with intervals |
| B3 | Chunking v2 staging re-index | P1 | staging copy | `CHUNKER_VERSION=v2`, re-index, regression script, compare chunk counts and citations, then production | 13 % more approved text searchable | single-query ranking without rewrite −0.05 MRR (measured) | all approved documents searchable; regression within tolerance on the rewrite path |
| B4 | Better visa / admission passages | P2 | B1 | passage selection inside long documents (rule and footnote sentences), measured on TEST | fewer partial answers | over-fitting to TEST | gold passage reaches the model ≥ 0.9 for visa needs on a new held-out set |
| B5 | Better Korean / Vietnamese handling | P2 | B2 | monitor rewrite failures; deterministic key-term variants for the no-LLM path | steadier cross-language quality | — | cross-language gold-passage rate ≥ 0.8 without the LLM rewrite |
| B6 | Contradictory-source handling | P2 | — | surface differing figures for the same unit with source dates | honest answers | noisy notes | conflicting cases name both values and dates in ≥ 4 / 5 languages |
| B7 | Controlled weekly agent activation | P2 | 0019, owner decision | enable one schedule (Robo, official notices) for a week; then the next | real autonomy | source load, false candidates | a week without errors; every candidate still reviewed |
| B8 | More approved external sources | P3 | permissions / keys | Work24, data.go.kr, Saramin keys; written permission for others | more opportunities | terms of use | each source validated live, allowlisted, reviewed |
| B9 | Translation quality assessment | P2 | native reviewers | rate a sample of ko→en / ko→id drafts | known draft quality | — | rated sample of ≥ 40 drafts per language |
| B10 | Entity check for figures | P2 | B1 | check the question's subject against the cited passage before a figure is kept | fewer right-number-wrong-thing answers | false removals | no wrong-entity amount on the negatives set; < 2 % extra removals |

## Stage C — Long-term development

| # | Item | Priority | Depends on | Approach | Expected impact | Risks | Acceptance criteria |
|---|---|---|---|---|---|---|---|
| C1 | More announcement languages (vi, zh-CN) | P3 | reviewers for those languages | extend Release 1 scope after B9 | equal treatment | review load | reviewers named; scope test updated |
| C2 | Scalable translation worker | P3 | budget decision | hosted small model or capped Gemini drafting | drafts without the school GPU | cost | drafts available without the workstation |
| C3 | Expanded multilingual knowledge | P3 | content team | approved official pages in more languages | better same-language retrieval | maintenance | each document reviewed and versioned |
| C4 | Advanced agent workflows | P3 | B7 | multi-step tasks with human checkpoints | less manual work | complexity | every step logged and reversible |
| C5 | More career integrations | P3 | B8 | official APIs only | — | — | — |
| C6 | Real-time monitoring of official sources | P3 | B7 | shorter intervals for critical sources | faster updates | source load | robots.txt and rate limits respected |
| C7 | Student feedback | P2 | — | thumbs up / down with an optional reason, stored without content | measures usefulness | gaming | feedback visible to admins in aggregate |
| C8 | Continuous RAG evaluation | P2 | B1 | regression script in CI on every change to retrieval / chunking | no silent regressions | CI time | CI fails on a regression |
| C9 | Infrastructure | P3 | budget | paid instance (no cold starts, more memory), automatic backups | reliability | cost | owner decision recorded |
