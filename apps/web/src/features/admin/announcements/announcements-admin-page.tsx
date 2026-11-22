"use client";

import { useState } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Label, Select } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { PublicationBadge, TestDataBadge } from "@/components/shared/badges";
import { EmptyState, ErrorState, LoadingState, PageHeader, Pagination } from "@/components/shared/states";
import { api } from "@/lib/api";
import { useApi } from "@/lib/use-api";
import { useCategoryName } from "@/lib/use-category-name";
import { formatDate } from "@/lib/utils";
import type { AdminAnnouncement, Page, PublicationStatus } from "@/types/api";

const STATUSES: PublicationStatus[] = ["draft", "pending_approval", "published", "rejected", "canceled"];

export function AnnouncementsAdminPage() {
  const t = useTranslations("admin.announcements");
  const c = useTranslations("common");
  const e = useTranslations("enums");
  const locale = useLocale();
  const categoryName = useCategoryName();
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const query = { status, page, page_size: 20 };
  const { data, error, loading, reload } = useApi<Page<AdminAnnouncement>>(`admin-anns:${JSON.stringify(query)}`, () =>
    api.get<Page<AdminAnnouncement>>("/api/v1/admin/announcements", query),
  );

  return (
    <div>
      <PageHeader
        title={t("title")}
        description={t("subtitle")}
        actions={
          <Button asChild>
            <Link href="/admin/announcements/new">
              <Plus /> {t("new")}
            </Link>
          </Button>
        }
      />
      <div className="mb-4 max-w-xs">
        <Label htmlFor="an-status" className="mb-1.5 block">
          {t("statusFilter")}
        </Label>
        <Select id="an-status" value={status} onChange={(ev) => { setStatus(ev.target.value); setPage(1); }}>
          <option value="">{c("all")}</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {e(`publication.${s}`)}
            </option>
          ))}
        </Select>
      </div>

      {loading && <LoadingState rows={4} />}
      {!loading && error && <ErrorState error={error} onRetry={reload} />}
      {!loading && !error && data && data.items.length === 0 && <EmptyState title={t("empty")} description={t("emptyBody")} />}
      {data && data.items.length > 0 && (
        <>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("colTitle")}</TableHead>
                <TableHead>{t("colStatus")}</TableHead>
                <TableHead>{t("colDeadline")}</TableHead>
                <TableHead>{t("colSubmitter")}</TableHead>
                <TableHead>{t("colCreated")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.items.map((a) => (
                <TableRow key={a.id}>
                  <TableCell className="min-w-56">
                    <Link href={`/admin/announcements/${a.id}`} className="font-medium text-primary hover:underline">
                      {a.title}
                    </Link>
                    <div className="text-xs text-muted-foreground">{categoryName(a.category)}</div>
                    {a.is_test_data && <TestDataBadge />}
                  </TableCell>
                  <TableCell>
                    <PublicationBadge status={a.publication_status} />
                  </TableCell>
                  <TableCell className="text-xs">{formatDate(a.deadline, locale)}</TableCell>
                  <TableCell className="text-xs">
                    {a.created_by_name ?? "—"}
                    <div className="text-muted-foreground">{e(`sourceType.${a.source_type}`)}</div>
                  </TableCell>
                  <TableCell className="text-xs">{formatDate(a.created_at, locale)}</TableCell>
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
