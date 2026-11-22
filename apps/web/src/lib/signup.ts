import { SUPPORT_LANGUAGES } from "@/lib/support";
import type { LanguageCode } from "@/types/api";

/** Signup metadata: a required, valid preferred language + optional display name. Never a role. */
export function buildSignupMetadata(
  language: LanguageCode | "" | string,
  displayName: string,
): { preferred_language: LanguageCode; display_name?: string } | null {
  if (!SUPPORT_LANGUAGES.includes(language as LanguageCode)) return null;
  const name = displayName.trim().slice(0, 80);
  return name ? { preferred_language: language as LanguageCode, display_name: name } : { preferred_language: language as LanguageCode };
}
