# Render-equivalent memory test (free plan: 512 MB, 0.1 CPU)

Measured 2026-11-26 on the university test computer (Linux, Python 3.11, int8 ONNX e5-small, no language model). Synthetic and public data only;
loopback only. Raw results: `scripts/benchmarks/results/render_like_*.json`.

## Verdict

- **Without a change the API does not reliably fit.** At 0.1 CPU, indexing the 27 public documents was killed at 512 MB (run `free`); a second
  run with the limit lifted peaked at 485 MB PSS / **540 MB RSS** (`slow_peak`). Unthrottled, the same work peaked at 476 MB (`unlimited`), so
  tests on a fast computer understate the free plan.
- **With `MALLOC_ARENA_MAX=2` it fits**: peak 457 MB PSS / 491 MB RSS, all ten phases passed (`slow_peak_arena2`). Memory after work is much
  lower: 312 MB instead of 422 MB after the 9 MB PDF, 336 MB instead of 432 MB at the end.
- The margin is still modest (about 50 MB PSS, about 20 MB RSS), and run-to-run spread was 485 → ≥512 MB without the setting. The staging test
  in [STAGING.md](../owner/STAGING.md#4-test) confirms it on real Render before production gets it.
- **The web service fits easily**: peak 205 MB under the same limits, ready in 7.9 s, 30 parallel page requests in 6.2 s, all 200.

## Why the slow CPU uses more memory

The API is one process with several threads (requests, the ingestion worker, the agent worker, a heartbeat ticker per job, two ONNX threads). The
ONNX session runs without its own memory arena (freed after each run), so its buffers go through glibc `malloc`, which gives busy threads their
own arenas (up to 8 per CPU). At 0.1 CPU the threads overlap far longer (indexing took 1,100 s instead of 51 s), more arenas are in use at the
same time and freed memory stays fragmented across them. `MALLOC_ARENA_MAX=2` caps the arenas; it is a glibc environment variable read at
process start: no code, no cost. The PDF extraction child process inherits it.

## Results

Peak memory per phase, MB (proportional set size of the API process tree).

| Phase | unlimited, 1 CPU | `free` 512 MB, 0.1 CPU | `slow_peak` 0.1 CPU | `slow_peak_arena2` 0.1 CPU, `MALLOC_ARENA_MAX=2` |
|---|---|---|---|---|
| Cold start (to `/health`) | 1.0 s | 14.3 s | 20.4 s | 20.4 s |
| Idle after start | 98 | 98 | 86 | 85 |
| First search (loads the model) | 312 (1.5 s) | 323 (13.1 s) | 309 (16.1 s) | 318 (16.3 s) |
| Index the 27 public documents | 452 (51 s) | **killed at 512** (460 s) | 485 (1,102 s) | 459 (1,118 s) |
| 3 MB Korean PDF (85,037 characters) | 430 (21 s) | — | 465 (523 s) | 367 (530 s) |
| 9 MB Korean PDF (255,954 characters) | 465 (61 s) | — | 485 (1,382 s) | 369 (1,382 s) |
| 40 searches, 10 in parallel | 415 (1.9 s) | — | 431 (35.5 s) | 336 (31.5 s) |
| Chat without a model, agent tools, a background task | 416 | — | 433 | 336 |
| **Server peak PSS / RSS** | 476 / 496 | 512 / 523 (killed) | 485 / **540** | **457 / 491** |

The `slow_peak` runs had the limit lifted to 4,096 MB so the true peak was recorded; they ran side by side on separate cores with separate
databases. Times at 0.1 CPU are what users of the free plan will see: a search after the model is loaded takes 0.6–1.7 s; the first search after
a wake-up takes 13–16 s extra (model load), on top of Render's wake-up of about a minute.

## Method and its limits

`scripts/render_like.py` runs a command with a memory and CPU budget, without root or containers (none are available on the test computer):

- **Memory:** every 0.2 s the proportional set size (PSS) of the whole process tree is read from `/proc/*/smaps_rollup`; above the limit the
  tree is killed, like the out-of-memory killer. Render's container charges something between PSS and RSS: RSS counts shared libraries in full,
  and page cache can be reclaimed before a kill. Both are reported; treat RSS as the cautious figure.
- **CPU:** the process group gets 10 ms of every 100 ms (SIGCONT/SIGSTOP; measured 0.094 CPU) and is pinned to one core with `taskset`. Render
  throttles more smoothly, so timings are approximate; memory is what matters here.
- **Not modelled:** Supabase over the internet (here a local PostgreSQL + PostgREST), Gemini answers (`--llm none`), and Render's wake-up.

`scripts/render_memory_test.py` is the workload: idle, model load, a repeat search, indexing of the public corpus, upload + extraction + indexing
of synthetic Korean PDFs with images (made with PyMuPDF, invented text), 40 searches 10 at a time, chat without a model, agent tools and an
`event_digest` task, idle. It records time and memory before, during and after each phase and whether the server is still alive.

Reproduce (about 55 minutes per run at 0.1 CPU; two can run side by side):

```bash
PG_BIN=<postgres with pgvector>/bin POSTGREST=<postgrest> PY=backend/.venv/bin/python WORK=<private dir> \
  scripts/render_memory_run.sh 512 0.1 free 7 1                          # as on Render: killed above 512 MB
PG_BIN=... POSTGREST=... PY=... WORK=... scripts/render_memory_run.sh 4096 0.1 slow_peak_arena2 6 2 MALLOC_ARENA_MAX=2   # true peak
```

## Recommendations

1. **Set `MALLOC_ARENA_MAX=2` on the API** (added to `render.yaml`; on the existing service it must be added under Environment by hand: owner
   action, it restarts the service). Staging first.
2. **Measure on staging** (same plan, $0) with `scripts/staging_memory_check.py` ([STAGING.md](../owner/STAGING.md) step 5): synthetic PDFs and
   texts uploaded at once, then responsiveness, restarts, out-of-memory kills, peak, recovery and stuck work from the read-only
   `GET /api/v1/admin/system/runtime` (process and container memory, an id that changes on every restart, ingestion slots, stale jobs).
   At most `INGESTION_MAX_CONCURRENT_JOBS` (default 1) ingestion jobs run at once in a process, also in inline mode. If it fails:
   [INDEXING-OFFLOAD.md](INDEXING-OFFLOAD.md).
3. Keep `EMBEDDING_ONNX_BATCH_SIZE=1` and `EMBEDDING_THREADS=0` (at most two threads). A reranker (about 120 MB more) does not fit beside this
   ([KOREAN-RETRIEVAL.md](KOREAN-RETRIEVAL.md)).
4. Index large uploads one at a time; at 0.1 CPU a 9 MB PDF takes about 25 minutes. A killed job is picked up again after the restart.
5. If memory is still tight on staging, the next steps that cost nothing are: `EMBEDDING_THREADS=1` (fewer arenas and buffers, slower), or
   calling `malloc_trim` after each job (a small code change, not made: not needed in the measurements).
