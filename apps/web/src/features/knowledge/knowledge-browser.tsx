"use client";

import { useState } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { ExternalLink, Search } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Label, Select } from "@/components/ui/input";
import { AuthorityBadge, ScopeBadge, StaleBadge } from "@/components/shared/badges";
import { EmptyState, ErrorState, LoadingState, Pagination } from "@/components/shared/states";
import { api } from "@/lib/api";
import { CATEGORY_SLUGS } from "@/lib/constants";
import { useApi } from "@/lib/use-api";
import { useCategoryName } from "@/lib/use-category-name";
import { cn, formatDate } from "@/lib/utils";
import type { KnowledgeDocumentSummary, Page } from "@/types/api";

const PAGE_SIZE = 12;

export function KnowledgeBrowser({
  initialQuery = "",
  initialCategory = "",
}: {
  initialQuery?: string;
  initialCategory?: string;
}) {
  const t = useTranslations("knowledge");
  const c = useTranslations("common");
  const locale = useLocale();
  const categoryName = useCategoryName();

  const [draftQ, setDraftQ] = useState(initialQuery);
  const [q, setQ] = useState(initialQuery);
  const [category, setCategory] = useState(initialCategory);
  const [scope, setScope] = useState("");
  const [authority, setAuthority] = useState("");
  const [page, setPage] = useState(1);

  const query = { q, category, scope, authority, page, page_size: PAGE_SIZE };
  const { data, error, loading, reload } = useApi<Page<KnowledgeDocumentSummary>>(
    `knowledge:${JSON.stringify(query)}`,
    () => api.get<Page<KnowledgeDocumentSummary>>("/api/v1/knowledge/documents", query),
  );

  return (
    <div className="grid gap-8 lg:grid-cols-[16rem_1fr]">
      <aside aria-label={t("categories")}>
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          {t("categories")}
        </h2>
        <ul className="flex flex-wrap gap-2 lg:flex-col lg:gap-1">
          {[{ slug: "", label: c("all") }, ...CATEGORY_SLUGS.map((s) => ({ slug: s as string, label: categoryName(s) }))].map(
            (item) => (
              <li key={item.slug || "all"}>
                <button
                  type="button"
                  aria-pressed={category === item.slug}
                  onClick={() => {
                    setCategory(item.slug);
                    setPage(1);
                  }}
                  className={cn(
                    "w-full rounded-md px-3 py-1.5 text-left text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    category === item.slug
                      ? "bg-secondary font-medium text-secondary-foreground"
                      : "border border-border hover:bg-muted lg:border-transparent",
                  )}
                >
                  {item.label}
                </button>
              </li>
            ),
          )}
        </ul>
      </aside>

      <div className="space-y-6">
        <form
          role="search"
          aria-label={t("searchLabel")}
          className="grid gap-3 rounded-xl border border-border bg-card p-4 sm:grid-cols-2 lg:grid-cols-[1fr_11rem_13rem_auto]"
          onSubmit={(e) => {
            e.preventDefault();
            setQ(draftQ.trim());
            setPage(1);
          }}
        >
          <div>
            <Label htmlFor="kc-q" className="mb-1.5 block">
              {t("searchLabel")}
            </Label>
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-3 size-4 text-muted-foreground" aria-hidden />
              <Input
                id="kc-q"
                className="pl-9"
                value={draftQ}
                onChange={(e) => setDraftQ(e.target.value)}
                placeholder={t("searchPlaceholder")}
              />
            </div>
          </div>
          <div>
            <Label htmlFor="kc-scope" className="mb-1.5 block">
              {t("scopeLabel")}
            </Label>
            <Select
              id="kc-scope"
              value={scope}
              onChange={(e) => {
                setScope(e.target.value);
                setPage(1);
              }}
            >
              <option value="">{c("all")}</option>
              <option value="university">{t("scope.university")}</option>
              <option value="national">{t("scope.national")}</option>
            </Select>
          </div>
          <div>
            <Label htmlFor="kc-auth" className="mb-1.5 block">
              {t("authorityLabel")}
            </Label>
            <Select
              id="kc-auth"
              value={authority}
              onChange={(e) => {
                setAuthority(e.target.value);
                setPage(1);
              }}
            >
              <option value="">{c("all")}</option>
              <option value="official_university">{t("authority.official_university")}</option>
              <option value="official_government">{t("authority.official_government")}</option>
              <option value="staff_communication">{t("authority.staff_communication")}</option>
            </Select>
          </div>
          <div className="flex items-end">
            <Button type="submit" className="w-full">
              <Search /> {c("search")}
            </Button>
          </div>
        </form>

        <p className="text-xs text-muted-foreground">{t("verifiedOnlyNote")}</p>

        {loading && <LoadingState rows={4} />}
        {!loading && error && <ErrorState error={error} onRetry={reload} />}
        {!loading && !error && data && data.items.length === 0 && (
          <EmptyState title={t("emptyTitle")} description={t("emptyBody")} />
        )}
        {!loading && !error && data && data.items.length > 0 && (
          <>
            <ul className="grid gap-4 md:grid-cols-2">
              {data.items.map((d) => (
                <li key={d.id}>
                  <Card className="h-full transition-shadow hover:shadow-md">
                    <CardHeader>
                      <div className="flex flex-wrap gap-2">
                        <ScopeBadge scope={d.scope} />
                        <AuthorityBadge authority={d.authority_type} />
                        <Badge variant="outline">{categoryName(d.category)}</Badge>
                        {d.is_stale && <StaleBadge days={d.verification_age_days} />}
                      </div>
                      <CardTitle className="mt-1 text-lg">
                        <Link href={`/knowledge/${d.id}`} className="hover:underline">
                          {d.title}
                        </Link>
                      </CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-2 text-sm">
                      {d.excerpt && <p className="line-clamp-3 text-muted-foreground">{d.excerpt}</p>}
                      <p className="text-xs text-muted-foreground">
                        {d.organization} · {t("verifiedOn", { date: formatDate(d.verified_at, locale) })}
                      </p>
                      {d.source_url && (
                        <a
                          href={d.source_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
                        >
                          <ExternalLink className="size-3.5" aria-hidden /> {t("officialSource")}
                        </a>
                      )}
                    </CardContent>
                  </Card>
                </li>
              ))}
            </ul>
            <Pagination page={data.page} pageSize={data.page_size} total={data.total} onChange={setPage} />
          </>
        )}
      </div>
    </div>
  );
}

