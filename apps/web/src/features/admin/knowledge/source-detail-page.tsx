"use client";

import { useState } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { ArrowLeft, ChevronDown, ChevronRight, CloudDownload, ExternalLink, Pencil, RotateCcw, Upload } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { JobStatusBadge, ScopeBadge, SourceStatusBadge, VersionStatusBadge } from "@/components/shared/badges";
import { EmptyState, ErrorState, LoadingState, PageHeader } from "@/components/shared/states";
import { EditSourceDialog } from "@/features/admin/knowledge/edit-source-dialog";
import { DocumentUploadBox } from "@/features/admin/knowledge/intake-document";
import { JobEvents } from "@/features/admin/knowledge/job-events";
import { JobSummary, JobTracker } from "@/features/admin/knowledge/job-tracker";
import { SuppressionsSection } from "@/features/admin/knowledge/suppressions-section";
import { isAdminRole, useMe } from "@/features/admin/shell/admin-context";
import { api, errorMessage } from "@/lib/api";
import { FETCHABLE_SOURCE_TYPES, FILE_SOURCE_TYPES } from "@/lib/constants";
import { useApi } from "@/lib/use-api";
import { useCategoryName } from "@/lib/use-category-name";
import { formatDateTime } from "@/lib/utils";
import type { Job, JobAccepted, SourceDetail, SourceHistory } from "@/types/api";

