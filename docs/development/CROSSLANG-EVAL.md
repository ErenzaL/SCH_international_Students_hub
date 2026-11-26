# Cross-language retrieval: English questions about Korean official notices

The weakest case found in [KOREAN-RETRIEVAL.md](KOREAN-RETRIEVAL.md): a student asks in English, the answer is in a short Korean notice.
This is a targeted evaluation for that case. **No ranking default was changed.** Both switches stay at 0 until the rule below is met.

## The set (`scripts/benchmarks/crosslang_en_ko_v1.json`, committed in 3a0e917 before any run)

- 36 public Korean notices of the university (the cached notice corpora; their text stays local, only ids and links are committed).
- Per notice, three questions: an **English topic** question in a student's own words (not a translated title), an **English detail**
  question about a fact that only the body contains, and a **Korean control** question with the same target. 108 questions.
- Corpus at evaluation time: the 22 public Knowledge Center documents and announcements that are not one of these notices, plus the 36
  notices (58 documents, 798 chunks), production chunker and model (multilingual-e5-small int8), `RETRIEVAL_MIN_SIMILARITY=0.80`.
- **Split by notice**, fixed seed: 18 notices dev (54 questions), 18 held-out (54). Questions of one notice are never in both.
- Labels: strict = the notice; lenient = also a closely related document named in the set (two notices have one). Written by an AI assistant,
  **not reviewed**: `docs/review/crosslang_en_ko_v1_review.csv` is the reviewer worksheet (links to the notices, no notice text).

## Development results (dev split only; held-out not looked at)

`cd backend && .venv/bin/python ../scripts/eval_crosslang.py --split dev --setting …` → `scripts/benchmarks/results/crosslang_dev_v1.json`

| Setting | EN R@1 | EN R@5 | EN MRR | EN topic / detail MRR | KO MRR | EN − KO gap (same notices) | ΔEN MRR vs baseline, 95 % interval |
|---|---|---|---|---|---|---|---|
| baseline (production) | 0.167 | 0.278 | **0.214** | 0.178 / 0.250 | **0.972** | −0.794 | – |
| cross-script titles (`RETRIEVAL_CROSS_SCRIPT_WEIGHT=1`) | 0.306 | 0.417 | 0.353 | 0.372 / 0.333 | 0.944 | −0.572 | +0.139 (0.042 to 0.258) |
| long-document penalty (`RETRIEVAL_HUB_BETA=0.1`) | 0.222 | 0.306 | 0.247 | 0.233 / 0.261 | 1.000 | −0.767 | +0.033 (−0.003 to 0.081) |
| both | 0.389 | 0.472 | **0.419** | 0.486 / 0.352 | 1.000 | −0.514 | **+0.205 (0.100 to 0.326)** |

What the misses show (baseline, 30 of 36 English questions not first):
- **The 157,000-character English guide comes first in 13 of them.** The long-document penalty removes almost all of these (13 → 2; with
  both switches 1), but on its own the notice then often still does not come first.
- **4 English questions get no result at all**: every passage is below the 0.80 similarity cut-off, which English-to-Korean similarities
  rarely reach. No setting above changes that. The chat then says that no approved source was found.
- Korean questions about the same notices are almost perfect (MRR 0.972): the notices are findable, the gap is cross-language.

These are development numbers on unreviewed labels: they choose what to test, they do not prove anything.

## Adoption rule (fixed before the held-out look)

A ranking default changes only when **all** hold, on the **held-out** split, with **reviewed** labels:
1. English MRR improves by at least **0.05** and the paired bootstrap 95 % interval of the difference is above 0;
2. Korean MRR on the same notices drops by at most **0.02**;
3. the general benchmarks (pilot, both blind sets of KOREAN-RETRIEVAL.md) do not get worse beyond their 95 % intervals;
4. then staging first (a week with real questions), production only with your approval.

**Pre-registered candidate for the one held-out look:** `both` (`RETRIEVAL_CROSS_SCRIPT_WEIGHT=1.0`, `RETRIEVAL_HUB_BETA=0.1`). Run it once,
after the review:

```bash
cd backend && .venv/bin/python ../scripts/eval_crosslang.py --split heldout --ledger-note "reviewed labels, pre-registered candidate" \
  --setting both=retrieval_cross_script_weight:1.0,retrieval_hub_beta:0.1
```

The script never prints or writes a held-out question or ranking, only aggregates, and appends every held-out run to
`scripts/benchmarks/results/crosslang_heldout_ledger.json` (time, commit, settings, numbers): the number of looks stays visible. A second look
needs a new reason in the ledger; tuning on held-out is not allowed.

## Next, in order

1. Native Korean and English reviewers fill in the worksheet (about 1 hour): is the question natural, does the notice answer it, which other page
   also does. Corrections go into a `v1.1` of the set, committed before the next run.
2. The held-out look above.
3. Separately, on dev: a lower similarity cut-off for questions whose script differs from the passage's (for the 4 empty results), and
   splitting the long English guide into chapters (editorial, no code), each measured on this set and the general ones.
