# Blockers — RAG v2

| # | Blocker | Effect | Needs |
|---|---|---|---|
| B1 | No Gemini API key on the school server (and production secrets must not be copied here) | Gemini answer quality cannot be measured; answer evaluation uses local Qwen 2.5 7B as a labelled proxy | owner runs the prepared, capped command with their own key, or approves a budget |
| B2 | No human reviewers | all labels are AI-drafted; nothing can be called human-validated | native speakers + a domain reviewer (HUMAN-REVIEW-CHECKLIST.md) |
| B3 | No hosted staging service | nothing can be called staging-verified | owner approval for a staging deploy (see the RC FINAL-SETUP-CHECKLIST) |
