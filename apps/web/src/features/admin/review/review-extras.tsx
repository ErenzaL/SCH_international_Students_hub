"use client";

import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { AlertTriangle, CheckCircle2, Save } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input, Label, Textarea } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ErrorState, LoadingState } from "@/components/shared/states";
import { changedFields, formatFieldValue, structuredToFieldValues } from "@/features/admin/knowledge/intake-utils";
import { api, errorMessage } from "@/lib/api";
import { KEY_FIELDS } from "@/lib/constants";
import { fetchBlobUrl } from "@/lib/upload";
import { useApi } from "@/lib/use-api";
import { formatDateTime } from "@/lib/utils";
import type { AuditEntry, ReviewWarning, Version } from "@/types/api";

export function ReviewWarnings({ warnings }: { warnings: ReviewWarning[] }) {
  const t = useTranslations("admin.review2");
  if (warnings.length === 0) return null;
  return (
    <Alert variant="warning" role="alert">
      <AlertTriangle className="size-4" aria-hidden />
      <AlertTitle>{t("warningsTitle")}</AlertTitle>
      <AlertDescription>
        <ul className="list-disc space-y-1 pl-5">
          {warnings.map((w, i) => <li key={`${w.code}-${i}`}>{w.message}</li>)}
        </ul>
      </AlertDescription>
    </Alert>
  );
}

/** Corrected-text editor for a draft/pending version (PATCH extracted_text re-chunks and re-embeds). */
export function TextEditor({ version, busy, onSave }: { version: Version; busy: boolean; onSave: (text: string) => void | Promise<void> }) {
  const t = useTranslations("admin.review2");
  const [text, setText] = useState(version.extracted_text);
  const dirty = text !== version.extracted_text;
  return (
    <div className="space-y-2">
      <Label htmlFor="rv-text">{t("editText")}</Label>
      <Textarea id="rv-text" rows={16} value={text} onChange={(e) => setText(e.target.value)} className="font-mono text-xs" />
      <div className="flex items-center gap-2">
        <Button size="sm" disabled={!dirty || busy || text.trim().length < 10} onClick={() => onSave(text)}><Save /> {t("saveText")}</Button>
        {dirty && <span className="text-xs text-amber-900">{t("unsaved")}</span>}
        {version.edited_at && <span className="text-xs text-muted-foreground">{t("editedAt", { date: formatDateTime(version.edited_at) })}</span>}
      </div>
    </div>
  );
}

export function RawEvidence({ text }: { text: string }) {
  const t = useTranslations("admin.review2");
  return (
    <details className="rounded-md border border-border bg-card p-3 text-sm">
      <summary className="cursor-pointer font-medium">{t("rawEvidence")}</summary>
      <p className="mt-1 text-xs text-muted-foreground">{t("rawEvidenceHint")}</p>
      <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap rounded bg-muted p-3 text-xs" tabIndex={0}>{text}</pre>
    </details>
  );
}

