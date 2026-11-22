"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input, Label, Select, Textarea } from "@/components/ui/input";
import { VersionPreview } from "@/features/admin/knowledge/intake-document";
import { EMPTY_META, SourceMetaFields, metaErrors } from "@/features/admin/knowledge/source-meta-fields";
import { api, errorMessage } from "@/lib/api";
import { useAction } from "@/lib/use-action";
import type { Job, SourceMeta } from "@/types/api";

export interface PasteValues {
  original_text: string;
  normalized_text: string;
  target_audience: string;
  event_date: string;
  deadline: string;
  location: string;
  application_method: string;
  notes: string;
  received_via: "kakaotalk" | "email" | "other";
}

const EMPTY: PasteValues = {
  original_text: "", normalized_text: "", target_audience: "", event_date: "", deadline: "", location: "",
  application_method: "", notes: "", received_via: "kakaotalk",
};

/** Body for POST /admin/intake/announcement. Empty optional fields are omitted (never sent as fake values). */
export function pastePayload(meta: SourceMeta, v: PasteValues, opts: { submit: boolean; redact: boolean; authorized: boolean }) {
  const opt = (s: string) => (s.trim() ? s.trim() : undefined);
  return {
    original_text: v.original_text,
    normalized_text: opt(v.normalized_text),
    title: meta.title.trim(),
    organization: meta.organization.trim(),
    category: meta.category,
    language: meta.language,
    scope: meta.scope,
    authority_type: meta.authority_type === "official_university" || meta.authority_type === "supporter_submitted" ? meta.authority_type : "staff_communication",
    received_via: v.received_via,
    target_audience: opt(v.target_audience),
    event_date: opt(v.event_date),
    deadline: opt(v.deadline),
    location: opt(v.location),
    application_method: opt(v.application_method),
    notes: opt(v.notes),
    original_url: opt(meta.original_url ?? ""),
    redact_personal_info: opts.redact,
    authorized_by_supporter: opts.authorized,
    submit: opts.submit,
  };
}

export function PasteIntake() {
  const t = useTranslations("admin.ks");
  const [meta, setMeta] = useState<SourceMeta>({ ...EMPTY_META, authority_type: "staff_communication", organization: "" });
  const [errs, setErrs] = useState<Partial<Record<keyof SourceMeta, string>>>({});
  const [v, setV] = useState<PasteValues>(EMPTY);
  const [authorized, setAuthorized] = useState(false);
  const [redact, setRedact] = useState(true);
  const [done, setDone] = useState<Job | null>(null);
  const action = useAction();
  const set = (k: keyof PasteValues, val: string) => setV((s) => ({ ...s, [k]: val }));

  async function save(submit: boolean) {
    const e = metaErrors(meta);
    setErrs(e);
    if (Object.keys(e).length || v.original_text.trim().length < 10 || !authorized) return;
    const job = await action.run(() => api.post<Job>("/api/v1/admin/intake/announcement", pastePayload(meta, v, { submit, redact, authorized })));
    if (job) setDone(job);
  }

  if (done) {
    return done.status === "failed" ? (
      <Alert variant="destructive"><AlertDescription>{done.error_message ?? done.error_code}</AlertDescription></Alert>
    ) : (
      <div className="space-y-3">
        <Alert variant="success"><AlertDescription>{done.outcome === "unchanged" ? t("pasteUnchanged") : t("pasteSaved")}</AlertDescription></Alert>
        {done.version_id && <VersionPreview versionId={done.version_id} documentId={done.document_id} />}
        <Button variant="outline" onClick={() => { setDone(null); setV(EMPTY); setAuthorized(false); }}>{t("pasteAnother")}</Button>
      </div>
    );
  }
  return (
    <div className="space-y-5">
      <Alert variant="warning">
        <AlertTitle>{t("privacyTitle")}</AlertTitle>
        <AlertDescription>{t("pastePrivacy")}</AlertDescription>
      </Alert>
      <div>
        <Label htmlFor="p-orig">{t("originalText")}</Label>
        <Textarea id="p-orig" rows={8} value={v.original_text} onChange={(ev) => set("original_text", ev.target.value)} />
        <p className="mt-1 text-xs text-muted-foreground">{t("originalTextHint")}</p>
      </div>
      <div>
        <Label htmlFor="p-norm">{t("normalizedText")}</Label>
        <Textarea id="p-norm" rows={6} value={v.normalized_text} onChange={(ev) => set("normalized_text", ev.target.value)} placeholder={t("normalizedHint")} />
      </div>
      <SourceMetaFields idPrefix="paste" value={meta} onChange={setMeta} errors={errs} authorities={["staff_communication", "official_university", "supporter_submitted"]} />
      <div className="grid gap-3 sm:grid-cols-2">
        <Field id="p-aud" label={t("fields.target_audience")} value={v.target_audience} onChange={(x) => set("target_audience", x)} />
        <Field id="p-loc" label={t("fields.location")} value={v.location} onChange={(x) => set("location", x)} />
        <Field id="p-event" type="date" label={t("fields.event_date")} value={v.event_date} onChange={(x) => set("event_date", x)} />
        <Field id="p-dead" type="date" label={t("fields.deadline")} value={v.deadline} onChange={(x) => set("deadline", x)} />
        <Field id="p-method" label={t("fields.application_method")} value={v.application_method} onChange={(x) => set("application_method", x)} />
        <div>
          <Label htmlFor="p-via">{t("receivedVia")}</Label>
          <Select id="p-via" value={v.received_via} onChange={(ev) => set("received_via", ev.target.value)}>
            <option value="kakaotalk">KakaoTalk</option>
            <option value="email">{t("viaEmail")}</option>
            <option value="other">{t("viaOther")}</option>
          </Select>
        </div>
        <div className="sm:col-span-2">
          <Label htmlFor="p-notes">{t("fields.notes")}</Label>
          <Textarea id="p-notes" rows={2} value={v.notes} onChange={(ev) => set("notes", ev.target.value)} />
        </div>
      </div>
      <label className="flex items-start gap-2 text-sm">
        <input type="checkbox" className="mt-1" checked={authorized} onChange={(ev) => setAuthorized(ev.target.checked)} />
        <span>{t("authorizedPaste")}</span>
      </label>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={redact} onChange={(ev) => setRedact(ev.target.checked)} /> {t("redactPersonal")}
      </label>
      {action.error && <Alert variant="destructive"><AlertDescription>{errorMessage(action.error)}</AlertDescription></Alert>}
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" disabled={action.busy || !authorized || v.original_text.trim().length < 10} onClick={() => save(false)}>{t("saveDraft")}</Button>
        <Button disabled={action.busy || !authorized || v.original_text.trim().length < 10} onClick={() => save(true)}>{t("submitForReview")}</Button>
      </div>
    </div>
  );
}

function Field({ id, label, value, onChange, type = "text" }: { id: string; label: string; value: string; onChange: (v: string) => void; type?: string }) {
  return (
    <div>
      <Label htmlFor={id}>{label}</Label>
      <Input id={id} type={type} value={value} onChange={(ev) => onChange(ev.target.value)} />
    </div>
  );
}
