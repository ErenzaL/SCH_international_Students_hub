"use client";

import { useLocale, useTranslations } from "next-intl";
import { Card, CardContent } from "@/components/ui/card";
import { ErrorState, LoadingState } from "@/components/shared/states";
import { api } from "@/lib/api";
import { useApi } from "@/lib/use-api";
import { formatDateTime } from "@/lib/utils";
import type { KnowledgeStats } from "@/types/api";

/** Real database counts (GET /admin/knowledge/stats). Nothing is estimated. */
export function KnowledgeStatsCards({ refreshKey }: { refreshKey: number }) {
  const t = useTranslations("admin.ks.statsCards");
  const locale = useLocale();
  const { data, error, loading, reload } = useApi<KnowledgeStats>(`ks-stats:${refreshKey}`, () =>
    api.get<KnowledgeStats>("/api/v1/admin/knowledge/stats"),
  );
  if (loading && !data) return <LoadingState rows={1} />;
  if (error) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return null;
  const cards: { label: string; value: string | number; hint?: string; tone?: string }[] = [
    { label: t("total"), value: data.sources_total },
    { label: t("active"), value: data.sources_active },
    { label: t("pending"), value: data.versions_pending, hint: t("drafts", { count: data.versions_draft }), tone: data.versions_pending ? "text-amber-800" : undefined },
    { label: t("approved"), value: data.documents_approved },
    { label: t("failedJobs"), value: data.jobs_failed, hint: t("failedSources", { count: data.sources_failed }), tone: data.jobs_failed ? "text-red-700" : undefined },
    { label: t("chunks"), value: data.searchable_chunks, hint: data.embedding_model },
    { label: t("latestSync"), value: formatDateTime(data.latest_success_at, locale), hint: t("queued", { count: data.jobs_queued }) },
    {
      label: t("ocr"),
      value: data.ocr_available ? data.ocr_provider : t("ocrOff"),
      hint: data.ocr_available ? undefined : (data.ocr_reason ?? undefined),
      tone: data.ocr_available ? undefined : "text-muted-foreground",
    },
  ];
  return (
    <ul className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-4" aria-label={t("label")}>
      {cards.map((c) => (
        <li key={c.label}>
          <Card className="h-full">
            <CardContent className="p-4">
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{c.label}</p>
              <p className={`mt-1 text-xl font-semibold ${c.tone ?? ""}`}>{c.value}</p>
              {c.hint && <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">{c.hint}</p>}
            </CardContent>
          </Card>
        </li>
      ))}
    </ul>
  );
}
