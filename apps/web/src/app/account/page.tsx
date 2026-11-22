import { getTranslations } from "next-intl/server";
import { PageHeader } from "@/components/shared/states";
import { AccountSettings } from "@/features/account/account-settings";

export default async function AccountPage() {
  const t = await getTranslations("account");
  return (
    <div className="mx-auto max-w-2xl px-4 py-8">
      <PageHeader title={t("title")} description={t("subtitle")} />
      <AccountSettings />
    </div>
  );
}
