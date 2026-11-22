"use client";

import { useTranslations } from "next-intl";
import { CATEGORY_SLUGS } from "@/lib/constants";

/** Localised category label; unknown slugs fall back to the raw slug. */
export function useCategoryName() {
  const t = useTranslations("categories");
  return (slug: string) =>
    (CATEGORY_SLUGS as readonly string[]).includes(slug) ? t(slug) : slug;
}
