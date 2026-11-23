"use client";

import { useTranslations } from "next-intl";
import type { OfficeCharacter, ZoneId } from "@/features/ai-office/characters";
import type { LanguageCode } from "@/types/api";

/** Short native names on the supporters' name tags (proper names of the languages, not translated). */
const NATIVE_SHORT: Record<LanguageCode, string> = { ko: "한국어", en: "English", id: "Indonesia", vi: "Tiếng Việt", "zh-CN": "中文" };

export function useOfficeLabels() {
  const t = useTranslations("office");
  const languageName = (l: LanguageCode) => t(`languages.${l}`);
  return {
    zone: (id: ZoneId) => t(`zones.${id}`),
    languageName,
    languageShort: (l: LanguageCode) => NATIVE_SHORT[l],
    roleTitle: (c: OfficeCharacter) =>
      c.role === "supporter" && c.language ? t("roles.supporter.title", { language: languageName(c.language) })
        : t(`roles.${c.role}.title`),
    roleDescription: (c: OfficeCharacter) =>
      c.role === "supporter" && c.language ? t("roles.supporter.description", { language: languageName(c.language) })
        : t(`roles.${c.role}.description`),
  };
}
