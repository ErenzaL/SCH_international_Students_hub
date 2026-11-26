# Multilingual evaluation (Korean, English, Indonesian, Vietnamese, Simplified Chinese)

All five languages are supported in retrieval, chat and the AI Office. Announcement **translation** in Release 1 covers only Korean, English
and Indonesian ([TRANSLATION-EVALUATION.md](TRANSLATION-EVALUATION.md)). Labels are AI-drafted and not reviewed by people.

## 1. Retrieval by question language (held-out, production configuration, 20 questions per language)

| Question language | Evidence language (mostly) | R@1 | R@5 | MRR@10 [95 %] | vs. vector-only MRR |
|---|---|---|---|---|---|
| Korean | Korean + English | 0.40 | 0.55 | 0.505 [0.313–0.693] | +0.197 |
| English | Korean + English | 0.65 | 0.90 | 0.767 [0.610–0.905] | −0.020 |
| Indonesian | Korean + English | 0.85 | 1.00 | 0.912 [0.812–1.000] | +0.066 |
| Vietnamese | Korean + English | 0.45 | 0.90 | 0.642 [0.490–0.790] | +0.065 |
| Chinese | Korean + English | 0.80 | 0.95 | 0.852 [0.700–0.975] | +0.215 |

The corpus holds no Indonesian, Vietnamese or Chinese documents: every non-Korean, non-English question is a cross-language retrieval. That
Indonesian and Chinese questions do best is partly the questions' wording (they name the official terms the glossary bridges) and partly
chance at n = 20; the intervals overlap. Korean questions suffer most from the long Korean guidebooks (RAG-ERROR-ANALYSIS §1).

## 2. The hard case: English questions about short Korean notices

From [CROSSLANG-EVAL.md](../development/CROSSLANG-EVAL.md) (development split, 18 notices, 54 questions; the held-out split is **not opened**
until native reviewers check the labels — one pre-registered look):

| | English MRR | Korean MRR (same notices) |
|---|---|---|
| production ranking | 0.214 | 0.972 |
| with both candidate switches (cross-script titles + length penalty) | 0.419 | 1.000 |

Interpretation: a Korean notice is easy to find in Korean and hard to find from English. The candidate fix doubles English MRR on the
development split but is **not adopted** until it passes the held-out look with reviewed labels.

## 3. Answers by question language (answer benchmark, Qwen 2.5 7B + RAG, 19 questions per language)

| Language | Qwen + RAG correct (n = 19) | excerpts only | no sources |
|---|---|---|---|
| Korean | 1.00 | 0.84 | 0 |
| English | 0.95 | 0.84 | 0 |
| Indonesian | 1.00 | 0.89 | 0 |
| Vietnamese | 0.84 | 0.89 | 0 |
| Chinese | 0.79 | 0.89 | 0 |

Every Qwen + RAG answer was in the question's language (95 / 95). Vietnamese and Chinese are the weakest for answers (passed-deadline and
two-date notices; RAG-ERROR-ANALYSIS §3); with 19 questions per language a difference of one or two answers is within noise.

## 4. Language behaviour that is guaranteed by code (tested)

* The answer language is checked; a wrong-language answer is retried once, then an honest fallback in the question's language
  (`test_one_retry_in_the_requested_language_then_an_honest_fallback`).
* Each supporter desk answers in its own language; Hana answers in the language of the question.
* Announcement pages show the approved translation of the selected language, or the original with a note; Vietnamese and Chinese readers
  are told that announcement translations are not offered yet; a pending machine draft is never shown (`test_release1_translation_scope.py`).
* Interface strings exist in all five languages (`messages.test.ts` checks key parity); the new strings of this release were written by an
  AI assistant and need a native check (vi, zh-CN, id especially).

## 5. Limitations

20 questions per language; AI-drafted questions may read less naturally than real students' questions; no Indonesian, Vietnamese or Chinese
source documents exist, so "same-language" retrieval for those languages is untested.
