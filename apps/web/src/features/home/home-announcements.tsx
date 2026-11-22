"use client";

import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { CalendarClock } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/shared/states";
import { AnnouncementCard } from "@/features/announcements/announcement-card";
import { api } from "@/lib/api";
import { useApi } from "@/lib/use-api";
import { formatDate } from "@/lib/utils";
import type { AnnouncementSummary, Page } from "@/types/api";

/** One request feeds both "Latest announcements" and "Important deadlines". */
export function HomeAnnouncements() {
  const t = useTranslations("home");
  const locale = useLocale();
  const { data, error, loading, reload } = useApi<Page<AnnouncementSummary>>("home-announcements", () =>
    api.get<Page<AnnouncementSummary>>("/api/v1/announcements", { status: "active", page_size: 20 }),
  );

  const latest = data?.items.slice(0, 3) ?? [];
  const deadlines = (data?.items ?? [])
    .filter((a) => a.deadline)
    .sort((a, b) => (a.deadline! < b.deadline! ? -1 : 1))
    .slice(0, 5);

  return (
    <>
      <section aria-labelledby="latest-h" className="mx-auto max-w-6xl px-4 pt-14">
        <div className="mb-4 flex items-end justify-between gap-3">
          <h2 id="latest-h" className="text-xl font-bold md:text-2xl">
            {t("latestTitle")}
          </h2>
          <Button asChild variant="link">
            <Link href="/announcements">{t("viewAll")}</Link>
          </Button>
        </div>
        {loading && <LoadingState rows={2} />}
        {!loading && error && <ErrorState error={error} onRetry={reload} />}
        {!loading && !error && latest.length === 0 && (
          <EmptyState title={t("latestEmptyTitle")} description={t("latestEmptyBody")} />
        )}
        {latest.length > 0 && (
          <ul className="grid gap-4 md:grid-cols-3">
            {latest.map((a) => (
              <li key={a.id}>
                <AnnouncementCard announcement={a} />
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="deadlines-h" className="mx-auto max-w-6xl px-4 pt-14">
        <h2 id="deadlines-h" className="mb-4 flex items-center gap-2 text-xl font-bold md:text-2xl">
          <CalendarClock className="size-6 text-primary" aria-hidden /> {t("deadlinesTitle")}
        </h2>
        {loading && <LoadingState rows={2} />}
        {!loading && error && <ErrorState error={error} onRetry={reload} />}
        {!loading && !error && deadlines.length === 0 && (
          <EmptyState title={t("deadlinesEmptyTitle")} description={t("deadlinesEmptyBody")} />
        )}
        {deadlines.length > 0 && (
          <Card>
            <ul className="divide-y divide-border">
              {deadlines.map((a) => (
                <li key={a.id}>
                  <Link
                    href={`/announcements/${a.id}`}
                    className="flex flex-wrap items-center justify-between gap-2 p-4 hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <span className="font-medium">{a.title}</span>
                    <span className="text-sm font-semibold text-primary">
                      {t("dueOn", { date: formatDate(a.deadline, locale) })}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </Card>
        )}
      </section>
    </>
  );
}
