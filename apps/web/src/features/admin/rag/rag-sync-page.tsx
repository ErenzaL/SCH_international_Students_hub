"use client";

import { Fragment, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { History, Loader2, RefreshCw, RotateCcw, ScrollText, Search } from "lucide-react";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { EmptyState, ErrorState, LoadingState, PageHeader } from "@/components/shared/states";
import { IndexingStatusBadge, JobStatusBadge, SourceStatusBadge } from "@/components/shared/badges";
import { JobEvents } from "@/features/admin/knowledge/job-events";
import { WithdrawButton } from "@/features/admin/review/withdraw-dialog";
import { api, errorMessage } from "@/lib/api";
import { FETCHABLE_SOURCE_TYPES } from "@/lib/constants";
import { formatDateTime } from "@/lib/utils";
import { ragHasActiveWork, relativeTime } from "@/lib/version-state";
import type { JobAccepted, RagStatus } from "@/types/api";

const REFRESH_MS = 10_000;

/** RAG synchronization dashboard (GET /admin/rag/status). Real database values only. */
export function RagSyncPage() {
  const t = useTranslations("admin.rag");
  const e = useTranslations("enums");
  const locale = useLocale();
  const [data, setData] = useState<RagStatus | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [notice, setNotice] = useState<{ kind: "success" | "destructive"; text: string } | null>(null);
  const [openLog, setOpenLog] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setRefreshing(true);
    try {
      const res = await api.get<RagStatus>("/api/v1/admin/rag/status");
      setData(res);
      setError(null);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- start of an async fetch cycle
    void load();
  }, [load]);

  const active = ragHasActiveWork(data);
  // Auto-refresh only while indexing work is queued/running and the tab is visible.
  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => {
      if (document.visibilityState === "visible") void load();
    }, REFRESH_MS);
    return () => clearInterval(id);
  }, [active, load]);

  async function act(id: string, fn: () => Promise<string>) {
    setBusyId(id);
    setNotice(null);
    try {
      setNotice({ kind: "success", text: await fn() });
      void load();
    } catch (err) {
      setNotice({ kind: "destructive", text: errorMessage(err) });
    } finally {
      setBusyId(null);
    }
  }

  if (loading && !data) return <LoadingState rows={4} />;

  return (
    <div className="space-y-8">
      <PageHeader
        title={t("title")}
        description={t("subtitle")}
        actions={
          <div className="flex items-center gap-3">
            {active && (
              <span className="inline-flex items-center gap-1 text-xs text-muted-foreground" aria-live="polite">
                <Loader2 className="size-3.5 animate-spin" aria-hidden /> {t("autoRefresh")}
              </span>
            )}
            <Button variant="outline" size="sm" disabled={refreshing} onClick={() => void load()}>
              <RefreshCw className={refreshing ? "animate-spin" : undefined} /> {t("refresh")}
            </Button>
          </div>
        }
      />
      {error != null && <ErrorState error={error} onRetry={() => void load()} />}
      {notice && <Alert variant={notice.kind}>{notice.text}</Alert>}

      {data && (
        <>
          <ul className="grid grid-cols-2 gap-3 md:grid-cols-5" aria-label={t("title")}>
            <Stat label={t("sources")} value={data.counts.sources_registered} href="/admin/knowledge-sources" />
            <Stat label={t("lastSync")} value={data.last_sync_at ? relativeTime(data.last_sync_at, locale) : t("never")} hint={formatDateTime(data.last_sync_at, locale)} />
            <Stat label={t("pendingReview")} value={data.counts.pending_review} href="/admin/review" tone={data.counts.pending_review ? "warn" : undefined} />
            <Stat label={t("waiting")} value={data.counts.waiting_for_indexing} tone={data.counts.waiting_for_indexing ? "info" : undefined} />
            <Stat label={t("indexingNow")} value={data.counts.indexing_now} tone={data.counts.indexing_now ? "info" : undefined} />
            <Stat label={t("active")} value={data.counts.active_versions} href="/admin/documents" />
            <Stat label={t("indexingFailed")} value={data.counts.indexing_failed} tone={data.counts.indexing_failed ? "bad" : undefined} />
            <Stat label={t("failedJobs")} value={data.counts.failed_jobs} tone={data.counts.failed_jobs ? "bad" : undefined} />
            <Stat label={t("searchableChunks")} value={data.counts.searchable_chunks} />
            <Stat label={t("modelChunks")} value={data.counts.chunks_with_current_model} />
          </ul>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">{t("embedding")}</CardTitle>
            </CardHeader>
            <CardContent>
              <dl className="grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-5">
                <Fact label={t("model")}><code className="break-all text-xs">{data.embedding.model}</code></Fact>
                <Fact label={t("dimensions")}>{data.embedding.dimensions}</Fact>
                <Fact label={t("provider")}>{data.embedding.provider}</Fact>
                <Fact label={t("loaded")}>{data.embedding.loaded ? t("loadedYes") : t("loadedNo")}</Fact>
                <Fact label={t("execution")}>{data.job_execution}</Fact>
              </dl>
            </CardContent>
          </Card>

          <section aria-labelledby="rag-queue" className="space-y-2">
            <h2 id="rag-queue" className="text-lg font-semibold">{t("queue")}</h2>
            {data.queue.length === 0 ? (
              <EmptyState title={t("noQueue")} />
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t("document")}</TableHead>
                    <TableHead>{t("version")}</TableHead>
                    <TableHead>{t("job")}</TableHead>
                    <TableHead>{t("attempts")}</TableHead>
                    <TableHead>{t("error")}</TableHead>
                    <TableHead>{t("created")}</TableHead>
                    <TableHead>{t("completed")}</TableHead>
                    <TableHead><span className="sr-only">{t("actions")}</span></TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.queue.map((q) => (
                    <Fragment key={q.job_id}>
                      <TableRow>
                        <TableCell className="max-w-xs">
                          {q.document_id ? (
                            <Link href={`/admin/documents/${q.document_id}`} className="font-medium text-primary hover:underline">
                              {q.document_title ?? t("unknownDocument")}
                            </Link>
                          ) : (
                            <span className="text-muted-foreground">{t("unknownDocument")}</span>
                          )}
                        </TableCell>
                        <TableCell className="whitespace-nowrap">
                          {q.version_number != null ? <span className="font-mono">v{q.version_number}</span> : "—"}{" "}
                          {q.indexing_status && <IndexingStatusBadge status={q.indexing_status} />}
                        </TableCell>
                        <TableCell className="whitespace-nowrap">
                          <JobStatusBadge status={q.status} />
                          {q.status === "queued" && q.run_after && q.attempts ? (
                            <span className="mt-0.5 block text-xs text-muted-foreground">
                              {t("retryAt")}: {relativeTime(q.run_after, locale)}
                            </span>
                          ) : null}
                        </TableCell>
                        <TableCell className="text-xs">{q.attempts ?? 0}/{q.max_attempts ?? 3}</TableCell>
                        <TableCell className="max-w-xs break-words text-xs text-red-800">{q.error_message ?? ""}</TableCell>
                        <TableCell className="whitespace-nowrap text-xs">{formatDateTime(q.created_at, locale)}</TableCell>
                        <TableCell className="whitespace-nowrap text-xs">
                          {q.completed_at ? formatDateTime(q.completed_at, locale) : q.started_at ? `${t("started")} ${formatDateTime(q.started_at, locale)}` : "—"}
                        </TableCell>
                        <TableCell>
                          <div className="flex flex-wrap gap-1">
                            {q.status === "failed" && (
                              <Button
                                size="sm"
                                variant="outline"
                                disabled={busyId === q.job_id}
                                onClick={() =>
                                  act(q.job_id, async () => {
                                    await api.post<JobAccepted>(`/api/v1/admin/ingestion-jobs/${encodeURIComponent(q.job_id)}/retry`);
                                    return t("retried");
                                  })
                                }
                              >
                                <RotateCcw /> {t("retry")}
                              </Button>
                            )}
                            {q.document_id && (
                              <Button asChild size="sm" variant="ghost">
                                <Link href={`/admin/documents/${q.document_id}#history`}>
                                  <History /> {t("history")}
                                </Link>
                              </Button>
                            )}
                            <Button size="sm" variant="ghost" aria-expanded={openLog === q.job_id} onClick={() => setOpenLog(openLog === q.job_id ? null : q.job_id)}>
                              <ScrollText /> {openLog === q.job_id ? t("hideLog") : t("log")}
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                      {openLog === q.job_id && (
                        <TableRow>
                          <TableCell colSpan={8}>
                            <JobEvents jobId={q.job_id} refreshKey={`${q.status}:${q.attempts}`} />
                          </TableCell>
                        </TableRow>
                      )}
                    </Fragment>
                  ))}
                </TableBody>
              </Table>
            )}
          </section>

          <section aria-labelledby="rag-acts" className="space-y-2">
            <h2 id="rag-acts" className="text-lg font-semibold">{t("activations")}</h2>
            {data.recent_activations.length === 0 ? (
              <EmptyState title={t("noActivations")} />
            ) : (
              <Card>
                <ul className="divide-y divide-border text-sm">
                  {data.recent_activations.map((a, i) => (
                    <li key={`${a.document_id}-${a.at}-${i}`} className="flex flex-wrap items-center justify-between gap-2 p-3">
                      <span>
                        {a.document_id ? (
                          <Link href={`/admin/documents/${a.document_id}`} className="font-medium text-primary hover:underline">
                            {a.document_title ?? t("unknownDocument")}
                          </Link>
                        ) : (
                          t("unknownDocument")
                        )}
                        <span className="ml-2 text-xs text-muted-foreground">
                          {a.version_number != null ? `v${a.version_number} · ` : ""}
                          {a.chunks != null ? `${t("chunks", { count: a.chunks })} · ` : ""}
                          {formatDateTime(a.at, locale)}
                        </span>
                      </span>
                      {a.document_id && (
                        <WithdrawButton
                          documentId={a.document_id}
                          title={a.document_title ?? ""}
                          size="sm"
                          label="short"
                          onDone={(m) => {
                            setNotice({ kind: "success", text: m });
                            void load();
                          }}
                        />
                      )}
                    </li>
                  ))}
                </ul>
              </Card>
            )}
          </section>

          <section aria-labelledby="rag-src" className="space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 id="rag-src" className="text-lg font-semibold">{t("sourcesTable")}</h2>
              <Button asChild size="sm" variant="outline">
                <Link href="/admin/review"><Search /> {t("reviewChanges")}</Link>
              </Button>
            </div>
            {data.sources.length === 0 ? (
              <EmptyState title={t("noSources")} />
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t("document")}</TableHead>
                    <TableHead>{t("type")}</TableHead>
                    <TableHead>{t("status")}</TableHead>
                    <TableHead>{t("frequency")}</TableHead>
                    <TableHead>{t("lastChecked")}</TableHead>
                    <TableHead>{t("lastSuccess")}</TableHead>
                    <TableHead>{t("lastChange")}</TableHead>
                    <TableHead><span className="sr-only">{t("actions")}</span></TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.sources.map((s) => (
                    <TableRow key={s.id}>
                      <TableCell className="max-w-xs">
                        <Link href={`/admin/knowledge-sources/${s.id}`} className="font-medium text-primary hover:underline">{s.title}</Link>
                        {!s.is_active && <Badge variant="muted" className="ml-2">{e("sourceStatus.inactive")}</Badge>}
                      </TableCell>
                      <TableCell className="text-xs">{e(`sourceType.${s.source_type}`)}</TableCell>
                      <TableCell><SourceStatusBadge status={s.status} /></TableCell>
                      <TableCell className="text-xs">{e(`sync.${s.sync_frequency}`)}</TableCell>
                      <TableCell className="whitespace-nowrap text-xs">{formatDateTime(s.last_checked_at, locale)}</TableCell>
                      <TableCell className="whitespace-nowrap text-xs">{formatDateTime(s.last_success_at, locale)}</TableCell>
                      <TableCell className="whitespace-nowrap text-xs">{formatDateTime(s.last_change_at, locale)}</TableCell>
                      <TableCell>
                        {FETCHABLE_SOURCE_TYPES.includes(s.source_type) && s.is_active && (
                          <Button
                            size="sm"
                            variant="outline"
                            disabled={busyId === s.id}
                            onClick={() =>
                              act(s.id, async () => {
                                await api.post<JobAccepted>(`/api/v1/admin/sources/${encodeURIComponent(s.id)}/ingest`);
                                return t("checkQueued", { title: s.title });
                              })
                            }
                          >
                            <RefreshCw /> {t("checkNow")}
                          </Button>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </section>
        </>
      )}
    </div>
  );
}

function Stat({ label, value, hint, href, tone }: { label: string; value: string | number; hint?: string; href?: string; tone?: "warn" | "bad" | "info" }) {
  const color = tone === "bad" ? "text-red-700" : tone === "warn" ? "text-amber-800" : tone === "info" ? "text-sky-800" : "";
  const body = (
    <Card className="h-full transition-shadow hover:shadow-sm">
      <CardContent className="p-4">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
        <p className={`mt-1 text-xl font-semibold ${color}`}>{value}</p>
        {hint && <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>}
      </CardContent>
    </Card>
  );
  return (
    <li>
      {href ? (
        <Link href={href} className="block rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          {body}
        </Link>
      ) : (
        body
      )}
    </li>
  );
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</dt>
      <dd className="mt-0.5">{children}</dd>
    </div>
  );
}
