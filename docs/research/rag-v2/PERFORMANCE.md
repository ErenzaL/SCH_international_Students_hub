# Performance and memory

Measured on the school server (CPU for retrieval, RTX 4070 only for the local proxy model). **Not hosted numbers**: Render
free has 0.1 CPU and 512 MB. The RC's Render-like emulation (`docs/development/RENDER-MEMORY.md`) remains the reference
for absolute memory: API peak 457 MB PSS / 491 MB RSS with `MALLOC_ARENA_MAX=2`.

## 1. What the v2 changes cost (A/B, `scripts/rag_v2/perf_check.py`, `P1_perf_{rc,v2}.json`)

Two separate processes, identical workload: index the corpus (int8 e5), then 200 DEV + VAL questions through
`respond()` without an LLM.

| | RC settings | v2 settings (gate log, injection screen, hub cache) |
|---|---|---|
| peak RSS | 460 MB | 437 MB |
| RSS after the workload | 349 MB | 323 MB |
| `respond()` p50 / p95 | 110.0 / 127.5 ms | 109.9 / 127.3 ms |
| hub chunk-count cache | — | 3.5 KB |

The difference in RSS is run-to-run noise (the in-memory store holds all vectors in this process; production keeps them
in PostgreSQL). Per answer, the new deterministic steps cost **2 µs** (gate), **0.1 ms** (citation check) and
**0.7 ms** (injection screen over all selected passages). The code adds no model, no dependency and no thread.

## 2. Retrieval latency (in-process, school server)

| Stage | p50 | p95 | file |
|---|---|---|---|
| search, memory store | 105–116 ms | 123–129 ms | `E1seed1_*` |
| search, PostgreSQL + PostgREST over a Unix socket | 85–92 ms | 109 ms | `E2_*_postgres.json` |
| local rewrite (Qwen 2.5 7B on the GPU; production uses Gemini Flash-Lite over the network) | 0.8 s median | — | `rewrites_qwen2.5-7b.json` |

Query variants add one search per variant (up to 4 per turn); production already runs them when the rewrite succeeds.

## 3. Index size

| Chunker | chunks | change |
|---|---|---|
| v1 (release) | 749 | — |
| v2 | 782 | +4.4 % rows of `document_chunks` (384-d vectors in PostgreSQL, not in API memory) |

## 4. Excluded for memory reasons

A cross-encoder reranker (+≈ 120 MB) and larger embedding models do not fit next to the API in 512 MB
(RETRIEVAL-EXPERIMENTS §5). Nothing in v2 changes the memory budget.

## 5. Not measured

Hosted latency and memory (no staging service, BLOCKERS B3); Gemini latency (no key, B1).
