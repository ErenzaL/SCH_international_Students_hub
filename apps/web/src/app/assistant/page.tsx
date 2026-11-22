import { getTranslations } from "next-intl/server";
import { PageHeader } from "@/components/shared/states";
import { AssistantEntry } from "@/features/assistant/assistant-entry";

export default async function AssistantPage({ searchParams }: { searchParams: Promise<{ q?: string }> }) {
  const [t, sp] = await Promise.all([getTranslations("assistant"), searchParams]);
  return (
    <div className="mx-auto max-w-6xl px-4 py-8">
      <PageHeader title={t("title")} description={t("subtitle")} />
      <AssistantEntry initialQuestion={sp.q ?? ""} />
    </div>
  );
}
