# GPU and Qwen evaluation

Measured 2026-11-25 on NVIDIA GeForce RTX 4070 (12282 MiB), `qwen2.5:7b-instruct` in Ollama on 127.0.0.1:11434. Files: `scripts/benchmarks/results/`.

| | |
|---|---|
| GPU memory with the model loaded | 5135 MiB; utilisation 98 % while generating |
| Speed | 97.0 tokens/s; three requests at once: 96.1 tokens/s together (they queue) |
| Cold load | 2.2 s when the file is in the disk cache |
| RAG answers | median 2.1 s, p95 2.9 s; correct 92–93 % on the synthetic benchmark ([RAG-EVALUATION.md](RAG-EVALUATION.md)) |
| RAG answers on the real public documents, whole request | 3.6–8.2 s (longer sources) |
| Translation draft, short notice | 1.6 s through the worker (including claim and hand-in) |
| Summaries (16) | 97 % of figures kept, 0 with an invented figure |
| Structured extraction (10 notices, JSON schema) | valid JSON 100 %, deadline 90 %, amount 90 % |
| the Hub's deterministic deadline extractor | 80 % (it takes every stated period; used because it never invents) |
| Category (9 classes) | 59 %: **not good enough**, rules are kept |
| Tool choice (20 requests, 7 tools) | 85 %; it failed on 2 of 3 requests for a **human**: routing stays deterministic |
| Translation benchmarks on real notices | earlier results in [ollama.md](../ollama.md); serious errors (offices, dormitories, exemptions) are why every draft needs a reviewer |

**End to end with the real model:** `e2e_gpu_worker.py` 20/20 (drafts in four languages, summary, killed worker, SIGTERM, Hub offline, cancel, pause, rotation, revocation, logs)
and the browser journey 12/12 (token shown once → request at Minh's desk → worker → `needs_review` → Vietnamese reviewer → public; Indonesian reviewer gets 403).

**Qwen and Gemini:** Gemini was **not** measured here (no key). Nothing says Qwen is better. Gemini stays the live provider.

| Used for | How |
|---|---|
| Development chat | `LLM_PROVIDER=ollama` (loopback only, never on Render) |
| Reviewed translation drafts and summaries | outbound worker, leased jobs, always `needs_review` |
| Not used | private questions, support requests, live student traffic, publishing |

Production activation: [GPU-SETUP.md](../owner/GPU-SETUP.md) (migration 0016, flag, token, IT consent, reviewers). Real-time gateway: [assessment](../gpu-gateway-assessment.md) only.

## API performance (real PostgreSQL on this computer; Render will be slower)

27 documents, 372979 characters indexed in 20.4 s. Memory 108 MB at start, 391 MB with the embedding model, 410 MB at the end.
Database +12 MB (35 KB per 1,000 characters). 60 searches, 10 at a time: 1.7 s, 0 failed.

| Endpoint | p50 ms | p95 ms |
|---|---|---|
| health | 3.7 | 7.0 |
| categories | 34.3 | 37.3 |
| announcements | 50.3 | 55.3 |
| documents | 25.8 | 41.8 |
| agents | 113.1 | 117.3 |
| search_first | 60.8 | 101.2 |
| search_again | 56.2 | 91.4 |
| agent_tool | 30.3 | 30.8 |
| admin_operations | 206.4 | 217.5 |
| admin_storage | 52.5 | 79.9 |

Budgets: search p95 below 300 ms, pages below 500 ms, API memory below 480 MB of 512 MB (met here; large PDF uploads can exceed it).
