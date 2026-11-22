"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import {
  CloudDownload,
  Eye,
  FileText,
  History,
  Loader2,
  PauseCircle,
  PlayCircle,
  RotateCcw,
  Search,
  Upload,
  ClipboardPaste,
  ExternalLink,
} from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input, Label, Select } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { JobStatusBadge, ScopeBadge, SourceStatusBadge, TestDataBadge } from "@/components/shared/badges";
import { EmptyState, ErrorState, LoadingState, PageHeader, Pagination } from "@/components/shared/states";
import { AddSourceDialog } from "@/features/admin/sources/add-source-dialog";
import { SourceDocumentsDialog, type SourceDialogMode } from "@/features/admin/sources/source-documents-dialog";
import { SubmitTextDialog } from "@/features/admin/sources/submit-text-dialog";
import { api, errorMessage } from "@/lib/api";
import { MAX_UPLOAD_MB, SOURCE_STATUSES, SOURCE_TYPES } from "@/lib/constants";
import { waitForJob } from "@/lib/jobs";
import { useApi } from "@/lib/use-api";
import { useCategoryName } from "@/lib/use-category-name";
import { formatDateTime } from "@/lib/utils";
import type { Job, JobAccepted, Page, Source } from "@/types/api";

interface Notice {
  kind: "success" | "destructive" | "info";
  text: string;
}

