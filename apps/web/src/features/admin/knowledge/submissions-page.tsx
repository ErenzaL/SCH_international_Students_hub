"use client";

import { useState } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { Pencil, Plus, Send } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Label, Textarea } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { IndexingStatusBadge, VersionStatusBadge } from "@/components/shared/badges";
import { EmptyState, ErrorState, LoadingState, PageHeader, Pagination } from "@/components/shared/states";
import { api, errorMessage } from "@/lib/api";
import { useAction } from "@/lib/use-action";
import { useApi } from "@/lib/use-api";
import { formatDateTime } from "@/lib/utils";
import type { MySubmission, Page, Version } from "@/types/api";

/** What the signed-in staff member submitted, with reviewer notes; drafts can be corrected and submitted. */
export function SubmissionsPage() {
  const t = useTranslations("admin.ks");
  const locale = useLocale();
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState<MySubmission | null>(null);
  const [notice, setNotice] = useState<{ kind: "success" | "destructive"; text: string } | null>(null);
  const submitAction = useAction();
  const { data, error, loading, reload } = useApi<Page<MySubmission>>(`mine:${page}`, () =>
    api.get<Page<MySubmission>>("/api/v1/admin/intake/mine", { page, page_size: 20 }),
  );

  async function submit(s: MySubmission) {
    setNotice(null);
    const v = await submitAction.run(() => api.post<Version>(`/api/v1/admin/versions/${s.id}/submit`));
    if (v) {
      setNotice({ kind: "success", text: t("submitted") });
      reload();
    }
  }

  return (
    <div>
      <PageHeader
        title={t("mySubmissions")}
        description={t("submissionsSubtitle")}
        actions={<Button asChild><Link href="/admin/knowledge-sources/new"><Plus /> {t("addKnowledge")}</Link></Button>}
      />
      {notice && <Alert variant={notice.kind} className="mb-4"><AlertDescription>{notice.text}</AlertDescription></Alert>}
      {submitAction.error && <Alert variant="destructive" className="mb-4"><AlertDescription>{errorMessage(submitAction.error)}</AlertDescription></Alert>}
      {loading && !data && <LoadingState rows={3} />}
      {error && <ErrorState error={error} onRetry={reload} />}
      {data && data.items.length === 0 && <EmptyState title={t("noSubmissions")} />}
      {data && data.items.length > 0 && (
        <>
          <Table>
            <TableHeader><TableRow>
              <TableHead>{t("meta.title")}</TableHead>
              <TableHead>{t("status")}</TableHead>
              <TableHead>{t("reviewNote")}</TableHead>
              <TableHead>{t("created")}</TableHead>
              <TableHead><span className="sr-only">{t("actionsLabel")}</span></TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {data.items.map((s) => (
                <TableRow key={s.id}>
                  <TableCell className="min-w-56">{s.document_title ?? "—"} <span className="font-mono text-xs">v{s.version_number}</span></TableCell>
                  <TableCell>
                    <div className="flex flex-col items-start gap-1">
                      <VersionStatusBadge status={s.verification_status} />
                      <IndexingStatusBadge status={s.indexing_status} />
                    </div>
                  </TableCell>
                  <TableCell className="max-w-64 text-xs">{s.review_note ?? s.rejected_reason ?? "—"}</TableCell>
                  <TableCell className="text-xs">{formatDateTime(s.created_at, locale)}</TableCell>
                  <TableCell>
                    {s.verification_status === "draft" && (
                      <div className="flex flex-wrap gap-1">
                        <Button size="sm" variant="outline" onClick={() => setEditing(s)}><Pencil /> {t("edit")}</Button>
                        <Button size="sm" disabled={submitAction.busy} onClick={() => submit(s)}><Send /> {t("submitForReview")}</Button>
                      </div>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <Pagination page={data.page} pageSize={data.page_size} total={data.total} onChange={setPage} />
        </>
      )}
      <EditDraftDialog submission={editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); setNotice({ kind: "success", text: t("draftSaved") }); reload(); }} />
    </div>
  );
}

function EditDraftDialog({ submission, onClose, onSaved }: { submission: MySubmission | null; onClose: () => void; onSaved: () => void }) {
  const c = useTranslations("common");
  return (
    <Dialog open={!!submission} onOpenChange={(o) => !o && onClose()}>
      <DialogContent closeLabel={c("close")} className="max-w-3xl">
        {submission && <EditDraft key={submission.id} id={submission.id} onSaved={onSaved} onClose={onClose} />}
      </DialogContent>
    </Dialog>
  );
}

function EditDraft({ id, onSaved, onClose }: { id: string; onSaved: () => void; onClose: () => void }) {
  const t = useTranslations("admin.ks");
  const c = useTranslations("common");
  const v = useApi<Version>(`draft:${id}`, () => api.get<Version>(`/api/v1/admin/versions/${id}`));
  const [text, setText] = useState<string | null>(null);
  const save = useAction();
  const value = text ?? v.data?.extracted_text ?? "";
  return (
    <div className="space-y-3">
      <DialogHeader><DialogTitle>{t("editDraft")}</DialogTitle></DialogHeader>
      {v.loading && <LoadingState rows={2} />}
      {v.error && <ErrorState error={v.error} onRetry={v.reload} />}
      {v.data && (
        <>
          {v.data.review_note && <Alert variant="warning"><AlertDescription>{t("reviewNote")}: {v.data.review_note}</AlertDescription></Alert>}
          <Label htmlFor="ed-text">{t("correctedText")}</Label>
          <Textarea id="ed-text" rows={16} value={value} onChange={(ev) => setText(ev.target.value)} />
          {save.error && <Alert variant="destructive"><AlertDescription>{errorMessage(save.error)}</AlertDescription></Alert>}
          <DialogFooter>
            <Button variant="outline" onClick={onClose}>{c("close")}</Button>
            <Button disabled={save.busy || value.trim().length < 10} onClick={async () => {
              const r = await save.run(() => api.patch<Version>(`/api/v1/admin/versions/${id}`, { extracted_text: value }));
              if (r) onSaved();
            }}>{save.busy ? c("saving") : t("save")}</Button>
          </DialogFooter>
        </>
      )}
    </div>
  );
}
