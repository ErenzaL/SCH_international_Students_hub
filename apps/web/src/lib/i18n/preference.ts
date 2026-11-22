import { LOCALE_COOKIE, LOCALE_STORAGE_KEY } from "@/lib/constants";
import { matchLocale } from "@/lib/i18n/merge";
import type { LanguageCode } from "@/types/api";

/** Persist the user's language choice in a cookie (read by the server) and localStorage. */
export function saveLocalePreference(locale: LanguageCode): void {
  document.cookie = `${LOCALE_COOKIE}=${encodeURIComponent(locale)}; path=/; max-age=31536000; samesite=lax`;
  try {
    localStorage.setItem(LOCALE_STORAGE_KEY, locale);
  } catch {
    /* storage may be unavailable (private mode) – the cookie still works */
  }
}

export function readStoredLocale(): LanguageCode | null {
  try {
    return matchLocale(localStorage.getItem(LOCALE_STORAGE_KEY));
  } catch {
    return null;
  }
}

export function hasLocaleCookie(): boolean {
  return document.cookie.split(";").some((c) => c.trim().startsWith(`${LOCALE_COOKIE}=`));
}