/** Structured fields with evidence and confirmation flags; admins correct values and confirm key facts. */
export function StructuredFields({
  version,
  busy,
  canConfirm,
  onSaveFields,
  onConfirm,
}: {
  version: Version;
  busy: boolean;
  canConfirm: boolean;
  onSaveFields?: (fields: Record<string, string | null>) => void | Promise<void>;
  onConfirm?: (confirmed: boolean) => void | Promise<void>;
}) {
  const t = useTranslations("admin.review2");
  const f = useTranslations("admin.ks.fields");
  const sd = version.structured_data ?? {};
  const original = structuredToFieldValues(sd);
  const [edited, setEdited] = useState<Partial<Record<string, string>>>(original);
  const changes = changedFields(original, edited);
  const editable = !!onSaveFields;
  const rows = KEY_FIELDS.filter((k) => editable || sd.fields?.[k]);
  return (
    <section aria-labelledby="sf-h" className="space-y-2">
      <h2 id="sf-h" className="text-lg font-semibold">{t("fieldsTitle")}</h2>
      <p className="text-xs text-muted-foreground">{t("fieldsHint")}</p>
      {rows.length === 0 ? <p className="text-sm text-muted-foreground">{t("noFields")}</p> : (
        <Table>
          <TableHeader><TableRow>
            <TableHead>{t("field")}</TableHead><TableHead>{t("value")}</TableHead><TableHead>{t("evidence")}</TableHead><TableHead>{t("state")}</TableHead>
          </TableRow></TableHeader>
          <TableBody>
            {rows.map((k) => {
              const fld = sd.fields?.[k];
              return (
                <TableRow key={k}>
                  <TableCell className="whitespace-nowrap text-xs font-medium">{f(k)}</TableCell>
                  <TableCell className="min-w-48">
                    {editable ? (
                      <Input aria-label={f(k)} value={edited[k] ?? ""} onChange={(e) => setEdited((s) => ({ ...s, [k]: e.target.value }))} />
                    ) : <span className="text-sm">{formatFieldValue(fld?.value) || "—"}</span>}
                    {fld?.needs_year && <p className="mt-0.5 text-xs text-amber-900">{t("needsYear")}</p>}
                  </TableCell>
                  <TableCell className="max-w-72 text-xs text-muted-foreground">{fld?.evidence ?? "—"}</TableCell>
                  <TableCell>
                    {fld ? (fld.confirmed ? <Badge variant="success">{t("confirmedBy", { source: fld.source })}</Badge> : <Badge variant="warning">{t("detectedOnly")}</Badge>) : <Badge variant="muted">{t("notFound")}</Badge>}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      )}
      {(sd.identifiers ?? []).length > 0 && <p className="text-xs">{t("identifiers")}: {sd.identifiers!.join(", ")}</p>}
      {editable && (
        <Button size="sm" variant="outline" disabled={busy || Object.keys(changes).length === 0} onClick={() => onSaveFields?.(changes)}>
          <Save /> {t("saveFields")}
        </Button>
      )}
      {onConfirm && canConfirm && (
        <div className={`rounded-md border p-3 ${version.requires_field_confirmation && !sd.fields_confirmed ? "border-amber-300 bg-amber-50" : "border-border"}`}>
          <label className="flex items-start gap-2 text-sm">
            <input type="checkbox" className="mt-1" checked={!!sd.fields_confirmed} disabled={busy} onChange={(e) => onConfirm(e.target.checked)} />
            <span>
              {t("confirmFields")}
              {version.requires_field_confirmation && <span className="block text-xs text-amber-900">{t("confirmRequired")}</span>}
            </span>
          </label>
          {sd.fields_confirmed && <p className="mt-1 inline-flex items-center gap-1 text-xs text-emerald-800"><CheckCircle2 className="size-3.5" aria-hidden /> {t("confirmed")}</p>}
        </div>
      )}
    </section>
  );
}

/** Original file / screenshot, fetched with the bearer token into a blob URL (the bucket is never public). */
export function OriginalFilePreview({ version }: { version: Version }) {
  const t = useTranslations("admin.review2");
  const [state, setState] = useState<{ url: string; type: string; text?: string } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const file = version.original_file;
  useEffect(() => {
    if (!open || !file) return;
    let url: string | null = null;
    let cancelled = false;
    fetchBlobUrl(`/api/v1/admin/versions/${version.id}/original`)
      .then(async (r) => {
        url = r.url;
        const text = r.type.startsWith("text/") ? await (await fetch(r.url)).text() : undefined;
        if (!cancelled) setState({ ...r, text });
      })
      .catch((e) => !cancelled && setErr(errorMessage(e)));
    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [open, file, version.id]);
  if (!file) return null;
  return (
    <section className="space-y-2" aria-labelledby="of-h">
      <h2 id="of-h" className="text-lg font-semibold">{t("originalFile")}</h2>
      <p className="text-xs text-muted-foreground">{file.filename} · {file.mime_type} · {Math.round(file.size / 1024)} KB · sha256 {file.sha256.slice(0, 12)}…</p>
      {!open && <Button size="sm" variant="outline" onClick={() => setOpen(true)}>{t("showOriginal")}</Button>}
      {open && !state && !err && <LoadingState rows={2} />}
      {err && <Alert variant="destructive"><AlertDescription>{err}</AlertDescription></Alert>}
      {state && state.type.startsWith("image/") && (
        // eslint-disable-next-line @next/next/no-img-element -- authenticated blob URL, not a public image
        <img src={state.url} alt={file.filename} className="max-h-[40rem] rounded border border-border" />
      )}
      {state && state.type === "application/pdf" && <object data={state.url} type="application/pdf" className="h-[40rem] w-full rounded border border-border" aria-label={file.filename} />}
      {state && state.text != null && <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded bg-muted p-3 text-xs">{state.text}</pre>}
      {state && !state.type.startsWith("image/") && state.type !== "application/pdf" && state.text == null && (
        <a className="text-sm text-primary underline" href={state.url} download={file.filename}>{t("download")}</a>
      )}
    </section>
  );
}

export function DocumentHistory({ documentId, refreshKey }: { documentId: string; refreshKey: number }) {
  const t = useTranslations("admin.review2");
  const locale = useLocale();
  const { data, error, loading, reload } = useApi<{ items: AuditEntry[] }>(`doc-hist:${documentId}:${refreshKey}`, () =>
    api.get<{ items: AuditEntry[] }>(`/api/v1/admin/documents/${documentId}/history`),
  );
  return (
    <section aria-labelledby="dh-h" className="space-y-2">
      <h2 id="dh-h" className="text-lg font-semibold">{t("history")}</h2>
      {loading && !data && <LoadingState rows={2} />}
      {error && <ErrorState error={error} onRetry={reload} />}
      {data && data.items.length === 0 && <p className="text-sm text-muted-foreground">{t("noHistory")}</p>}
      {data && data.items.length > 0 && (
        <ol className="space-y-1 text-sm">
          {data.items.map((a) => {
            const d = (a.details ?? {}) as Record<string, unknown>;
            return (
              <li key={a.id} className="rounded border border-border px-3 py-2">
                <span className="font-mono text-xs">{a.action}</span> · {a.actor_name || "—"} · <span className="text-xs text-muted-foreground">{formatDateTime(a.created_at, locale)}</span>
                {d.previous_status != null && <span className="text-xs"> · {String(d.previous_status)} → {String(d.new_status)}</span>}
                {d.note || d.reason ? <p className="text-xs text-muted-foreground">{String(d.note ?? d.reason)}</p> : null}
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
