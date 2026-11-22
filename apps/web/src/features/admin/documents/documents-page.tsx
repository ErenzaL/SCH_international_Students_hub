"use client";

import { useState } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { Search } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { EmptyState, ErrorState, LoadingState, PageHeader, Pagination } from "@/components/shared/states";
import { api } from "@/lib/api";
import { useApi } from "@/lib/use-api";
import { useCategoryName } from "@/lib/use-category-name";
import { formatDate } from "@/lib/utils";
import type { DocumentItem, Page } from "@/types/api";

export function DocumentsPage() {
  const t = useTranslations("admin.documents");
  const c = useTranslations("common");
  const locale = useLocale();
  const categoryName = useCategoryName();
  const [draftQ, setDraftQ] = useState("");
  const [q, setQ] = useState("");
  const [pendingOnly, setPendingOnly] = useState(false);
  const [page, setPage] = useState(1);
  const query = { q, has_pending: pendingOnly ? true : undefined, page, page_size: 20 };
  const { data, error, loading, reload } = useApi<Page<DocumentItem>>(`admin-docs:${JSON.stringify(query)}`, () =>
    api.get<Page<DocumentItem>>("/api/v1/admin/documents", query),
  );

  return (
    <div>
      <PageHeader title={t("title")} description={t("subtitle")} />
      <form
        role="search"
        className="mb-4 flex flex-wrap items-end gap-3 rounded-xl border border-border bg-card p-4"
        onSubmit={(e) => {
          e.preventDefault();
          setQ(draftQ.trim());
          setPage(1);
        }}
      >
        <div className="min-w-56 flex-1">
          <Label htmlFor="d-q" className="mb-1.5 block">
            {c("search")}
          </Label>
          <Input id="d-q" value={draftQ} onChange={(e) => setDraftQ(e.target.value)} />
        </div>
        <label className="flex items-center gap-2 pb-2 text-sm">
          <input
            type="checkbox"
            checked={pendingOnly}
            onChange={(e) => {
              setPendingOnly(e.target.checked);
              setPage(1);
            }}
          />
          {t("pendingOnly")}
        </label>
        <Button type="submit">
          <Search /> {c("search")}
        </Button>
      </form>

      {loading && <LoadingState rows={4} />}
      {!loading && error && <ErrorState error={error} onRetry={reload} />}
      {!loading && !error && data && data.items.length === 0 && <EmptyState title={t("empty")} description={t("emptyBody")} />}
      {data && data.items.length > 0 && (
        <>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("document")}</TableHead>
                <TableHead>{t("source")}</TableHead>
                <TableHead>{t("state")}</TableHead>
                <TableHead>{t("created")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.items.map((d) => (
                <TableRow key={d.id}>
                  <TableCell className="min-w-56">
                    <Link href={`/admin/documents/${d.id}`} className="font-medium text-primary hover:underline">
                      {d.title}
                    </Link>
                    <div className="break-all text-xs text-muted-foreground">{d.canonical_url}</div>
                  </TableCell>
                  <TableCell className="text-xs">
                    <div>{d.source_title}</div>
                    <div className="text-muted-foreground">
                      {d.organization} · {categoryName(d.category)}
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="flex flex-wrap gap-1">
                      {d.current_version_id ? <Badge variant="success">{t("hasApproved")}</Badge> : <Badge variant="muted">{t("noApproved")}</Badge>}
                      {d.pending_version_id && <Badge variant="warning">{t("hasPending")}</Badge>}
                      {d.is_canceled && <Badge variant="danger">{t("canceled")}</Badge>}
                    </div>
                  </TableCell>
                  <TableCell className="text-xs">{formatDate(d.created_at, locale)}</TableCell>
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
