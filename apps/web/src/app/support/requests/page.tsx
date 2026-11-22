import { getTranslations } from "next-intl/server";
import { PageHeader } from "@/components/shared/states";
import { MyRequests } from "@/features/support/my-requests";

export default async function MyRequestsPage() {
  const t = await getTranslations("requests");
  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      <PageHeader title={t("title")} description={t("subtitle")} />
      <MyRequests />
    </div>
  );
}
