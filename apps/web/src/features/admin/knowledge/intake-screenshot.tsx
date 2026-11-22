"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { ImageUp, RotateCcw } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input, Label, Textarea } from "@/components/ui/input";
import { ErrorState, LoadingState } from "@/components/shared/states";
import { KeyFieldsEditor } from "@/features/admin/knowledge/key-fields-editor";
import { EMPTY_META, SourceMetaFields, metaErrors, metaPayload } from "@/features/admin/knowledge/source-meta-fields";
import { fieldsPayload, formatBytes, structuredToFieldValues, validateImageFile } from "@/features/admin/knowledge/intake-utils";
import { VersionPreview } from "@/features/admin/knowledge/intake-document";
import { api, errorMessage } from "@/lib/api";
import { MAX_IMAGE_MB } from "@/lib/constants";
import { uploadWithProgress } from "@/lib/upload";
import { useAction } from "@/lib/use-action";
import { useApi } from "@/lib/use-api";
import type { Job, OcrStatus, ScreenshotIntake as Intake, SourceMeta } from "@/types/api";

export function ScreenshotIntake() {
  const t = useTranslations("admin.ks");
  const ocrStatus = useApi<OcrStatus>("ocr-status", () => api.get<OcrStatus>("/api/v1/admin/intake/ocr-status"));
  const [meta, setMeta] = useState<SourceMeta>({ ...EMPTY_META, authority_type: "staff_communication" });
  const [errs, setErrs] = useState<Partial<Record<keyof SourceMeta, string>>>({});
  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [authorized, setAuthorized] = useState(false);
  const [fileErr, setFileErr] = useState<string | null>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [intake, setIntake] = useState<Intake | null>(null);
  const [uploadErr, setUploadErr] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => () => { if (previewUrl) URL.revokeObjectURL(previewUrl); }, [previewUrl]);

  function choose(f: File | undefined) {
    setFileErr(null);
    if (!f) return;
    const problem = validateImageFile(f, MAX_IMAGE_MB);
    if (problem) {
      setFileErr(t(`fileErrors.${problem}`, { mb: MAX_IMAGE_MB, kind: "png/jpg/webp" }));
      return;
    }
    setFile(f);
    setPreviewUrl(URL.createObjectURL(f));
    setIntake(null);
  }

  async function runOcr() {
    const e = metaErrors(meta);
    setErrs(e);
    if (!file || Object.keys(e).length || !authorized) return;
    setUploadErr(null);
    setProgress(0);
    const fd = new FormData();
    fd.append("file", file);
    fd.append("metadata", JSON.stringify(metaPayload(meta)));
    fd.append("authorized_for_distribution", "true");
    try {
      setIntake(await uploadWithProgress<Intake>("/api/v1/admin/intake/screenshot", fd, setProgress));
    } catch (ex) {
      setUploadErr(errorMessage(ex));
    } finally {
      setProgress(null);
    }
  }

  return (
    <div className="space-y-5">
      <Alert variant="warning">
        <AlertTitle>{t("privacyTitle")}</AlertTitle>
        <AlertDescription>{t("screenshotPrivacy")}</AlertDescription>
      </Alert>
      {ocrStatus.data && (
        <p className="text-sm">
          {ocrStatus.data.available
            ? t("ocrAvailable", { provider: ocrStatus.data.provider, languages: ocrStatus.data.languages ?? "" })
            : t("ocrUnavailable", { reason: ocrStatus.data.reason ?? "" })}
          {ocrStatus.data.external_processing && <span className="block text-xs text-amber-900">{t("ocrExternal")}</span>}
        </p>
      )}
      {ocrStatus.error && <ErrorState error={ocrStatus.error} onRetry={ocrStatus.reload} />}
      {!intake && (
        <>
          <SourceMetaFields idPrefix="shot" value={meta} onChange={setMeta} errors={errs} />
          <div className="flex flex-wrap items-start gap-4">
            <div>
              <Button type="button" variant="outline" onClick={() => inputRef.current?.click()}><ImageUp /> {t("chooseImage")}</Button>
              <input ref={inputRef} type="file" accept=".png,.jpg,.jpeg,.webp,image/png,image/jpeg,image/webp" className="sr-only" tabIndex={-1} aria-hidden data-testid="shot-input" onChange={(ev) => { choose(ev.target.files?.[0]); ev.target.value = ""; }} />
              {file && <p className="mt-1 text-xs text-muted-foreground">{file.name} · {formatBytes(file.size)}</p>}
              {fileErr && <p className="mt-1 text-xs text-red-700">{fileErr}</p>}
            </div>
            {previewUrl && (
              // eslint-disable-next-line @next/next/no-img-element -- local object URL preview, never a remote image
              <img src={previewUrl} alt={t("imagePreview")} className="max-h-64 rounded border border-border" />
            )}
          </div>
          <label className="flex items-start gap-2 text-sm">
            <input type="checkbox" className="mt-1" checked={authorized} onChange={(ev) => setAuthorized(ev.target.checked)} />
            <span>{t("authorizedScreenshot")}</span>
          </label>
          {progress != null && <p className="text-sm" role="status">{t("uploadingPct", { pct: Math.round(progress * 100) })}</p>}
          {uploadErr && <Alert variant="destructive"><AlertDescription>{uploadErr}</AlertDescription></Alert>}
          <Button type="button" disabled={!file || !authorized || progress != null} onClick={runOcr}>{t("extractText")}</Button>
        </>
      )}
      {intake && <ScreenshotReview intake={intake} title={meta.title} imageUrl={previewUrl} onRetry={setIntake} />}
    </div>
  );
}

