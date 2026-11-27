# Citation and figure validation

## 1. The checks, in the order they run on every generated answer

| Step | Code | What it guarantees | Since |
|---|---|---|---|
| marker repair | `_validate_answer` | `[n]` markers that do not exist are removed; repeated markers collapsed; a model-written source list removed | RC |
| link check | `_sanitize_links` | a link not present in the selected passages becomes plain text | RC |
| figure grounding | `_validate_answer` | a sentence stating a figure (≥ 2 digits: fee, date, duration, count) that appears in **none** of the selected passages is removed | RC |
| **per-citation support** | `citation_check.check_citations` | a sentence whose figures are not in the source **it cites** is re-attributed to the one selected source that states them all, else reported as ambiguous | **v2** |
| attribution | `_attribute` | an answer without markers whose figures all come from one source gets that source's marker | RC |
| no citations | `respond` | an answer with sources but without any valid marker becomes the fallback message with sources | RC |

All deterministic; no model is asked to vouch for a citation.

## 2. Measured (local proxy answers; not Gemini)

DEV + VALIDATION + DEV-negatives (A1, 235 turns; 212 with a generated, cited answer):

| | count |
|---|---|
| sentences with figures and a marker (checked) | 112 |
| supported by the cited source | 104 (92.9 %) |
| **re-attributed** to the source that states the figures | **7 (6.3 %)** |
| ambiguous (figures spread over several sources) | 1 |
| sentences with figures but no marker, in an answer that cites elsewhere | 86 (their figures still had to appear in some selected source) |
| answers replaced by the fallback (unsupported 1, no citations 1, wrong language 2, truncated 1) | 5 |

TEST results: ANSWER-EVALUATION.md §3 (citation precision against the graded labels and "a cited passage contains a
gold quote").

## 3. What these checks cannot catch

- **A correct figure attached to the wrong entity.** A student-ID question answered with the residence-card fee
  (KRW 35,000) cites the residence-card article, which does state 35,000. Every figure check passes. Only an
  entity-level check, or refusing weak evidence (the gate, not reliable enough to enforce yet), would stop it.
- **Wording without figures** (procedures, yes / no answers) is not checked; that needs human rating
  (`A*_human_rating.csv`).
- **Contradicting sources.** The checks keep a figure if any cited source states it. For the one genuine conflict in
  TEST (WRK-02: 25 weekday hours in the 2026-reviewed article vs 20 in the 2021 guidebook), whether the answer mentions
  both values is reported in ANSWER-EVALUATION.md.

## 4. Recommendation

Ship the per-citation check (always on, ≈ 0.1 ms per answer). Do not present "92.9 % supported" as a Gemini number:
it describes the checks applied to a local 7B model's answers.
