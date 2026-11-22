"use client";

import { useState } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { Search } from "lucide-react";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";
import { Tabs } from "@/components/ui/tabs";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { EmptyState, ErrorState, LoadingState, PageHeader, Pagination } from "@/components/shared/states";
import { ArchiveButton, DeleteDocumentButton, LifecycleBadge, RestoreButton } from "@/features/admin/documents/lifecycle-actions";
import { useMe } from "@/features/admin/shell/admin-context";
import { api } from "@/lib/api";
import { canArchive, canRestore, lifecycleOf } from "@/lib/document-lifecycle";
import { useApi } from "@/lib/use-api";
import { useCategoryName } from "@/lib/use-category-name";
import { formatDate } from "@/lib/utils";
import type { DocumentItem, LifecycleFilter, Page } from "@/types/api";

const LIFECYCLE_TABS: LifecycleFilter[] = ["active", "archived", "withdrawn"];

export function DocumentsPage() {
  const t = useTranslations("admin.documents");
  const c = useTranslations("common");
  const locale = useLocale();
  const tl = useTranslations("admin.lifecycle");
  const categoryName = useCategoryName();
  const me = useMe();
  const isSuper = me.role === "super_admin";
  const [lifecycle, setLifecycle] = useState<LifecycleFilter>("active");
  const [notice, setNotice] = useState<{ kind: "success" | "destructive"; text: string } | null>(null);
  const [draftQ, setDraftQ] = useState("");
  const [q, setQ] = useState("");
  const [pendingOnly, setPendingOnly] = useState(false);
  const [page, setPage] = useState(1);
  const query = { lifecycle, q, has_pending: pendingOnly ? true : undefined, page, page_size: 20 };
  const { data, error, loading, reload } = useApi<Page<DocumentItem>>(`admin-docs:${JSON.stringify(query)}`, () =>
    api.get<Page<DocumentItem>>("/api/v1/admin/documents", query),
  );

  return (
    <div>
      <PageHeader title={t("title")} description={t("subtitle")} />
      <Tabs
        label={tl("filterLabel")}
        items={LIFECYCLE_TABS.map((id) => ({ id, label: tl(`filter.${id}`) }))}
        value={lifecycle}
        onChange={(id) => {
          setLifecycle(id as LifecycleFilter);
          setPage(1);
          setNotice(null);
        }}
        className="mb-4"
      />
      {notice && (
        <Alert variant={notice.kind} className="mb-4" aria-live="polite">
          {notice.text}
        </Alert>
      )}
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
      {!loading && !error && data && data.items.length === 0 && <EmptyState title={lifecycle === "active" ? t("empty") : tl(`empty.${lifecycle}`)} description={lifecycle === "active" ? t("emptyBody") : undefined} />}
      {data && data.items.length > 0 && (
        <>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("document")}</TableHead>
                <TableHead>{t("source")}</TableHead>
                <TableHead>{t("state")}</TableHead>
                <TableHead>{t("created")}</TableHead>
                <TableHead>
                  <span className="sr-only">{tl("actions")}</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.items.map((d) => {
                const lc = lifecycleOf(d);
                const done = (text: string) => {
                  setNotice({ kind: "success", text });
                  reload();
                };
                return (
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
                      <LifecycleBadge lifecycle={lc} />
                      {d.pending_version_id && <Badge variant="warning">{t("hasPending")}</Badge>}
                    </div>
                    {lc === "archived" && d.archive_reason && (
                      <div className="mt-1 text-xs text-muted-foreground">{tl("reasonShort", { reason: d.archive_reason })}</div>
                    )}
                    {lc === "withdrawn" && d.canceled_reason && (
                      <div className="mt-1 text-xs text-muted-foreground">{tl("reasonShort", { reason: d.canceled_reason })}</div>
                    )}
                  </TableCell>
                  <TableCell className="text-xs">{formatDate(d.created_at, locale)}</TableCell>
                  <TableCell>
                    <div className="flex flex-wrap justify-end gap-1">
                      {canArchive(lc) && <ArchiveButton size="sm" documentId={d.id} title={d.title} onDone={done} />}
                      {canRestore(lc) && <RestoreButton size="sm" documentId={d.id} title={d.title} lifecycle={lc} onDone={done} />}
                      {isSuper && (
                        <DeleteDocumentButton
                          size="sm"
                          documentId={d.id}
                          onFinished={(r) => done(tl("deletedNotice", { title: r.title }))}
                        />
                      )}
                    </div>
                  </TableCell>
                </TableRow>
                );
              })}
            </TableBody>
          </Table>
          <Pagination page={data.page} pageSize={data.page_size} total={data.total} onChange={setPage} />
        </>
      )}
    </div>
  );
}
