"use client";

import { useTranslations } from "next-intl";
import { Badge } from "@/components/ui/badge";
import { translationBadge } from "@/lib/support";
import type { TranslationStatus } from "@/types/api";

export function TranslationStateBadge({
  translation,
}: {
  translation: { translation_status: TranslationStatus; is_outdated?: boolean; published?: boolean };
}) {
  const t = useTranslations("admin.trreview.badge");
  const b = translationBadge(translation);
  return <Badge variant={b.variant}>{t(b.key)}</Badge>;
}
