"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { ArrowLeft, CheckCircle2, Loader2, RotateCcw } from "lucide-react";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { ErrorState, LoadingState, PageHeader } from "@/components/shared/states";
import { ArchiveButton, DeleteDocumentButton, LifecycleBadge, RestoreButton } from "@/features/admin/documents/lifecycle-actions";
import { DocumentHistory } from "@/features/admin/review/review-extras";
import { ReviewPanel } from "@/features/admin/review/review-panel";
import { isAdminRole, useMe } from "@/features/admin/shell/admin-context";
import { api, errorMessage } from "@/lib/api";
import { waitForJob } from "@/lib/jobs";
import { canArchive, canRestore, lifecycleOf } from "@/lib/document-lifecycle";
import { useApi } from "@/lib/use-api";
import { formatDateTime } from "@/lib/utils";
import { activationOutcome, waitForActivation } from "@/lib/version-state";
import type { ApproveResult, Chunk, DocumentDetail, JobAccepted, Version } from "@/types/api";

type Activation =
  | { versionId: string; jobId: string; state: "queued" | "indexing"; detail?: string }
  | { versionId: string; jobId: string; state: "active" }
  | { versionId: string; jobId: string; state: "failed"; error: string }
  | { versionId: string; jobId: string; state: "timeout" };

