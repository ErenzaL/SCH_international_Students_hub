import { isSchBoardUrl } from "@/features/admin/knowledge/intake-utils";
import { CATEGORY_SLUGS, LOCALES } from "@/lib/constants";
import type {
  AuthorityType,
  LanguageCode,
  Scope,
  SourceCreate,
  SourceType,
  SyncFrequency,
} from "@/types/api";

export interface SourceFormValues {
  title: string;
  original_url: string;
  organization: string;
  source_type: SourceType;
  authority_type: AuthorityType;
  scope: Scope;
  category: string;
  language: LanguageCode;
  sync_frequency: SyncFrequency;
}

export type SourceFormErrorCode =
  | "required"
  | "tooLong"
  | "urlRequired"
  | "invalidUrl"
  | "manualOnly"
  | "kakaoAuthority"
  | "boardUrl"
  | "invalidChoice";

export type SourceFormErrors = Partial<Record<keyof SourceFormValues, SourceFormErrorCode>>;

export const EMPTY_SOURCE_FORM: SourceFormValues = {
  title: "",
  original_url: "",
  organization: "",
  source_type: "website",
  authority_type: "official_government",
  scope: "national",
  category: "visa-immigration",
  language: "en",
  sync_frequency: "manual",
};

export function isHttpUrl(value: string): boolean {
  try {
    const u = new URL(value);
    return (u.protocol === "http:" || u.protocol === "https:") && Boolean(u.hostname);
  } catch {
    return false;
  }
}

/**
 * Pure client-side validation. It mirrors the backend rules for fast feedback only;
 * the backend (including the domain allow-list) remains the source of truth.
 */
export function validateSourceForm(v: SourceFormValues): SourceFormErrors {
  const errors: SourceFormErrors = {};
  const title = v.title.trim();
  if (!title) errors.title = "required";
  else if (title.length > 200) errors.title = "tooLong";

  if (!v.organization.trim()) errors.organization = "required";

  const url = v.original_url.trim();
  const networked = v.source_type === "website" || v.source_type === "sch_board";
  if (networked) {
    if (!url) errors.original_url = "urlRequired";
    else if (!isHttpUrl(url)) errors.original_url = "invalidUrl";
    else if (v.source_type === "sch_board" && !isSchBoardUrl(url)) errors.original_url = "boardUrl";
  } else if (url && !isHttpUrl(url)) {
    errors.original_url = "invalidUrl";
  }

  if (!networked && v.sync_frequency !== "manual") {
    errors.sync_frequency = "manualOnly";
  }
  if (
    v.source_type === "kakao_message" &&
    v.authority_type !== "supporter_submitted" &&
    v.authority_type !== "staff_communication"
  ) {
    errors.authority_type = "kakaoAuthority";
  }
  if (!(CATEGORY_SLUGS as readonly string[]).includes(v.category)) errors.category = "invalidChoice";
  if (!LOCALES.includes(v.language)) errors.language = "invalidChoice";
  return errors;
}

export function toSourceCreate(v: SourceFormValues): SourceCreate {
  const url = v.original_url.trim();
  return {
    title: v.title.trim(),
    original_url: url || undefined,
    organization: v.organization.trim(),
    source_type: v.source_type,
    authority_type: v.authority_type,
    scope: v.scope,
    category: v.category,
    language: v.language,
    sync_frequency: v.sync_frequency,
    is_active: true,
  };
}
