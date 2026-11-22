"use client";

import { useTranslations } from "next-intl";
import { AlertTriangle, RotateCcw } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { jobStageKey, progressPercent } from "@/lib/job-progress";
import type { Job } from "@/types/api";

/** Live stage / progress / liveness of an ingestion job, and per-stage timings once it has run. */
export function JobProgress({ job, compact = false }: { job: Job; compact?: boolean }) {
  const t = useTranslations("admin.ks.progress");
  const running = job.status === "running" || job.status === "queued";
  const pct = progressPercent(job.progress);
  const stageLabel = job.stage ? t(`stage.${jobStageKey(job.stage)}`) : null;

  if (compact) {
    if (!running) return null;
    return (
      <span className="block text-xs text-muted-foreground" data-testid="job-progress-compact">
        {stageLabel ?? t("waitingForWorker")}
        {job.progress && job.progress.total > 0 && ` · ${t("pages", { done: job.progress.done, total: job.progress.total })}`}
        {job.stale && <span className="block font-medium text-amber-800 dark:text-amber-300">{t("staleShort")}</span>}
      </span>
    );
  }

  return (
    <div className="space-y-2 text-xs" data-testid="job-progress">
      {running && (
        <div className="space-y-1">
          <p>
            <span className="font-medium">{stageLabel ?? t("waitingForWorker")}</span>
            {job.progress && job.progress.total > 0 && <> · {t("pages", { done: job.progress.done, total: job.progress.total })}</>}
            {job.heartbeat_age_seconds != null && (
              <span className="text-muted-foreground"> · {t("lastSignal", { seconds: job.heartbeat_age_seconds })}</span>
            )}
          </p>
          {pct != null && (
            <div className="h-1.5 w-full max-w-sm overflow-hidden rounded bg-muted" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}>
              <div className="h-full bg-primary transition-all" style={{ width: `${pct}%` }} />
            </div>
          )}
        </div>
      )}
      {job.stale && (
        <Alert variant="warning">
          <AlertTriangle className="size-4" aria-hidden />
          <AlertDescription>{t("staleLong", { attempt: job.attempts ?? 1, max: job.max_attempts ?? 3 })}</AlertDescription>
        </Alert>
      )}
      {job.resumed_from_stage && (
        <p className="flex items-center gap-1 text-amber-800 dark:text-amber-300">
          <RotateCcw className="size-3" aria-hidden />
          {t("resumed", { stage: t(`stage.${jobStageKey(job.resumed_from_stage)}`), attempt: job.attempts ?? 2 })}
        </p>
      )}
      {job.pdf && (
        <p className="text-muted-foreground">
          {t("pdfSummary", {
            pages: job.pdf.pages ?? 0,
            text: job.pdf.pages_with_text ?? 0,
            ocr: job.pdf.needs_ocr_pages ?? 0,
            korean: Math.round((job.pdf.hangul_ratio ?? 0) * 100),
          })}
        </p>
      )}
      {(job.stages ?? []).length > 0 && (
        <ol className="flex flex-wrap gap-x-3 gap-y-1 text-muted-foreground" aria-label={t("timings")}>
          {(job.stages ?? []).map((s, i) => (
            <li key={`${s.stage}-${i}`} className={s.ok ? "" : "font-medium text-destructive"}>
              {t(`stage.${jobStageKey(s.stage)}`)} {formatMs(s.ms)}
              {!s.ok && s.error ? ` (${s.error})` : ""}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function formatMs(ms: number): string {
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)} s`;
}