export function DocumentReviewPage({ id }: { id: string }) {
  const t = useTranslations("admin.review");
  const t2 = useTranslations("admin.review2");
  const c = useTranslations("common");
  const e = useTranslations("enums");
  const tl = useTranslations("admin.lifecycle");
  const locale = useLocale();
  const router = useRouter();
  const me = useMe();
  const [histKey, setHistKey] = useState(0);
  const { data, error, loading, reload } = useApi<DocumentDetail>(`admin-doc:${id}`, () =>
    api.get<DocumentDetail>(`/api/v1/admin/documents/${id}`),
  );
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ kind: "success" | "destructive" | "info"; text: string } | null>(null);
  const [chunksFor, setChunksFor] = useState<string | null>(null);
  const [activation, setActivation] = useState<Activation | null>(null);
  const pollAbort = useRef<AbortController | null>(null);
  useEffect(() => () => pollAbort.current?.abort(), []);

  /** After approval: poll the version until it is active (searchable) or indexing failed. */
  async function track(versionId: string, jobId: string, initial?: Version) {
    pollAbort.current?.abort();
    const ctrl = new AbortController();
    pollAbort.current = ctrl;
    const settle = (v: Version | null, outcome: string) => {
      if (ctrl.signal.aborted) return;
      if (outcome === "active") setActivation({ versionId, jobId, state: "active" });
      else if (outcome === "failed")
        setActivation({ versionId, jobId, state: "failed", error: v?.indexing_error ?? v?.verification_status ?? "failed" });
      else setActivation({ versionId, jobId, state: "timeout" });
      reload();
      setHistKey((k) => k + 1);
    };
    if (initial && activationOutcome(initial) !== "pending") return settle(initial, activationOutcome(initial));
    setActivation({ versionId, jobId, state: "queued" });
    try {
      const res = await waitForActivation(versionId, {
        signal: ctrl.signal,
        onUpdate: (v) => {
          if (!ctrl.signal.aborted && v.indexing_status === "indexing")
            setActivation({ versionId, jobId, state: "indexing", detail: v.indexing_status });
        },
      });
      settle(res.version, res.outcome);
    } catch (err) {
      if (!ctrl.signal.aborted) setNotice({ kind: "destructive", text: errorMessage(err) });
    }
  }

  async function approve(vid: string, note: string) {
    setBusy(true);
    setNotice(null);
    try {
      const res = await api.post<ApproveResult>(`/api/v1/admin/versions/${vid}/approve`, { note: note || undefined });
      void track(vid, res.indexing_job_id, res);
    } catch (err) {
      setNotice({ kind: "destructive", text: errorMessage(err) });
    } finally {
      setBusy(false);
    }
  }

  async function retryIndexing(a: Activation) {
    setBusy(true);
    try {
      const res = await api.post<JobAccepted>(`/api/v1/admin/ingestion-jobs/${encodeURIComponent(a.jobId)}/retry`);
      void track(a.versionId, res.job_id);
    } catch (err) {
      setNotice({ kind: "destructive", text: errorMessage(err) });
    } finally {
      setBusy(false);
    }
  }

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
      {activation && (
        <Alert
          variant={activation.state === "active" ? "success" : activation.state === "failed" ? "destructive" : "info"}
          className="mb-4"
          aria-live="polite"
        >
          <div className="flex flex-wrap items-center gap-2">
            {activation.state === "active" ? (
              <CheckCircle2 className="size-4" aria-hidden />
            ) : activation.state === "queued" || activation.state === "indexing" ? (
              <Loader2 className="size-4 animate-spin" aria-hidden />
            ) : null}
            <span>
              {activation.state === "queued" && t2("approvalQueued")}
              {activation.state === "indexing" && t2("approvalIndexing", { status: e("indexing.indexing") })}
              {activation.state === "active" && t2("activeSearchable")}
              {activation.state === "failed" && t2("indexingFailed", { error: activation.error })}
              {activation.state === "timeout" && t2("indexingStillRunning")}
            </span>
            {activation.state === "failed" && (
              <Button size="sm" variant="outline" disabled={busy} onClick={() => retryIndexing(activation)}>
                <RotateCcw /> {t2("retryIndexing")}
              </Button>
            )}
            {(activation.state === "timeout" || activation.state === "failed") && (
              <Link href="/admin/rag-sync" className="text-sm text-primary underline">
                {t("ragSyncLink")}
              </Link>
            )}
          </div>
        </Alert>
      )}
      {data && (
        <>
          <PageHeader title={data.title} description={t("subtitle")} />
          <LifecycleBar
            lifecycle={lifecycleOf(data)}
            reason={lifecycleOf(data) === "archived" ? data.archive_reason : lifecycleOf(data) === "withdrawn" ? data.canceled_reason : null}
            at={lifecycleOf(data) === "archived" ? data.archived_at : lifecycleOf(data) === "withdrawn" ? data.canceled_at : null}
            locale={locale}
            label={tl("lifecycleLabel")}
            describe={(lc) => tl(`explain.${lc}`)}
            sinceLabel={(when, reason) => (reason ? tl("since", { when, reason }) : tl("sinceNoReason", { when }))}
          >
            {canArchive(lifecycleOf(data)) && isAdminRole(me.role) && (
              <ArchiveButton
                documentId={data.id}
                title={data.title}
                onDone={(text) => {
                  setNotice({ kind: "success", text });
                  reload();
                  setHistKey((k) => k + 1);
                }}
              />
            )}
            {canRestore(lifecycleOf(data)) && isAdminRole(me.role) && (
              <RestoreButton
                documentId={data.id}
                title={data.title}
                lifecycle={lifecycleOf(data)}
                onDone={(text) => {
                  setNotice({ kind: "success", text });
                  reload();
                  setHistKey((k) => k + 1);
                }}
              />
            )}
            {me.role === "super_admin" && (
              <DeleteDocumentButton documentId={data.id} onFinished={() => router.push("/admin/documents")} />
            )}
          </LifecycleBar>
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
              onApprove: (vid, note) => approve(vid, note),
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
              onWithdrawn: (message) => {
                setNotice({ kind: "success", text: message });
                reload();
                setHistKey((k) => k + 1);
              },
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
          <div className="mt-8 scroll-mt-20" id="history">
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

function LifecycleBar({
  lifecycle,
  reason,
  at,
  locale,
  label,
  describe,
  sinceLabel,
  children,
}: {
  lifecycle: ReturnType<typeof lifecycleOf>;
  reason?: string | null;
  at?: string | null;
  locale: string;
  label: string;
  describe: (lc: ReturnType<typeof lifecycleOf>) => string;
  sinceLabel: (when: string, reason?: string | null) => string;
  children: React.ReactNode;
}) {
  return (
    <section
      aria-label={label}
      className="mb-6 flex flex-wrap items-start justify-between gap-3 rounded-xl border border-border bg-card p-4"
    >
      <div className="min-w-56 flex-1 space-y-1 text-sm">
        <div className="flex items-center gap-2">
          <span className="font-medium">{label}</span>
          <LifecycleBadge lifecycle={lifecycle} />
        </div>
        <p className="text-muted-foreground">{describe(lifecycle)}</p>
        {at && <p className="text-xs text-muted-foreground">{sinceLabel(formatDateTime(at, locale), reason)}</p>}
      </div>
      <div className="flex flex-wrap gap-2">{children}</div>
    </section>
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
