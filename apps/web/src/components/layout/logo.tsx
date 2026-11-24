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
      {/* the name: on phones (beside the menu button) and from 1280 px; between, the full menu needs the room */}
      <span className="hidden whitespace-nowrap text-sm font-semibold leading-tight text-primary sm:inline lg:hidden xl:inline">
        {t("name")}
      </span>
    </span>
  );
}
