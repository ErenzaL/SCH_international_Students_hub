# Fallback: offloading heavy document indexing (design, not built)

For the case that the hosted memory test on staging ([STAGING.md](../owner/STAGING.md#5-verify-on-your-computer)) shows that the free Render
instance (512 MB, 0.1 CPU) is not enough. Zero cost throughout; nothing here changes production without approval.

## Where the memory goes (measured, [RENDER-MEMORY.md](RENDER-MEMORY.md))

| Part | MB | Can it leave Render? |
|---|---|---|
| API without the model | ~85–100 | no |
| Embedding model (int8 e5-small) and its runtime | ~200–220 | no: every search embeds the question |
| Indexing working set (long documents, embedding batches, chunk lists) | up to ~140 above idle | **yes** (option A) |
| PDF extraction child process (PyMuPDF) | up to ~140 for large files | **yes, with a policy decision** (option B) |

So offloading can save about 140 MB at the peak, never the ~300 MB the API needs to answer searches.

## Triggers (from `scripts/staging_memory_check.py` on staging, with `MALLOC_ARENA_MAX=2`)

| Result | Then |
|---|---|
| all PASS | nothing; keep the limits below |
| peak memory WARN (470–512 MB) or recovery WARN | stage 0 |
| any out-of-memory kill, restart, FAIL on peak memory, or a PDF job failing with an extraction timeout | stage 0, then option A; option B only if PDFs are the cause and you approve it |
| `/health` p95 above 5 s while indexing (CPU, not memory) | option A (the embedding is the CPU-heavy part) |

## Stage 0: limits in place (no new infrastructure)

Already done: one ingestion job at a time (`INGESTION_MAX_CONCURRENT_JOBS=1`), batch 1, at most two ONNX threads, `MALLOC_ARENA_MAX=2`, PDF
extraction in a child process with a timeout (a kill fails the job, not the API). Next, each a small change with a test, in this order:

1. `EMBEDDING_THREADS=1` (environment only): fewer buffers, slower indexing.
2. `PDF_MAX_PAGES` lower on the free plan (today 300) and `MAX_UPLOAD_MB` (today 10): a clear message to split the file instead of a killed job.
3. Return freed memory to the system after each job (`malloc_trim(0)`, Linux only): lowers the plateau between jobs, not the peak.
4. Extract large PDFs in page ranges inside the child and write the text out as it goes, so the child never holds the whole document.

## Option A (recommended next): approved text is embedded by the existing outbound worker

Reuses the GPU worker design ([docs/gpu-worker.md](../gpu-worker.md)): the worker calls the Hub over HTTPS, nothing connects to it, credentials
only work on claim / heartbeat / complete / fail, leases and idempotent results. Only **approved** text leaves Render, as today.

1. **Routing.** `index_version` jobs of versions with more than N chunks (setting, e.g. 150) get `executor = gpu`, if a worker was seen in the
   last 10 minutes; otherwise they run locally as today. Off by default (`GPU_WORKER_JOB_TYPES` gains `index_version` only when you enable it).
2. **Claim payload.** Version id, chunk ids and chunk texts (the approved text), the model id `intfloat/multilingual-e5-small#qint8` and the
   SHA-256 of the model file. No student data, no secrets.
3. **Worker.** Same int8 ONNX file (checked by hash), same `passage: ` prefix and normalisation as the API; returns one 384-number vector per
   chunk, the model id and the file hash. A CPU is enough; no GPU needed.
4. **The API checks before storing:** chunk count and ids match; 384 finite numbers; length 1 ± 0.01; model id and file hash equal its own. Then
   it embeds **two random chunks itself** and requires cosine ≥ 0.995 with the worker's vectors; otherwise the result is discarded and the
   job runs locally. Only then the normal activation path runs (store vectors, activate, the existing RAG health check).
5. **Failure.** Lease expires → the job returns to the queue (existing). The existing sweep fails GPU jobs that waited longer than
   `GPU_WORKER_MAX_QUEUE_HOURS`, or hands them to the server's own model only for translations (`GPU_WORKER_ON_EXPIRY=local`); for
   `index_version` it must be extended to **always** hand the job back to local execution after about 30 minutes (indexing needs no language
   model), so nothing waits forever. Re-indexing a version is idempotent.

**Where the worker can run, all $0:** the university server (the existing worker; needs the same university IT approval as before), an
administrator's computer while it is on, or a GitHub Actions run started by hand (free minutes for a public repository; the logs are public, so
the worker prints counts only; the worker token is an Actions secret that works on four endpoints only).
**Saves** the indexing working set (~140 MB peak) and most of the CPU time of indexing on Render. Effort: about two days with tests.

## Option B (only with your approval): PDF extraction by the same worker

For uploads above a size threshold. The API puts a signed Storage link valid for 10 minutes into the claim; the worker extracts with the same
PyMuPDF version and the same page / time limits and returns plain text and page statistics; personal-data redaction, normalisation and chunking
stay in the API. **This sends files that nobody has reviewed yet off Render**, which the worker's rule ("only approved content leaves") forbids
today. It needs your decision and, for the university server, university IT's. Saves the extraction child (~140 MB for large files).

## Not chosen

| Alternative | Why not |
|---|---|
| a paid Render instance | not allowed: no payment |
| a second free Render service as indexing worker | same 512 MB per service, uses the same 750 free hours, sleeps after 15 minutes and must be woken |
| a smaller or different embedding model | changes every search result; needs a full retrieval re-evaluation and re-indexing |
| embedding in the browser | approved content must not depend on an administrator's browser; mixed model builds |
