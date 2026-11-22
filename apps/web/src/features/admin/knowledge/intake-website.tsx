"use client";

import { useState } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { CheckCircle2, CloudDownload, Eye, ShieldCheck, XCircle } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { FieldError, Input, Label, Select } from "@/components/ui/input";
import { isSchBoardUrl, suggestedSync, formatFieldValue } from "@/features/admin/knowledge/intake-utils";
import { JobTracker } from "@/features/admin/knowledge/job-tracker";
import { toSourceCreate, validateSourceForm, type SourceFormErrors, type SourceFormValues } from "@/features/admin/sources/source-validation";
import { ApiError, api, errorMessage } from "@/lib/api";
import { AUTHORITY_TYPES, CATEGORY_SLUGS, LOCALES, LOCALE_LABELS, SCOPES, SYNC_FREQUENCIES } from "@/lib/constants";
import { useAction } from "@/lib/use-action";
import { useCategoryName } from "@/lib/use-category-name";
import { formatDate } from "@/lib/utils";
import type { JobAccepted, Source, UrlPreview, UrlValidation } from "@/types/api";

const INITIAL: SourceFormValues = {
  title: "",
  original_url: "",
  organization: "",
  source_type: "website",
  authority_type: "official_government",
  scope: "national",
  category: "visa-immigration",
  language: "ko",
  sync_frequency: "weekly",
};

