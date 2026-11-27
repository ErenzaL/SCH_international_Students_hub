# Baseline audit — RAG pipeline of the release candidate

Code audited: branch `research/rag-reliability-v2` = RC `school/rc-2026-11-27` @ `8fd791b` (unchanged code).
Corpus: the 27 approved public documents (snapshot `7bb1a20f19fd28bc`). Every number links to a result file in
`scripts/benchmarks/results/rag_v2/`. "Measured" = run on this server; "read" = from the code / SQL.

## 1. The request path (one chatbot turn)

```
question ─▶ reply language, small-talk check, daily AI budget
         ─▶ _queries: Gemini Flash-Lite rewrite → ≤ 4 queries (standalone, original, en, ko)     [only with an LLM]
              no LLM / rewrite failed → [question] (+ previous question for short follow-ups)
         ─▶ _retrieve: per query RetrievalService.search(top 10, ≤ 5 passages / document) → RRF across queries
         ─▶ _rerank (cross-encoder, OFF: RERANK_PROVIDER=none, model files absent)
         ─▶ _select: drop expired, newest edition of a notice family, visa-code filter, figures-first ordering,
              near-duplicate removal, ≤ 4 documents × 3 passages, ≤ 9,000 characters
         ─▶ (EvidenceChecker: OFF, ASSISTANT_EVIDENCE_CHECK=false)
         ─▶ _generate: system_v2 prompt, [n] markers, META JSON (evidence class, needs_human, in_scope, follow-ups)
         ─▶ post-checks: attribution, unsupported-figure / link removal, script mixing, prompt leak, wrong language,
              missing citations → localized fallback with sources; escalation decided by backend policy
```

## 2. Stage by stage

