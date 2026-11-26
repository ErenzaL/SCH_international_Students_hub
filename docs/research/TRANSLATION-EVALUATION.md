# Announcement translation evaluation (Release 1: Korean, English, Indonesian)

Measured 2026-11-27 on the university workstation (RTX 4070 12 GB, Ollama 0.40.2, seed 1, temperature 0.2, context 16k). Script:
`scripts/bench_announcements.py` (the GPU worker's own generation code and checks). Raw numbers: `scripts/benchmarks/results/announcements_*.json`;
the translated texts stay in `backend/.eval-cache` (not committed: they are copies of university notices).

**What is and is not measured.** The script checks, per draft, every fact it can verify mechanically: dates, times, amounts, links
(URLs, domains, e-mail, phone), weekdays, a glossary of 25 administrative terms and 11 proper nouns, missing lines, added numbers or links,
leftover Korean, stray Chinese and leaked instructions. **Fluency, word choice outside the glossary and overall meaning are NOT measured**;
no native speaker has rated these drafts yet. "No measured error" therefore means "no detectable fact error", not "correct translation".
The glossary was written by an AI assistant and needs confirmation by native speakers.

## 1. Data

| Set | Notices | Directions | Drafts per config | Use |
|---|---|---|---|---|
| development | 26 real public SCH notices (academic, international office, scholarship; median 590 characters, longest 1,704) | ko → en, ko → id | 52 | choosing the configuration |
| held-out | 10 other public notices (median 525, longest 1,038) | ko → en, ko → id | 20 | one run each, after the choice |

No notice contains personal data (checked when the corpus was built). English → Indonesian and Indonesian → Korean/English were **not**
benchmarked: the university's notices are Korean, so no original English or Indonesian notices were available; those directions work in the
code (tested with fixtures) but their quality is unmeasured.

## 2. Models and prompts

| Model | Size | Licence | GPU memory while translating |
|---|---|---|---|
| `qwen2.5:7b-instruct` (previous worker default) | 4.7 GB Q4_K_M | Apache 2.0 | 5.6 GB |
| `translategemma:4b` (Google's translation-tuned Gemma 3) | 3.3 GB Q4_K_M | Gemma Terms of Use | 8.4 GB |
| `translategemma:12b` | 8.1 GB Q4_K_M | Gemma Terms of Use | 9.7 GB |

Prompt styles: **shared** = the Hub's translation prompt with the exact forms of every date/amount and glossary term as hints, and up to two
repair passes that name what a draft lost; **native** = TranslateGemma's own single-turn prompt from its model card, no hints, no repairs
(the same automatic checks still run and are shown to the reviewer).

## 3. Development results (26 notices × 2 languages = 52 drafts)

| Configuration | Drafts without a measured error | Fact errors | Wrong weekday | Glossary terms | Proper nouns | Failed drafts | Median / p95 s per notice |
|---|---|---|---|---|---|---|---|
| Qwen 2.5 7B, shared | 47 / 52 | 4 | 0 | 83 / 84 | 71 / 72 | 0 | 5.7 / 16.8 |
| TranslateGemma 4B, native | 41 / 52 | 11 | 9 | 74 / 84 | 48 / 72 | 0 | 2.9 / 6.0 |
| TranslateGemma 4B, shared | 40 / 47 | 3 | 2 | 71 / 73 | 60 / 62 | 5 (wrong language → refused) | 3.8 / 8.6 |
| TranslateGemma 12B, native | 42 / 52 | 9 | 1 | 76 / 84 | 58 / 72 | 0 | 7.8 / 16.2 |
| **TranslateGemma 12B, shared** | **50 / 52** | **1** | **0** | **84 / 84** | **72 / 72** | 0 | 8.8 / 27.8 |

Dates (138/138), money (24/24) and links (30/30) were preserved by every configuration except single slips (12B native: one date in
Indonesian; 4B native: one link in English).

Per language, TranslateGemma 12B shared: English 24 / 26 without a measured error (1 fact error), Indonesian 26 / 26 (0).

**Paired test** (the same 52 drafts): TranslateGemma 12B shared vs. Qwen 2.5 7B shared — Qwen worse alone on 4 drafts, TranslateGemma worse
alone on 1; exact McNemar p = 0.375. The difference is **not statistically significant** at this sample size.

**Finding:** for the 12B model the Hub's prompts are clearly better than TranslateGemma's own prompt (50 vs. 42 drafts without a measured error,
1 vs. 9 fact errors). For the 4B model the picture is mixed: the Hub's prompts cut fact errors from 11 to 3 but 5 English drafts came back in
the wrong language and were refused. The native prompt mostly lost weekdays and proper nouns (no hints). The worker therefore uses the Hub's
prompts for every model (`GPU_WORKER_PROMPT_STYLE=auto`).

## 4. Choice (rule fixed before the held-out run)

Rule: most development drafts without a measured error; ties broken by fewer fact errors, then lower median time; must fit the 12 GB GPU
with a median under 30 s. → **TranslateGemma 12B with the Hub's prompts.** Qwen 2.5 7B stays a supported alternative (comparable quality on
these checks, 35 % faster, 4 GB less GPU memory).

## 5. Held-out results (one run each)

| Configuration | Drafts without a measured error | Fact errors | Failed | Dates / times / money / links | Weekdays | Terms | Names | Median / p95 s |
|---|---|---|---|---|---|---|---|---|
| **TranslateGemma 12B, shared** | **20 / 20** (en 10/10, id 10/10) | 0 | 0 | 52/52 · 14/14 · 8/8 · 12/12 | 50/50 | 17/18 | 12/12 | 7.7 / 20.8 |
| Qwen 2.5 7B, shared | 17 / 19 (en 9/9, id 8/10) | 2 | 1 | 49/49 · 13/13 · 8/8 · 12/12 | 46/46 | 15/16 | 12/12 | 6.2 / 10.4 |

Paired over the 20 drafts (a failed draft counts as an error): Qwen worse alone on 3, TranslateGemma on 0; exact McNemar p = 0.25 —
**consistent with the development result, still not statistically significant** (20 drafts). The automatic checks flagged 4 of the 20
TranslateGemma drafts for the reviewer (all false alarms) and missed none with a measured error.

**Conclusion for the slides:** on 72 real notice translations (52 development + 20 held-out) TranslateGemma 12B with the Hub's prompts kept
every date, amount and link and had 1 detectable fact error in total; Qwen 2.5 7B had 6 plus one failed draft. Both need a human reviewer —
neither result says anything about fluency.

## 6. How the automatic checks behave (development, 12B shared)

The production checks flagged 13 of the 52 drafts for the reviewer: 2 had a real measured error, 11 were false alarms (mostly a number written
differently, e.g. a range or a date rewritten). They missed **no** draft with a measured error. Flags never block a draft; they are shown
next to it in the review screen. Wrong-language drafts are refused before they are stored.

## 7. Review integration (what happens to a draft)

1. Only an **approved, published** announcement is sent, and only its approved text (pending edits are never translated).
2. Targets: the other two of ko / en / id; never the original language; never vi / zh-CN in this release.
3. The draft is stored as `needs_review` (GPU worker) or `machine_draft`; it is **never** shown to students, whatever
   `PUBLIC_MACHINE_TRANSLATIONS` says.
4. Only a reviewer assigned to that language (`can_review`, checked on the server and in the database) can approve; the reviewer sees the
   original, the draft, the warnings and the history, can edit, approve, reject or request a new draft.
5. When the original changes, the translation is marked outdated, its history kept, and it disappears from the public page until reviewed again.
Tested by `test_release1_translation_scope.py`, `test_auto_translation.py`, `test_gpu_worker.py` and the integration tests on PostgreSQL.

## 8. Limitations

* No human quality rating yet; "no measured error" ≠ correct. Native reviewers for English and Indonesian are the next step (§FINAL-SETUP-CHECKLIST 6.3).
* 26 + 10 notices from three offices; long notices (> 1,700 characters) and tables are under-represented.
* Gemini as a translation alternative is **not measured** (no key on the development server).
* The school PC is development only: production never waits for it (48-hour hand-over to the server's model or a visible failure).
