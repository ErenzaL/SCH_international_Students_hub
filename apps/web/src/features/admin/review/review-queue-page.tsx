"use client";

import { useState } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Tabs } from "@/components/ui/tabs";
import { EmptyState, ErrorState, LoadingState, PageHeader } from "@/components/shared/states";
import { api } from "@/lib/api";
import { useApi } from "@/lib/use-api";
import { formatDate } from "@/lib/utils";
import type { AdminAnnouncement, DocumentItem, Page } from "@/types/api";

export function ReviewQueuePage() {
  const t = useTranslations("admin.queue");
  const locale = useLocale();
  const [tab, setTab] = useState<"pending_review" | "draft">("pending_review");
  const docs = useApi<Page<DocumentItem>>(`queue-docs:${tab}`, () =>
    api.get<Page<DocumentItem>>("/api/v1/admin/documents", { review_status: tab, page_size: 100 }),
  );
  const anns = useApi<Page<AdminAnnouncement>>("queue-anns", () =>
    api.get<Page<AdminAnnouncement>>("/api/v1/admin/announcements", { status: "pending_approval", page_size: 100 }),
  );

  return (
    <div className="space-y-8">
      <PageHeader
        title={t("title")}
        description={t("subtitle")}
        actions={
          <Link href="/admin/rag-sync" className="text-sm text-primary hover:underline">
            {t("ragSyncLink")}
          </Link>
        }
      />

      <section aria-labelledby="q-docs" className="space-y-2">
        <h2 id="q-docs" className="text-lg font-semibold">
          {t("documents")}
        </h2>
        <Tabs
          label={t("documents")}
          value={tab}
          onChange={(id) => setTab(id as "pending_review" | "draft")}
          items={[{ id: "pending_review", label: t("tabPending") }, { id: "draft", label: t("tabDrafts") }]}
        />
        {docs.loading && <LoadingState rows={2} />}
        {docs.error && <ErrorState error={docs.error} onRetry={docs.reload} />}
        {docs.data && docs.data.items.length === 0 && <EmptyState title={t("noDocs")} />}
        {docs.data && docs.data.items.length > 0 && (
          <Card>
            <ul className="divide-y divide-border">
              {docs.data.items.map((d) => (
                <li key={d.id}>
                  <Link href={`/admin/documents/${d.id}`} className="flex flex-wrap items-center justify-between gap-2 p-4 hover:bg-muted/50">
                    <span>
                      <span className="font-medium">{d.title}</span>
                      <span className="block text-xs text-muted-foreground">
                        {d.source_title} · {d.organization}
                        {d.source_type ? ` · ${d.source_type}` : ""}
                      </span>
                    </span>
                    <Badge variant={tab === "draft" ? "muted" : "warning"}>{tab === "draft" ? t("draftOpen") : t("reviewNow")}</Badge>
                  </Link>
                </li>
              ))}
            </ul>
          </Card>
        )}
      </section>

      <section aria-labelledby="q-anns" className="space-y-2">
        <h2 id="q-anns" className="text-lg font-semibold">
          {t("announcements")}
        </h2>
        {anns.loading && <LoadingState rows={2} />}
        {anns.error && <ErrorState error={anns.error} onRetry={anns.reload} />}
        {anns.data && anns.data.items.length === 0 && <EmptyState title={t("noAnnouncements")} />}
        {anns.data && anns.data.items.length > 0 && (
          <Card>
            <ul className="divide-y divide-border">
              {anns.data.items.map((a) => (
                <li key={a.id}>
                  <Link href={`/admin/announcements/${a.id}`} className="flex flex-wrap items-center justify-between gap-2 p-4 hover:bg-muted/50">
                    <span>
                      <span className="font-medium">{a.title}</span>
                      <span className="block text-xs text-muted-foreground">
                        {a.created_by_name ?? "—"} · {formatDate(a.submitted_at, locale)}
                      </span>
                    </span>
                    <Badge variant="warning">{t("reviewNow")}</Badge>
                  </Link>
                </li>
              ))}
            </ul>
          </Card>
        )}
      </section>
    </div>
  );
}
