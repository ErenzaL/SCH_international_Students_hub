# Korean PDF chunk quality (notebook 13)

### Conclusions

* **Cause (verified).** The fragmentation is an *extraction* defect - the body font size is estimated from the
  first 20 pages (6.2 pt instead of 9.4 pt), so
  82% of the text is tagged `##`, one "heading" per visual line - and the
  heading-aware chunker turns it into **content loss**: consecutive headings overwrite each other, so only
  24% of the guidebook's Hangul words reach chunk text (43%
  including the embedded heading field). OCR, encoding and the chunker's size logic are not the cause.
* **Repair works at the data level.** Every variant keeps 97-100 % of the words in chunks; median chunk length
  37 -> 539-404
  characters; a guidebook passage reaches the E2 top 5 for 31% -> 67%
  of held-out questions, and the page that holds the answer (reviewed scenarios) is hit in the top 5 for
  20% -> 51% (C3).
* **But benchmark scores fall.** With the frozen labels, held-out E2 MRR is 0.698 for
  production text and 0.655-0.646 for the repaired variants;
  significantly lower after Holm correction: C3 heading-aware, C4 table-aware, C2 paragraph-aware, C1 merge short fragments, P1 production extractor, fixed body size; significantly higher: none.
  The development set agrees (pilot E2 MRR 0.792 vs 0.737 for C2).
  The rebuilt identical index changes E2 MRR by +0.0 pp [+0.0, +0.1], so these are real effects, not tie noise.
* **Why.** A fully indexed 94-page general guide competes with the specific official pages for almost every
  question. Some of those wins are correct answers the frozen labels do not credit (H03: "TOPIK ... 연간 6회", p. 26;
  H06: the D-10 change, p. 75); others are topical distractors (H09-ko: the part-time hours table ranks first for
  "can I work before my permit is approved?"). With the AI-proposed guidebook credits (not
  human-reviewed) the differences shrink and their intervals include zero: C1 -3.1 pp [-7.8, +1.0], C2 -1.6 pp [-5.5, +2.1], C3 -3.3 pp [-8.4, +0.9], C4 -2.6 pp [-8.2, +2.5], P1 -2.2 pp [-6.1, +1.3]. Korean-question MRR under those
  labels: C0 0.667, C2 0.685.
* **Recommendation.** (1) Fix the extraction defect anyway - today most of an approved document is silently
  unsearchable, which is a data-integrity bug, not a tuning choice. Minimal production change: body-size estimate over
  all pages (P1); better: re-flow lines and drop page furniture (C2/C3). Re-extract the guidebook as a *new version*
  through the normal approval flow. (2) Do not expect higher benchmark numbers from it: judge the change only after
  human review of the guidebook labels (v0.3), and pair it with a control for broad documents - the reranker
  (notebook 10/12) or a per-document cap / lower authority weight for the 2021 general guide. Nothing was changed in
  production here.

### Limitations

* Labels: the frozen labels pre-date the guidebook; the sensitivity labels are AI-proposed and **not human-reviewed**
  (worksheet status: pending). Document-level binary relevance; 20 held-out scenarios -> wide intervals.
* Only one document differs between variants; evidence completeness uses page-level matches for 7 reviewed scenarios.
* The guidebook is the 2021 edition; some rules may be outdated even where it is "relevant" for retrieval.
* Variants were designed on this one PDF; P1 is the only variant that is the production extractor itself.
* Pages 4, 5 and 91 are images and remain unextracted (OCR not attempted); latency is local (Apple M1), not Render.
