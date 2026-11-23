# Retrieval reliability (notebook 14)

### Findings

* **Failure audit (corpus_v2, assistant path E2S, 200 questions; multi-label, automatic rules).**
  2 right doc, wrong passage: 28; 5b outdated: top source is an old edition: 28; 1 wrong document: 21; 3 missing numeric/conditional: 21; 7 cross-language: 21; 4 fragmented context: 10; 6 conflicting sources: 10; 8 incomplete labels: 9. 108 questions match no failure rule.
  100% of wrong-document failures are cross-language questions (base rate 80%).
* **Fragmentation.** An extraction defect (notebook 13): only 24 % of the guidebook's words reach chunk text in
  production; repaired variants keep 97-100 % but score lower against the frozen labels.
* **Evidence layer** (top-source check, development-calibrated): needed information types were missing in the top
  source for 61 of 200 questions (both sets); the layer added passages for 50 and
  14 remain incomplete (recorded, not guessed). On held-out: supporting passage in context
  E2S 0.58 -> 0.58
  (paired +0.0 pp [+0.0, +0.0]), evidence-term coverage +0.0 pp [+0.0, +0.0]; median added cost
  5 ms (p90 105 ms);
  document ranking +0.0 pp [+0.0, +0.0] MRR. No statistically supported improvement in the independent evidence measures.
* **Repaired guidebook (P1) vs production text, same questions:** supporting passage (E2S) +5.0 pp [+1.0, +10.0],
  evidence-term coverage +5.5 pp [+0.5, +12.5] - while frozen-label MRR falls
  (-4.6 pp [-7.8, -1.7]): the repair brings more answer-bearing text into the context than the frozen labels can credit.
* **Reranking.** E3 mMiniLM vs E2 +7.5 pp [+2.4, +12.2], E3 bge-m3 vs E2 +8.0 pp [+1.7, +14.0] MRR (frozen labels);
  with the assistant's selection: E4 vs E2S +3.8 pp [-0.6, +8.5]; supporting passage E4 vs E2S +7.0 pp [+3.0, +13.0].
  Median cost per question 62 ms (E2S) vs 415 ms (E4, mMiniLM on the M1 GPU;
  about 1.1 s on the M1 CPU).
* **Source reliability.** Unknown fields across 26 documents: authority 0, domain 21, validity 24, published 26, version_status 0;
  overlaps: 외국인학생취업관련 정보 in 한국 유학생 생활 가이드북 (96%);
  past-dated statements in held-out/pilot contexts: 0 questions.
* **Not evaluated:** citation support and unsupported-answer rate of generated answers (no LLM calls, no human-scored answers).
  The repaired-guidebook corpus (P1) is included above.

### Recommendation (none deployed)

1. **Fix PDF extraction** and re-extract the guidebook as a new version through approval (data integrity).
2. **Evidence-sufficiency layer:** keep off; run it in shadow mode (log `evidence_check` reports) - it detects incomplete evidence and records it, but the measured completeness gain is not established.
3. **Reranking (mMiniLM):** largest supported gain (+7.5 pp MRR vs E2); needs ~1 GB RAM and ~1 s/question
   on CPU - only with a larger instance or a quantised model, measured on that hardware first.
4. **Source-quality report** for editors (unknowns, old editions, past deadlines, overlaps) - no automatic changes.
5. **Human review** of the v0.3 draft before any accuracy claim.