export function SourcesPage() {
  const t = useTranslations("admin.sources");
  const c = useTranslations("common");
  const e = useTranslations("enums");
  const locale = useLocale();
  const categoryName = useCategoryName();

  const [status, setStatus] = useState("");
  const [sourceType, setSourceType] = useState("");
  const [draftQ, setDraftQ] = useState("");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [runningJobs, setRunningJobs] = useState<Record<string, Job | { status: "queued"; id: string }>>({});
  const [dialog, setDialog] = useState<{ source: Source; mode: SourceDialogMode } | null>(null);
  const [textSource, setTextSource] = useState<Source | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const uploadRef = useRef<HTMLInputElement>(null);
  const uploadTarget = useRef<Source | null>(null);
  const abort = useRef<AbortController | null>(null);

  const query = { status, source_type: sourceType, q, page, page_size: 20 };
  const { data, error, loading, reload } = useApi<Page<Source>>(`sources:${JSON.stringify(query)}`, () =>
    api.get<Page<Source>>("/api/v1/admin/sources", query),
  );

  useEffect(() => {
    abort.current = new AbortController();
    const ctl = abort.current;
    return () => ctl.abort();
  }, []);

  /** Follow a job to its end, showing the real outcome reported by the backend. */
  const track = useCallback(
    async (source: Source, jobId: string) => {
      setRunningJobs((m) => ({ ...m, [source.id]: { id: jobId, status: "queued" } }));
      try {
        const job = await waitForJob(jobId, {
          signal: abort.current?.signal,
          onUpdate: (j) => setRunningJobs((m) => ({ ...m, [source.id]: j })),
        });
        if (job.status === "succeeded") {
          setNotice({
            kind: "success",
            text: t("jobSucceeded", { title: source.title, outcome: job.outcome ? e(`jobOutcome.${job.outcome}`) : "" }),
          });
        } else {
          setNotice({
            kind: "destructive",
            text: t("jobFailed", { title: source.title, error: job.error_message ?? job.error_code ?? "unknown" }),
          });
        }
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") return;
        setNotice({ kind: "destructive", text: errorMessage(err) });
      } finally {
        setRunningJobs((m) => {
          const { [source.id]: _drop, ...rest } = m;
          void _drop;
          return rest;
        });
        reload();
      }
    },
    [e, reload, t],
  );

  async function withBusy(id: string, fn: () => Promise<void>) {
    setBusyId(id);
    setNotice(null);
    try {
      await fn();
    } catch (err) {
      setNotice({ kind: "destructive", text: errorMessage(err) });
    } finally {
      setBusyId(null);
    }
  }

  const fetchNow = (s: Source) =>
    withBusy(s.id, async () => {
      const res = await api.post<JobAccepted>(`/api/v1/admin/sources/${s.id}/ingest`);
      setNotice({ kind: "info", text: t("jobQueued", { title: s.title }) });
      void track(s, res.job_id);
    });

  const retry = (s: Source) =>
    withBusy(s.id, async () => {
      const lastJob = s.last_ingestion_result?.job_id;
      const res = lastJob
        ? await api.post<JobAccepted>(`/api/v1/admin/ingestion-jobs/${lastJob}/retry`)
        : await api.post<JobAccepted>(`/api/v1/admin/sources/${s.id}/ingest`);
      setNotice({ kind: "info", text: t("jobQueued", { title: s.title }) });
      void track(s, res.job_id);
    });

  const toggle = (s: Source) =>
    withBusy(s.id, async () => {
      await api.post<Source>(`/api/v1/admin/sources/${s.id}/${s.is_active ? "disable" : "enable"}`);
      setNotice({ kind: "success", text: s.is_active ? t("disabled", { title: s.title }) : t("enabled", { title: s.title }) });
      reload();
    });

  function pickFile(s: Source) {
    uploadTarget.current = s;
    uploadRef.current?.click();
  }

  async function onFile(ev: React.ChangeEvent<HTMLInputElement>) {
    const file = ev.target.files?.[0];
    const s = uploadTarget.current;
    ev.target.value = "";
    if (!file || !s) return;
    const ext = file.name.split(".").pop()?.toLowerCase();
    if (ext !== s.source_type) {
      setNotice({ kind: "destructive", text: t("wrongFileType", { type: s.source_type.toUpperCase() }) });
      return;
    }
    if (file.size > MAX_UPLOAD_MB * 1024 * 1024) {
      setNotice({ kind: "destructive", text: t("fileTooLarge", { mb: MAX_UPLOAD_MB }) });
      return;
    }
    await withBusy(s.id, async () => {
      const fd = new FormData();
      fd.append("file", file);
      const res = await api.upload<JobAccepted>(`/api/v1/admin/sources/${s.id}/upload`, fd);
      setNotice({ kind: "info", text: t("jobQueued", { title: s.title }) });
      void track(s, res.job_id);
    });
  }

  return (
    <div>
      <PageHeader
        title={t("title")}
        description={t("subtitle")}
        actions={
          <AddSourceDialog
            onCreated={(s) => {
              setNotice({ kind: "success", text: t("created", { title: s.title }) });
              reload();
            }}
          />
        }
      />

      <form
        role="search"
        className="mb-4 grid gap-3 rounded-xl border border-border bg-card p-4 sm:grid-cols-[2fr_1fr_1fr_auto]"
        onSubmit={(ev) => {
          ev.preventDefault();
          setQ(draftQ.trim());
          setPage(1);
        }}
      >
        <div>
          <Label htmlFor="s-q" className="mb-1.5 block">
            {c("search")}
          </Label>
          <Input id="s-q" value={draftQ} onChange={(ev) => setDraftQ(ev.target.value)} placeholder={t("searchPlaceholder")} />
        </div>
        <div>
          <Label htmlFor="s-status" className="mb-1.5 block">
            {t("fields.status")}
          </Label>
          <Select id="s-status" value={status} onChange={(ev) => { setStatus(ev.target.value); setPage(1); }}>
            <option value="">{c("all")}</option>
            {SOURCE_STATUSES.map((s) => (
              <option key={s} value={s}>
                {e(`sourceStatus.${s}`)}
              </option>
            ))}
          </Select>
        </div>
        <div>
          <Label htmlFor="s-type" className="mb-1.5 block">
            {t("fields.sourceType")}
          </Label>
          <Select id="s-type" value={sourceType} onChange={(ev) => { setSourceType(ev.target.value); setPage(1); }}>
            <option value="">{c("all")}</option>
            {SOURCE_TYPES.map((s) => (
              <option key={s} value={s}>
                {e(`sourceType.${s}`)}
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

      <input ref={uploadRef} type="file" accept=".pdf,.docx" className="sr-only" tabIndex={-1} aria-hidden onChange={onFile} data-testid="upload-input" />

      {notice && (
        <Alert variant={notice.kind} className="mb-4">
          <AlertDescription>{notice.text}</AlertDescription>
        </Alert>
      )}

      {loading && <LoadingState rows={4} />}
      {!loading && error && <ErrorState error={error} onRetry={reload} />}
      {!loading && !error && data && data.items.length === 0 && (
        <EmptyState title={t("emptyTitle")} description={t("emptyBody")} />
      )}
      {data && data.items.length > 0 && (
        <>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("fields.title")}</TableHead>
                <TableHead>{t("fields.status")}</TableHead>
                <TableHead>{t("columns.details")}</TableHead>
                <TableHead>{t("columns.timing")}</TableHead>
                <TableHead>{t("columns.lastResult")}</TableHead>
                <TableHead>{t("columns.actions")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.items.map((s) => {
                const running = runningJobs[s.id];
                const busy = busyId === s.id || !!running;
                const isWebsite = s.source_type === "website";
                const isFile = s.source_type === "pdf" || s.source_type === "docx";
                const isText = s.source_type === "manual_text" || s.source_type === "kakao_message";
                return (
                  <TableRow key={s.id}>
                    <TableCell className="min-w-56">
                      <div className="font-medium">{s.title}</div>
                      <div className="text-xs text-muted-foreground">{s.organization}</div>
                      {s.original_url && (
                        <a href={s.original_url} target="_blank" rel="noopener noreferrer" className="mt-0.5 inline-flex max-w-xs items-center gap-1 break-all text-xs text-primary hover:underline">
                          <ExternalLink className="size-3 shrink-0" aria-hidden /> {s.original_url}
                        </a>
                      )}
                      {s.is_test_data && (
                        <div className="mt-1">
                          <TestDataBadge />
                        </div>
                      )}
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-col items-start gap-1">
                        <SourceStatusBadge status={s.status} />
                        {!s.is_active && <Badge variant="muted">{e("sourceStatus.inactive")}</Badge>}
                        {running && (
                          <span className="inline-flex items-center gap-1 text-xs text-muted-foreground" role="status">
                            <Loader2 className="size-3 animate-spin" aria-hidden />
                            {"status" in running ? e(`jobStatus.${running.status}`) : ""}
                          </span>
                        )}
                      </div>
                    </TableCell>
                    <TableCell className="text-xs">
                      <div className="flex flex-wrap gap-1">
                        <Badge variant="outline">{e(`sourceType.${s.source_type}`)}</Badge>
                        <ScopeBadge scope={s.scope} />
                      </div>
                      <dl className="mt-1 space-y-0.5 text-muted-foreground">
                        <div>{e(`authority.${s.authority_type}`)}</div>
                        <div>{categoryName(s.category)} · {s.language}</div>
                        <div>
                          {t("fields.sync")}: {e(`sync.${s.sync_frequency}`)}
                        </div>
                        <div>
                          {t("columns.createdBy")}: {s.created_by_name ?? "—"}
                        </div>
                        <div>
                          {t("columns.documents")}: {s.document_count}
                        </div>
                      </dl>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      <div>
                        {t("columns.lastChecked")}: {formatDateTime(s.last_checked_at, locale)}
                      </div>
                      <div>
                        {t("columns.lastUpdated")}: {formatDateTime(s.updated_at, locale)}
                      </div>
                    </TableCell>
                    <TableCell className="max-w-56 text-xs">
                      {s.last_ingestion_result ? (
                        <div className="space-y-1">
                          <JobStatusBadge status={s.last_ingestion_result.status} />
                          {s.last_ingestion_result.outcome && (
                            <span className="ml-1 text-muted-foreground">{e(`jobOutcome.${s.last_ingestion_result.outcome}`)}</span>
                          )}
                          {s.last_ingestion_result.message && (
                            <p className="break-words text-muted-foreground">{s.last_ingestion_result.message}</p>
                          )}
                        </div>
                      ) : (
                        <span className="text-muted-foreground">{t("noResultYet")}</span>
                      )}
                    </TableCell>
                    <TableCell className="min-w-44">
                      <div className="flex flex-wrap gap-1">
                        {isWebsite && (
                          <Button size="sm" disabled={busy || !s.is_active} onClick={() => fetchNow(s)}>
                            <CloudDownload /> {t("actions.fetchNow")}
                          </Button>
                        )}
                        {isFile && (
                          <Button size="sm" disabled={busy || !s.is_active} onClick={() => pickFile(s)}>
                            <Upload /> {t("actions.upload")}
                          </Button>
                        )}
                        {isText && (
                          <Button size="sm" disabled={busy || !s.is_active} onClick={() => setTextSource(s)}>
                            <ClipboardPaste /> {t("actions.submitText")}
                          </Button>
                        )}
                        {s.status === "failed" && (
                          <Button size="sm" variant="outline" disabled={busy} onClick={() => retry(s)}>
                            <RotateCcw /> {t("actions.retry")}
                          </Button>
                        )}
                        <Button size="sm" variant="outline" onClick={() => setDialog({ source: s, mode: "content" })}>
                          <Eye /> {t("actions.viewContent")}
                        </Button>
                        <Button size="sm" variant="outline" onClick={() => setDialog({ source: s, mode: "versions" })}>
                          <History /> {t("actions.viewVersions")}
                        </Button>
                        <Button size="sm" variant="ghost" disabled={busyId === s.id} onClick={() => toggle(s)}>
                          {s.is_active ? <PauseCircle /> : <PlayCircle />}
                          {s.is_active ? t("actions.disable") : t("actions.enable")}
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
          <Pagination page={data.page} pageSize={data.page_size} total={data.total} onChange={setPage} />
          <p className="mt-3 text-xs text-muted-foreground">
            <FileText className="mr-1 inline size-3" aria-hidden />
            <Link href="/admin/documents" className="underline">
              {t("goToDocuments")}
            </Link>
          </p>
        </>
      )}

      <SourceDocumentsDialog source={dialog?.source ?? null} mode={dialog?.mode ?? "content"} onClose={() => setDialog(null)} />
      <SubmitTextDialog
        source={textSource}
        onClose={() => setTextSource(null)}
        onDone={(job) => {
          const s = textSource;
          setTextSource(null);
          setNotice(
            job.status === "failed"
              ? { kind: "destructive", text: t("jobFailed", { title: s?.title ?? "", error: job.error_message ?? job.error_code ?? "unknown" }) }
              : { kind: "success", text: t("jobSucceeded", { title: s?.title ?? "", outcome: job.outcome ? e(`jobOutcome.${job.outcome}`) : "" }) },
          );
          reload();
        }}
      />
    </div>
  );
}