| # | Stage | Implementation (read) | In → out | Model / cost | Weaknesses found | Security boundary | Failure handling | Tests | Recommended change |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Intake and extraction | `ingestion/pipeline.py`, `extractors_html.py`, `extractors_files.py`, PDF via PyMuPDF in a child process (`pdf_child.py`, `pdf_isolation.py`), OCR provider, KakaoTalk redaction (`privacy.py`), SCH board reader | URL / file / pasted text → `document_versions.extracted_text` (draft) | none (CPU) | **PDF line starts become markdown `## ` marks** in the Korean guidebook (2,479 of its 3,319 lines), mid-sentence page headers (`┃제3장┃…`), tables flattened into number runs ("20시간 무제한 25시간") | `GuardedFetcher`: domain allowlist, robots.txt, public-IP resolution check; PDF parsing isolated in a child process with limits | job error recorded, version stays unpublished | ingestion and fetcher suites | detect line-start `#` artefacts at extraction; keep tables as rows (Phase 3) |
| 2 | Review and approval | version lifecycle `draft → pending_review → approved` (`review.py`, `request_activation`), document lifecycle (cancel, archive, supersede), source lifecycle (deactivate) | version → approved current version | none | approval is a workflow state, not a content check: 6 approved documents say "REVIEW REQUIRED before authoritative release" (25af9ce5, a37644b0, b3f79749) or "Draft for official-policy verification" (744fdb55, 4650e940, 491d4c3f) in their own header | admin roles; RLS; reviewer actions audited | — | review / lifecycle suites, 15 SQL behaviour suites | show such self-declared drafts to reviewers (out of scope here) |
| 3 | Chunking | `chunking.py` v1: headings → section boundaries, `[Page N]` → page refs, paragraphs; target 320 / max 420 / overlap 48 estimated tokens | text → chunks (heading, content, page) | none | **a heading line followed by another heading line is dropped**: `parse_segments` stores a heading line only as the *current heading* and never as text, so consecutive heading lines overwrite each other. Measured: **57.7 % of the Korean guidebook's text (45,144 of 78,268 characters) is in no chunk**; 13.3 % of the whole corpus; 14 of 27 documents lose something (mostly a title line). 3 of the 57 test gold quotes are in lost text. Two guides hold 455 of 749 chunks (61 %) | — | — | `test_hashing_and_chunking.py` (no "no text lost" invariant) | **chunker v2: never drop text** (Phase 3) + an invariant test |
| 4 | Embedding | `embeddings/e5_onnx.py`: multilingual-e5-small, int8 ONNX, 384-d, L2-normalised, `passage:` / `query:` prefixes, 512-token truncation; input = title + heading + text; question vectors cached | text → vector(384) | CPU; ≈ 440 MB steady for the whole API (RC PERFORMANCE.md) | small model (dense-only DEV MRR 0.62); a long document has hundreds of chunks, so one is close to almost any question | model id stored per chunk, search filters on it | embedding error → keyword-only search with a warning | embedding suites | keep (Render 512 MB); test larger models only if they fit (Phase 4) |
| 5 | Index | `document_chunks`: `vector(384)` HNSW cosine (pgvector 0.8.1, `ef_search` default 40), `search_tsv = to_tsvector('simple', heading ‖ content)` GIN, trigram GIN | — | Supabase free tier | `'simple'` has no Korean morphology: keyword leg alone DEV hit@1 0.10, VALIDATION 0.09 (measured, PostgreSQL) | table RLS; written by service role only | — | SQL suites | keep; the Python lexical scorer already compensates (§3) |
| 6 | Visibility filter | view `searchable_chunks` (latest: migration `20261122000009`), `security_invoker = on`: `verification_status = 'approved'` **and** current version (`d.current_version_id = v.id`) **and** `not is_canceled` **and** `archived_at is null` **and** source `is_active` **and** `valid_from ≤ now() < valid_until`. `search_knowledge_v2` (migration `…000006`, `security invoker`, `stable`) reads only this view | chunks → visible chunks | — | none found: drafts, superseded versions, cancelled / archived documents, inactive sources and expired notices are unreachable from search. Language, category, scope and authority are **not** filtered by the assistant (cross-language retrieval is intended) | view and function revoked from `anon` / `authenticated`, executable by `service_role` only; Python defence in depth: `_select` drops passed `valid_until`; older editions / copies (families) leave the context | — | `test_only_approved_content_is_returned`, RLS / lifecycle SQL suites | keep; add a regression test that a superseded edition never enters `_select` output (exists: families tests) |
| 7 | Retrieval (weighted fusion) | `RetrievalService._search_weighted`: vector leg + keyword leg (30 candidates each) + glossary-bridge dense queries (weight 0.75); Python lexical coverage over the candidates; RRF-style weights vector 1.0 / keyword 0.35; code-mismatch penalty 0.5; min similarity 0.80 for semantic-only matches; ≤ 3 passages per document (the assistant asks for 5); Jaccard 0.8 de-duplication; content-based tie-breaks | query → ranked passages | ≈ 85–115 ms p50 in-process (measured, CPU) | the candidate pool is decided by the store's own ordering (memory: random-UUID tie-breaks; SQL: unordered ties, approximate HNSW). Measured effect: ± 0.01 hit@1 across seeds (§3) | runs as service role inside the API only | embedding down → keyword only | `test_retrieval*.py` | — |
| 8 | Query rewrite | `_queries`: Flash-Lite, `fast`, low effort, ≤ 500 tokens; variants that change a visa code are dropped; bridge off when rewritten | question + history → ≤ 4 queries | 1 Flash-Lite call per turn | **not measurable here** (no Gemini key on this server); with an LLM the production path differs from everything measured below | prompt-injection surface: the rewrite sees the student's text | LLM error → original question; provider down → fallback answer | assistant suites (mocked LLM) | measure with the owner's capped run; local proxy with Qwen (Phase 8) |
| 9 | Reranking | `retrieval/rerank.py` ONNX cross-encoder (mMiniLM) | hits → reordered hits | off (`RERANK_PROVIDER=none`); model files not present on this server | — | — | any error → first-stage order | `test_rerank_selection.py` | evaluate only if a model fits Render memory (Phase 4) |
| 10 | Evidence selection | `_select` (above) | hits → ≤ 4 sources × 3 passages | none | measured: the primary document reaches the model in 90 % (DEV) / 80 % (VALIDATION) of questions; long guides take source slots | — | — | `test_reliability_and_evidence.py`, families tests | Phase 4 / 6 |
| 11 | Evidence sufficiency | `EvidenceChecker` (adjacent chunks, second search, need types quantity / date / requirement / eligibility / procedure) exists, **off**. The evidence class comes from the model's own META self-report | sources → class | — | **no deterministic gate**: whether to answer is decided by the LLM. When no source passes, the LLM is still called ("could not verify") | — | missing / invalid META → "partial" | `test_evidence_sufficiency.py` | deterministic gate before generation (Phase 6) |
| 12 | Generation | `_generate`: `system_v2`, sources as `[n]` blocks with title / organisation / URL / language / verified / published / valid-until / deadline / "may be outdated"; Gemini 3.6 Flash primary, 3.5 Flash-Lite fallback, thinking low, ≤ 2,048 output tokens | sources + question → answer + META | per-answer Gemini cost (RC COST-EVALUATION.md); budgets and emergency stop (migration 0018) | quality **unmeasured for Gemini** (only Qwen 2.5 7B locally) | passages are wrapped and stripped of tags (`_untagged`); system prompt marked confidential | LLM error → fallback with sources | assistant suites (mocked) | Phase 9 (capped, owner-approved run) |
| 13 | Post-generation checks | `_attribute`, `_validate_answer` (removes invalid `[n]`, links not in the sources, **sentences whose figures appear in no source**), `_fix_script_mixing`, `_unverified` (second look, local models only), `_leaks_prompt`, `_wrong_language`, citation presence | answer → checked answer or fallback | none | the figure check accepts a number found in **any** source, not in the cited one; no claim-level support check; one bounded retry only for wrong language | — | fallback message + sources | `test_assistant*.py`, `test_citation_links.py` | per-citation support validator (Phase 7) |
| 14 | Monitoring | `rag_health.py` (index / model consistency), usage and budget tables (0018), structured logs of tokens and latency | — | — | **no retrieval-quality monitoring, no regression script** | admin-only views | — | rag_health tests | Phase 11 |
| 15 | Evaluation tooling before v2 | `rag_research_eval.py`, `rag_lab.py`, answer benchmark | — | — | question-level bootstrap (the 5 language versions of a need counted as independent → intervals too narrow: VALIDATION lenient MRR 0.735, question-level [0.660, 0.803] vs need-level [0.635, 0.825], one third wider); lenient labels only; no passage level; in-memory store only; random tie-breaks; the answer benchmark's synthetic documents made "0 % without sources" an artefact (invented figures cannot be known without the documents) | — | — | — | replaced by `scripts/rag_v2/` (this mission) |

