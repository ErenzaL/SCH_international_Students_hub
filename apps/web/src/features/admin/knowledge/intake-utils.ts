import { DEFAULT_SYNC_BY_CATEGORY, KEY_FIELDS, type KeyField } from "@/lib/constants";
import { formatFieldValue } from "@/lib/format-field";
import type { SourceType, StructuredData, SyncFrequency } from "@/types/api";

export { formatFieldValue };

export type DocumentKind = "pdf" | "docx" | "text_file";
export type FileErrorCode = "empty" | "tooLarge" | "unsupportedType";

const DOC_EXT: Record<string, DocumentKind> = { pdf: "pdf", docx: "docx", txt: "text_file", md: "text_file", markdown: "text_file" };
const IMAGE_EXT = new Set(["png", "jpg", "jpeg", "webp"]);

export function fileExtension(name: string): string {
  const i = name.lastIndexOf(".");
  return i >= 0 ? name.slice(i + 1).toLowerCase() : "";
}

export function documentKind(name: string): DocumentKind | null {
  return DOC_EXT[fileExtension(name)] ?? null;
}

/** Client-side pre-check only; the backend re-validates type, magic bytes and size. */
export function validateDocumentFile(file: { name: string; size: number }, maxMb: number, expected?: DocumentKind): FileErrorCode | null {
  if (file.size === 0) return "empty";
  const kind = documentKind(file.name);
  if (!kind || (expected && kind !== expected)) return "unsupportedType";
  if (file.size > maxMb * 1024 * 1024) return "tooLarge";
  return null;
}

export function validateImageFile(file: { name: string; size: number }, maxMb: number): FileErrorCode | null {
  if (file.size === 0) return "empty";
  if (!IMAGE_EXT.has(fileExtension(file.name))) return "unsupportedType";
  if (file.size > maxMb * 1024 * 1024) return "tooLarge";
  return null;
}

/** SCH Global Education notice boards (notice01.php on *.sch.ac.kr). Mirrors backend is_sch_board_url. */
export function isSchBoardUrl(value: string): boolean {
  try {
    const u = new URL(value);
    return (u.protocol === "https:" || u.protocol === "http:") && u.hostname.endsWith("sch.ac.kr") && u.pathname.endsWith("notice01.php");
  } catch {
    return false;
  }
}

/** Suggested schedule: only network sources can sync; others are always manual. */
export function suggestedSync(category: string, sourceType: SourceType): SyncFrequency {
  if (sourceType !== "website" && sourceType !== "sch_board") return "manual";
  return DEFAULT_SYNC_BY_CATEGORY[category] ?? "weekly";
}

/** Detected structured fields -> editable string values (only known keys). */
export function structuredToFieldValues(sd: StructuredData | null | undefined): Partial<Record<KeyField, string>> {
  const out: Partial<Record<KeyField, string>> = {};
  for (const [k, f] of Object.entries(sd?.fields ?? {})) {
    if ((KEY_FIELDS as readonly string[]).includes(k) && f && f.value != null && f.value !== "") {
      out[k as KeyField] = formatFieldValue(f.value);
    }
  }
  return out;
}

/** Drop empty values and trim; returns only non-empty fields (unknown keys are ignored). */
export function fieldsPayload(values: Partial<Record<string, string>>, allowed: readonly string[] = KEY_FIELDS): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(values)) {
    const t = (v ?? "").trim();
    if (t && allowed.includes(k)) out[k] = t;
  }
  return out;
}

/** Fields whose value differs from the original detection (for PATCH /versions/{id} {fields}). Empty string clears. */
export function changedFields(original: Partial<Record<string, string>>, edited: Partial<Record<string, string>>): Record<string, string | null> {
  const out: Record<string, string | null> = {};
  const keys = new Set([...Object.keys(original), ...Object.keys(edited)]);
  for (const k of keys) {
    const a = (original[k] ?? "").trim();
    const b = (edited[k] ?? "").trim();
    if (a !== b) out[k] = b === "" ? null : b;
  }
  return out;
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}
