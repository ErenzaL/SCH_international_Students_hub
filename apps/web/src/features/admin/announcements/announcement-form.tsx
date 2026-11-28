"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { ArrowLeft, Save, Send } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { FieldError, Input, Label, Select, Textarea } from "@/components/ui/input";
import { PageHeader } from "@/components/shared/states";
import {
  cleanTargets,
  EMPTY_ANNOUNCEMENT_FORM,
  toAnnouncementCreate,
  validateAnnouncementForm,
  type AnnouncementFormErrors,
  type AnnouncementFormValues,
} from "@/features/admin/announcements/announcement-validation";
import { api, errorMessage } from "@/lib/api";
import { ANNOUNCEMENT_MACHINE_LANGUAGES, CATEGORY_SLUGS, LOCALE_LABELS } from "@/lib/constants";
import { useAction } from "@/lib/use-action";
import { useCategoryName } from "@/lib/use-category-name";
import type { AdminAnnouncement, LanguageCode } from "@/types/api";

export function formFromAnnouncement(a: AdminAnnouncement): AnnouncementFormValues {
  return {
    title: a.title,
    body: a.body,
    category: a.category,
    target_audience: a.target_audience ?? "",
    event_date: a.event_date ?? "",
    deadline: a.deadline ?? "",
    valid_from: a.valid_from ?? "",
    source_type: a.source_type,
    source_published_at: "",
    evidence_note: a.evidence_note ?? "",
    evidence_url: a.evidence_url ?? "",
    authorized_by_supporter: a.source_type === "kakao_message",
    original_language: a.original_language,
    translation_targets: a.translation_targets ?? [],
  };
}

