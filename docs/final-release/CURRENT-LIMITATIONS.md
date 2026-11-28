# Current limitations of the final release

Only limitations that still apply to `release/sch-hub-final-2026-11-30`. Each entry: **condition · evidence · why it
matters · severity · improvement · resources · benefit · priority (P1 high – P3 low) · needed before a wider public
rollout?** Evidence links point to the measured files (`docs/research/rag-v2/`, `scripts/benchmarks/results/rag_v2/`).

## RAG

**L1 Benchmark labels are AI-drafted.** Condition: every relevance label, question and reference answer was written by an AI
assistant. Evidence: DATASET-CARD §7; review sheet unfilled. Why: all RAG numbers could be biased by the labeller. Severity:
high for research claims, low for daily use. Improvement: native speakers + an international-office reviewer fill
`testset_v0.3_review.csv`; κ ≥ 0.6 on a double-graded sample. Resources: ~10 person-hours. Benefit: numbers become
human-validated. Priority P1. Before rollout: **yes**, for any published accuracy claim.

**L2 Gemini answer quality is unmeasured.** Condition: answers were measured with a local proxy (Qwen 2.5 7B), not Gemini.
Evidence: ANSWER-EVALUATION §6 (blocked: no key on the workstation). Why: production answers come from Gemini. Severity: high.
Improvement: the prepared capped run (`answer_eval.py --provider gemini`). Resources: about US$2–3 for 210 questions at
standard prices; owner approval. Benefit: real accuracy figures. Priority P1. Before rollout: **yes**.

**L3 Cross-language retrieval depends on the rewrite.** Condition: without the Gemini rewrite (no key, outage, daily cap
reached), questions in another language than the source reach their evidence far less often. Evidence: TEST gold passage
reaches the model 58 % vs 84 % with variants (RETRIEVAL-RESULTS §2). Why: the fallback path is weak exactly when budgets run
out. Severity: medium. Improvement: monitor `rewritten = false`; keep the glossary bridge; consider a deterministic
translation of key terms. Resources: monitoring only. Benefit: fewer silent quality drops. Priority P2. Before rollout: monitoring yes.

**L4 Visa and admission passages inside long documents.** Condition: the right document is found, but the passage with the
rule is not among the three passages kept per document. Evidence: TEST admission gold passage 0.00 even with variants; visa
0.56 → 0.82 (RETRIEVAL-RESULTS §6). Why: answers miss footnotes such as "★ units do not admit foreigners". Severity: medium.
Improvement: passage selection that favours rule / footnote sentences inside long documents; evaluate on TEST. Resources:
engineering days + an evaluation run. Benefit: fewer partial answers. Priority P2. Before rollout: no.

**L5 Korean / Vietnamese weaknesses.** Condition: Korean questions about English documents were the weakest pair on
DEV/VAL (hit@1 0.30); Vietnamese answers had the lowest figure recall with the proxy (0.37). Evidence: MULTILINGUAL-RESULTS.
Why: two of the five supported languages are less reliable. Severity: medium. Improvement: evaluate with Gemini (L2); native
review of the vi questions. Resources: as L1 / L2. Benefit: known per-language quality. Priority P2. Before rollout: no.

**L6 Numbers can be right for the wrong thing.** Condition: a figure correct for another item passes every figure check
(student-ID fee answered with the residence-card fee). Evidence: ERROR-ANALYSIS §7. Why: a confident wrong amount. Severity:
medium. Improvement: an entity check between the question's subject and the cited passage, or a reliable evidence gate.
Resources: research days. Benefit: fewer plausible wrong amounts. Priority P2. Before rollout: no, but say so in user help.

**L7 Conflicts between sources are not surfaced.** Condition: when two approved sources disagree, the proxy gave the newer
value without mentioning the other. Evidence: WRK-02, 0 / 5 surfaced (ANSWER-EVALUATION §4). Why: students are not told that
an official text says otherwise. Severity: medium. Improvement: detect differing figures for the same unit across selected
sources (the evidence checker already reports them, off) and add a fixed note. Resources: engineering + evaluation. Benefit:
transparency. Priority P2. Before rollout: no.

**L8 Chunker v2 not activated.** Condition: 13 % of the corpus text (58 % of the Korean guidebook) is not searchable with the
release's default chunker v1. Evidence: BASELINE-AUDIT stage 3; fix behind `CHUNKER_VERSION=v2`. Why: approved information is
invisible to the chat. Severity: medium. Improvement: re-index in staging, run the regression script, then production.
Resources: a staging copy (owner), ~1 hour. Benefit: all approved text searchable. Priority P1 after the presentation.
Before rollout: yes.

