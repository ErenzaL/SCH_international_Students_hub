# Application readiness

**Verdict: release candidate pending human approval.** Everything that can be built and tested here is built and tested here. It is **not** production verified, and
not staging verified.

| Level | What |
|---|---|
| Fully implemented and locally verified | RAG changes, 14 agents, monitoring of seven desks, review and publication rules, GPU drafts and summaries, admin pages, five languages, phone, keyboard, `doctor` |
| Staging verified | **nothing** (no staging project) |
| Production verified | only that today's live services answer and refuse as they should (read-only) |
| Blocked outside | Gemini comparison, two job API keys, JobKorea, Buddies, reviewers, supporters, consent of IT and the international office, migrations, approvals |

| Area | Ready for staging | Ready for production | Why not yet |
|---|---|---|---|
| Release A | yes | after review, backup, staging, approvals | – |
| Release B | yes | after A, 0016, IT consent, native reviewers | Qwen makes mistakes; every draft needs a person |
| RAG | yes | after review | labels not checked by people; Korean specific notices still second |
| Agents, monitoring | yes | after 0017, sources added and reviewed | content gaps: TOPIK, scholarships, leave |
| Autonomous schedules | yes (shown in development) | two switches, your approval | must stay off |
| Qwen on the GPU | yes | as Release B | – |
| Web, Admin | yes | after review | Safari, real phones untested |
| Cost | 0 | 0 | free limits: 500 MB database, 750 h, 512 MB memory; large PDFs are the weak point |

Reports: [RAG](RAG-EVALUATION.md) · [agents](AGENT-MATRIX.md) · [GPU](GPU-EVALUATION.md) · [security](SECURITY-REVIEW.md) · [tests](TEST-RESULTS.md) ·
[matrix](IMPLEMENTATION-MATRIX.md) · [release plan](RELEASE-CANDIDATE.md) · [blockers](BLOCKERS.md) · [owner checklist](../owner/SETUP-CHECKLIST.md)

## Defects found and fixed on the way

| Defect | Where found |
|---|---|
| correct sentences deleted because `09` ≠ `9`, `3,35` ≠ `3.35` | answer benchmark |
| answers thrown away for a missing citation | answer benchmark |
| an older edition alone was presented as current | answer benchmark |
| a fee of something else given as the answer (local model) | answer benchmark |
| source text could close its own tag | code review |
| discovered board notices were imported as a generic page: site name as title, menus in the text, no attachments | browser test on live data |
| sources could not be added in the interface | browser test |
| five desks had no monitoring at all although listed as monitoring desks | audit |
| supporters had no access to their own review queue from their desk; tasks of supporters lost their language permissions | audit |

## Known limits

Not a reviewed legal or immigration source; the chat may be wrong and says so when evidence is missing. Free Render sleeps. One API process. Historical titles and
attachment rows as documented in [release-a-plan](../release/release-a-plan.md#known-risks). Retention R1–R4 not implemented.
