import { notFound } from "next/navigation";
import { DocTranslationEditor } from "@/features/admin/translations/doc-translation-editor";
import { LOCALES } from "@/lib/constants";
import type { LanguageCode } from "@/types/api";

export default async function Page({ params }: { params: Promise<{ documentId: string; lang: string }> }) {
  const { documentId, lang } = await params;
  const language = decodeURIComponent(lang) as LanguageCode;
  if (!LOCALES.includes(language)) notFound();
  return <DocTranslationEditor documentId={documentId} language={language} />;
}
