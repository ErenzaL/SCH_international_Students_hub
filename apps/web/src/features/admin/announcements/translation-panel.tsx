"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Check, Save } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Label, Select, Textarea } from "@/components/ui/input";
import { TranslationStatusBadge } from "@/components/shared/badges";
import { useMe } from "@/features/admin/shell/admin-context";
import { api, errorMessage } from "@/lib/api";
import { LOCALES, LOCALE_LABELS } from "@/lib/constants";
import { useAction } from "@/lib/use-action";
import { formatDateTime } from "@/lib/utils";
import type { AdminAnnouncement, LanguageCode, Translation } from "@/types/api";

/** Per-language translation editors. Machine drafts are always labelled as unreviewed. */
export function TranslationPanel({
  announcement,
  onChanged,
}: {
  announcement: AdminAnnouncement;
  onChanged: () => void;
}) {
  const t = useTranslations("admin.translations");
  const targets = LOCALES.filter((l) => l !== announcement.original_language);
  return (
    <section aria-labelledby="tp-h" className="space-y-3">
      <h2 id="tp-h" className="text-lg font-semibold">
        {t("panelTitle")}
      </h2>
      <Alert variant="info">
        <AlertDescription>{t("flowNote")}</AlertDescription>
      </Alert>
      <div className="grid gap-4 lg:grid-cols-2">
        {targets.map((lang) => (
          <TranslationEditor
            key={lang}
            announcement={announcement}
            language={lang}
            existing={announcement.translations.find((x) => x.language_code === lang)}
            onChanged={onChanged}
          />
        ))}
      </div>
    </section>
  );
}

function TranslationEditor({
  announcement,
  language,
  existing,
  onChanged,
}: {
  announcement: AdminAnnouncement;
  language: LanguageCode;
  existing?: Translation;
  onChanged: () => void;
}) {
  const t = useTranslations("admin.translations");
  const e = useTranslations("enums");
  const locale = useLocale();
  const me = useMe();
  const [title, setTitle] = useState(existing?.title ?? "");
  const [body, setBody] = useState(existing?.body ?? "");
  const [status, setStatus] = useState<"machine_draft" | "in_review">(
    existing?.translation_status === "in_review" ? "in_review" : "machine_draft",
  );
  const action = useAction();
  const [done, setDone] = useState<string | null>(null);

  const isAdmin = me.role === "admin" || me.role === "super_admin";
  const canEdit = isAdmin || (me.role === "supporter" && me.languages.includes(language));
  const approved = existing?.translation_status === "human_approved";

  async function save() {
    setDone(null);
    const res = await action.run(() =>
      api.put<Translation>(`/api/v1/admin/announcements/${announcement.id}/translations/${language}`, {
        title: title.trim(),
        body,
        translation_status: status,
      }),
    );
    if (res) {
      setDone(t("saved"));
      onChanged();
    }
  }
  async function approve() {
    setDone(null);
    const res = await action.run(() =>
      api.post<Translation>(`/api/v1/admin/announcements/${announcement.id}/translations/${language}/approve`),
    );
    if (res) {
      setDone(t("approvedDone"));
      onChanged();
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2 text-base">
          {LOCALE_LABELS[language]}
          {existing ? <TranslationStatusBadge status={existing.translation_status} /> : <span className="text-xs font-normal text-muted-foreground">{t("none")}</span>}
        </CardTitle>
        {existing?.translation_status === "machine_draft" && (
          <p className="text-xs font-medium text-amber-800">{t("machineWarning")}</p>
        )}
        {existing?.reviewed_at && (
          <p className="text-xs text-muted-foreground">
            {t("reviewedBy", { name: existing.reviewed_by_name ?? "—", date: formatDateTime(existing.reviewed_at, locale) })}
          </p>
        )}
      </CardHeader>
      <CardContent className="space-y-3">
        {!canEdit && <p className="text-xs text-muted-foreground">{t("notAssigned")}</p>}
        <div>
          <Label htmlFor={`tr-title-${language}`}>{t("fieldTitle")}</Label>
          <Input id={`tr-title-${language}`} lang={language} value={title} disabled={!canEdit} onChange={(ev) => setTitle(ev.target.value)} />
        </div>
        <div>
          <Label htmlFor={`tr-body-${language}`}>{t("fieldBody")}</Label>
          <Textarea id={`tr-body-${language}`} lang={language} rows={6} value={body} disabled={!canEdit} onChange={(ev) => setBody(ev.target.value)} />
        </div>
        <div>
          <Label htmlFor={`tr-status-${language}`}>{t("statusLabel")}</Label>
          <Select id={`tr-status-${language}`} value={status} disabled={!canEdit} onChange={(ev) => setStatus(ev.target.value as typeof status)}>
            <option value="machine_draft">{e("translation.machine_draft")}</option>
            <option value="in_review">{e("translation.in_review")}</option>
          </Select>
        </div>
        {action.error && <Alert variant="destructive">{errorMessage(action.error)}</Alert>}
        {done && <Alert variant="success">{done}</Alert>}
        {canEdit && (
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="outline" disabled={action.busy || !title.trim() || !body.trim()} onClick={save}>
              <Save /> {t("save")}
            </Button>
            {existing && !approved && (
              <Button size="sm" disabled={action.busy} onClick={approve}>
                <Check /> {t("approveHuman")}
              </Button>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
