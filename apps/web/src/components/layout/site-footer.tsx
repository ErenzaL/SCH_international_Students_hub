import Link from "next/link";
import { useTranslations } from "next-intl";
import { NAV_ITEMS } from "@/components/layout/nav-items";

export function SiteFooter() {
  const t = useTranslations("footer");
  const n = useTranslations("nav");
  return (
    <footer className="mt-16 border-t border-border bg-muted/40">
      <div className="mx-auto grid max-w-6xl gap-8 px-4 py-10 md:grid-cols-3">
        <div className="space-y-2">
          <p className="text-sm font-semibold text-primary">{t("brand")}</p>
          <p className="text-sm text-muted-foreground">{t("about")}</p>
        </div>
        <div>
          <p className="mb-2 text-sm font-semibold">{t("links")}</p>
          <ul className="space-y-1 text-sm">
            {NAV_ITEMS.map((i) => (
              <li key={i.href}>
                <Link href={i.href} className="text-muted-foreground hover:text-foreground hover:underline">
                  {n(i.key)}
                </Link>
              </li>
            ))}
          </ul>
        </div>
        <div className="space-y-2">
          <p className="text-sm font-semibold">{t("supportTitle")}</p>
          <p className="text-sm text-muted-foreground">{t("support")}</p>
          <Link href="/support" className="text-sm font-medium text-primary hover:underline">
            {t("supportLink")}
          </Link>
        </div>
      </div>
      <div className="border-t border-border">
        <div className="mx-auto max-w-6xl space-y-1 px-4 py-4 text-xs text-muted-foreground">
          <p>{t("disclaimer")}</p>
          <p>{t("uiNote")}</p>
        </div>
      </div>
    </footer>
  );
}
