# Performance

Two different machines, never mixed: the **university workstation** (RTX 4070 12 GB, 20 CPU threads, 31 GB RAM; development and GPU work)
and **Render-like limits emulated on that workstation** (512 MB, 0.1 CPU via `scripts/render_like.py`). Real hosted Render latency was
**not measured** in this work (no staging service exists yet; FINAL-SETUP-CHECKLIST §3.1).

## 1. Retrieval (workstation CPU, in-process, held-out questions)

| Configuration | p50 | p95 | max |
|---|---|---|---|
| vector only | 22 ms | 23 ms | 24 ms |
| hybrid (production) | 107 ms | 127 ms | 145 ms |

The production hybrid issues up to three dense queries (question + concept bridge) plus a keyword query. Earlier measured on the Render-like
0.1 CPU limit: a search takes 0.6–1.7 s once the model is loaded; the first search after a wake-up adds 13–16 s (model load) on top of
Render's own wake-up of about a minute ([RENDER-MEMORY.md](../development/RENDER-MEMORY.md)).

## 2. Answer generation (local Qwen 2.5 7B on the GPU; Gemini NOT measured)

| Mode | Median | p95 | Model calls per answer |
|---|---|---|---|
| Qwen 2.5 7B + RAG (rewrite, answer, second look) | 2.2 s | 2.9 s | 2.9 |
| excerpts only | 20 ms | 28 ms | 0 |

Workstation GPU, warm model. With Gemini in production the second look is skipped and the time is dominated by Gemini's latency plus the
free Render CPU (not measured).

## 3. Announcement translation (TranslateGemma 12B / Qwen 2.5 7B on the RTX 4070)

| Model | Median per notice | p95 | Max | GPU memory | Power (median) |
|---|---|---|---|---|---|
| TranslateGemma 12B (development, 52 drafts) | 8.8 s | 27.8 s | 34.9 s | 9.7 GB | ≈ 200 W |
| TranslateGemma 12B (held-out, 20 drafts) | 7.7 s | 20.8 s | 25.5 s | 9.7 GB | – |
| Qwen 2.5 7B (development) | 5.7 s | 16.8 s | 21.8 s | 5.6 GB | – |
| TranslateGemma 4B (development, native) | 2.9 s | 6.0 s | 6.8 s | 8.4 GB | – |

A notice includes its title and up to two repair passes. Throughput at the 12B median: about **400 notice translations per hour**; a week of
SCH notices (tens) takes minutes. Model size on disk: 8.1 GB (12B), 3.3 GB (4B), 4.7 GB (Qwen).

## 4. Memory on the free plan (512 MB, 0.1 CPU), emulated

MEMORY_PLACEHOLDER

## 5. Database growth and indexing

Measured earlier on the local database: about **35 KB per 1,000 indexed characters** (vectors and their index are most of it); the 27
public documents (373,000 characters) took 13 MB and indexed in 20 s on the workstation, about 1,100 s at 0.1 CPU. Migration 0018 adds at
most one row per day, lane, model and purpose (a few hundred rows a year) and one counter row per budget and day.

## 6. Queue latency and failure behaviour

Background jobs are durable rows claimed atomically (`claim_*` RPCs with leases and heartbeats). Tested behaviour, not timed under load:
a dead worker's job is re-queued after its lease; quota or budget exhaustion defers jobs (24 deferrals at most, then a visible failure);
the emergency stop defers them hourly; a model outage gives students the cited sources instead of an answer
(`test_r_s_both_models_unavailable_gives_a_localized_message_and_sources_only`).

## 7. What is too heavy for the free plan

* Local LLMs (TranslateGemma, Qwen): never on Render; the school PC is optional and production never waits for it.
* The cross-encoder reranker (+~120 MB): off.
* Indexing very large PDFs at 0.1 CPU: works with `MALLOC_ARENA_MAX=2` but slowly (minutes); ingestion concurrency is 1.
