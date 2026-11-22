"use client";

import { useState } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { Label, Select } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { TranslationStatusBadge } from "@/components/shared/badges";
import { EmptyState, ErrorState, LoadingState, PageHeader, Pagination } from "@/components/shared/states";
import { api } from "@/lib/api";
import { LOCALES, LOCALE_LABELS } from "@/lib/constants";
import { useApi } from "@/lib/use-api";
import { formatDateTime } from "@/lib/utils";
import type { Page, TranslationListItem, TranslationStatus } from "@/types/api";

const STATUSES: TranslationStatus[] = ["machine_draft", "in_review", "human_approved", "rejected"];

export function TranslationsPage() {
  const t = useTranslations("admin.translations");
  const c = useTranslations("common");
  const e = useTranslations("enums");
  const locale = useLocale();
  const [status, setStatus] = useState("");
  const [language, setLanguage] = useState("");
  const [page, setPage] = useState(1);
  const query = { status, language, page, page_size: 20 };
  const { data, error, loading, reload } = useApi<Page<TranslationListItem>>(`admin-trs:${JSON.stringify(query)}`, () =>
    api.get<Page<TranslationListItem>>("/api/v1/admin/translations", query),
  );

  return (
    <div>
      <PageHeader title={t("title")} description={t("subtitle")} />
      <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:max-w-xl">
        <div>
          <Label htmlFor="tr-f-status" className="mb-1.5 block">
            {t("statusLabel")}
          </Label>
          <Select id="tr-f-status" value={status} onChange={(ev) => { setStatus(ev.target.value); setPage(1); }}>
            <option value="">{c("all")}</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {e(`translation.${s}`)}
              </option>
            ))}
          </Select>
        </div>
        <div>
          <Label htmlFor="tr-f-lang" className="mb-1.5 block">
            {t("languageLabel")}
          </Label>
          <Select id="tr-f-lang" value={language} onChange={(ev) => { setLanguage(ev.target.value); setPage(1); }}>
            <option value="">{c("all")}</option>
            {LOCALES.filter((l) => l !== "ko").map((l) => (
              <option key={l} value={l}>
                {LOCALE_LABELS[l]}
              </option>
            ))}
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
                <TableHead>{t("languageLabel")}</TableHead>
                <TableHead>{t("statusLabel")}</TableHead>
                <TableHead>{t("reviewer")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.items.map((tr) => (
                <TableRow key={tr.id}>
                  <TableCell>
                    <Link href={`/admin/announcements/${tr.announcement_id}`} className="font-medium text-primary hover:underline">
                      {tr.announcement_title}
                    </Link>
                    <div lang={tr.language_code} className="text-xs text-muted-foreground">{tr.title}</div>
                  </TableCell>
                  <TableCell>{LOCALE_LABELS[tr.language_code]}</TableCell>
                  <TableCell>
                    <TranslationStatusBadge status={tr.translation_status} />
                  </TableCell>
                  <TableCell className="text-xs">
                    {tr.reviewed_by_name ?? "—"}
                    <div className="text-muted-foreground">{formatDateTime(tr.reviewed_at, locale)}</div>
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
