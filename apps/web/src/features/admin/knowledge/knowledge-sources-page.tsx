"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import {
  ArrowDown,
  ArrowUp,
  ClipboardPaste,
  CloudDownload,
  ExternalLink,
  Eye,
  History,
  Loader2,
  PauseCircle,
  Pencil,
  PlayCircle,
  Plus,
  RotateCcw,
  Search,
  Upload,
} from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input, Label, Select } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { JobStatusBadge, ScopeBadge, SourceStatusBadge, TestDataBadge } from "@/components/shared/badges";
import { EmptyState, ErrorState, LoadingState, PageHeader, Pagination } from "@/components/shared/states";
import { EditSourceDialog } from "@/features/admin/knowledge/edit-source-dialog";
import { documentKind, validateDocumentFile, type DocumentKind } from "@/features/admin/knowledge/intake-utils";
import { KnowledgeStatsCards } from "@/features/admin/knowledge/stats-cards";
import { isAdminRole, useMe } from "@/features/admin/shell/admin-context";
import { SourceDocumentsDialog, type SourceDialogMode } from "@/features/admin/sources/source-documents-dialog";
import { SubmitTextDialog } from "@/features/admin/sources/submit-text-dialog";
import { api, errorMessage } from "@/lib/api";
import { CATEGORY_SLUGS, FETCHABLE_SOURCE_TYPES, FILE_SOURCE_TYPES, MAX_UPLOAD_MB, SOURCE_STATUSES, SOURCE_TYPES } from "@/lib/constants";
import { waitForJob } from "@/lib/jobs";
import { useApi } from "@/lib/use-api";
import { useCategoryName } from "@/lib/use-category-name";
import { formatDateTime } from "@/lib/utils";
import type { Job, JobAccepted, Page, Source } from "@/types/api";

type SortKey = "title" | "organization" | "source_type" | "category" | "last_checked_at" | "updated_at" | "status" | "created_at";
interface Notice {
  kind: "success" | "destructive" | "info";
  text: string;
}
const ACCEPT: Record<string, string> = { pdf: ".pdf", docx: ".docx", text_file: ".txt,.md,.markdown" };

export function KnowledgeSourcesPage() {
  const me = useMe();
  const t = useTranslations("admin.ks");
  if (!isAdminRole(me.role)) {
    return (
      <Alert variant="info">
        <AlertDescription>
          {t("supporterRedirect")}{" "}
          <Link className="underline" href="/admin/submissions">{t("mySubmissions")}</Link>
        </AlertDescription>
      </Alert>
    );
  }
  return <AdminKnowledgeSources />;
}

