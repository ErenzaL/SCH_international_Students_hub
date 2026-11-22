"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { LayoutGrid, List, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input, Label, Select } from "@/components/ui/input";
import { EmptyState, ErrorState, LoadingState, Pagination } from "@/components/shared/states";
import { AnnouncementCard } from "@/features/announcements/announcement-card";
import { api } from "@/lib/api";
import { CATEGORY_SLUGS, LOCALES, LOCALE_LABELS } from "@/lib/constants";
import { useApi } from "@/lib/use-api";
import { useCategoryName } from "@/lib/use-category-name";
import type { AnnouncementSummary, Page } from "@/types/api";

const PAGE_SIZE = 12;

export function AnnouncementsBrowser() {
  const t = useTranslations("announcements");
  const c = useTranslations("common");
  const s = useTranslations("status");
  const categoryName = useCategoryName();

  const [draftQ, setDraftQ] = useState("");
  const [q, setQ] = useState("");
  const [category, setCategory] = useState("");
  const [language, setLanguage] = useState("");
  const [status, setStatus] = useState("");
  const [view, setView] = useState<"card" | "list">("card");
  const [page, setPage] = useState(1);

  const query = { q, category, language, status, page, page_size: PAGE_SIZE };
  const { data, error, loading, reload } = useApi<Page<AnnouncementSummary>>(
    `announcements:${JSON.stringify(query)}`,
    () => api.get<Page<AnnouncementSummary>>("/api/v1/announcements", query),
  );

  const reset = <T,>(setter: (v: T) => void) => (v: T) => {
    setter(v);
    setPage(1);
  };

  return (
    <div className="space-y-6">
      <form
        role="search"
        aria-label={t("searchLabel")}
        className="grid gap-3 rounded-xl border border-border bg-card p-4 md:grid-cols-[2fr_1fr_1fr_1fr_auto]"
        onSubmit={(e) => {
          e.preventDefault();
          setQ(draftQ.trim());
          setPage(1);
        }}
      >
        <div>
          <Label htmlFor="ann-q" className="mb-1.5 block">
            {t("searchLabel")}
          </Label>
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-3 size-4 text-muted-foreground" aria-hidden />
            <Input
              id="ann-q"
              value={draftQ}
              onChange={(e) => setDraftQ(e.target.value)}
              placeholder={t("searchPlaceholder")}
              className="pl-9"
            />
          </div>
        </div>
        <div>
          <Label htmlFor="ann-cat" className="mb-1.5 block">
            {t("category")}
          </Label>
          <Select id="ann-cat" value={category} onChange={(e) => reset(setCategory)(e.target.value)}>
            <option value="">{c("all")}</option>
            {CATEGORY_SLUGS.map((slug) => (
              <option key={slug} value={slug}>
                {categoryName(slug)}
              </option>
            ))}
          </Select>
        </div>
        <div>
          <Label htmlFor="ann-lang" className="mb-1.5 block">
            {t("language")}
          </Label>
          <Select id="ann-lang" value={language} onChange={(e) => reset(setLanguage)(e.target.value)}>
            <option value="">{c("all")}</option>
            {LOCALES.map((l) => (
              <option key={l} value={l}>
                {LOCALE_LABELS[l]}
              </option>
            ))}
          </Select>
        </div>
        <div>
          <Label htmlFor="ann-status" className="mb-1.5 block">
            {t("statusLabel")}
          </Label>
          <Select id="ann-status" value={status} onChange={(e) => reset(setStatus)(e.target.value)}>
            <option value="">{c("all")}</option>
            {(["active", "upcoming", "expired"] as const).map((v) => (
              <option key={v} value={v}>
                {s(v)}
              </option>
            ))}
          </Select>
        </div>
        <div className="flex items-end">
          <Button type="submit" className="w-full">
            <Search /> {c("search")}
          </Button>
        </div>
      </form>

      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground" aria-live="polite">
          {data ? t("resultCount", { count: data.total }) : " "}
        </p>
        <div className="flex gap-1" role="group" aria-label={t("viewMode")}>
          <Button
            variant={view === "card" ? "secondary" : "ghost"}
            size="sm"
            aria-pressed={view === "card"}
            onClick={() => setView("card")}
          >
            <LayoutGrid /> {t("viewCards")}
          </Button>
          <Button
            variant={view === "list" ? "secondary" : "ghost"}
            size="sm"
            aria-pressed={view === "list"}
            onClick={() => setView("list")}
          >
            <List /> {t("viewList")}
          </Button>
        </div>
      </div>

      {loading && <LoadingState rows={4} />}
      {!loading && error && <ErrorState error={error} onRetry={reload} />}
      {!loading && !error && data && data.items.length === 0 && (
        <EmptyState title={t("emptyTitle")} description={t("emptyBody")} />
      )}
      {!loading && !error && data && data.items.length > 0 && (
        <>
          <ul className={view === "card" ? "grid gap-4 md:grid-cols-2 lg:grid-cols-3" : "space-y-3"}>
            {data.items.map((a) => (
              <li key={a.id}>
                <AnnouncementCard announcement={a} layout={view === "card" ? "card" : "row"} />
              </li>
            ))}
          </ul>
          <Pagination page={data.page} pageSize={data.page_size} total={data.total} onChange={setPage} />
        </>
      )}
    </div>
  );
}
