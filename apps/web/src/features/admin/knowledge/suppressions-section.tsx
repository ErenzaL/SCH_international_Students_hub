"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Loader2, Unlock } from "lucide-react";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ErrorState, LoadingState } from "@/components/shared/states";
import { api, errorMessage } from "@/lib/api";
import { useApi } from "@/lib/use-api";
import { formatDateTime } from "@/lib/utils";
import type { DocumentSuppression } from "@/types/api";

/** Deliberately deleted documents that future syncs of this source will skip, with "Allow re-import". */
export function SuppressionsSection({ sourceId, canManage }: { sourceId: string; canManage: boolean }) {
  const t = useTranslations("admin.lifecycle.suppressions");
  const c = useTranslations("common");
  const locale = useLocale();
  const [key, setKey] = useState(0);
  const list = useApi<{ items: DocumentSuppression[] }>(`suppr:${sourceId}:${key}`, () =>
    api.get<{ items: DocumentSuppression[] }>(`/api/v1/admin/sources/${encodeURIComponent(sourceId)}/suppressions`),
  );
  const [target, setTarget] = useState<DocumentSuppression | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function allow() {
    if (!target) return;
    setBusy(true);
    setError(null);
    try {
      await api.delete(`/api/v1/admin/sources/${encodeURIComponent(sourceId)}/suppressions/${target.id}`);
      setNotice(t("allowed", { title: label(target) }));
      setTarget(null);
      setKey((k) => k + 1);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const items = list.data?.items ?? [];
  return (
    <section className="space-y-2" aria-labelledby="sd-suppr">
      <h2 id="sd-suppr" className="text-lg font-semibold">
        {t("title")}
      </h2>
      <p className="text-sm text-muted-foreground">{t("explain")}</p>
      {notice && (
        <Alert variant="success" aria-live="polite">
          {notice}
        </Alert>
      )}
      {list.loading && !list.data && <LoadingState rows={1} />}
      {list.error && <ErrorState error={list.error} onRetry={list.reload} />}
      {list.data && items.length === 0 && <p className="text-sm text-muted-foreground">{t("empty")}</p>}
      {items.length > 0 && (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("document")}</TableHead>
              <TableHead>{t("reason")}</TableHead>
              <TableHead>{t("blockedAt")}</TableHead>
              <TableHead>
                <span className="sr-only">{t("actions")}</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((s) => (
              <TableRow key={s.id}>
                <TableCell className="min-w-56">
                  <div className="font-medium">{s.title ?? "—"}</div>
                  {s.canonical_url && <div className="break-all text-xs text-muted-foreground">{s.canonical_url}</div>}
                  {s.external_id && <div className="font-mono text-xs text-muted-foreground">{s.external_id}</div>}
                </TableCell>
                <TableCell className="text-xs">{s.reason ?? "—"}</TableCell>
                <TableCell className="text-xs">{formatDateTime(s.created_at, locale)}</TableCell>
                <TableCell>
                  {canManage && (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => {
                        setError(null);
                        setNotice(null);
                        setTarget(s);
                      }}
                    >
                      <Unlock /> {t("allow")}
                    </Button>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      <Dialog open={!!target} onOpenChange={(o) => !o && !busy && setTarget(null)}>
        <DialogContent closeLabel={c("close")}>
          <DialogHeader>
            <DialogTitle>{t("confirmTitle")}</DialogTitle>
            <DialogDescription>{target ? t("confirmBody", { title: label(target) }) : null}</DialogDescription>
          </DialogHeader>
          {error && <Alert variant="destructive">{error}</Alert>}
          <DialogFooter>
            <Button variant="outline" disabled={busy} onClick={() => setTarget(null)}>
              {t("cancel")}
            </Button>
            <Button disabled={busy} onClick={allow}>
              {busy ? <Loader2 className="animate-spin" /> : <Unlock />} {t("allow")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}

function label(s: DocumentSuppression): string {
  return s.title ?? s.canonical_url ?? s.external_id ?? String(s.id);
}
