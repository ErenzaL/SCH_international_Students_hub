"use client";

import { useState } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Label, Select } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { EmptyState, ErrorState, LoadingState, PageHeader, Pagination } from "@/components/shared/states";
import { TranslationStateBadge } from "@/features/admin/translations/translation-state-badge";
import { api } from "@/lib/api";
import { LOCALES, LOCALE_LABELS } from "@/lib/constants";
import { useApi } from "@/lib/use-api";
import { formatDateTime } from "@/lib/utils";
import type { Page, TranslationStatus, TranslationTask } from "@/types/api";

const STATUSES: TranslationStatus[] = ["todo", "machine_draft", "in_review", "changes_requested", "human_approved", "rejected"];

/** Translation tasks in the caller's assigned languages only (the API filters; nothing else is fetched). */
export function TranslationsPage() {
  const t = useTranslations("admin.trreview");
  const c = useTranslations("common");
  const locale = useLocale();
  const [status, setStatus] = useState("");
  const [language, setLanguage] = useState("");
  const [outdated, setOutdated] = useState("");
  const [page, setPage] = useState(1);
  const query = { status, language, outdated, page, page_size: 20 };
  const { data, error, loading, reload } = useApi<Page<TranslationTask>>(`admin-trs:${JSON.stringify(query)}`, () =>
    api.get<Page<TranslationTask>>("/api/v1/admin/translations", query),
  );

  return (
    <div>
      <PageHeader title={t("title")} description={t("subtitle")} />
      <Alert variant="info" className="mb-4">
        <AlertDescription>{t("separationNote")}</AlertDescription>
      </Alert>
      <div className="mb-4 grid gap-3 sm:grid-cols-3 lg:max-w-3xl">
        <div>
          <Label htmlFor="tr-f-status" className="mb-1.5 block">
            {t("status")}
          </Label>
          <Select id="tr-f-status" value={status} onChange={(ev) => { setStatus(ev.target.value); setPage(1); }}>
            <option value="">{c("all")}</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {t(`badge.${s}`)}
              </option>
            ))}
          </Select>
        </div>
        <div>
          <Label htmlFor="tr-f-lang" className="mb-1.5 block">
            {t("language")}
          </Label>
          <Select id="tr-f-lang" value={language} onChange={(ev) => { setLanguage(ev.target.value); setPage(1); }}>
            <option value="">{t("myLanguages")}</option>
            {LOCALES.map((l) => (
              <option key={l} value={l}>
                {LOCALE_LABELS[l]}
              </option>
            ))}
          </Select>
        </div>
        <div>
          <Label htmlFor="tr-f-out" className="mb-1.5 block">
            {t("outdatedFilter")}
          </Label>
          <Select id="tr-f-out" value={outdated} onChange={(ev) => { setOutdated(ev.target.value); setPage(1); }}>
            <option value="">{c("all")}</option>
            <option value="true">{t("onlyOutdated")}</option>
            <option value="false">{t("onlyCurrent")}</option>
          </Select>
        </div>
      </div>

      {loading && <LoadingState rows={3} />}
      {!loading && error && <ErrorState error={error} onRetry={reload} />}
      {!loading && !error && data && data.items.length === 0 && <EmptyState title={t("empty")} description={t("emptyBody")} />}
      {data && data.items.length > 0 && (
        <>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("announcement")}</TableHead>
                <TableHead>{t("language")}</TableHead>
                <TableHead>{t("status")}</TableHead>
                <TableHead>{t("lastChange")}</TableHead>
                <TableHead>
                  <span className="sr-only">{t("open")}</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.items.map((tr) => (
                <TableRow key={tr.id}>
                  <TableCell>
                    <Link
                      href={`/admin/translations/${tr.announcement_id}/${tr.language_code}`}
                      className="font-medium text-primary hover:underline"
                    >
                      {tr.announcement_title}
                    </Link>
                    {tr.title && (
                      <div lang={tr.language_code} className="text-xs text-muted-foreground">
                        {tr.title}
                      </div>
                    )}
                  </TableCell>
                  <TableCell>{LOCALE_LABELS[tr.language_code]}</TableCell>
                  <TableCell>
                    <TranslationStateBadge translation={tr} />
                  </TableCell>
                  <TableCell className="text-xs">
                    {tr.reviewed_by_name ?? tr.last_edited_by_name ?? "—"}
                    <div className="text-muted-foreground">{formatDateTime(tr.reviewed_at ?? tr.last_edited_at, locale)}</div>
                  </TableCell>
                  <TableCell>
                    <Button asChild size="sm" variant="outline">
                      <Link href={`/admin/translations/${tr.announcement_id}/${tr.language_code}`}>
                        {tr.can_review && ["in_review", "machine_draft"].includes(tr.translation_status) ? t("review") : t("open")}
                      </Link>
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <Pagination page={data.page} pageSize={data.page_size} total={data.total} onChange={setPage} />
        </>
      )}
    </div>
  );
}
