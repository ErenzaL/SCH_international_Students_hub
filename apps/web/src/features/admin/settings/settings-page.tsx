"use client";

import { useTranslations } from "next-intl";
import { Check, X } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { ErrorState, LoadingState, PageHeader } from "@/components/shared/states";
import { api } from "@/lib/api";
import { useApi } from "@/lib/use-api";
import type { AdminSettings } from "@/types/api";

export function SettingsPage() {
  const t = useTranslations("admin.settings");
  const { data, error, loading, reload } = useApi<AdminSettings>("admin-settings", () =>
    api.get<AdminSettings>("/api/v1/admin/settings"),
  );
  return (
    <div>
      <PageHeader title={t("title")} description={t("subtitle")} />
      {loading && <LoadingState rows={3} />}
      {!loading && error && <ErrorState error={error} onRetry={reload} />}
      {data && (
        <Card>
          <CardContent className="p-0">
            <dl className="divide-y divide-border text-sm">
              <Row label={t("supabase")}>
                {data.supabase_configured ? <Check className="size-4 text-emerald-700" aria-label="yes" /> : <X className="size-4 text-red-700" aria-label="no" />}
              </Row>
              <Row label={t("embeddingProvider")}>{data.embedding_provider}</Row>
              <Row label={t("embeddingModel")}>
                <code>{data.embedding_model}</code> ({data.embedding_dimensions}d)
              </Row>
              <Row label={t("allowedDomains")}>
                <ul className="flex flex-wrap gap-1">
                  {data.allowed_domains.map((d) => (
                    <li key={d} className="rounded bg-muted px-2 py-0.5 font-mono text-xs">
                      {d}
                    </li>
                  ))}
                </ul>
              </Row>
              <Row label={t("maxUpload")}>{data.max_upload_mb} MB</Row>
              <Row label={t("maxResponse")}>{data.max_response_mb} MB</Row>
              <Row label={t("llm")}>{data.llm_provider}</Row>
              <Row label={t("answerGeneration")}>{data.answer_generation}</Row>
              <Row label={t("rateLimits")}>
                <ul className="space-y-0.5 font-mono text-xs">
                  {Object.entries(data.rate_limits).map(([k, v]) => (
                    <li key={k}>
                      {k}: {String(v)}
                    </li>
                  ))}
                </ul>
              </Row>
            </dl>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-1 p-4 sm:grid-cols-[14rem_1fr]">
      <dt className="font-medium text-muted-foreground">{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}
