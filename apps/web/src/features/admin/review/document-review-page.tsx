"use client";

import { useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { ArrowLeft } from "lucide-react";
import { Alert } from "@/components/ui/alert";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { ErrorState, LoadingState, PageHeader } from "@/components/shared/states";
import { DocumentHistory } from "@/features/admin/review/review-extras";
import { ReviewPanel } from "@/features/admin/review/review-panel";
import { isAdminRole, useMe } from "@/features/admin/shell/admin-context";
import { api, errorMessage } from "@/lib/api";
import { waitForJob } from "@/lib/jobs";
import { useApi } from "@/lib/use-api";
import type { Chunk, DocumentDetail, JobAccepted, Version } from "@/types/api";

export function DocumentReviewPage({ id }: { id: string }) {
  const t = useTranslations("admin.review");
  const t2 = useTranslations("admin.review2");
  const c = useTranslations("common");
  const e = useTranslations("enums");
  const me = useMe();
  const [histKey, setHistKey] = useState(0);
  const { data, error, loading, reload } = useApi<DocumentDetail>(`admin-doc:${id}`, () =>
    api.get<DocumentDetail>(`/api/v1/admin/documents/${id}`),
  );
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ kind: "success" | "destructive" | "info"; text: string } | null>(null);
  const [chunksFor, setChunksFor] = useState<string | null>(null);

  async function act(fn: () => Promise<string>) {
    setBusy(true);
    setNotice(null);
    try {
      const text = await fn();
      setNotice({ kind: "success", text });
      reload();
      setHistKey((k) => k + 1);
    } catch (err) {
      setNotice({ kind: "destructive", text: errorMessage(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <Link href="/admin/documents" className="mb-3 inline-flex items-center gap-1 text-sm text-primary hover:underline">
        <ArrowLeft className="size-4" /> {t("back")}
      </Link>
      {loading && <LoadingState rows={4} />}
      {!loading && error && <ErrorState error={error} onRetry={reload} />}
      {notice && (
        <Alert variant={notice.kind} className="mb-4">
          {notice.text}
        </Alert>
      )}
      {data && (
        <>
          <PageHeader title={data.title} description={t("subtitle")} />
          <ReviewPanel
            detail={data}
            busy={busy}
            canConfirm={isAdminRole(me.role)}
            handlers={{
              onSaveText: (vid, text) =>
                act(async () => {
                  await api.patch<Version>(`/api/v1/admin/versions/${vid}`, { extracted_text: text });
                  return t2("textSaved");
                }),
              onSaveFields: (vid, fields) =>
                act(async () => {
                  await api.patch<Version>(`/api/v1/admin/versions/${vid}`, { fields });
                  return t2("fieldsSaved");
                }),
              onConfirmFields: (vid, confirmed) =>
                act(async () => {
                  await api.patch<Version>(`/api/v1/admin/versions/${vid}`, { fields_confirmed: confirmed });
                  return confirmed ? t2("fieldsConfirmed") : t2("fieldsUnconfirmed");
                }),
              onRequestChanges: (vid, note) =>
                act(async () => {
                  await api.post<Version>(`/api/v1/admin/versions/${vid}/request-changes`, { note });
                  return t2("changesRequested");
                }),
              onApprove: (vid, note) =>
                act(async () => {
                  await api.post<Version>(`/api/v1/admin/versions/${vid}/approve`, { note: note || undefined });
                  return t("approved");
                }),
              onReject: (vid, reason) =>
                act(async () => {
                  await api.post<Version>(`/api/v1/admin/versions/${vid}/reject`, { reason });
                  return t("rejected");
                }),
              onReprocess: (vid) =>
                act(async () => {
                  await api.post<Version>(`/api/v1/admin/versions/${vid}/reprocess`);
                  return t("reprocessed");
                }),
              onRollback: (vid) =>
                act(async () => {
                  await api.post<DocumentDetail>(`/api/v1/admin/documents/${data.id}/rollback`, { version_id: vid });
                  return t("rolledBack");
                }),
              onCancelDocument: (reason) =>
                act(async () => {
                  await api.post(`/api/v1/admin/documents/${data.id}/cancel`, { reason });
                  return t("canceledDone");
                }),
              onRetryExtraction: () =>
                act(async () => {
                  if (data.source.source_type && !["website", "sch_board"].includes(data.source.source_type)) {
                    throw new Error(t2("retryNotFetchable"));
                  }
                  const res = await api.post<JobAccepted>(`/api/v1/admin/sources/${data.source_id}/ingest`);
                  const job = await waitForJob(res.job_id);
                  if (job.status === "failed") throw new Error(job.error_message ?? job.error_code ?? "failed");
                  return t("retryDone", { outcome: job.outcome ? e(`jobOutcome.${job.outcome}`) : "" });
                }),
              onViewChunks: (vid) => setChunksFor(vid),
            }}
          />
          <div className="mt-8">
            <DocumentHistory documentId={data.id} refreshKey={histKey} />
          </div>
        </>
      )}
      <Dialog open={!!chunksFor} onOpenChange={(o) => !o && setChunksFor(null)}>
        <DialogContent closeLabel={c("close")} className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>{t("chunksTitle")}</DialogTitle>
            <DialogDescription>{t("chunksDescription")}</DialogDescription>
          </DialogHeader>
          {chunksFor && <ChunkList versionId={chunksFor} />}
        </DialogContent>
      </Dialog>
    </div>
  );
}

function ChunkList({ versionId }: { versionId: string }) {
  const t = useTranslations("admin.review");
  const { data, error, loading, reload } = useApi<{ items: Chunk[] }>(`chunks:${versionId}`, () =>
    api.get<{ items: Chunk[] }>(`/api/v1/admin/versions/${versionId}/chunks`),
  );
  if (loading) return <LoadingState rows={2} />;
  if (error) return <ErrorState error={error} onRetry={reload} />;
  if (!data || data.items.length === 0) return <p className="text-sm text-muted-foreground">{t("noChunks")}</p>;
  return (
    <ol className="space-y-3">
      {data.items.map((ch) => (
        <li key={ch.chunk_index} className="rounded-md border border-border p-3 text-sm">
          <p className="mb-1 text-xs text-muted-foreground">
            #{ch.chunk_index}
            {ch.heading ? ` · ${ch.heading}` : ""}
            {ch.page != null ? ` · p.${ch.page}` : ""} · {ch.has_embedding ? t("embeddedYes") : t("embeddedNo")}
          </p>
          <p className="whitespace-pre-wrap">{ch.content}</p>
        </li>
      ))}
    </ol>
  );
}