**L9 No freshness / authority ranking.** Condition: an older edition is demoted only for notice families; a 2021 guidebook
can rank next to a 2026 article. Evidence: VIS-09 / VIS-10 sources from 2021. Severity: low–medium. Improvement: date-aware
tie-breaks and a "source date" line in answers (the date is already shown in the prompt). Priority P3. Before rollout: no.

**L10 Evidence gate cannot be enforced.** Condition: thresholds tuned on development questions refuse 18 % of realistic
answerable questions. Evidence: G-T in EXPERIMENT-LOG. Severity: low (it runs in log mode). Improvement: refit on real,
human-labelled traffic. Priority P3. Before rollout: no.

**L11 No real student questions evaluated.** Condition: all datasets are written questions. Severity: medium for claims.
Improvement: collect consented, anonymised questions (the support flow already asks consent). Priority P2. Before rollout: no.

## Translation

**T1 Release 1 drafts ko / en / id only.** Condition: Vietnamese and Chinese readers see the original or an existing approved
translation with a note. Evidence: `test_release1_translation_scope.py`. Why: two chat languages get no new announcement
translations. Severity: low (by decision). Improvement: add languages after reviewers exist. Priority P3. Before rollout: no.

**T2 No human quality rating of translations.** Condition: TranslateGemma 12B had 1 detectable fact error in 72 notices, but
"no detected error" is not "correct". Evidence: TRANSLATION-EVALUATION §6. Severity: medium (reviewers approve each draft).
Improvement: native reviewers rate a sample. Priority P2. Before rollout: yes, for automatic drafting.

**T3 No always-on translation model in production.** Condition: free drafts need the school GPU worker (off); Gemini drafting
costs budget. Severity: low (reviewers can translate by hand). Improvement: decide between paid Gemini drafts with a
background cap or a hosted small model. Priority P3. Before rollout: no.

## Autonomous agents and external sources

**A1 Weekly schedules off.** Condition: discovery runs only when a person starts it. Evidence: both switches false; 0019 not
applied. Why: "autonomous" desks are request-driven today. Severity: low. Improvement: enable one schedule, watch a week.
Priority P2. Before rollout: no.

**A2 Human approval is required for everything discovered.** By design; it limits throughput. Severity: none (safety
feature). Keep.

**A3 Career APIs not connected.** Work24, data.go.kr and Saramin need keys; Linkareer, Buddies Korea and JobKorea give no
permission for automated access (links only). Severity: low. Improvement: apply for keys. Priority P3.

**A4 Live websites can change.** A layout change breaks a reader; the source backs off and alerts after 5 failures.
Severity: low. Improvement: monitor the alerts. Priority P3.

## Infrastructure

**I1 Memory headroom on Render free (512 MB).** Peak 457 MB PSS / 491 MB RSS with `MALLOC_ARENA_MAX=2` during heavy
ingestion. Severity: medium. Improvement: set the variable; one upload at a time; paid plan only by decision. Priority P1.
Before rollout: yes (the variable).

**I2 No automatic database backups (Supabase free).** Severity: high for data safety. Improvement: weekly `pg_dump` by hand
or a scheduled export. Priority P1. Before rollout: **yes**.

**I3 Cold starts.** The free API sleeps; the first request took 42.6 s. Severity: low–medium for demos. Improvement: open the
site a minute before a demo; a paid instance avoids it. Priority P3.

**I4 Monitoring is manual.** Metrics, billing and the SQL query are checked by hand; no alerting. Severity: medium.
Improvement: Google budget alerts (free), an uptime check. Priority P1. Before rollout: budget alert yes.

**I5 Gemini model retirement.** `gemini-3.6-flash` is listed for retirement on 2027-01-28. Severity: medium (answers would
fall back, then fail). Improvement: test a newer Flash model with the prepared run before January. Priority P1 (January).

## Research

**R1 Statistical uncertainty.** 42 TEST needs; per-language cells have 38 questions; intervals are wide. **R2** DEV /
VALIDATION labels are not exhaustive (misled one experiment). **R3** No usability study with students. **R4** Multilingual
quality compared only with a proxy model. Improvements in FUTURE-IMPROVEMENTS Stage B / C.
