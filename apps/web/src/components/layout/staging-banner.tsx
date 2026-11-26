import { getTranslations } from "next-intl/server";

/** NEXT_PUBLIC_SITE_ENV=staging (set only on the staging web service): a banner on every page and no search indexing. */
export const SITE_ENV = process.env.NEXT_PUBLIC_SITE_ENV ?? "production";

export async function StagingBanner() {
  if (SITE_ENV !== "staging") return null;
  const t = await getTranslations("staging");
  return (
    <div role="note" data-testid="staging-banner"
      className="bg-amber-400 px-4 py-1.5 text-center text-sm font-semibold text-amber-950">
      {t("banner")}
    </div>
  );
}
