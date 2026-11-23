import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { AiOffice } from "@/features/ai-office/ai-office";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("office");
  return { title: t("title"), description: t("subtitle") };
}

export default function AiOfficePage() {
  return <AiOffice />;
}
