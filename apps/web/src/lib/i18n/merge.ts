import { DEFAULT_LOCALE, LOCALES } from "@/lib/constants";
import type { LanguageCode } from "@/types/api";

type Dict = { [key: string]: string | Dict };

/**
 * Deep-merge `override` onto `base`. Any key missing in `override` keeps the
 * base (English) value – this implements the fallback-to-English requirement.
 */
export function deepMerge<T extends Dict>(base: T, override: Dict | undefined): T {
  if (!override) return base;
  const out: Dict = { ...base };
  for (const [k, v] of Object.entries(override)) {
    const b = out[k];
    if (typeof v === "string") {
      if (v.trim() !== "") out[k] = v;
    } else if (v && typeof v === "object") {
      out[k] = deepMerge((typeof b === "object" && b ? b : {}) as Dict, v);
    }
  }
  return out as T;
}

/** Map one BCP-47 tag (e.g. "ko-KR", "zh-Hans", "id") to a supported locale or null. */
export function matchLocale(tag: string | null | undefined): LanguageCode | null {
  if (!tag) return null;
  const t = tag.trim().toLowerCase();
  const exact = LOCALES.find((l) => l.toLowerCase() === t);
  if (exact) return exact;
  const primary = t.split("-")[0];
  if (primary === "zh") {
    // Only Simplified Chinese is supported; Traditional variants are not mapped.
    if (/^zh-(tw|hk|mo|hant)/.test(t)) return null;
    return "zh-CN";
  }
  if (primary === "in") return "id"; // legacy Indonesian code
  return LOCALES.find((l) => l === primary) ?? null;
}

/** Resolve the locale from an explicit preference, then Accept-Language, then English. */
export function resolveLocale(
  preferred: string | null | undefined,
  acceptLanguage: string | null | undefined,
): LanguageCode {
  const fromPref = matchLocale(preferred);
  if (fromPref) return fromPref;
  if (acceptLanguage) {
    const ranked = acceptLanguage
      .split(",")
      .map((part) => {
        const [tag, ...params] = part.trim().split(";");
        const q = params.find((p) => p.trim().startsWith("q="));
        return { tag, q: q ? parseFloat(q.split("=")[1]) || 0 : 1 };
      })
      .sort((a, b) => b.q - a.q);
    for (const { tag } of ranked) {
      const m = matchLocale(tag);
      if (m) return m;
    }
  }
  return DEFAULT_LOCALE;
}
