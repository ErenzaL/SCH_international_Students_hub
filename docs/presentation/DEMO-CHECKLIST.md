# Demo checklist (presentation, Monday 2026-11-30)

## The day before
- [ ] Decide which version you demo: the **live site** (the `main` deploy, or the release if you merged it, see
      FINAL-PRODUCTION-CHECKLIST) or the **local stack** on the workstation (`docs/development/DEMO.md`).
- [ ] Daily AI cap high enough for the demo (`AI_DAILY_LIMIT_GLOBAL` ≥ 30 that day) and the Google budget alert set.
- [ ] Test accounts: one student, one admin (yours). Never show a real student's data.
- [ ] Screenshots in the slides as a backup, in case the network or Render fails.

## 10 minutes before
- [ ] Open https://sch-hub-api.onrender.com/health (wakes the API; the first call can take ~45 s), then the website.
- [ ] Ask one question to warm the model.

## Live sequence (about 8 minutes)
| # | Show | Say (accurately) |
|---|---|---|
| 1 | Home → switch ko / en / id / vi / zh-CN | five chat languages |
| 2 | Chat: "외국인등록증 발급 수수료가 얼마예요?" → open the citation | answer only from approved sources; the citation opens the source |
| 3 | Same question in Indonesian | cross-language: Korean / English sources, Indonesian answer |
| 4 | Ask something no source has ("Can I rent a locker on campus?") | it says it has no approved information (it may still suggest an office) |
| 5 | Knowledge Center → open a document and its original | only approved, current versions |
| 6 | Announcements → an approved Indonesian translation | drafts are private until a reviewer approves; Release 1: ko / en / id |
| 7 | AI Office → Yuna, Leo, Robo, Sumin (phone width) | 14 desks; work starts on request; schedules exist but are off |
| 8 | Admin (your account) → Review queue, Agents, AI usage | nothing is published without a person |

## Do not claim
- Gemini accuracy (only a local proxy model was measured).
- Human-validated results (labels are AI-drafted).
- That discovered opportunities are published automatically (they are not).
- That weekly agents run on their own in production (schedules are off).
- That the school GPU serves the live site (it does not).
