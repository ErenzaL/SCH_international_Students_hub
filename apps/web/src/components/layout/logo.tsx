import { useTranslations } from "next-intl";

/** Text-based temporary identity. Replace only with officially approved SCH assets. */
export function Logo() {
  const t = useTranslations("brand");
  return (
    <span className="flex items-center gap-2">
      <span
        aria-hidden
        className="flex size-9 items-center justify-center rounded-lg bg-primary text-sm font-bold text-primary-foreground"
      >
        SCH
      </span>
      <span className="hidden flex-col leading-tight sm:flex">
        <span className="text-sm font-semibold text-primary">{t("name")}</span>
        <span className="text-[11px] text-muted-foreground">{t("unofficial")}</span>
      </span>
    </span>
  );
}
