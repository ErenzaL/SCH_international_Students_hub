# Retrieval experiments — design and protocol

Every run is listed in EXPERIMENT-LOG.md with its result file. This file explains **how** the experiments were run so
that the numbers can be judged.

## 1. Protocol

| Step | Data | Rule |
|---|---|---|
| tune | DEV (v0.1, 100 q, 20 needs) | anything may be tried and looked at |
| select | VALIDATION (v0.2, 100 q, 20 needs; not blind since the previous mission) | choice by a rule written **before** the run (P1) |
| gate tuning | DEV + VALIDATION + DEV-negatives (35 q, DEV-only) | thresholds frozen before TEST (G1) |
| confirm | TEST (v0.3, 210 q, 42 needs, frozen and committed before any experiment) | **one** run of configurations fixed in advance (P2); no tuning afterwards |

TEST was used once (T1–T3, same day, all configurations of P2). Two additional TEST configurations (chunker v2 with the
baseline and with the rewrite) are labelled **post-hoc** and are not used for claims.

## 2. What is measured

- **Document level** (`RetrievalService.search(question, top_k = 10)`, one passage per document for the weighted
  hybrid): strict hit@k / MRR (grade-2 document), lenient versions (grade ≥ 1), nDCG@5/10, P@5, recall@5/10.
- **What the answer model reads** (`AssistantEngine._retrieve(queries)` + `_select`, production limits 4 sources × 3
  passages, 9,000 characters): `ctx_doc_hit` = a grade-2 document is among the sources; `ctx_hit` = a passage
  containing a **gold quote** is (TEST only); `ctx_qrecall` = share of the gold quotes that are.
  `f_*` = document ranking after reciprocal-rank fusion over the query variants.
- **Gate features** over the selected passages: best similarity, best keyword coverage, exact identifier match.
- Intervals: percentile bootstrap that resamples **information needs** (5,000 resamples). Paired differences use the
  same resampled needs.

The two stages answer different questions. A configuration can rank the primary document lower and still give the
model the evidence (and the reverse). `ctx_hit` is the metric closest to answer quality.

## 3. Configurations (`scripts/rag_v2/configs.py`)

| Name | What changes against the production settings (`render.yaml`: min similarity 0.80) |
|---|---|
| `baseline` | nothing (weighted hybrid, vector 1.0, keyword 0.35, glossary bridge 0.75, pool 30, ≤ 3 passages / document) |
| `vector`, `keyword`, `hybrid_legacy`, `no_bridge` | single legs; SQL-side RRF fusion of the earlier release; bridge off |
| `hub{β}` | long documents scaled by (median chunks / their chunks)^β, β ∈ {0.05 … 1.0} (switch existed, off) |
| `oracle_en`, `oracle_en_ko` | the same need's English (and Korean) question added as extra queries: a **perfect translation**, upper bound of what a rewrite can add |
| `llm_rewrite` | the engine's own `_queries` step (production rewrite prompt, code-preservation rule) with **Qwen 2.5 7B on loopback Ollama**, temperature 0, cached, as a proxy for the Gemini Flash-Lite rewrite |
| `hub0.1_*` | combinations |
| chunker `v1` / `v2` / `v2b` | index-time: v1 = release; v2 never drops text; v2b also reads PDF `#` marks as text |

## 4. Stores

- **memory**: the in-memory mirror (exact cosine; simpler keyword leg). Chunk ids come from a seeded generator, so ties
  break the same way in every run. Tie sensitivity measured with three seeds: ≤ 0.01 hit@1 (E1s).
- **PostgreSQL**: PostgreSQL 17.12 + pgvector 0.8.1 (HNSW, `ef_search` 40) + PostgREST + all migrations, through the real
  `SupabaseStore`, on a socket-only scratch stack (`scripts/scratch_db.sh`). The same first-relevant rank as memory for
  98 / 100 (DEV), 98 / 100 (VAL) and 208 / 210 (TEST) questions. Headline TEST numbers were confirmed on PostgreSQL (T3).

## 5. Candidates not run, and why

| Candidate | Reason (evidence) |
|---|---|
| cross-encoder reranker (mMiniLM int8, ≈ 120 MB) | does not fit Render free (512 MB): the API already peaks at 457 MB PSS / 491 MB RSS with `MALLOC_ARENA_MAX=2` (RC `docs/development/RENDER-MEMORY.md`); model files are not on this server and downloading them for a configuration that cannot ship was not justified |
| larger embedding models (e5-base, bge-m3) | same memory limit; would also need a full re-index and a migration of `vector(384)` |
| cross-script weight | evaluated in the previous mission: helped the development sets, failed the blind set (RC `KOREAN-RETRIEVAL.md`) |
| a paid Gemini rewrite | no key on this server (BLOCKERS B1); the local proxy is labelled as such |

## 6. Threats to validity

- Labels are AI-drafted and unreviewed (all splits). The DEV / VALIDATION labels are **not exhaustive**: a guidebook
  passage that answers is often unlabelled. This biased the hub-scaling selection (RETRIEVAL-RESULTS §3).
- VALIDATION was not blind (looked at in the previous mission), which is why TEST was built.
- The rewrite proxy is a 7B local model. Gemini Flash-Lite may write better or worse variants (MULTILINGUAL-RESULTS §4).
- Small corpus (27 documents) and 42 TEST needs: intervals are wide, and per-language cells have 38 questions.
- Latency is in-process on the school server, not the hosted latency.
