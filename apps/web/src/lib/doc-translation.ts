/** Pure helpers for multilingual Knowledge Center articles and document-translation review. */
import { LOCALES } from "@/lib/constants";
import type { DocTranslation, DocTranslationStatus, KnowledgeDocumentDetail, LanguageCode } from "@/types/api";

export type ArticleMode = "original" | "verified" | "machine" | "fallback";

export interface ArticleView {
  mode: ArticleMode;
  title: string;
  content: string;
  /** Language of the text actually shown (for the `lang` attribute). */
  language: LanguageCode;
}

/** The content language to request: explicit choice (?lang=) > site language. Never changes the profile. */
export function contentLanguage(explicit: string | null | undefined, siteLocale: string): LanguageCode {
  const ok = (l: string | null | undefined): l is LanguageCode => !!l && (LOCALES as readonly string[]).includes(l);
  return ok(explicit) ? explicit : ok(siteLocale) ? siteLocale : "en";
}

/**
 * What the article shows. The original is authoritative; a translation is shown only when the API returned one
 * for the requested language (verified, or a clearly-labelled machine draft) and the reader did not ask for the
 * original. Without one, the original is shown as a fallback.
 */
export function articleView(d: Pick<KnowledgeDocumentDetail, "title" | "content" | "language" | "translation">,
  requested: LanguageCode, showOriginal: boolean): ArticleView {
  const original = { title: d.title, content: d.content, language: d.language };
  if (requested === d.language) return { mode: "original", ...original };
  if (!showOriginal && d.translation && d.translation.language === requested) {
    return { mode: d.translation.status, title: d.translation.title, content: d.translation.content, language: requested };
  }
  return { mode: d.translation && showOriginal ? "original" : "fallback", ...original };
}

type Variant = "default" | "secondary" | "outline" | "success" | "warning" | "danger" | "info" | "muted";

export const DOC_TR_VARIANT: Record<DocTranslationStatus, Variant> = {
  todo: "muted",
  machine_draft: "info",
  draft: "secondary",
  in_review: "warning",
  changes_requested: "warning",
  human_approved: "success",
  rejected: "danger",
};

/** Badge key for a translation row: outdated beats everything (never shown as verified). */
export function docTranslationState(t: Pick<DocTranslation, "translation_status" | "is_outdated"> | null): DocTranslationStatus | "outdated" | "none" {
  if (!t) return "none";
  if (t.is_outdated) return "outdated";
  return t.translation_status;
}

export type DiffOp = { op: "same" | "add" | "del"; text: string };

/** Line diff (LCS) for version comparison. Large inputs fall back to a coarse comparison to stay responsive. */
export function lineDiff(a: string, b: string, maxCells = 400_000): DiffOp[] {
  const x = a.split("\n");
  const y = b.split("\n");
  if (x.length * y.length > maxCells) {
    const ys = new Set(y);
    const xs = new Set(x);
    return [...x.filter((l) => !ys.has(l)).map((text) => ({ op: "del" as const, text })),
      ...y.map((text) => ({ op: xs.has(text) ? ("same" as const) : ("add" as const), text }))];
  }
  const m = x.length;
  const n = y.length;
  const dp: Uint32Array[] = Array.from({ length: m + 1 }, () => new Uint32Array(n + 1));
  for (let i = m - 1; i >= 0; i--) {
    for (let j = n - 1; j >= 0; j--) {
      dp[i][j] = x[i] === y[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const out: DiffOp[] = [];
  let i = 0;
  let j = 0;
  while (i < m && j < n) {
    if (x[i] === y[j]) {
      out.push({ op: "same", text: x[i] });
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      out.push({ op: "del", text: x[i++] });
    } else {
      out.push({ op: "add", text: y[j++] });
    }
  }
  while (i < m) out.push({ op: "del", text: x[i++] });
  while (j < n) out.push({ op: "add", text: y[j++] });
  return out;
}

/** Split Markdown-ish text into blocks so headings render as headings (no HTML injection: text only). */
export function textBlocks(text: string): { kind: "h1" | "h2" | "h3" | "p"; text: string }[] {
  return text
    .split(/\n\s*\n/)
    .map((block) => block.trim())
    .filter(Boolean)
    .map((block) => {
      const m = /^(#{1,6})\s+(.+)$/.exec(block);
      if (m && !block.includes("\n")) {
        const level = Math.min(m[1].length, 3);
        return { kind: (`h${level}` as "h1" | "h2" | "h3"), text: m[2].replace(/\s+#+\s*$/, "") };
      }
      return { kind: "p" as const, text: block };
    });
}
