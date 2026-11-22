/** Pure helpers for showing ingestion job progress. */
import type { Job } from "@/types/api";

export const KNOWN_STAGES = ["download", "validate", "extract", "ocr", "process", "fetch", "index", "translate"] as const;
export type StageKey = (typeof KNOWN_STAGES)[number] | "other";

export function jobStageKey(stage: string | null | undefined): StageKey {
  return (KNOWN_STAGES as readonly string[]).includes(stage ?? "") ? (stage as StageKey) : "other";
}

export function progressPercent(p: Job["progress"]): number | null {
  if (!p || !p.total || p.total <= 0) return null;
  return Math.max(0, Math.min(100, Math.round((p.done / p.total) * 100)));
}
