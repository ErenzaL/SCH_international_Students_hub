import { getTranslations } from "next-intl/server";
import { PageHeader } from "@/components/shared/states";
import { KnowledgeBrowser } from "@/features/knowledge/knowledge-browser";

export default async function KnowledgePage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string; category?: string }>;
}) {
  const [t, sp] = await Promise.all([getTranslations("knowledge"), searchParams]);
  return (
    <div className="mx-auto max-w-6xl px-4 py-8">
      <PageHeader title={t("title")} description={t("subtitle")} />
      <KnowledgeBrowser initialQuery={sp.q ?? ""} initialCategory={sp.category ?? ""} />
    </div>
  );
}