function ScreenshotReview({ intake, title: initialTitle, imageUrl, onRetry }: {
  intake: Intake; title: string; imageUrl: string | null; onRetry: (i: Intake) => void;
}) {
  const t = useTranslations("admin.ks");
  const detected = structuredToFieldValues(intake.detected);
  const [title, setTitle] = useState(initialTitle);
  const [text, setText] = useState(intake.ocr.text);
  const [fields, setFields] = useState<Partial<Record<string, string>>>(detected);
  const [redact, setRedact] = useState(true);
  const [done, setDone] = useState<Job | null>(null);
  const submit = useAction();
  const retry = useAction();
  const ocr = intake.ocr;

  async function save(asSubmit: boolean) {
    const job = await submit.run(() => api.post<Job>(`/api/v1/admin/intake/screenshot/${intake.job.id}/submit`, {
      title: title.trim(), text, submit: asSubmit, redact_personal_info: redact, fields: fieldsPayload(fields),
    }));
    if (job) setDone(job);
  }
  async function retryOcr() {
    const r = await retry.run(() => api.post<Intake>(`/api/v1/admin/intake/screenshot/${intake.job.id}/retry-ocr`));
    if (r) {
      onRetry(r);
      setText(r.ocr.text);
    }
  }

  if (done) {
    return done.status === "failed" ? (
      <Alert variant="destructive"><AlertDescription>{done.error_message ?? done.error_code}</AlertDescription></Alert>
    ) : (
      <div className="space-y-3">
        <Alert variant="success"><AlertDescription>{t("screenshotSaved")}</AlertDescription></Alert>
        {done.version_id && <VersionPreview versionId={done.version_id} documentId={done.document_id} />}
      </div>
    );
  }
  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-2">
        <div>
          <p className="mb-1 text-sm font-medium">{t("originalImage")}</p>
          {imageUrl ? (
            // eslint-disable-next-line @next/next/no-img-element -- local object URL of the uploaded file
            <img src={imageUrl} alt={t("imagePreview")} className="max-h-[32rem] w-full rounded border border-border object-contain" />
          ) : <LoadingState rows={2} />}
        </div>
        <div className="space-y-2">
          {!ocr.available && <Alert variant="info"><AlertDescription>{t("manualTranscription")} {ocr.warnings.join(" ")}</AlertDescription></Alert>}
          {ocr.available && (
            <p className="text-xs text-muted-foreground">
              {t("ocrMeta", { provider: ocr.provider, model: ocr.model ?? "?", confidence: ocr.mean_confidence ?? "n/a" })}
            </p>
          )}
          {ocr.available && ocr.warnings.length > 0 && <ul className="list-disc pl-5 text-xs text-amber-900">{ocr.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>}
          <Label htmlFor="shot-text">{t("correctedText")}</Label>
          <Textarea id="shot-text" rows={14} value={text} onChange={(ev) => setText(ev.target.value)} placeholder={t("typeFromImage")} />
          {ocr.available && (
            <Button size="sm" variant="ghost" disabled={retry.busy} onClick={retryOcr}><RotateCcw /> {t("retryOcr")}</Button>
          )}
          {retry.error && <p className="text-xs text-red-700">{errorMessage(retry.error)}</p>}
        </div>
      </div>
      {ocr.uncertain_lines.length > 0 && (
        <div>
          <p className="text-sm font-medium text-amber-900">{t("uncertainLines")}</p>
          <ul className="mt-1 space-y-0.5 rounded-md border border-amber-200 bg-amber-50 p-2 text-xs">
            {ocr.uncertain_lines.map((l, i) => <li key={i}><span className="font-mono">{l.confidence ?? "?"}</span> {l.text}</li>)}
          </ul>
        </div>
      )}
      {(intake.detected?.dates ?? []).length > 0 && (
        <p className="text-xs text-muted-foreground">
          {t("detectedDates")}: {intake.detected!.dates!.map((d) => d.iso ?? `${d.text} (${t("noYear")})`).join(", ")}
        </p>
      )}
      {(intake.detected?.warnings ?? []).map((w, i) => <p key={i} className="text-xs text-amber-900">{w}</p>)}
      <div>
        <Label htmlFor="shot-title">{t("meta.title")}</Label>
        <Input id="shot-title" value={title} onChange={(ev) => setTitle(ev.target.value)} />
      </div>
      <p className="text-sm font-medium">{t("keyFieldsTitle")}</p>
      <p className="text-xs text-muted-foreground">{t("keyFieldsHint")}</p>
      <KeyFieldsEditor idPrefix="shotf" values={fields} onChange={setFields} detected={detected} />
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={redact} onChange={(ev) => setRedact(ev.target.checked)} /> {t("redactPersonal")}
      </label>
      {submit.error && <Alert variant="destructive"><AlertDescription>{errorMessage(submit.error)}</AlertDescription></Alert>}
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" disabled={submit.busy || text.trim().length < 10 || !title.trim()} onClick={() => save(false)}>{t("saveDraft")}</Button>
        <Button disabled={submit.busy || text.trim().length < 10 || !title.trim()} onClick={() => save(true)}>{t("submitForReview")}</Button>
      </div>
    </div>
  );
}
