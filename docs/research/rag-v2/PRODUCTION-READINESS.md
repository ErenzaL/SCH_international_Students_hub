# Production readiness — RAG v2

**Nothing of this mission is in production or on a hosted staging service.** Branch `research/rag-reliability-v2`,
local commits only; no push, deploy, migration, production data change, schedule activation or paid API call.

## 1. Classification of every change

| Change | Implemented | Locally evaluated | Human-validated | Hosted staging | Production | Recommendation |
|---|---|---|---|---|---|---|
| Frozen TEST set v0.3, DEV-negatives, evaluator, regression script | yes | — (tooling) | **no** (labels AI-drafted) | — | — | use for every RAG change; human review first |
| Chunker v2 (`CHUNKER_VERSION`, default `v1`) | yes | yes (DEV / VAL / TEST post-hoc) | no | no | no | **adopt with the re-index, staging first**: fixes 13 % of corpus text (58 % of the Korean guidebook) that approved documents show but search cannot see; neutral where the rewrite works; costs single-query ranking without it |
| Hub scaling (`RETRIEVAL_HUB_BETA`) | existed | yes, rejected on TEST | no | no | off | **keep 0** |
| Query rewrite (exists; Gemini Flash-Lite) | existed | yes, with a **local proxy** only | no | no | in production code | keep; monitor failures (§4) |
| Evidence gate (`ASSISTANT_EVIDENCE_GATE`, default `log`) | yes | yes; thresholds **do not transfer** to TEST | no | no | no | ship in `log` only; **do not enforce** |
| Per-citation support check (always on) | yes | yes (proxy answers: 7 of 112 figure sentences re-attributed) | no | no | no | ship |
| Prompt-injection screens (always on) | yes | yes (11 / 11 with the proxy; 0 false positives on corpus and 410 questions) | no | no | no | ship |
| Monitoring fields in message metadata (`evidence_gate`, `injection_screened`, `citation_check`) | yes | unit tests | — | no | no | ship |
| `scratch_db.sh stop` refuses without `pg_ctl` | yes | used | — | — | — (test tooling) | ship |

Gemini answer quality and the Gemini rewrite: **blocked** (no key on this server; BLOCKERS B1).

## 2. Settings for the next release

| Variable | Value | Why |
|---|---|---|
| `CHUNKER_VERSION` | `v2` **after** the re-index in staging | the code default stays `v1`, so nothing changes silently |
| `RETRIEVAL_HUB_BETA` | `0` (unchanged) | TEST −0.112 MRR on guide-answered needs |
| `ASSISTANT_EVIDENCE_GATE` | `log` (default) | decision visible in metadata, no behaviour change |
| everything else retrieval-related | unchanged (`render.yaml`: `RETRIEVAL_MIN_SIMILARITY=0.80`) | |

## 3. Owner steps (each needs your approval; none was done)

1. Review the branch (second person); merge into the release branch you choose. **No migration is needed.**
2. Staging (RC FINAL-SETUP-CHECKLIST): deploy, set `CHUNKER_VERSION=v2`, re-index the 27 documents (the indexer reuses
   unchanged embeddings by input hash), then run `scripts/rag_v2/regression.py --update-reference` against the staging
   corpus snapshot and keep the file.
3. Capped Gemini run (ANSWER-EVALUATION §6): prices from the official list, `--max-questions` of your choice,
   `--confirm-paid-run`. It replaces the proxy numbers for the rewrite and the answers.
4. Human review of the TEST labels (HUMAN-REVIEW-CHECKLIST.md) and of a sample of answers
   (`A9_test_human_rating.csv`).
5. Only after 3 and 4: decide whether the gate's thresholds can be re-fitted on Gemini traffic. Until then, keep `log`.

## 4. Monitoring (read-only, aggregates only, no message content)

The assistant now writes, per answer: `metadata.evidence_gate` (none / insufficient / sufficient),
`metadata.injection_screened` (sentences removed), `metadata.citation_check` (checked / supported / reattributed /
ambiguous / uncited), next to the existing `rewritten`, `answer_generation`, `fallback_reason`, `evidence_level`.

```sql
-- weekly, admin SQL editor (service role); counts only
select date_trunc('week', created_at) as week,
       metadata->>'answer_generation'             as generation,
       metadata->>'evidence_gate'                 as gate,
       (metadata->>'rewritten')::boolean          as rewritten,
       count(*)                                   as answers,
       sum((metadata->>'injection_screened')::int) as screened_sentences,
       sum((metadata->'citation_check'->>'reattributed')::int) as reattributed_citations
from public.ai_messages
where role = 'assistant' and created_at > now() - interval '8 weeks'
group by 1, 2, 3, 4 order by 1 desc, 5 desc;
```

Alarms worth acting on: `rewritten = false` above a few percent (cross-language questions fall to the weak path);
any `screened_sentences > 0` (an approved document contains orders to the model: find and fix it at review);
`insufficient` rising after a corpus change; `fallback_reason` trends.

Before every change to chunking, embedding, retrieval or selection:
`backend/.venv/bin/python scripts/rag_v2/regression.py` (exit 1 = regression, 2 = reference not comparable).

## 5. What would make this production-verified

A hosted staging run of steps 2–3 with the regression reference stored, the human reviews of step 4, and, after release,
the §4 query on real traffic for a few weeks.
