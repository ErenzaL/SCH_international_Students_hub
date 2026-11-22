"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { FileUp } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { ErrorState, LoadingState } from "@/components/shared/states";
import { EMPTY_META, SourceMetaFields, metaErrors, metaPayload } from "@/features/admin/knowledge/source-meta-fields";
import { formatBytes, validateDocumentFile, type DocumentKind } from "@/features/admin/knowledge/intake-utils";
import { JobTracker } from "@/features/admin/knowledge/job-tracker";
import { isAdminRole, useMe } from "@/features/admin/shell/admin-context";
import { ApiError, api, errorMessage } from "@/lib/api";
import { MAX_UPLOAD_MB } from "@/lib/constants";
import { uploadWithProgress } from "@/lib/upload";
import { useApi } from "@/lib/use-api";
import type { Job, SourceMeta, Version } from "@/types/api";

const ACCEPT = ".pdf,.docx,.txt,.md,.markdown";

/** File picker + drag & drop + client pre-checks + upload with progress. Calls onQueued with the job id. */
export function DocumentUploadBox({
  sourceId,
  meta,
  expected,
  onQueued,
  beforeUpload,
}: {
  sourceId?: string;
  meta?: SourceMeta;
  expected?: DocumentKind;
  onQueued: (jobId: string) => void;
  beforeUpload?: () => boolean;
}) {
  const t = useTranslations("admin.ks");
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [drag, setDrag] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [duplicate, setDuplicate] = useState<string | null>(null);

  function choose(f: File | undefined) {
    setError(null);
    setDuplicate(null);
    if (!f) return;
    const problem = validateDocumentFile(f, MAX_UPLOAD_MB, expected);
    if (problem) {
      setFile(null);
      setError(t(`fileErrors.${problem}`, { mb: MAX_UPLOAD_MB, kind: expected ?? "pdf/docx/txt/md" }));
      return;
    }
    setFile(f);
  }

  async function upload() {
    if (!file || (beforeUpload && !beforeUpload())) return;
    setError(null);
    setDuplicate(null);
    setProgress(0);
    const fd = new FormData();
    fd.append("file", file);
    if (sourceId) fd.append("source_id", sourceId);
    else if (meta) fd.append("metadata", JSON.stringify(metaPayload(meta)));
    try {
      const res = await uploadWithProgress<{ job_id: string }>("/api/v1/admin/intake/document", fd, setProgress);
      setFile(null);
      onQueued(res.job_id);
    } catch (ex) {
      if (ex instanceof ApiError && ex.status === 409) {
        const d = ex.details as { document_id?: string } | null;
        setDuplicate(d?.document_id ?? null);
      }
      setError(errorMessage(ex));
    } finally {
      setProgress(null);
    }
  }

  return (
    <div className="space-y-3">
      <div
        role="button"
        tabIndex={0}
        aria-label={t("dropZone")}
        onClick={() => inputRef.current?.click()}
        onKeyDown={(ev) => (ev.key === "Enter" || ev.key === " ") && inputRef.current?.click()}
        onDragOver={(ev) => { ev.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={(ev) => { ev.preventDefault(); setDrag(false); choose(ev.dataTransfer.files?.[0]); }}
        className={`flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed p-6 text-center text-sm ${drag ? "border-primary bg-secondary/40" : "border-border"}`}
      >
        <FileUp className="size-6 text-muted-foreground" aria-hidden />
        <span>{t("dropZone")}</span>
        <span className="text-xs text-muted-foreground">{t("documentTypes", { mb: MAX_UPLOAD_MB })}</span>
        <input ref={inputRef} type="file" accept={ACCEPT} className="sr-only" tabIndex={-1} aria-hidden data-testid="doc-input" onChange={(ev) => { choose(ev.target.files?.[0]); ev.target.value = ""; }} />
      </div>
      {file && (
        <p className="text-sm">
          <span className="font-medium">{file.name}</span> · {formatBytes(file.size)} · {file.type || "?"} · {t("lastModified")}{" "}
          {new Date(file.lastModified).toLocaleDateString()}
        </p>
      )}
      {progress != null && (
        <div className="h-2 w-full overflow-hidden rounded bg-muted" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(progress * 100)} aria-label={t("uploading")}>
          <div className="h-full bg-primary transition-all" style={{ width: `${Math.round(progress * 100)}%` }} />
        </div>
      )}
      {error && (
        <Alert variant="destructive">
          <AlertDescription>
            {error}
            {duplicate && <> <Link className="underline" href={`/admin/documents/${duplicate}`}>{t("openExisting")}</Link></>}
          </AlertDescription>
        </Alert>
      )}
      <Button type="button" disabled={!file || progress != null} onClick={upload}>{progress != null ? t("uploading") : t("uploadAndExtract")}</Button>
    </div>
  );
}

export function DocumentIntake() {
  const t = useTranslations("admin.ks");
  const [meta, setMeta] = useState<SourceMeta>({ ...EMPTY_META });
  const [errs, setErrs] = useState<Partial<Record<keyof SourceMeta, string>>>({});
  const [jobId, setJobId] = useState<string | null>(null);
  const [done, setDone] = useState<Job | null>(null);
  return (
    <div className="space-y-5">
      <p className="text-sm text-muted-foreground">{t("documentIntro")}</p>
      <SourceMetaFields idPrefix="doc" value={meta} onChange={setMeta} errors={errs} />
      <DocumentUploadBox
        meta={meta}
        beforeUpload={() => {
          const e = metaErrors(meta);
          setErrs(e);
          return Object.keys(e).length === 0;
        }}
        onQueued={(id) => { setDone(null); setJobId(id); }}
      />
      {jobId && <JobTracker key={jobId} jobId={jobId} onDone={setDone} />}
      {done?.status === "succeeded" && done.version_id && <VersionPreview versionId={done.version_id} documentId={done.document_id} />}
    </div>
  );
}

/** Extracted-text preview of the version a job created (admins: link to review; supporters: own submissions). */
export function VersionPreview({ versionId, documentId }: { versionId: string; documentId: string | null }) {
  const t = useTranslations("admin.ks");
  const me = useMe();
  const { data, error, loading, reload } = useApi<Version>(`vprev:${versionId}`, () => api.get<Version>(`/api/v1/admin/versions/${versionId}`));
  if (loading) return <LoadingState rows={2} />;
  if (error) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return null;
  const pages = (data.extracted_text.match(/^\[Page \d+\]$/gm) ?? []).length;
  return (
    <section className="space-y-2 rounded-lg border border-border p-4" aria-labelledby="vprev-h">
      <h3 id="vprev-h" className="font-semibold">{t("extractedPreview", { version: data.version_number })}</h3>
      <p className="text-xs text-muted-foreground">
        {t("previewStats", { chars: data.content_length, chunks: data.chunk_count, embedded: data.embedded_chunk_count, pages })}
      </p>
      {(data.warnings ?? []).length > 0 && (
        <Alert variant="warning"><AlertDescription><ul className="list-disc pl-5">{data.warnings!.map((w, i) => <li key={i}>{w}</li>)}</ul></AlertDescription></Alert>
      )}
      <pre className="max-h-80 overflow-auto whitespace-pre-wrap rounded-md bg-muted p-3 text-xs" tabIndex={0}>{data.extracted_text.slice(0, 6000)}</pre>
      {isAdminRole(me.role) && documentId ? (
        <Button asChild size="sm"><Link href={`/admin/documents/${documentId}`}>{t("openReview")}</Link></Button>
      ) : (
        <Button asChild size="sm" variant="outline"><Link href="/admin/submissions">{t("mySubmissions")}</Link></Button>
      )}
    </section>
  );
}
