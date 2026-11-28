import { resolveApiBaseUrl } from "@/lib/api-url";
import type {
  AuthorityType,
  LanguageCode,
  Role,
  Scope,
  SourceStatus,
  SourceType,
  SyncFrequency,
} from "@/types/api";

export const LOCALES: readonly LanguageCode[] = ["en", "ko", "id", "vi", "zh-CN"];
/** Release 1: announcements are machine-translated (TranslateGemma on the GPU worker) only between these languages. */
export const ANNOUNCEMENT_MACHINE_LANGUAGES: readonly LanguageCode[] = ["ko", "en", "id"];
export const DEFAULT_LOCALE: LanguageCode = "en";
export const LOCALE_COOKIE = "NEXT_LOCALE";
export const LOCALE_STORAGE_KEY = "sch-hub-locale";

/** Native language names – never translated so users can always find their own language. */
export const LOCALE_LABELS: Record<LanguageCode, string> = {
  en: "English",
  ko: "한국어",
  id: "Bahasa Indonesia",
  vi: "Tiếng Việt",
  "zh-CN": "简体中文",
};

export const CATEGORY_SLUGS = [
  "visa-immigration",
  "part-time-employment",
  "academic-life",
  "scholarships",
  "dormitory-housing",
  "health-insurance",
  "topik-korean",
  "employment-internships",
  "banking-taxes",
  "daily-living",
  "university-announcements",
] as const;
export type CategorySlug = (typeof CATEGORY_SLUGS)[number];

export const CATEGORY_ICONS: Record<CategorySlug, string> = {
  "visa-immigration": "Stamp",
  "part-time-employment": "Briefcase",
  "academic-life": "GraduationCap",
  scholarships: "Award",
  "dormitory-housing": "Home",
  "health-insurance": "HeartPulse",
  "topik-korean": "Languages",
  "employment-internships": "Building2",
  "banking-taxes": "Landmark",
  "daily-living": "ShoppingBasket",
  "university-announcements": "Megaphone",
};

export const SOURCE_TYPES: SourceType[] = [
  "website",
  "sch_board",
  "pdf",
  "docx",
  "text_file",
  "screenshot",
  "manual_text",
  "kakao_message",
];
export const FETCHABLE_SOURCE_TYPES: SourceType[] = ["website", "sch_board"];
export const FILE_SOURCE_TYPES: SourceType[] = ["pdf", "docx", "text_file"];
export const AUTHORITY_TYPES: AuthorityType[] = [
  "official_university",
  "official_government",
  "staff_communication",
  "supporter_submitted",
  "other",
];
/** Suggested sync policy per category (mirrors backend DEFAULT_SYNC_BY_CATEGORY; admins may change it). */
export const DEFAULT_SYNC_BY_CATEGORY: Partial<Record<string, SyncFrequency>> = {
  "university-announcements": "daily",
  "topik-korean": "daily",
  "visa-immigration": "weekly",
  "health-insurance": "weekly",
};
/** Structured fields reviewers can confirm/correct (mirrors backend structured.py / ScreenshotSubmit). */
export const KEY_FIELDS = [
  "deadline",
  "event_date",
  "application_period",
  "time",
  "location",
  "fee",
  "contact",
  "eligibility",
  "required_documents",
  "application_method",
  "target_audience",
  "notes",
] as const;
export type KeyField = (typeof KEY_FIELDS)[number];
export const SCOPES: Scope[] = ["university", "national"];
export const SYNC_FREQUENCIES: SyncFrequency[] = ["manual", "daily", "weekly"];
export const SOURCE_STATUSES: SourceStatus[] = [
  "registered",
  "fetching",
  "processing",
  "pending_review",
  "approved",
  "failed",
  "blocked",
  "inactive",
];
export const ROLES: Role[] = ["super_admin", "admin", "supporter", "student"];

// Each process.env.NEXT_PUBLIC_* must be referenced literally so Next.js can inline it.
export const API_BASE_URL = resolveApiBaseUrl({
  apiUrl: process.env.NEXT_PUBLIC_API_URL,
  legacyApiBaseUrl: process.env.NEXT_PUBLIC_API_BASE_URL,
  nodeEnv: process.env.NODE_ENV,
});
export const isApiConfigured = Boolean(API_BASE_URL);
export const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
export const SUPABASE_ANON_KEY = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "";
export const isSupabaseConfigured = Boolean(SUPABASE_URL && SUPABASE_ANON_KEY);

export const MAX_UPLOAD_MB = 10;
export const MAX_IMAGE_MB = 8;
