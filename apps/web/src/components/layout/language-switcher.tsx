"use client";

import { useEffect } from "react";
import { useLocale, useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { Globe } from "lucide-react";
import { LOCALES, LOCALE_LABELS } from "@/lib/constants";
import { matchLocale } from "@/lib/i18n/merge";
import { hasLocaleCookie, readStoredLocale, saveLocalePreference } from "@/lib/i18n/preference";
import type { LanguageCode } from "@/types/api";

export function LanguageSwitcher() {
  const t = useTranslations("nav");
  const locale = useLocale();
  const router = useRouter();

  // If the cookie was cleared but a stored preference exists, restore it once.
  useEffect(() => {
    if (hasLocaleCookie()) return;
    const stored = readStoredLocale();
    if (stored && stored !== locale) {
      saveLocalePreference(stored);
      router.refresh();
    }
  }, [locale, router]);

  function onChange(value: string) {
    const next = matchLocale(value) as LanguageCode | null;
    if (!next) return;
    saveLocalePreference(next);
    router.refresh();
  }

  return (
    <div className="relative inline-flex items-center">
      <Globe className="pointer-events-none absolute left-2.5 size-4 text-muted-foreground" aria-hidden />
      <select
        aria-label={t("language")}
        value={locale}
        onChange={(e) => onChange(e.target.value)}
        className="h-9 rounded-md border border-border bg-background pl-8 pr-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        {LOCALES.map((l) => (
          <option key={l} value={l} lang={l}>
            {LOCALE_LABELS[l]}
          </option>
        ))}
      </select>
    </div>
  );
}
