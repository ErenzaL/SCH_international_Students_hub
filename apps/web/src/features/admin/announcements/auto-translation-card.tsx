"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Languages, Save } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api, errorMessage } from "@/lib/api";
import { ANNOUNCEMENT_MACHINE_LANGUAGES, LOCALE_LABELS } from "@/lib/constants";
import { useAction } from "@/lib/use-action";
import type { AdminAnnouncement, LanguageCode } from "@/types/api";

type Saved = AdminAnnouncement & { queued: { job_id: string; language: LanguageCode; status: string }[] };

/** The machine-translation languages of one announcement. Chosen while writing it; admins can change them while it
 *  waits for approval, and for a published announcement saving queues the missing drafts of the chosen languages
 *  (approved translations and reviewers' work are never replaced). */
export function AutoTranslationCard({ announcement: a, admin, onChanged }: {
  announcement: AdminAnnouncement; admin: boolean; onChanged: () => void;
}) {
  const t = useTranslations("admin.announcements.autoTr");
  const offered = (a.machine_languages ?? ANNOUNCEMENT_MACHINE_LANGUAGES) as LanguageCode[];
  const [chosen, setChosen] = useState<LanguageCode[]>(a.translation_targets ?? []);
  const [notice, setNotice] = useState<string | null>(null);
  const action = useAction();
  const editable = admin && (a.publication_status === "pending_approval" || a.publication_status === "published");
  const inScope = offered.includes(a.original_language);
  const targets = offered.filter((l) => l !== a.original_language);

  async function save() {
    setNotice(null);
    const res = await action.run(() =>
      api.put<Saved>(`/api/v1/admin/announcements/${a.id}/translation-targets`, { languages: chosen }),
    );
    if (res) {
      setNotice(res.queued.length ? t("savedQueued", { count: res.queued.length }) : t("saved"));
      onChanged();
    }
  }

  return (
    <Card data-testid="auto-translation-card">
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-base">
          <Languages className="size-4 text-primary" aria-hidden /> {t("title")}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {!inScope ? (
          <p className="text-muted-foreground">{t("notOffered")}</p>
        ) : (
          <>
            <p className="text-xs text-muted-foreground">{t("hint")}</p>
            <div className="flex flex-wrap gap-4">
              {targets.map((l) => (
                <label key={l} className="flex items-center gap-2">
                  <input type="checkbox" data-testid={`card-auto-tr-${l}`} disabled={!editable || action.busy}
                    checked={chosen.includes(l)}
                    onChange={(ev) => setChosen((c) => (ev.target.checked ? [...c, l] : c.filter((x) => x !== l)))} />
                  {LOCALE_LABELS[l]}
                </label>
              ))}
            </div>
            <p className="text-xs text-muted-foreground">
              {a.translation_targets == null ? t("notChosen")
                : a.publication_status === "published" ? t("publishedNote") : t("afterApproval")}
            </p>
            {editable && (
              <Button size="sm" variant="outline" disabled={action.busy} onClick={save} data-testid="auto-tr-save">
                <Save /> {a.publication_status === "published" ? t("saveAndQueue") : t("save")}
              </Button>
            )}
            {!editable && (a.publication_status === "draft" || a.publication_status === "rejected") && (
              <p className="text-xs text-muted-foreground">{t("editToChange")}</p>
            )}
          </>
        )}
        {notice && <Alert variant="success"><AlertDescription>{notice}</AlertDescription></Alert>}
        {action.error && <Alert variant="destructive">{errorMessage(action.error)}</Alert>}
      </CardContent>
    </Card>
  );
}
