"use client";

import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { ArrowLeft, CalendarClock, ExternalLink, ShieldCheck, Users } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  AnnouncementStatusBadge,
  AuthorityBadge,
  ScopeBadge,
  TestDataBadge,
} from "@/components/shared/badges";
import { ErrorState, LoadingState } from "@/components/shared/states";
import { api } from "@/lib/api";
import { LOCALE_LABELS } from "@/lib/constants";
import { useApi } from "@/lib/use-api";
import { useCategoryName } from "@/lib/use-category-name";
import { formatDate, formatDateTime } from "@/lib/utils";
import type { AnnouncementDetail as Detail } from "@/types/api";

export function AnnouncementDetail({ id }: { id: string }) {
  const t = useTranslations("announcements");
  const c = useTranslations("common");
  const locale = useLocale();
  const categoryName = useCategoryName();
  const { data: a, error, loading, reload } = useApi<Detail>(`announcement:${id}`, () =>
    api.get<Detail>(`/api/v1/announcements/${encodeURIComponent(id)}`),
  );

  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      <Link href="/announcements" className="mb-4 inline-flex items-center gap-1 text-sm text-primary hover:underline">
        <ArrowLeft className="size-4" /> {t("backToList")}
      </Link>
      {loading && <LoadingState rows={4} />}
      {!loading && error && <ErrorState error={error} onRetry={reload} />}
      {a && (
        <article className="space-y-6">
          <header className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <AnnouncementStatusBadge status={a.status} />
              <Badge variant="outline">{categoryName(a.category)}</Badge>
              {a.is_test_data && <TestDataBadge />}
            </div>
            <h1 className="text-2xl font-bold tracking-tight md:text-3xl">{a.title}</h1>
            {a.is_test_data && (
              <p className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
                {t("testDataNote")}
              </p>
            )}
          </header>

          <Card>
            <CardContent className="grid gap-4 p-5 sm:grid-cols-2">
              <Fact label={t("published")} value={formatDate(a.published_at, locale)} />
              <Fact
                icon={<CalendarClock className="size-4" aria-hidden />}
                label={t("deadline")}
                value={formatDate(a.deadline, locale)}
              />
              <Fact label={t("eventDate")} value={formatDate(a.event_date, locale)} />
              <Fact
                icon={<Users className="size-4" aria-hidden />}
                label={t("targetAudience")}
                value={a.target_audience ?? "—"}
              />
            </CardContent>
          </Card>

          <section aria-labelledby="orig-h">
            <h2 id="orig-h" className="mb-2 text-lg font-semibold">
              {t("originalText", { language: LOCALE_LABELS[a.original_language] ?? a.original_language })}
            </h2>
            <div lang={a.original_language} className="whitespace-pre-wrap rounded-lg border border-border bg-card p-5 leading-relaxed">
              {a.body}
            </div>
          </section>

          <section aria-labelledby="tr-h" className="space-y-3">
            <h2 id="tr-h" className="text-lg font-semibold">
              {t("translations")}
            </h2>
            {a.translations.length === 0 ? (
              <p className="rounded-md border border-dashed border-border p-4 text-sm text-muted-foreground">
                {t("noTranslations")}
              </p>
            ) : (
              a.translations.map((tr) => (
                <Card key={tr.language}>
                  <CardHeader>
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant="success">{t("humanReviewed")}</Badge>
                      <span className="text-xs text-muted-foreground">
                        {LOCALE_LABELS[tr.language]} · {t("reviewedOn", { date: formatDate(tr.reviewed_at, locale) })}
                      </span>
                    </div>
                    <CardTitle lang={tr.language}>{tr.title}</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div lang={tr.language} className="whitespace-pre-wrap leading-relaxed">
                      {tr.body}
                    </div>
                  </CardContent>
                </Card>
              ))
            )}
          </section>

          <section aria-labelledby="src-h">
            <Card>
              <CardHeader>
                <CardTitle id="src-h" className="flex items-center gap-2">
                  <ShieldCheck className="size-5 text-primary" aria-hidden /> {t("sourceAndVerification")}
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 text-sm">
                <div className="flex flex-wrap gap-2">
                  <ScopeBadge scope={a.source.scope} />
                  <AuthorityBadge authority={a.source.authority_type} />
                </div>
                <dl className="grid gap-3 sm:grid-cols-2">
                  <Fact label={t("sourceTitle")} value={a.source.title} />
                  <Fact label={t("organization")} value={a.source.organization} />
                  <Fact label={t("sourcePublished")} value={formatDate(a.source_published_at, locale)} />
                  <Fact label={t("verifiedAt")} value={formatDateTime(a.verified_at, locale)} />
                </dl>
                {a.source.url ? (
                  <a
                    href={a.source.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 break-all font-medium text-primary hover:underline"
                  >
                    <ExternalLink className="size-4 shrink-0" aria-hidden /> {t("officialSource")}
                  </a>
                ) : (
                  <p className="text-muted-foreground">{c("noSourceUrl")}</p>
                )}
              </CardContent>
            </Card>
          </section>
        </article>
      )}
    </div>
  );
}

function Fact({ label, value, icon }: { label: string; value: string; icon?: React.ReactNode }) {
  return (
    <div>
      <dt className="flex items-center gap-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {icon}
        {label}
      </dt>
      <dd className="mt-0.5 text-sm">{value}</dd>
    </div>
  );
}
