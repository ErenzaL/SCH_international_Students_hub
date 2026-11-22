import { notFound } from "next/navigation";
import { TranslationEditor } from "@/features/admin/translations/translation-editor";
import { LOCALES } from "@/lib/constants";
import type { LanguageCode } from "@/types/api";

export default async function Page({ params }: { params: Promise<{ announcementId: string; lang: string }> }) {
  const { announcementId, lang } = await params;
  const language = decodeURIComponent(lang) as LanguageCode;
  if (!LOCALES.includes(language)) notFound();
  return <TranslationEditor announcementId={announcementId} language={language} />;
}
