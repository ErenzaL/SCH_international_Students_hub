import { CATEGORY_SLUGS } from "@/lib/constants";
import { isHttpUrl } from "@/features/admin/sources/source-validation";
import type { AnnouncementCreate, LanguageCode } from "@/types/api";

export interface AnnouncementFormValues {
  title: string;
  body: string;
  category: string;
  target_audience: string;
  event_date: string;
  deadline: string;
  valid_from: string;
  source_type: "manual_text" | "kakao_message";
  source_published_at: string;
  evidence_note: string;
  evidence_url: string;
  authorized_by_supporter: boolean;
  original_language: LanguageCode;
  /** machine drafts to make after approval (never the original language) */
  translation_targets: LanguageCode[];
}

export type AnnouncementErrorCode =
  | "required"
  | "bodyTooShort"
  | "tooLong"
  | "invalidUrl"
  | "invalidChoice"
  | "authorizationRequired";

export type AnnouncementFormErrors = Partial<Record<keyof AnnouncementFormValues, AnnouncementErrorCode>>;

export const EMPTY_ANNOUNCEMENT_FORM: AnnouncementFormValues = {
  title: "",
  body: "",
  category: "university-announcements",
  target_audience: "",
  event_date: "",
  deadline: "",
  valid_from: "",
  source_type: "manual_text",
  source_published_at: "",
  evidence_note: "",
  evidence_url: "",
  authorized_by_supporter: false,
  original_language: "ko",
  translation_targets: [],
};

/** The selected targets without the original language (it is never translated into itself). */
export function cleanTargets(v: Pick<AnnouncementFormValues, "original_language" | "translation_targets">): LanguageCode[] {
  return v.translation_targets.filter((l, i, all) => l !== v.original_language && all.indexOf(l) === i);
}

export function validateAnnouncementForm(v: AnnouncementFormValues): AnnouncementFormErrors {
  const errors: AnnouncementFormErrors = {};
  if (!v.title.trim()) errors.title = "required";
  else if (v.title.trim().length > 300) errors.title = "tooLong";
  if (!v.body.trim()) errors.body = "required";
  else if (v.body.trim().length < 10) errors.body = "bodyTooShort";
  if (!(CATEGORY_SLUGS as readonly string[]).includes(v.category)) errors.category = "invalidChoice";
  if (v.evidence_url.trim() && !isHttpUrl(v.evidence_url.trim())) errors.evidence_url = "invalidUrl";
  if (v.source_type === "kakao_message" && !v.authorized_by_supporter) errors.authorized_by_supporter = "authorizationRequired";
  return errors;
}

export function toAnnouncementCreate(v: AnnouncementFormValues, submit: boolean): AnnouncementCreate {
  const opt = (s: string) => (s.trim() ? s.trim() : undefined);
  return {
    title: v.title.trim(),
    body: v.body,
    category: v.category,
    target_audience: opt(v.target_audience),
    event_date: opt(v.event_date),
    deadline: opt(v.deadline),
    valid_from: opt(v.valid_from),
    source_type: v.source_type,
    source_published_at: opt(v.source_published_at),
    evidence_note: opt(v.evidence_note),
    evidence_url: opt(v.evidence_url),
    original_language: v.original_language,
    translation_targets: cleanTargets(v),
    submit,
    authorized_by_supporter: v.source_type === "kakao_message" ? v.authorized_by_supporter : undefined,
  };
}
