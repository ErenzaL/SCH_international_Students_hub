"use client";

import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { Languages } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { TranslationStateBadge } from "@/features/admin/translations/translation-state-badge";
import { LOCALES, LOCALE_LABELS } from "@/lib/constants";
import { formatDateTime } from "@/lib/utils";
import type { AdminAnnouncement, Translation } from "@/types/api";

/** Per-language translation status; editing and review happen in the language-scoped review editor. */
export function TranslationPanel({ announcement }: { announcement: AdminAnnouncement; onChanged?: () => void }) {
  const t = useTranslations("admin.trreview");
  const locale = useLocale();
  const targets = LOCALES.filter((l) => l !== announcement.original_language);
  return (
    <section aria-labelledby="tp-h" className="space-y-3">
      <h2 id="tp-h" className="text-lg font-semibold">
        {t("panelTitle")}
      </h2>
      <Alert variant="info">
        <AlertDescription>{t("panelNote")}</AlertDescription>
      </Alert>
      <div className="grid gap-3 sm:grid-cols-2">
        {targets.map((lang) => {
          const tr = announcement.translations.find((x) => x.language_code === lang) as
            | (Translation & { is_outdated?: boolean })
            | undefined;
          return (
            <Card key={lang}>
              <CardHeader>
                <CardTitle className="flex flex-wrap items-center gap-2 text-base">
                  {LOCALE_LABELS[lang]}
                  {tr ? <TranslationStateBadge translation={tr} /> : <span className="text-xs font-normal text-muted-foreground">{t("badge.todo")}</span>}
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2 text-sm">
                {tr?.title && <p lang={lang} className="truncate">{tr.title}</p>}
                {tr?.reviewed_at && (
                  <p className="text-xs text-muted-foreground">
                    {t("reviewedBy", { name: tr.reviewed_by_name ?? "—", date: formatDateTime(tr.reviewed_at, locale) })}
                  </p>
                )}
                <Button asChild size="sm" variant="outline">
                  <Link href={`/admin/translations/${announcement.id}/${lang}`}>
                    <Languages /> {t("open")}
                  </Link>
                </Button>
              </CardContent>
            </Card>
          );
        })}
      </div>
    </section>
  );
}
