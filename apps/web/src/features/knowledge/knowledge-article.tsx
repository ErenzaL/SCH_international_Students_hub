"use client";

import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { ArrowLeft, ExternalLink } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { AuthorityBadge, ScopeBadge } from "@/components/shared/badges";
import { ErrorState, LoadingState } from "@/components/shared/states";
import { api } from "@/lib/api";
import { useApi } from "@/lib/use-api";
import { useCategoryName } from "@/lib/use-category-name";
import { formatDate } from "@/lib/utils";
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
            </div>
            <h1 className="text-2xl font-bold tracking-tight md:text-3xl">{d.title}</h1>
          </header>

          <Card>
            <CardContent className="grid gap-4 p-5 text-sm sm:grid-cols-2">
              <Meta label={t("organization")} value={d.organization} />
              <Meta label={t("sourcePublished")} value={formatDate(d.source_published_at, locale)} />
              <Meta label={t("verifiedAt")} value={formatDate(d.verified_at, locale)} />
              <Meta label={t("version")} value={`v${d.version_number}`} />
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
