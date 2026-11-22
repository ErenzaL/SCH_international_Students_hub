import { getTranslations } from "next-intl/server";
import { PageHeader } from "@/components/shared/states";
import { AnnouncementsBrowser } from "@/features/announcements/announcements-browser";

export default async function AnnouncementsPage() {
  const t = await getTranslations("announcements");
  return (
    <div className="mx-auto max-w-6xl px-4 py-8">
      <PageHeader title={t("title")} description={t("subtitle")} />
      <AnnouncementsBrowser />
    </div>
  );
}