function AdminKnowledgeSources() {
  const t = useTranslations("admin.ks");
  const ts = useTranslations("admin.sources");
  const c = useTranslations("common");
  const e = useTranslations("enums");
  const locale = useLocale();
  const categoryName = useCategoryName();

  const [status, setStatus] = useState("");
  const [sourceType, setSourceType] = useState("");
  const [category, setCategory] = useState("");
  const [draftQ, setDraftQ] = useState("");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState<SortKey>("created_at");
  const [order, setOrder] = useState<"asc" | "desc">("desc");
  const [notice, setNotice] = useState<Notice | null>(null);
  const [running, setRunning] = useState<Record<string, Job | { status: "queued"; id: string }>>({});
  const [dialog, setDialog] = useState<{ source: Source; mode: SourceDialogMode } | null>(null);
  const [textSource, setTextSource] = useState<Source | null>(null);
  const [editing, setEditing] = useState<Source | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [statsKey, setStatsKey] = useState(0);
  const uploadRef = useRef<HTMLInputElement>(null);
  const uploadTarget = useRef<Source | null>(null);
  const abort = useRef<AbortController | null>(null);

  const query = { status, source_type: sourceType, category, q, page, page_size: 20, sort, order };
  const { data, error, loading, reload: reloadList } = useApi<Page<Source>>(`ks:${JSON.stringify(query)}`, () =>
    api.get<Page<Source>>("/api/v1/admin/sources", query),
  );
  const reload = useCallback(() => {
    reloadList();
    setStatsKey((k) => k + 1);
  }, [reloadList]);

  useEffect(() => {
    abort.current = new AbortController();
    const ctl = abort.current;
    return () => ctl.abort();
  }, []);

  const track = useCallback(
    async (source: Source, jobId: string) => {
      setRunning((m) => ({ ...m, [source.id]: { id: jobId, status: "queued" } }));
      try {
        const job = await waitForJob(jobId, {
          signal: abort.current?.signal,
          onUpdate: (j) => setRunning((m) => ({ ...m, [source.id]: j })),
        });
        setNotice(
          job.status === "succeeded"
            ? { kind: "success", text: ts("jobSucceeded", { title: source.title, outcome: job.outcome ? e(`jobOutcome.${job.outcome}`) : "" }) }
            : { kind: "destructive", text: ts("jobFailed", { title: source.title, error: job.error_message ?? job.error_code ?? "unknown" }) },
        );
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") return;
        setNotice({ kind: "destructive", text: errorMessage(err) });
      } finally {
        setRunning((m) => {
          const { [source.id]: _drop, ...rest } = m;
          void _drop;
          return rest;
        });
        reload();
      }
    },
    [e, reload, ts],
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
      setNotice({ kind: "info", text: ts("jobQueued", { title: s.title }) });
      void track(s, res.job_id);
    });

  const retry = (s: Source) =>
    withBusy(s.id, async () => {
      const lastJob = s.last_ingestion_result?.job_id;
      if (!lastJob) throw new Error(t("noJobToRetry"));
      const res = await api.post<JobAccepted>(`/api/v1/admin/ingestion-jobs/${lastJob}/retry`);
      setNotice({ kind: "info", text: ts("jobQueued", { title: s.title }) });
      void track(s, res.job_id);
    });

  const toggle = (s: Source) =>
    withBusy(s.id, async () => {
      await api.post<Source>(`/api/v1/admin/sources/${s.id}/${s.is_active ? "disable" : "enable"}`);
      setNotice({ kind: "success", text: s.is_active ? ts("disabled", { title: s.title }) : ts("enabled", { title: s.title }) });
      reload();
    });

  function pickFile(s: Source) {
    uploadTarget.current = s;
    if (uploadRef.current) uploadRef.current.accept = ACCEPT[s.source_type] ?? "";
    uploadRef.current?.click();
  }

  async function onFile(ev: React.ChangeEvent<HTMLInputElement>) {
    const file = ev.target.files?.[0];
    const s = uploadTarget.current;
    ev.target.value = "";
    if (!file || !s) return;
    const problem = validateDocumentFile(file, MAX_UPLOAD_MB, s.source_type as DocumentKind);
    if (problem) {
      setNotice({ kind: "destructive", text: t(`fileErrors.${problem}`, { mb: MAX_UPLOAD_MB, kind: documentKind(file.name) ?? "?" }) });
      return;
    }
    await withBusy(s.id, async () => {
      const fd = new FormData();
      fd.append("file", file);
      const res = await api.upload<JobAccepted>(`/api/v1/admin/sources/${s.id}/upload`, fd);
      setNotice({ kind: "info", text: ts("jobQueued", { title: s.title }) });
      void track(s, res.job_id);
    });
  }

  function sortBy(key: SortKey) {
    if (sort === key) setOrder((o) => (o === "asc" ? "desc" : "asc"));
    else {
      setSort(key);
      setOrder(key === "title" || key === "organization" ? "asc" : "desc");
    }
    setPage(1);
  }
  return (
    <div>
      <PageHeader
        title={t("title")}
        description={t("subtitle")}
        actions={
          <Button asChild>
            <Link href="/admin/knowledge-sources/new">
              <Plus /> {t("addKnowledge")}
            </Link>
          </Button>
        }
      />
      <KnowledgeStatsCards refreshKey={statsKey} />

      <form
        role="search"
        className="mb-4 grid gap-3 rounded-xl border border-border bg-card p-4 sm:grid-cols-2 lg:grid-cols-[2fr_1fr_1fr_1fr_auto]"
        onSubmit={(ev) => {
          ev.preventDefault();
          setQ(draftQ.trim());
          setPage(1);
        }}
      >
        <div>
          <Label htmlFor="ks-q" className="mb-1.5 block">{c("search")}</Label>
          <Input id="ks-q" value={draftQ} onChange={(ev) => setDraftQ(ev.target.value)} placeholder={ts("searchPlaceholder")} />
        </div>
        <FilterSelect id="ks-cat" label={t("meta.category")} value={category} onChange={(v) => { setCategory(v); setPage(1); }}
          options={CATEGORY_SLUGS.map((x) => [x, categoryName(x)])} all={c("all")} />
        <FilterSelect id="ks-type" label={ts("fields.sourceType")} value={sourceType} onChange={(v) => { setSourceType(v); setPage(1); }}
          options={SOURCE_TYPES.map((x) => [x, e(`sourceType.${x}`)])} all={c("all")} />
        <FilterSelect id="ks-status" label={ts("fields.status")} value={status} onChange={(v) => { setStatus(v); setPage(1); }}
          options={SOURCE_STATUSES.map((x) => [x, e(`sourceStatus.${x}`)])} all={c("all")} />
        <div className="flex items-end">
          <Button type="submit" className="w-full"><Search /> {c("search")}</Button>
        </div>
      </form>

      <input ref={uploadRef} type="file" className="sr-only" tabIndex={-1} aria-hidden onChange={onFile} data-testid="upload-input" />

      {notice && (
        <Alert variant={notice.kind} className="mb-4"><AlertDescription>{notice.text}</AlertDescription></Alert>
      )}

      {loading && !data && <LoadingState rows={4} />}
      {!loading && error && <ErrorState error={error} onRetry={reload} />}
      {!loading && !error && data && data.items.length === 0 && (
        <EmptyState title={ts("emptyTitle")} description={t("emptyBody")} />
      )}
      {data && data.items.length > 0 && (
        <>
          <Table>
            <TableHeader>
              <TableRow>
                <SortHead sort={sort} order={order} onSort={sortBy} k="title">{ts("fields.title")}</SortHead>
                <SortHead sort={sort} order={order} onSort={sortBy} k="source_type">{t("columns.type")}</SortHead>
                <SortHead sort={sort} order={order} onSort={sortBy} k="category">{t("columns.categoryLanguage")}</SortHead>
                <SortHead sort={sort} order={order} onSort={sortBy} k="last_checked_at">{ts("columns.lastChecked")}</SortHead>
                <SortHead sort={sort} order={order} onSort={sortBy} k="updated_at">{ts("columns.lastUpdated")}</SortHead>
                <SortHead sort={sort} order={order} onSort={sortBy} k="status">{ts("fields.status")}</SortHead>
                <TableHead>{ts("columns.documents")}</TableHead>
                <TableHead>{ts("columns.actions")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.items.map((s) => {
                const run = running[s.id];
                const busy = busyId === s.id || !!run;
                const fetchable = FETCHABLE_SOURCE_TYPES.includes(s.source_type);
                const isFile = FILE_SOURCE_TYPES.includes(s.source_type);
                const isText = s.source_type === "manual_text" || s.source_type === "kakao_message";
                const failed = s.status === "failed" || s.status === "blocked" || s.last_ingestion_result?.status === "failed";
                return (
                  <TableRow key={s.id}>
                    <TableCell className="min-w-56">
                      <Link href={`/admin/knowledge-sources/${s.id}`} className="font-medium hover:underline">{s.title}</Link>
                      <div className="text-xs text-muted-foreground">{s.organization}</div>
                      {s.original_url && (
                        <a href={s.original_url} target="_blank" rel="noopener noreferrer" className="mt-0.5 inline-flex max-w-xs items-center gap-1 break-all text-xs text-primary hover:underline">
                          <ExternalLink className="size-3 shrink-0" aria-hidden /> {s.original_url}
                        </a>
                      )}
                      {s.is_test_data && <div className="mt-1"><TestDataBadge /></div>}
                    </TableCell>
                    <TableCell className="text-xs">
                      <Badge variant="outline">{e(`sourceType.${s.source_type}`)}</Badge>
                      <div className="mt-1"><ScopeBadge scope={s.scope} /></div>
                      <div className="mt-1 text-muted-foreground">{e(`authority.${s.authority_type}`)}</div>
                      {fetchable && <div className="text-muted-foreground">{ts("fields.sync")}: {e(`sync.${s.sync_frequency}`)}</div>}
                    </TableCell>
                    <TableCell className="text-xs">{categoryName(s.category)}<div className="text-muted-foreground">{s.language}</div></TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {formatDateTime(s.last_checked_at, locale)}
                      {s.last_success_at && <div>{t("lastSuccess")}: {formatDateTime(s.last_success_at, locale)}</div>}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">{formatDateTime(s.last_change_at ?? s.updated_at, locale)}</TableCell>
                    <TableCell className="max-w-56 text-xs">
                      <div className="flex flex-col items-start gap-1">
                        <SourceStatusBadge status={s.status} />
                        {run && (
                          <span className="inline-flex items-center gap-1 text-muted-foreground" role="status">
                            <Loader2 className="size-3 animate-spin" aria-hidden /> {e(`jobStatus.${run.status}`)}
                          </span>
                        )}
                        {s.last_ingestion_result && (
                          <span className="text-muted-foreground">
                            <JobStatusBadge status={s.last_ingestion_result.status} />{" "}
                            <span className="break-words">{s.last_ingestion_result.message}</span>
                          </span>
                        )}
                      </div>
                    </TableCell>
                    <TableCell className="text-center">{s.document_count}</TableCell>
                    <TableCell className="min-w-52">
                      <div className="flex flex-wrap gap-1">
                        {fetchable && (
                          <Button size="sm" disabled={busy || !s.is_active} onClick={() => fetchNow(s)}><CloudDownload /> {ts("actions.fetchNow")}</Button>
                        )}
                        {isFile && (
                          <Button size="sm" disabled={busy || !s.is_active} onClick={() => pickFile(s)}><Upload /> {ts("actions.upload")}</Button>
                        )}
                        {isText && (
                          <Button size="sm" disabled={busy || !s.is_active} onClick={() => setTextSource(s)}><ClipboardPaste /> {ts("actions.submitText")}</Button>
                        )}
                        {failed && s.last_ingestion_result?.job_id && (
                          <Button size="sm" variant="outline" disabled={busy} onClick={() => retry(s)}><RotateCcw /> {ts("actions.retry")}</Button>
                        )}
                        <Button size="sm" variant="outline" asChild>
                          <Link href={`/admin/knowledge-sources/${s.id}`}><Eye /> {t("viewDetails")}</Link>
                        </Button>
                        <Button size="sm" variant="outline" onClick={() => setDialog({ source: s, mode: "content" })}>{ts("actions.viewContent")}</Button>
                        <Button size="sm" variant="outline" onClick={() => setDialog({ source: s, mode: "versions" })}><History /> {ts("actions.viewVersions")}</Button>
                        <Button size="sm" variant="ghost" onClick={() => setEditing(s)}><Pencil /> {t("edit")}</Button>
                        <Button size="sm" variant="ghost" disabled={busyId === s.id} onClick={() => toggle(s)}>
                          {s.is_active ? <PauseCircle /> : <PlayCircle />}
                          {s.is_active ? ts("actions.disable") : ts("actions.enable")}
                        </Button>
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

      <SourceDocumentsDialog source={dialog?.source ?? null} mode={dialog?.mode ?? "content"} onClose={() => setDialog(null)} />
      <EditSourceDialog
        source={editing}
        onClose={() => setEditing(null)}
        onSaved={(s) => {
          setEditing(null);
          setNotice({ kind: "success", text: t("saved", { title: s.title }) });
          reload();
        }}
      />
      <SubmitTextDialog
        source={textSource}
        onClose={() => setTextSource(null)}
        onDone={(job) => {
          const s = textSource;
          setTextSource(null);
          setNotice(
            job.status === "failed"
              ? { kind: "destructive", text: ts("jobFailed", { title: s?.title ?? "", error: job.error_message ?? job.error_code ?? "unknown" }) }
              : { kind: "success", text: ts("jobSucceeded", { title: s?.title ?? "", outcome: job.outcome ? e(`jobOutcome.${job.outcome}`) : "" }) },
          );
          reload();
        }}
      />
    </div>
  );
}

function SortHead({ k, sort, order, onSort, children }: {
  k: SortKey; sort: SortKey; order: "asc" | "desc"; onSort: (k: SortKey) => void; children: React.ReactNode;
}) {
  return (
    <TableHead aria-sort={sort === k ? (order === "asc" ? "ascending" : "descending") : "none"}>
      <button type="button" className="inline-flex items-center gap-1 hover:underline" onClick={() => onSort(k)}>
        {children}
        {sort === k && (order === "asc" ? <ArrowUp className="size-3" aria-hidden /> : <ArrowDown className="size-3" aria-hidden />)}
      </button>
    </TableHead>
  );
}

function FilterSelect({ id, label, value, onChange, options, all }: {
  id: string; label: string; value: string; onChange: (v: string) => void; options: [string, string][]; all: string;
}) {
  return (
    <div>
      <Label htmlFor={id} className="mb-1.5 block">{label}</Label>
      <Select id={id} value={value} onChange={(ev) => onChange(ev.target.value)}>
        <option value="">{all}</option>
        {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </Select>
    </div>
  );
}
