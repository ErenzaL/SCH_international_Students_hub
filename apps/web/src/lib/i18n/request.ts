import { cookies, headers } from "next/headers";
import { getRequestConfig } from "next-intl/server";
import { LOCALE_COOKIE } from "@/lib/constants";
import { deepMerge, resolveLocale } from "@/lib/i18n/merge";
import en from "@/messages/en.json";

type Dict = { [key: string]: string | Dict };

const loaders = {
  ko: () => import("@/messages/ko.json"),
  id: () => import("@/messages/id.json"),
  vi: () => import("@/messages/vi.json"),
  "zh-CN": () => import("@/messages/zh-CN.json"),
} as const;

export default getRequestConfig(async () => {
  const [cookieStore, headerStore] = await Promise.all([cookies(), headers()]);
  const locale = resolveLocale(
    cookieStore.get(LOCALE_COOKIE)?.value,
    headerStore.get("accept-language"),
  );
  let messages: typeof en = en;
  if (locale !== "en") {
    const mod = await loaders[locale]();
    // English is the base; missing translated keys fall back to it.
    messages = deepMerge(en as Dict, mod.default as Dict) as typeof en;
  }
  return { locale, messages };
});