/** Create (no `existing`) or edit (draft/rejected `existing`) a manual announcement. */
export function AnnouncementForm({
  existing,
  onSaved,
}: {
  existing?: AdminAnnouncement;
  onSaved?: (a: AdminAnnouncement) => void;
}) {
  const t = useTranslations("admin.announcements.form");
  const e = useTranslations("enums");
  const v = useTranslations("admin.announcements.validation");
  const at = useTranslations("admin.announcements.autoTr");
  const router = useRouter();
  const categoryName = useCategoryName();
  const [values, setValues] = useState<AnnouncementFormValues>(
    existing ? formFromAnnouncement(existing) : EMPTY_ANNOUNCEMENT_FORM,
  );
  const [errors, setErrors] = useState<AnnouncementFormErrors>({});
  const action = useAction();

  const set = <K extends keyof AnnouncementFormValues>(k: K, val: AnnouncementFormValues[K]) =>
    setValues((s) => ({ ...s, [k]: val }));
  const err = (k: keyof AnnouncementFormValues) => (errors[k] ? v(errors[k]!) : undefined);

  async function save(submit: boolean) {
    const errs = validateAnnouncementForm(values);
    setErrors(errs);
    if (Object.keys(errs).length) return;
    const saved = await action.run(async () => {
      if (!existing) {
        return api.post<AdminAnnouncement>("/api/v1/admin/announcements", toAnnouncementCreate(values, submit));
      }
      const nul = (x: string) => (x.trim() ? x.trim() : null);
      const patch = {
        title: values.title.trim(),
        body: values.body,
        category: values.category,
        target_audience: nul(values.target_audience),
        event_date: nul(values.event_date),
        deadline: nul(values.deadline),
        valid_from: nul(values.valid_from),
        evidence_note: nul(values.evidence_note),
        evidence_url: nul(values.evidence_url),
        original_language: values.original_language,
        translation_targets: cleanTargets(values),
      };
      let res = await api.patch<AdminAnnouncement>(`/api/v1/admin/announcements/${existing.id}`, patch);
      if (submit) res = await api.post<AdminAnnouncement>(`/api/v1/admin/announcements/${existing.id}/submit`);
      return res;
    });
    if (!saved) return;
    if (onSaved) onSaved(saved);
    else router.push(`/admin/announcements/${saved.id}`);
  }

  const isKakao = values.source_type === "kakao_message";
  return (
    <div>
      {!existing && (
        <>
          <Link href="/admin/announcements" className="mb-3 inline-flex items-center gap-1 text-sm text-primary hover:underline">
            <ArrowLeft className="size-4" /> {t("back")}
          </Link>
          <PageHeader title={t("newTitle")} description={t("newSubtitle")} />
        </>
      )}
      <Alert variant="info" className="mb-4">
        <AlertDescription>{t("noAutoPublish")}</AlertDescription>
      </Alert>
      <Card>
        <CardContent className="p-5">
          <form
            noValidate
            className="grid gap-4 sm:grid-cols-2"
            onSubmit={(ev) => {
              ev.preventDefault();
              void save(false);
            }}
          >
            <div className="sm:col-span-2">
              <Label htmlFor="an-title">{t("title")}</Label>
              <Input id="an-title" value={values.title} aria-invalid={!!errors.title} onChange={(ev) => set("title", ev.target.value)} />
              <FieldError>{err("title")}</FieldError>
            </div>
            <div>
              <Label htmlFor="an-lang">{t("originalLanguage")}</Label>
              <Select id="an-lang" value={values.original_language}
                onChange={(ev) => set("original_language", ev.target.value as LanguageCode)}>
                {ANNOUNCEMENT_MACHINE_LANGUAGES.map((l) => (
                  <option key={l} value={l}>{LOCALE_LABELS[l]}</option>
                ))}
              </Select>
            </div>
            <div className="sm:col-span-2">
              <Label htmlFor="an-body">{t("body")}</Label>
              <Textarea id="an-body" lang={values.original_language} rows={12} value={values.body} aria-invalid={!!errors.body} onChange={(ev) => set("body", ev.target.value)} placeholder={t("bodyPlaceholder")} />
              <p className="mt-1 text-xs text-muted-foreground">{t("bodyHint")}</p>
              <FieldError>{err("body")}</FieldError>
            </div>
            <div>
              <Label htmlFor="an-cat">{t("category")}</Label>
              <Select id="an-cat" value={values.category} onChange={(ev) => set("category", ev.target.value)}>
                {CATEGORY_SLUGS.map((s) => (
                  <option key={s} value={s}>
                    {categoryName(s)}
                  </option>
                ))}
              </Select>
            </div>
            <div>
              <Label htmlFor="an-aud">{t("audience")}</Label>
              <Input id="an-aud" value={values.target_audience} onChange={(ev) => set("target_audience", ev.target.value)} placeholder={t("audiencePlaceholder")} />
            </div>
            <div>
              <Label htmlFor="an-event">{t("eventDate")}</Label>
              <Input id="an-event" type="date" value={values.event_date} onChange={(ev) => set("event_date", ev.target.value)} />
            </div>
            <div>
              <Label htmlFor="an-deadline">{t("deadline")}</Label>
              <Input id="an-deadline" type="date" value={values.deadline} onChange={(ev) => set("deadline", ev.target.value)} />
            </div>
            <div>
              <Label htmlFor="an-from">{t("validFrom")}</Label>
              <Input id="an-from" type="date" value={values.valid_from} onChange={(ev) => set("valid_from", ev.target.value)} />
            </div>
            <div>
              <Label htmlFor="an-pub">{t("sourcePublished")}</Label>
              <Input id="an-pub" type="date" value={values.source_published_at} disabled={!!existing} onChange={(ev) => set("source_published_at", ev.target.value)} />
            </div>
            <div>
              <Label htmlFor="an-srctype">{t("sourceType")}</Label>
              <Select id="an-srctype" value={values.source_type} disabled={!!existing} onChange={(ev) => set("source_type", ev.target.value as AnnouncementFormValues["source_type"])}>
                <option value="manual_text">{e("sourceType.manual_text")}</option>
                <option value="kakao_message">{e("sourceType.kakao_message")}</option>
              </Select>
            </div>
            <div>
              <Label htmlFor="an-evurl">{t("evidenceUrl")}</Label>
              <Input id="an-evurl" type="url" placeholder="https://…" value={values.evidence_url} aria-invalid={!!errors.evidence_url} onChange={(ev) => set("evidence_url", ev.target.value)} />
              <FieldError>{err("evidence_url")}</FieldError>
            </div>
            <div className="sm:col-span-2">
              <Label htmlFor="an-evnote">{t("evidenceNote")}</Label>
              <Textarea id="an-evnote" rows={2} value={values.evidence_note} onChange={(ev) => set("evidence_note", ev.target.value)} placeholder={t("evidenceNotePlaceholder")} />
            </div>

            <fieldset className="sm:col-span-2 rounded-lg border border-border p-4" data-testid="auto-translation">
              <legend className="px-1 text-sm font-semibold">{at("title")}</legend>
              <p className="mb-2 text-xs text-muted-foreground">{at("hint")}</p>
              <div className="flex flex-wrap gap-4">
                {ANNOUNCEMENT_MACHINE_LANGUAGES.map((l) => {
                  const original = l === values.original_language;
                  return (
                    <label key={l} className={`flex items-center gap-2 text-sm ${original ? "text-muted-foreground" : ""}`}>
                      <input type="checkbox" data-testid={`auto-tr-${l}`} disabled={original}
                        checked={!original && values.translation_targets.includes(l)}
                        onChange={(ev) => set("translation_targets", ev.target.checked
                          ? [...values.translation_targets, l]
                          : values.translation_targets.filter((x) => x !== l))} />
                      {LOCALE_LABELS[l]}{original && ` (${at("original")})`}
                    </label>
                  );
                })}
              </div>
              <p className="mt-2 text-xs text-muted-foreground">
                {cleanTargets(values).length === 0 ? at("noneChosen") : at("afterApproval")}
              </p>
            </fieldset>

            {isKakao && (
              <div className="sm:col-span-2">
                <Alert variant="warning">
                  <AlertTitle>{t("kakaoTitle")}</AlertTitle>
                  <AlertDescription>
                    <p>{t("kakaoBody")}</p>
                    <label className="mt-2 flex items-start gap-2">
                      <input
                        type="checkbox"
                        className="mt-1"
                        checked={values.authorized_by_supporter}
                        disabled={!!existing}
                        onChange={(ev) => set("authorized_by_supporter", ev.target.checked)}
                      />
                      <span>{t("kakaoAuthorized")}</span>
                    </label>
                    <FieldError>{err("authorized_by_supporter")}</FieldError>
                  </AlertDescription>
                </Alert>
              </div>
            )}

            {action.error && (
              <Alert variant="destructive" className="sm:col-span-2">
                {errorMessage(action.error)}
              </Alert>
            )}
            <div className="flex flex-wrap gap-2 sm:col-span-2">
              <Button type="submit" variant="outline" disabled={action.busy}>
                <Save /> {t("saveDraft")}
              </Button>
              <Button type="button" disabled={action.busy} onClick={() => void save(true)}>
                <Send /> {t("submitForApproval")}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