export function SourceDetailPage({ id }: { id: string }) {
  const t = useTranslations("admin.ks");
  const ts = useTranslations("admin.sources");
  const e = useTranslations("enums");
  const locale = useLocale();
  const categoryName = useCategoryName();
  const me = useMe();
  const [key, setKey] = useState(0);
  const src = useApi<SourceDetail>(`src:${id}:${key}`, () => api.get<SourceDetail>(`/api/v1/admin/sources/${id}`));
  const hist = useApi<SourceHistory>(`src-hist:${id}:${key}`, () => api.get<SourceHistory>(`/api/v1/admin/sources/${id}/history`));
  const [activeJob, setActiveJob] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [showUpload, setShowUpload] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const refresh = () => setKey((k) => k + 1);

  async function fetchNow() {
    setErr(null);
    try {
      const res = await api.post<JobAccepted>(`/api/v1/admin/sources/${id}/ingest`);
      setActiveJob(res.job_id);
    } catch (ex) {
      setErr(errorMessage(ex));
    }
  }
  async function retry(job: Job) {
    setErr(null);
    try {
      const res = await api.post<JobAccepted>(`/api/v1/admin/ingestion-jobs/${job.id}/retry`);
      setActiveJob(res.job_id);
    } catch (ex) {
      setErr(errorMessage(ex));
    }
  }

  const s = src.data;
  return (
    <div className="space-y-6">
      <Link href="/admin/knowledge-sources" className="inline-flex items-center gap-1 text-sm text-primary hover:underline">
        <ArrowLeft className="size-4" /> {t("backToSources")}
      </Link>
      {src.loading && !s && <LoadingState rows={4} />}
      {src.error && <ErrorState error={src.error} onRetry={src.reload} />}
      {s && (
        <>
          <PageHeader
            title={s.title}
            description={s.organization}
            actions={
              <div className="flex flex-wrap gap-2">
                {FETCHABLE_SOURCE_TYPES.includes(s.source_type) && (
                  <Button disabled={!s.is_active || !!activeJob} onClick={fetchNow}><CloudDownload /> {ts("actions.fetchNow")}</Button>
                )}
                {FILE_SOURCE_TYPES.includes(s.source_type) && (
                  <Button variant="outline" onClick={() => setShowUpload((v) => !v)}><Upload /> {t("uploadNewVersion")}</Button>
                )}
                <Button variant="outline" onClick={() => setEditing(true)}><Pencil /> {t("edit")}</Button>
              </div>
            }
          />
          {err && <Alert variant="destructive"><AlertDescription>{err}</AlertDescription></Alert>}
          {activeJob && <JobTracker jobId={activeJob} onDone={() => { setActiveJob(null); refresh(); }} />}
          {showUpload && FILE_SOURCE_TYPES.includes(s.source_type) && (
            <Card><CardContent className="p-4">
              <DocumentUploadBox sourceId={s.id} expected={s.source_type as "pdf" | "docx" | "text_file"} onQueued={(jid) => { setShowUpload(false); setActiveJob(jid); }} />
            </CardContent></Card>
          )}
          <Card>
            <CardContent className="grid gap-4 p-5 text-sm sm:grid-cols-2 lg:grid-cols-3">
              <Meta label={ts("fields.status")}><SourceStatusBadge status={s.status} /></Meta>
              <Meta label={ts("fields.sourceType")}>{e(`sourceType.${s.source_type}`)}</Meta>
              <Meta label={ts("fields.authority")}>{e(`authority.${s.authority_type}`)}</Meta>
              <Meta label={ts("fields.scope")}><ScopeBadge scope={s.scope} /></Meta>
              <Meta label={ts("fields.category")}>{categoryName(s.category)}</Meta>
              <Meta label={ts("fields.language")}>{s.language}</Meta>
              <Meta label={ts("fields.sync")}>{e(`sync.${s.sync_frequency}`)}</Meta>
              <Meta label={ts("columns.lastChecked")}>{formatDateTime(s.last_checked_at, locale)}</Meta>
              <Meta label={t("lastSuccess")}>{formatDateTime(s.last_success_at, locale)}</Meta>
              <Meta label={t("lastChange")}>{formatDateTime(s.last_change_at, locale)}</Meta>
              <Meta label={ts("columns.createdBy")}>{s.created_by_name ?? "—"}</Meta>
              {s.source_type === "sch_board" && <Meta label={t("boardMaxItems")}>{s.config?.max_items ?? "—"} / {t("boardMaxPages")}: {s.config?.max_pages ?? 1}</Meta>}
              {s.original_url && (
                <div className="sm:col-span-2 lg:col-span-3">
                  <Meta label={ts("fields.url")}>
                    <a href={s.original_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 break-all text-primary hover:underline">
                      <ExternalLink className="size-3.5 shrink-0" aria-hidden /> {s.original_url}
                    </a>
                  </Meta>
                </div>
              )}
            </CardContent>
          </Card>

          <section className="space-y-2" aria-labelledby="sd-docs">
            <h2 id="sd-docs" className="text-lg font-semibold">{t("documentsTitle", { count: s.documents.length })}</h2>
            {s.documents.length === 0 ? (
              <EmptyState title={ts("docsDialog.noDocs")} description={ts("docsDialog.noDocsBody")} />
            ) : (
              <Table>
                <TableHeader><TableRow>
                  <TableHead>{ts("fields.title")}</TableHead>
                  <TableHead>{t("latestVersion")}</TableHead>
                  <TableHead>{t("published")}</TableHead>
                  <TableHead><span className="sr-only">{ts("columns.actions")}</span></TableHead>
                </TableRow></TableHeader>
                <TableBody>
                  {s.documents.map((d) => (
                    <TableRow key={d.id}>
                      <TableCell className="min-w-64">
                        <div className="font-medium">{d.title}</div>
                        {d.canonical_url && <a className="break-all text-xs text-primary hover:underline" href={d.canonical_url} target="_blank" rel="noopener noreferrer">{d.canonical_url}</a>}
                      </TableCell>
                      <TableCell>{d.latest_version ? <span className="whitespace-nowrap font-mono text-xs">v{d.latest_version.version_number} <VersionStatusBadge status={d.latest_version.verification_status} /></span> : "—"}</TableCell>
                      <TableCell>{d.current_version_id ? <Badge variant="success">{t("yes")}</Badge> : <Badge variant="muted">{t("no")}</Badge>}</TableCell>
                      <TableCell><Button size="sm" variant="outline" asChild><Link href={`/admin/documents/${d.id}`}>{t("review")}</Link></Button></TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </section>
          <SuppressionsSection sourceId={s.id} canManage={isAdminRole(me.role)} />
        </>
      )}

      <section className="space-y-2" aria-labelledby="sd-jobs">
        <h2 id="sd-jobs" className="text-lg font-semibold">{t("jobsTitle")}</h2>
        {hist.loading && !hist.data && <LoadingState rows={2} />}
        {hist.error && <ErrorState error={hist.error} onRetry={hist.reload} />}
        {hist.data && hist.data.jobs.length === 0 && <p className="text-sm text-muted-foreground">{t("noJobs")}</p>}
        {hist.data && hist.data.jobs.length > 0 && (
          <ul className="space-y-2">
            {hist.data.jobs.map((j) => <JobRow key={j.id} job={j} onRetry={retry} />)}
          </ul>
        )}
      </section>

      {hist.data && hist.data.audit.length > 0 && (
        <section className="space-y-2" aria-labelledby="sd-audit">
          <h2 id="sd-audit" className="text-lg font-semibold">{t("auditTitle")}</h2>
          <Card><CardContent className="p-0">
            <ul className="divide-y divide-border text-sm">
              {hist.data.audit.map((a) => (
                <li key={a.id} className="flex flex-wrap justify-between gap-2 px-4 py-2">
                  <span className="font-mono text-xs">{a.action}</span>
                  <span className="text-xs text-muted-foreground">{formatDateTime(a.created_at, locale)}</span>
                </li>
              ))}
            </ul>
          </CardContent></Card>
        </section>
      )}

      {s && (
        <EditSourceDialog source={editing ? s : null} onClose={() => setEditing(false)} onSaved={() => { setEditing(false); refresh(); }} />
      )}
    </div>
  );
}

function JobRow({ job, onRetry }: { job: Job; onRetry: (j: Job) => void }) {
  const t = useTranslations("admin.ks");
  const e = useTranslations("enums");
  const locale = useLocale();
  const [open, setOpen] = useState(false);
  return (
    <li>
      <Card>
        <CardHeader className="p-3">
          <CardTitle className="flex flex-wrap items-center gap-2 text-sm font-normal">
            <button type="button" aria-expanded={open} onClick={() => setOpen((o) => !o)} className="inline-flex items-center gap-1 font-medium hover:underline">
              {open ? <ChevronDown className="size-4" aria-hidden /> : <ChevronRight className="size-4" aria-hidden />}
              {formatDateTime(job.created_at, locale)}
            </button>
            <JobStatusBadge status={job.status} />
            <Badge variant="outline">{e(`jobType.${job.job_type ?? "ingest"}`)}</Badge>
            <span className="text-xs text-muted-foreground">{e(`trigger.${job.trigger}`)}</span>
            {job.outcome && <span className="text-xs text-muted-foreground">{e(`jobOutcome.${job.outcome}`)}</span>}
            {job.status === "failed" && (
              <Button size="sm" variant="outline" className="ml-auto" onClick={() => onRetry(job)}><RotateCcw /> {t("retry")}</Button>
            )}
          </CardTitle>
        </CardHeader>
        {open && (
          <CardContent className="space-y-2 p-3 pt-0">
            <JobSummary job={job} />
            <JobEvents jobId={job.id} />
          </CardContent>
        )}
      </Card>
    </li>
  );
}

function Meta({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
      <div className="mt-0.5">{children}</div>
    </div>
  );
}
