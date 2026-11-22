"use client";

import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState, PageHeader } from "@/components/shared/states";
import { JobStatusBadge } from "@/components/shared/badges";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { NotificationItems, useNotifications } from "@/features/admin/notifications/notification-bell";
import { api } from "@/lib/api";
import { useApi } from "@/lib/use-api";
import { formatDateTime } from "@/lib/utils";
import type { Overview } from "@/types/api";

export function OverviewPage() {
  const t = useTranslations("admin.overview");
  const tn = useTranslations("admin.notifications");
  const locale = useLocale();
  const { data, error, loading, reload } = useApi<Overview>("admin-overview", () =>
    api.get<Overview>("/api/v1/admin/overview"),
  );
  const notes = useNotifications(5, null);

  return (
    <div>
      <PageHeader title={t("title")} description={t("subtitle")} />
      {loading && <LoadingState rows={3} />}
      {!loading && error && <ErrorState error={error} onRetry={reload} />}
      {data && (
        <div className="space-y-8">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
            <Stat label={t("sources")} value={data.sources_total} href="/admin/knowledge-sources" />
            <Stat label={t("failed")} value={data.sources_failed} href="/admin/knowledge-sources" tone={data.sources_failed ? "bad" : undefined} />
            <Stat label={t("pendingVersions")} value={data.versions_pending} href="/admin/review" tone={data.versions_pending ? "warn" : undefined} />
            <Stat label={t("pendingAnnouncements")} value={data.announcements_pending} href="/admin/review" tone={data.announcements_pending ? "warn" : undefined} />
            <Stat label={t("approvedDocs")} value={data.documents_approved} href="/admin/documents" />
          </div>

          <section aria-labelledby="notes-h" className="space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 id="notes-h" className="text-lg font-semibold">
                {t("notifications")}
              </h2>
              <Link href="/admin/rag-sync" className="text-sm text-primary hover:underline">
                {tn("viewAll")}
              </Link>
            </div>
            {notes.error != null && !notes.data ? (
              <ErrorState error={notes.error} onRetry={() => void notes.reload()} />
            ) : (
              <Card>
                <NotificationItems items={notes.data?.items ?? []} />
              </Card>
            )}
          </section>

          <section aria-labelledby="jobs-h" className="space-y-2">
            <h2 id="jobs-h" className="text-lg font-semibold">
              {t("recentJobs")}
            </h2>
            {data.recent_jobs.length === 0 ? (
              <EmptyState title={t("noJobs")} />
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t("source")}</TableHead>
                    <TableHead>{t("status")}</TableHead>
                    <TableHead>{t("when")}</TableHead>
                    <TableHead>{t("message")}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.recent_jobs.map((j) => (
                    <TableRow key={j.id}>
                      <TableCell>{j.source_title}</TableCell>
                      <TableCell>
                        <JobStatusBadge status={j.status} />
                      </TableCell>
                      <TableCell>{formatDateTime(j.completed_at ?? j.created_at, locale)}</TableCell>
                      <TableCell className="max-w-md break-words text-xs text-muted-foreground">
                        {j.error_message ?? j.outcome ?? "—"}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </section>

          <section aria-labelledby="audit-h" className="space-y-2">
            <h2 id="audit-h" className="text-lg font-semibold">
              {t("recentAudit")}
            </h2>
            {data.recent_audit.length === 0 ? (
              <EmptyState title={t("noAudit")} />
            ) : (
              <Card>
                <ul className="divide-y divide-border text-sm">
                  {data.recent_audit.map((a) => (
                    <li key={a.id} className="flex flex-wrap justify-between gap-2 p-3">
                      <span>
                        <code className="text-xs">{a.action}</code> · {a.entity_type} · {a.actor_name ?? a.actor_id ?? "—"}
                      </span>
                      <span className="text-xs text-muted-foreground">{formatDateTime(a.created_at, locale)}</span>
                    </li>
                  ))}
                </ul>
              </Card>
            )}
          </section>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, href, tone }: { label: string; value: number; href: string; tone?: "warn" | "bad" }) {
  return (
    <Link href={href} className="focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-xl">
      <Card className="h-full transition-shadow hover:shadow-md">
        <CardHeader className="pb-1">
          <CardTitle className="text-sm font-medium text-muted-foreground">{label}</CardTitle>
        </CardHeader>
        <CardContent>
          <p
            className={
              tone === "bad" ? "text-3xl font-bold text-red-700" : tone === "warn" ? "text-3xl font-bold text-amber-700" : "text-3xl font-bold"
            }
          >
            {value}
          </p>
        </CardContent>
      </Card>
    </Link>
  );
}
