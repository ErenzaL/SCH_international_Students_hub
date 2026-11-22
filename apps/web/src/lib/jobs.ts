import { api } from "@/lib/api";
import type { Job } from "@/types/api";

export const JOB_POLL_INTERVAL_MS = 2000;
const MAX_POLLS = 300; // ~10 minutes at 2s

const sleep = (ms: number, signal?: AbortSignal) =>
  new Promise<void>((resolve, reject) => {
    const t = setTimeout(resolve, ms);
    signal?.addEventListener("abort", () => {
      clearTimeout(t);
      reject(new DOMException("Aborted", "AbortError"));
    });
  });

/** Poll an ingestion job until it reaches a terminal state (succeeded/failed). */
export async function waitForJob(
  jobId: string,
  opts: { signal?: AbortSignal; intervalMs?: number; onUpdate?: (job: Job) => void } = {},
): Promise<Job> {
  const interval = opts.intervalMs ?? JOB_POLL_INTERVAL_MS;
  for (let i = 0; i < MAX_POLLS; i++) {
    const job = await api.get<Job>(`/api/v1/admin/ingestion-jobs/${encodeURIComponent(jobId)}`);
    opts.onUpdate?.(job);
    if (job.status === "succeeded" || job.status === "failed") return job;
    await sleep(interval, opts.signal);
  }
  throw new Error("Timed out while waiting for the ingestion job.");
}
