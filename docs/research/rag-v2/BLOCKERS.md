# Blockers — RAG v2

| # | Blocker | Effect | Needs |
|---|---|---|---|
| B1 | No Gemini API key on the school server (and production secrets must not be copied here) | Gemini answer quality cannot be measured; answer evaluation uses local Qwen 2.5 7B as a labelled proxy | owner runs the prepared, capped command with their own key, or approves a budget |
| B2 | No human reviewers | all labels are AI-drafted; nothing can be called human-validated | native speakers + a domain reviewer (HUMAN-REVIEW-CHECKLIST.md) |
| B3 | No hosted staging service | nothing can be called staging-verified | owner approval for a staging deploy (see the RC FINAL-SETUP-CHECKLIST) |
| B4 | DEV / VALIDATION labels are not exhaustive (a guidebook that answers is often unlabelled) | rankings that penalise guides look better on them than on TEST (hub scaling) | regrade DEV / VAL with the TEST procedure (term search + reading every hit) or retire them |
| B5 | The evidence-gate thresholds are phrasing-dependent | `enforce` would refuse 18 % of realistic answerable questions | refit on real (Gemini) traffic labelled by people, or replace the similarity signal |
| B6 | No owner approval for re-indexing with chunker v2 | 13 % of approved text stays unsearchable in production | staging re-index (PRODUCTION-READINESS §3) |

