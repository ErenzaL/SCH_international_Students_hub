"use client";

import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { CalendarClock, Users } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { AnnouncementStatusBadge, TestDataBadge } from "@/components/shared/badges";
import { useCategoryName } from "@/lib/use-category-name";
import { formatDate } from "@/lib/utils";
import { LOCALE_LABELS } from "@/lib/constants";
import type { AnnouncementSummary } from "@/types/api";

export function AnnouncementCard({
  announcement: a,
  layout = "card",
}: {
  announcement: AnnouncementSummary;
  layout?: "card" | "row";
}) {
  const t = useTranslations("announcements");
  const locale = useLocale();
  const categoryName = useCategoryName();

  return (
    <Card className="transition-shadow hover:shadow-md">
      <CardHeader className={layout === "row" ? "pb-2" : undefined}>
        <div className="flex flex-wrap items-center gap-2">
          <AnnouncementStatusBadge status={a.status} />
          <Badge variant="outline">{categoryName(a.category)}</Badge>
          {a.is_test_data && <TestDataBadge />}
        </div>
        <CardTitle className="mt-1 text-lg">
          <Link href={`/announcements/${a.id}`} lang={a.display_title ? locale : a.original_language}
            className="hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
            {a.display_title ?? a.title}
          </Link>
        </CardTitle>
        {a.display_title && (
          <p className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <span lang={a.original_language}>{a.title}</span>
            {a.display_title_status === "machine" && <Badge variant="warning">{t("machineTranslated")}</Badge>}
          </p>
        )}
      </CardHeader>
      <CardContent className="space-y-3">
        {a.excerpt && <p className="line-clamp-2 text-sm text-muted-foreground">{a.excerpt}</p>}
        <dl className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted-foreground">
          <div className="flex items-center gap-1">
            <dt className="sr-only">{t("published")}</dt>
            <dd>
              {t("published")}: {formatDate(a.published_at, locale)}
            </dd>
          </div>
          {a.deadline && (
            <div className="flex items-center gap-1 font-medium text-foreground">
              <CalendarClock className="size-3.5" aria-hidden />
              <dt>{t("deadline")}:</dt>
              <dd>{formatDate(a.deadline, locale)}</dd>
            </div>
          )}
          {a.target_audience && (
            <div className="flex items-center gap-1">
              <Users className="size-3.5" aria-hidden />
              <dt className="sr-only">{t("targetAudience")}</dt>
              <dd>{a.target_audience}</dd>
            </div>
          )}
        </dl>
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <span>{a.source.organization}</span>
          <span aria-hidden>·</span>
          <span>
            {t("languages")}: {a.available_languages.map((l) => LOCALE_LABELS[l] ?? l).join(", ")}
          </span>
        </div>
      </CardContent>
    </Card>
  );
}
