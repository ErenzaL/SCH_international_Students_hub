"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { Loader2 } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { JobStatusBadge } from "@/components/shared/badges";
import { JobEvents } from "@/features/admin/knowledge/job-events";
import { errorMessage } from "@/lib/api";
import { waitForJob } from "@/lib/jobs";
import type { BoardFailure, BoardNoticeStat, Job } from "@/types/api";

/** Follows a queued job to its real end state and shows the outcome, statistics and step log. */
export function JobTracker({ jobId, onDone }: { jobId: string; onDone?: (job: Job) => void }) {
  const t = useTranslations("admin.ks");
  const e = useTranslations("enums");
  const [job, setJob] = useState<Job | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    const ctl = new AbortController();
    waitForJob(jobId, { signal: ctl.signal, onUpdate: setJob })
      .then((j) => onDone?.(j))
      .catch((ex) => {
        if (!(ex instanceof DOMException && ex.name === "AbortError")) setErr(errorMessage(ex));
      });
    return () => ctl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- follow one job id
  }, [jobId]);

  const done = job?.status === "succeeded" || job?.status === "failed";
  return (
    <div className="space-y-2 rounded-lg border border-border p-3 text-sm" aria-live="polite">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{t("job")}</span>
        {job ? <JobStatusBadge status={job.status} /> : <Loader2 className="size-4 animate-spin" aria-label={t("waiting")} />}
        {job?.outcome && <span className="text-muted-foreground">{e(`jobOutcome.${job.outcome}`)}</span>}
        {!done && <Loader2 className="size-3.5 animate-spin text-muted-foreground" aria-hidden />}
      </div>
      {err && <Alert variant="destructive"><AlertDescription>{err}</AlertDescription></Alert>}
      {job && <JobSummary job={job} />}
      <JobEvents jobId={jobId} refreshKey={`${job?.status ?? "q"}:${job?.heartbeat_at ?? ""}`} />
    </div>
  );
}

export function JobSummary({ job }: { job: Job }) {
  const t = useTranslations("admin.ks");
  const s = job.statistics as Record<string, unknown>;
  const notices = (s.notices as BoardNoticeStat[] | undefined) ?? [];
  const failures = (s.failures as BoardFailure[] | undefined) ?? [];
  const warnings = (s.warnings as string[] | undefined) ?? [];
  return (
    <div className="space-y-2">
      {job.status === "failed" && (
        <Alert variant="destructive">
          <AlertTitle>{job.error_code ?? t("failed")}</AlertTitle>
          <AlertDescription>
            {job.error_message}
            {job.error_code && BLOCKED.has(job.error_code) && <p className="mt-1">{t("blockedHint")}</p>}
          </AlertDescription>
        </Alert>
      )}
      {job.status === "succeeded" && job.error_code === "embedding_unavailable" && (
        <Alert variant="warning"><AlertDescription>{job.error_message}</AlertDescription></Alert>
      )}
      <dl className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
        {STAT_KEYS.filter((k) => s[k] != null).map((k) => (
          <div key={k}>
            <dt className="inline">{t(`stats.${k}`)}:</dt> <dd className="inline font-medium text-foreground">{String(s[k])}</dd>
          </div>
        ))}
      </dl>
      {warnings.length > 0 && (
        <ul className="list-disc space-y-0.5 pl-5 text-xs text-amber-900">
          {warnings.map((w, i) => <li key={i}>{w}</li>)}
        </ul>
      )}
      {notices.length > 0 && (
        <div>
          <p className="text-xs font-medium">{t("boardNotices")}</p>
          <ul className="mt-1 space-y-0.5 text-xs">
            {notices.map((n) => (
              <li key={n.notice_no}>
                #{n.notice_no} {n.title} — {n.outcome}
                {n.document_id && (
                  <>
                    {" "}
                    <Link className="text-primary underline" href={`/admin/documents/${n.document_id}`}>{t("review")}</Link>
                  </>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
      {failures.length > 0 && (
        <ul className="space-y-0.5 text-xs text-red-800">
          {failures.map((f) => <li key={f.notice_no}>#{f.notice_no} {f.title}: {f.code} — {f.message}</li>)}
        </ul>
      )}
      {job.status === "succeeded" && job.document_id && notices.length === 0 && (
        <Link className="text-sm font-medium text-primary underline" href={`/admin/documents/${job.document_id}`}>
          {t("openReview")}
        </Link>
      )}
    </div>
  );
}

const BLOCKED = new Set(["robots_disallowed", "http_401", "http_403", "http_406", "http_429"]);
const STAT_KEYS = [
  "fetched_bytes", "content_chars", "chunk_count", "embedded_chunks", "embedding_ms", "duration_ms",
  "items_found", "items_new", "items_unchanged", "items_failed", "ocr_chars", "ocr_mean_confidence",
] as const;
