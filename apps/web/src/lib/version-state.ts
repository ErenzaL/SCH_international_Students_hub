import { api } from "@/lib/api";
import type { RagStatus, Version, VersionSummary } from "@/types/api";

/**
 * Human-facing state of a document version in the RAG lifecycle (see docs/api-contract.md, migration 0007):
 * pending review → approved & indexing → active (searchable), or indexing failed (previous version stays live).
 */
export type VersionState =
  | "draft"
  | "pending_review"
  | "indexing"
  | "index_failed"
  | "active"
  | "approved_inactive"
  | "superseded"
  | "rejected";

type Lifecycle = Pick<
  VersionSummary,
  "verification_status" | "is_current" | "indexing_status" | "activation_requested_at"
>;

export function versionState(v: Lifecycle): VersionState {
  switch (v.verification_status) {
    case "draft":
      return "draft";
    case "rejected":
      return "rejected";
    case "superseded":
      return "superseded";
    case "approved":
      return v.is_current ? "active" : "approved_inactive";
    case "pending_review":
      if (v.indexing_status === "failed" && v.activation_requested_at) return "index_failed";
      if (v.activation_requested_at || v.indexing_status === "queued" || v.indexing_status === "indexing") {
        return "indexing";
      }
      return "pending_review";
  }
}

export type ActivationOutcome = "active" | "failed" | "pending";

/** Polling stop condition after approval. */
export function activationOutcome(v: Lifecycle): ActivationOutcome {
  if (v.verification_status === "approved" && v.is_current) return "active";
  if (v.indexing_status === "failed") return "failed";
  if (v.verification_status !== "pending_review" && v.verification_status !== "approved") return "failed";
  return "pending";
}

export const ACTIVATION_POLL_MS = 3000;
export const ACTIVATION_MAX_MS = 3 * 60 * 1000;

/** Poll a version after approval until it is active, failed, or the time budget runs out ("pending"). */
export async function waitForActivation(
  versionId: string,
  opts: { intervalMs?: number; maxMs?: number; signal?: AbortSignal; onUpdate?: (v: Version) => void } = {},
): Promise<{ outcome: ActivationOutcome; version: Version | null }> {
  const interval = opts.intervalMs ?? ACTIVATION_POLL_MS;
  const deadline = Date.now() + (opts.maxMs ?? ACTIVATION_MAX_MS);
  let last: Version | null = null;
  while (Date.now() <= deadline) {
    if (opts.signal?.aborted) break;
    last = await api.get<Version>(`/api/v1/admin/versions/${encodeURIComponent(versionId)}`);
    opts.onUpdate?.(last);
    const outcome = activationOutcome(last);
    if (outcome !== "pending") return { outcome, version: last };
    await new Promise((r) => setTimeout(r, interval));
  }
  return { outcome: "pending", version: last };
}

/** Auto-refresh the RAG sync page only while work is in flight. */
export function ragHasActiveWork(status: Pick<RagStatus, "counts" | "queue"> | null | undefined): boolean {
  if (!status) return false;
  return (
    status.counts.waiting_for_indexing > 0 ||
    status.counts.indexing_now > 0 ||
    status.queue.some((q) => q.status === "queued" || q.status === "running")
  );
}

/** Compact relative time ("3 minutes ago") with Intl.RelativeTimeFormat. */
export function relativeTime(iso: string | null | undefined, locale = "en", now: number = Date.now()): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const diffSec = Math.round((then - now) / 1000);
  const fmt = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
  const abs = Math.abs(diffSec);
  if (abs < 45) return fmt.format(diffSec, "second");
  if (abs < 45 * 60) return fmt.format(Math.round(diffSec / 60), "minute");
  if (abs < 22 * 3600) return fmt.format(Math.round(diffSec / 3600), "hour");
  if (abs < 26 * 86400) return fmt.format(Math.round(diffSec / 86400), "day");
  if (abs < 320 * 86400) return fmt.format(Math.round(diffSec / (30 * 86400)), "month");
  return fmt.format(Math.round(diffSec / (365 * 86400)), "year");
}
