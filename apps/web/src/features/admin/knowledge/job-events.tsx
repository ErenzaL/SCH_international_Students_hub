"use client";

import { useLocale, useTranslations } from "next-intl";
import { ErrorState, LoadingState } from "@/components/shared/states";
import { api } from "@/lib/api";
import { useApi } from "@/lib/use-api";
import { cn, formatDateTime } from "@/lib/utils";
import type { JobEvent } from "@/types/api";

const LEVEL_CLASS: Record<JobEvent["level"], string> = {
  info: "text-foreground",
  warning: "text-amber-900",
  error: "text-red-800",
};

/** Step-by-step ingestion log of one job (GET /admin/ingestion-jobs/{id}/events). */
export function JobEvents({ jobId, refreshKey = 0 }: { jobId: string; refreshKey?: number | string }) {
  const t = useTranslations("admin.ks");
  const locale = useLocale();
  const { data, error, loading, reload } = useApi<{ items: JobEvent[] }>(`job-events:${jobId}:${refreshKey}`, () =>
    api.get<{ items: JobEvent[] }>(`/api/v1/admin/ingestion-jobs/${encodeURIComponent(jobId)}/events`),
  );
  if (loading && !data) return <LoadingState rows={1} />;
  if (error) return <ErrorState error={error} onRetry={reload} />;
  if (!data || data.items.length === 0) return <p className="text-xs text-muted-foreground">{t("noEvents")}</p>;
  return (
    <ol className="max-h-72 space-y-1 overflow-auto rounded-md border border-border bg-muted/40 p-2 font-mono text-xs" aria-label={t("eventLog")}>
      {data.items.map((ev) => (
        <li key={ev.id} className={cn("whitespace-pre-wrap", LEVEL_CLASS[ev.level])}>
          <span className="text-muted-foreground">{formatDateTime(ev.created_at, locale)}</span>{" "}
          <span className="font-semibold">[{ev.step}]</span> {ev.message}
        </li>
      ))}
    </ol>
  );
}
