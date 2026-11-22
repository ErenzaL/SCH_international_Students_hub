"use client";

import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { AlertTriangle, ArrowLeft, ExternalLink, Paperclip } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { AuthorityBadge, ScopeBadge, StaleBadge } from "@/components/shared/badges";
import { ErrorState, LoadingState } from "@/components/shared/states";
import { api } from "@/lib/api";
import { useApi } from "@/lib/use-api";
import { useCategoryName } from "@/lib/use-category-name";
import { formatDate } from "@/lib/utils";
import { formatFieldValue } from "@/lib/format-field";
import type { KnowledgeDocumentDetail } from "@/types/api";

export function KnowledgeArticle({ id }: { id: string }) {
  const t = useTranslations("knowledge");
  const c = useTranslations("common");
  const locale = useLocale();
  const categoryName = useCategoryName();
  const { data: d, error, loading, reload } = useApi<KnowledgeDocumentDetail>(`kdoc:${id}`, () =>
    api.get<KnowledgeDocumentDetail>(`/api/v1/knowledge/documents/${encodeURIComponent(id)}`),
  );

  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      <Link href="/knowledge" className="mb-4 inline-flex items-center gap-1 text-sm text-primary hover:underline">
        <ArrowLeft className="size-4" /> {t("backToList")}
      </Link>
      {loading && <LoadingState rows={4} />}
      {!loading && error && <ErrorState error={error} onRetry={reload} />}
      {d && (
        <article className="space-y-6">
          <header className="space-y-3">
            <div className="flex flex-wrap gap-2">
              <ScopeBadge scope={d.scope} />
              <AuthorityBadge authority={d.authority_type} />
              <Badge variant="outline">{categoryName(d.category)}</Badge>
              {d.is_stale && <StaleBadge days={d.verification_age_days} />}
            </div>
            <h1 className="text-2xl font-bold tracking-tight md:text-3xl">{d.title}</h1>
          </header>

          {d.is_stale && (
            <Alert variant="warning">
              <AlertTriangle className="size-4" aria-hidden />
              <AlertTitle>{t("staleTitle")}</AlertTitle>
              <AlertDescription>{t("staleBody", { days: d.verification_age_days ?? 0 })}</AlertDescription>
            </Alert>
          )}

          {d.key_facts && Object.keys(d.key_facts).length > 0 && (
            <section aria-labelledby="kf-h" className="rounded-lg border border-border bg-card p-5">
              <h2 id="kf-h" className="mb-2 font-semibold">{t("keyFacts")}</h2>
              <dl className="grid gap-2 text-sm sm:grid-cols-2">
                {Object.entries(d.key_facts).map(([k, v]) => (
                  <div key={k}>
                    <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{t.has(`facts.${k}`) ? t(`facts.${k}`) : k}</dt>
                    <dd>{formatFieldValue(v)}</dd>
                  </div>
                ))}
              </dl>
              <p className="mt-2 text-xs text-muted-foreground">{t("keyFactsNote")}</p>
            </section>
          )}

          <Card>
            <CardContent className="grid gap-4 p-5 text-sm sm:grid-cols-2">
              <Meta label={t("organization")} value={d.organization} />
              <Meta label={t("sourcePublished")} value={formatDate(d.source_published_at, locale)} />
              <Meta label={t("verifiedAt")} value={formatDate(d.verified_at, locale)} />
              <Meta label={t("version")} value={`v${d.version_number}`} />
              {d.valid_until && <Meta label={t("validUntil")} value={formatDate(d.valid_until, locale)} />}
              {d.notice_no && <Meta label={t("noticeNo")} value={`#${d.notice_no}`} />}
              <div className="sm:col-span-2">
                <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  {t("officialSource")}
                </p>
                {d.source_url ? (
                  <a
                    href={d.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 break-all text-primary hover:underline"
                  >
                    <ExternalLink className="size-4 shrink-0" aria-hidden /> {d.source_url}
                  </a>
                ) : (
                  <p className="text-muted-foreground">{c("noSourceUrl")}</p>
                )}
              </div>
              {(d.attachments ?? []).length > 0 && (
                <div className="sm:col-span-2">
                  <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{t("attachments")}</p>
                  <ul className="mt-1 space-y-0.5">
                    {d.attachments!.map((a) => (
                      <li key={a.url}>
                        <a href={a.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-primary hover:underline">
                          <Paperclip className="size-3.5" aria-hidden /> {a.name}
                        </a>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </CardContent>
          </Card>

          <div lang={d.language} className="whitespace-pre-wrap rounded-lg border border-border bg-card p-5 leading-relaxed">
            {d.content}
          </div>
          <p className="text-xs text-muted-foreground">{t("articleDisclaimer")}</p>
        </article>
      )}
    </div>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="mt-0.5">{value}</p>
    </div>
  );
}