export function WebsiteIntake() {
  const t = useTranslations("admin.ks");
  const e = useTranslations("enums");
  const v = useTranslations("admin.sources.validation");
  const locale = useLocale();
  const categoryName = useCategoryName();
  const [values, setValues] = useState<SourceFormValues>(INITIAL);
  const [maxItems, setMaxItems] = useState("5");
  const [errors, setErrors] = useState<SourceFormErrors>({});
  const [check, setCheck] = useState<UrlValidation | null>(null);
  const [preview, setPreview] = useState<UrlPreview | null>(null);
  const [previewErr, setPreviewErr] = useState<ApiError | null>(null);
  const [created, setCreated] = useState<Source | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const validate = useAction();
  const fetchPreview = useAction();
  const register = useAction();

  const set = <K extends keyof SourceFormValues>(k: K, val: SourceFormValues[K]) =>
    setValues((s) => {
      const next = { ...s, [k]: val };
      if (k === "category" || k === "source_type") next.sync_frequency = suggestedSync(next.category, next.source_type);
      if (k === "original_url" && typeof val === "string" && isSchBoardUrl(val)) {
        next.source_type = "sch_board";
        next.scope = "university";
        next.authority_type = "official_university";
        next.category = "university-announcements";
        next.sync_frequency = suggestedSync("university-announcements", "sch_board");
      }
      return next;
    });
  const urlBody = () => ({ url: values.original_url.trim(), source_type: values.source_type as "website" | "sch_board", language: values.language });

  async function doValidate() {
    setCheck(null);
    const r = await validate.run(() => api.post<UrlValidation>("/api/v1/admin/sources/validate-url", urlBody()));
    if (r) setCheck(r);
  }
  async function doPreview() {
    setPreview(null);
    setPreviewErr(null);
    try {
      setPreview(await fetchPreview.run(async () => api.post<UrlPreview>("/api/v1/admin/sources/preview", urlBody())) ?? null);
    } catch (ex) {
      setPreviewErr(ex as ApiError);
    }
  }
  async function doRegister(andFetch: boolean) {
    const errs = validateSourceForm(values);
    setErrors(errs);
    if (Object.keys(errs).length) return;
    const body = { ...toSourceCreate(values), ...(values.source_type === "sch_board" ? { config: { max_items: Number(maxItems) || 5, max_pages: 1 } } : {}) };
    const src = await register.run(() => api.post<Source>("/api/v1/admin/sources", body));
    if (!src) return;
    setCreated(src);
    if (andFetch) {
      const res = await register.run(() => api.post<JobAccepted>(`/api/v1/admin/sources/${src.id}/ingest`));
      if (res) setJobId(res.job_id);
    }
  }
  const err = (k: keyof SourceFormValues) => (errors[k] ? v(errors[k]!) : undefined);
  const blocked = (fetchPreview.error?.details as { blocked?: boolean } | null)?.blocked;

  return (
    <div className="space-y-5">
      <p className="text-sm text-muted-foreground">{t("websiteIntro")}</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="sm:col-span-2">
          <Label htmlFor="w-url">{t("officialUrl")}</Label>
          <Input id="w-url" value={values.original_url} aria-invalid={!!errors.original_url} placeholder="https://" onChange={(ev) => set("original_url", ev.target.value)} />
          <FieldError>{err("original_url")}</FieldError>
          <p className="mt-1 text-xs text-muted-foreground">{t("urlHint")}</p>
        </div>
        <div>
          <Label htmlFor="w-type">{t("connector")}</Label>
          <Select id="w-type" value={values.source_type} onChange={(ev) => set("source_type", ev.target.value as SourceFormValues["source_type"])}>
            <option value="website">{e("sourceType.website")}</option>
            <option value="sch_board">{e("sourceType.sch_board")}</option>
          </Select>
        </div>
        <div>
          <Label htmlFor="w-title">{t("meta.title")}</Label>
          <Input id="w-title" value={values.title} aria-invalid={!!errors.title} onChange={(ev) => set("title", ev.target.value)} />
          <FieldError>{err("title")}</FieldError>
        </div>
        <div>
          <Label htmlFor="w-org">{t("meta.organization")}</Label>
          <Input id="w-org" value={values.organization} aria-invalid={!!errors.organization} onChange={(ev) => set("organization", ev.target.value)} />
          <FieldError>{err("organization")}</FieldError>
        </div>
        <div>
          <Label htmlFor="w-cat">{t("meta.category")}</Label>
          <Select id="w-cat" value={values.category} onChange={(ev) => set("category", ev.target.value)}>
            {CATEGORY_SLUGS.map((c) => <option key={c} value={c}>{categoryName(c)}</option>)}
          </Select>
        </div>
        <div>
          <Label htmlFor="w-lang">{t("meta.language")}</Label>
          <Select id="w-lang" value={values.language} onChange={(ev) => set("language", ev.target.value as SourceFormValues["language"])}>
            {LOCALES.map((l) => <option key={l} value={l}>{LOCALE_LABELS[l]}</option>)}
          </Select>
        </div>
        <div>
          <Label htmlFor="w-scope">{t("meta.scope")}</Label>
          <Select id="w-scope" value={values.scope} onChange={(ev) => set("scope", ev.target.value as SourceFormValues["scope"])}>
            {SCOPES.map((s) => <option key={s} value={s}>{e(`scope.${s}`)}</option>)}
          </Select>
        </div>
        <div>
          <Label htmlFor="w-auth">{t("meta.authority")}</Label>
          <Select id="w-auth" value={values.authority_type} onChange={(ev) => set("authority_type", ev.target.value as SourceFormValues["authority_type"])}>
            {AUTHORITY_TYPES.map((a) => <option key={a} value={a}>{e(`authority.${a}`)}</option>)}
          </Select>
        </div>
        <div>
          <Label htmlFor="w-sync">{t("syncSchedule")}</Label>
          <Select id="w-sync" value={values.sync_frequency} onChange={(ev) => set("sync_frequency", ev.target.value as SourceFormValues["sync_frequency"])}>
            {SYNC_FREQUENCIES.map((s) => <option key={s} value={s}>{e(`sync.${s}`)}</option>)}
          </Select>
          <p className="mt-1 text-xs text-muted-foreground">{t("syncHint")}</p>
        </div>
        {values.source_type === "sch_board" && (
          <div>
            <Label htmlFor="w-items">{t("boardMaxItems")}</Label>
            <Input id="w-items" type="number" min={1} max={30} value={maxItems} onChange={(ev) => setMaxItems(ev.target.value)} />
          </div>
        )}
      </div>

      <div className="flex flex-wrap gap-2">
        <Button type="button" variant="outline" disabled={!values.original_url.trim() || validate.busy} onClick={doValidate}><ShieldCheck /> {t("validateUrl")}</Button>
        <Button type="button" variant="outline" disabled={!values.original_url.trim() || fetchPreview.busy} onClick={doPreview}><Eye /> {fetchPreview.busy ? t("fetching") : t("fetchPreview")}</Button>
        <Button type="button" variant="outline" disabled={register.busy || !!created} onClick={() => doRegister(false)}>{t("register")}</Button>
        <Button type="button" disabled={register.busy || !!created} onClick={() => doRegister(true)}><CloudDownload /> {t("registerAndFetch")}</Button>
      </div>

      {validate.error && <Alert variant="destructive"><AlertDescription>{errorMessage(validate.error)}</AlertDescription></Alert>}
      {check && (
        <ul className="space-y-1 rounded-lg border border-border p-3 text-sm" aria-label={t("checks")}>
          {check.checks.map((c) => (
            <li key={c.name} className="flex items-start gap-2">
              {c.ok ? <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-700" aria-label="ok" /> : <XCircle className="mt-0.5 size-4 shrink-0 text-red-700" aria-label="failed" />}
              <span><span className="font-medium">{t(`checkNames.${c.name}`)}</span>: {c.message}</span>
            </li>
          ))}
          <li className="pt-1 font-medium">{check.ok ? t("checksOk") : t("checksFailed")}</li>
        </ul>
      )}

      {fetchPreview.error && (
        <Alert variant="destructive">
          <AlertTitle>{fetchPreview.error.code}</AlertTitle>
          <AlertDescription>
            {errorMessage(fetchPreview.error)}
            {blocked && <p className="mt-1">{t("blockedHint")}</p>}
          </AlertDescription>
        </Alert>
      )}
      {previewErr && !fetchPreview.error && <Alert variant="destructive"><AlertDescription>{errorMessage(previewErr)}</AlertDescription></Alert>}
      {preview?.kind === "page" && (
        <section className="space-y-2 rounded-lg border border-border p-4" aria-label={t("previewTitle")}>
          <h3 className="font-semibold">{preview.title || t("untitled")}</h3>
          <p className="text-xs text-muted-foreground">
            {t("pagePreviewStats", { chars: preview.content_chars, chunks: preview.estimated_chunks, extractor: preview.extractor ?? "?" })}
            {preview.source_published_at && ` · ${t("publishedOn", { date: formatDate(preview.source_published_at, locale) })}`}
          </p>
          {preview.final_url !== values.original_url.trim() && <p className="break-all text-xs">{t("finalUrl")}: {preview.final_url}</p>}
          {preview.warnings.length > 0 && <Alert variant="warning"><AlertDescription><ul className="list-disc pl-5">{preview.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul></AlertDescription></Alert>}
          {Object.keys(preview.structured.fields ?? {}).length > 0 && (
            <dl className="grid gap-1 text-xs sm:grid-cols-2">
              {Object.entries(preview.structured.fields ?? {}).map(([k, f]) => (
                <div key={k}><dt className="inline font-medium">{k}:</dt> <dd className="inline">{formatFieldValue(f.value) || "?"}</dd></div>
              ))}
            </dl>
          )}
          <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-md bg-muted p-3 text-xs" tabIndex={0}>{preview.text}</pre>
          {preview.truncated && <p className="text-xs text-muted-foreground">{t("truncated")}</p>}
        </section>
      )}
      {preview?.kind === "board" && (
        <section className="space-y-2 rounded-lg border border-border p-4" aria-label={t("previewTitle")}>
          <p className="text-sm font-medium">{t("boardFound", { count: preview.notice_count })}</p>
          <ul className="space-y-1 text-sm">
            {preview.notices.map((n) => (
              <li key={n.notice_no} className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-xs">#{n.notice_no}</span>
                {n.pinned && <Badge variant="info">{t("pinned")}</Badge>}
                <a href={n.url} target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">{n.title}</a>
                <span className="text-xs text-muted-foreground">{n.posted ?? "—"} · {n.author ?? "—"}</span>
              </li>
            ))}
          </ul>
          {preview.sample_notice && (
            <div className="space-y-1">
              <p className="text-xs font-medium">{t("sampleNotice")}</p>
              {preview.sample_notice.warnings.map((w, i) => <p key={i} className="text-xs text-amber-900">{w}</p>)}
              <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded-md bg-muted p-3 text-xs" tabIndex={0}>{preview.sample_notice.text}</pre>
            </div>
          )}
        </section>
      )}

      {register.error && <Alert variant="destructive"><AlertDescription>{errorMessage(register.error)}</AlertDescription></Alert>}
      {created && (
        <Alert variant="success">
          <AlertDescription>
            {t("registered", { title: created.title })}{" "}
            <Link className="underline" href={`/admin/knowledge-sources/${created.id}`}>{t("viewDetails")}</Link>
          </AlertDescription>
        </Alert>
      )}
      {jobId && <JobTracker jobId={jobId} />}
    </div>
  );
}