## 3. Baseline numbers (measured, no LLM rewrite)

Production retrieval configuration (`configs.py: baseline`), document level, strict = the primary / grade-2 document,
lenient = any labelled document. Intervals resample information needs.

| Split | Store | hit@1 | hit@10 | MRR | MRR (lenient) | nDCG@10 | primary doc in model context | file |
|---|---|---|---|---|---|---|---|---|
| DEV (100 q, 20 needs) | memory | 0.69 | 0.97 | 0.782 | 0.853 | 0.820 | 0.90 | `E1seed1_dev_memory.json` |
| DEV | **PostgreSQL + pgvector** | 0.69 | 0.98 | 0.782 | 0.853 | 0.823 | 0.90 | `E2_dev_postgres.json` |
| VALIDATION (100 q, 20 needs) | memory | 0.52 | 0.95 | 0.656 | 0.735 | 0.753 | 0.80 | `E1seed1_val_memory.json` |
| VALIDATION | **PostgreSQL + pgvector** | 0.52 | 0.95 | 0.655 [0.536, 0.767] | 0.735 [0.635, 0.825] | 0.752 | 0.80 | `E2_val_postgres.json` |

Intervals: 95 %, resampling information needs.

- The lenient DEV numbers reproduce the RC result (`rag_research_dev.json`: R@1 0.75, R@10 0.99, MRR 0.848) within
  tie-break noise (0.76 / 0.99 / 0.853); nDCG differs because labels pointing outside the corpus (5) are now dropped.
- **Memory mirror vs real SQL:** same first-relevant rank for 98 / 100 questions on both splits; same top-5 documents
  95 / 100 (DEV) and 98 / 100 (VALIDATION); same context documents 92 / 95. The weighted hybrid computes its keyword
  evidence in Python over the candidates, so the mirror's simpler keyword leg matters little. It matters for the
  SQL-side legacy fusion (DEV hit@1 0.43 memory vs 0.35 PostgreSQL).
- **Tie-breaks:** three id seeds change the first relevant rank of 2 / 100 (DEV) and 1 / 100 (VALIDATION) questions;
  hit@1 varies by at most 0.01.
- Other configurations on PostgreSQL (DEV / VALIDATION MRR): vector only 0.620 / 0.575, keyword only 0.184 / 0.197,
  without the glossary bridge 0.752 / 0.666, legacy SQL fusion 0.517 / 0.465. Paired with the baseline (need-level
  95 % interval): vector −0.162 [−0.250, −0.081] / −0.080 [−0.167, 0.005]; no bridge −0.030 [−0.059, −0.001] /
  +0.011 [−0.019, 0.042]. The bridge helps DEV (where it was developed) and is neutral on VALIDATION.
- PostgreSQL 17.12, pgvector 0.8.1; index of 749 chunks built in 28 s; the two sample rows of the migrations
  (no embedding, not in production) were removed before indexing.

## 4. What the audit found, by severity

1. **Text loss in chunking** (stage 3): 58 % of the Korean guidebook and 13 % of the corpus never reach the index,
   although the documents are approved and shown in full in the Knowledge Center. Expected in production too: the
   snapshot's text is the production `extracted_text` and the chunker is the same (not verified in production, which
   was not touched).
2. **No deterministic evidence gate** (stage 11): answer / no-answer is the model's decision.
3. **Figure check not tied to the cited source** (stage 13).
4. **Unmeasured production path**: the Gemini rewrite and Gemini answers (blocked: no key, see BLOCKERS.md).
5. **Hub documents** take 61 % of the chunks and compete for the 4 source slots (stage 10); quantified in
   ERROR-ANALYSIS.md.
6. **Evaluation artefacts** (stage 15): too-narrow intervals, lenient-only labels, synthetic-document answer benchmark.

The visibility filter (stage 6) has no gap: unapproved, superseded, cancelled, archived, inactive-source and expired
content is unreachable from search, and only the service role can call it.
