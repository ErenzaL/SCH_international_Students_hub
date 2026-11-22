/** Types mirroring docs/api-contract.md. Keep in sync with the backend. */

export type LanguageCode = "ko" | "en" | "id" | "vi" | "zh-CN";
export type SourceType = "website" | "pdf" | "docx" | "manual_text" | "kakao_message";
export type AuthorityType =
  | "official_university"
  | "official_government"
  | "supporter_submitted"
  | "other";
export type Scope = "university" | "national";
export type SyncFrequency = "manual" | "daily" | "weekly";
export type SourceStatus =
  | "registered"
  | "fetching"
  | "processing"
  | "pending_review"
  | "approved"
  | "failed"
  | "inactive";
export type VerificationStatus =
  | "draft"
  | "pending_review"
  | "approved"
  | "rejected"
  | "superseded";
export type JobStatus = "queued" | "running" | "succeeded" | "failed";
export type JobOutcome = "new_version" | "unchanged";
export type PublicationStatus =
  | "draft"
  | "pending_approval"
  | "published"
  | "rejected"
  | "canceled";
export type AnnouncementStatus = "active" | "upcoming" | "expired";
export type TranslationStatus =
  | "machine_draft"
  | "in_review"
  | "human_approved"
  | "rejected";
export type Role = "super_admin" | "admin" | "supporter" | "student";

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface Category {
  slug: string;
  name: string;
  description: string;
  sort_order: number;
  document_count: number | null;
  announcement_count: number | null;
}

export interface SourceRef {
  title: string;
  organization: string;
  url: string | null;
  authority_type: AuthorityType;
  scope: Scope;
}

export interface AnnouncementSummary {
  id: string;
  title: string;
  category: string;
  target_audience: string | null;
  event_date: string | null;
  deadline: string | null;
  published_at: string | null;
  status: AnnouncementStatus;
  original_language: LanguageCode;
  available_languages: LanguageCode[];
  excerpt: string;
  is_test_data: boolean;
  source: SourceRef;
}

export interface PublicTranslation {
  language: LanguageCode;
  title: string;
  body: string;
  translation_status: "human_approved";
  reviewed_at: string | null;
}

export interface AnnouncementDetail extends AnnouncementSummary {
  body: string;
  source_published_at: string | null;
  verified_at: string | null;
  version_id: string;
  translations: PublicTranslation[];
}

export interface AssistantStatus {
  answer_generation: "disabled" | "enabled";
  retrieval: "available" | "unavailable";
  reason: string | null;
}

export interface SearchResult {
  chunk_id: string;
  document_id: string;
  version_id: string;
  document_title: string;
  passage: string;
  heading: string | null;
  page: number | null;
  similarity: number | null;
  keyword_rank: number | null;
  score: number;
  source_url: string | null;
  organization: string;
  authority_type: AuthorityType;
  scope: Scope;
  category: string;
  source_published_at: string | null;
  verified_at: string | null;
  language: LanguageCode;
}

export interface SearchResponse {
  query: string;
  results: SearchResult[];
  retrieval: {
    mode: "hybrid" | "vector" | "keyword";
    embedding_model: string;
    total: number;
    warning: string | null;
  };
}

export interface KnowledgeDocumentSummary {
  id: string;
  title: string;
  category: string;
  organization: string;
  scope: Scope;
  authority_type: AuthorityType;
  language: LanguageCode;
  source_url: string | null;
  source_published_at: string | null;
  verified_at: string | null;
  excerpt: string;
}

export interface KnowledgeDocumentDetail extends KnowledgeDocumentSummary {
  content: string;
  version_id: string;
  version_number: number;
}

export interface Me {
  id: string;
  email: string | null;
  display_name: string | null;
  role: Role;
  preferred_language: LanguageCode;
  languages: LanguageCode[];
  is_staff: boolean;
}

export interface JobResultSummary {
  job_id: string;
  status: JobStatus;
  outcome: JobOutcome | null;
  message: string | null;
  completed_at: string | null;
}

export interface Source {
  id: string;
  title: string;
  original_url: string | null;
  organization: string;
  source_type: SourceType;
  authority_type: AuthorityType;
  scope: Scope;
  category: string;
  language: LanguageCode;
  sync_frequency: SyncFrequency;
  is_active: boolean;
  status: SourceStatus;
  created_by: string | null;
  created_by_name: string | null;
  created_at: string;
  updated_at: string;
  last_checked_at: string | null;
  last_ingestion_result: JobResultSummary | null;
  is_test_data: boolean;
  document_count: number;
}

export interface SourceDetail extends Source {
  documents: {
    id: string;
    title: string;
    canonical_url: string | null;
    current_version_id: string | null;
    latest_version: {
      id: string;
      version_number: number;
      verification_status: VerificationStatus;
      created_at: string;
    } | null;
  }[];
}

export interface SourceCreate {
  title: string;
  original_url?: string;
  organization: string;
  source_type: SourceType;
  authority_type: AuthorityType;
  scope: Scope;
  category: string;
  language: LanguageCode;
  sync_frequency?: SyncFrequency;
  is_active?: boolean;
}

export interface Job {
  id: string;
  source_id: string;
  source_title: string;
  status: JobStatus;
  trigger: "manual" | "schedule" | "retry";
  outcome: JobOutcome | null;
  document_id: string | null;
  version_id: string | null;
  error_code: string | null;
  error_message: string | null;
  statistics: Record<string, number | string | null>;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface JobAccepted {
  job_id: string;
  status: JobStatus;
}

export interface DocumentItem {
  id: string;
  source_id: string;
  source_title: string;
  title: string;
  canonical_url: string | null;
  language: LanguageCode;
  document_type: string;
  organization: string;
  category: string;
  current_version_id: string | null;
  pending_version_id: string | null;
  latest_version_number: number | null;
  is_canceled: boolean;
  created_at: string;
}

export interface VersionSummary {
  id: string;
  document_id: string;
  version_number: number;
  content_hash: string;
  content_length: number;
  source_published_at: string | null;
  fetched_at: string | null;
  valid_from: string | null;
  valid_until: string | null;
  verification_status: VerificationStatus;
  approved_by: string | null;
  approved_at: string | null;
  rejected_reason: string | null;
  created_at: string;
  chunk_count: number;
  embedded_chunk_count: number;
  embedding_model: string | null;
  is_current: boolean;
}

export interface Version extends VersionSummary {
  extracted_text: string;
}

export interface Diff {
  added_count: number;
  removed_count: number;
  added_lines: string[];
  removed_lines: string[];
  unified: string;
}

export interface DocumentDetail extends DocumentItem {
  source: Source;
  current_version: Version | null;
  pending_version: Version | null;
  versions: VersionSummary[];
  diff: Diff | null;
}

export interface Chunk {
  chunk_index: number;
  heading: string | null;
  content: string;
  page: number | null;
  has_embedding: boolean;
  embedding_model: string | null;
}

export interface Translation {
  id: string;
  announcement_id: string;
  language_code: LanguageCode;
  title: string;
  body: string;
  translation_status: TranslationStatus;
  reviewed_by: string | null;
  reviewed_by_name: string | null;
  reviewed_at: string | null;
  is_machine_translated: boolean;
}

export interface TranslationListItem extends Translation {
  announcement_title: string;
}

export interface AdminAnnouncement {
  id: string;
  document_id: string;
  version_id: string;
  title: string;
  category: string;
  target_audience: string | null;
  event_date: string | null;
  deadline: string | null;
  valid_from: string | null;
  publication_status: PublicationStatus;
  original_language: LanguageCode;
  body: string;
  source_type: "manual_text" | "kakao_message";
  evidence_note: string | null;
  evidence_url: string | null;
  created_by: string | null;
  created_by_name: string | null;
  created_at: string;
  submitted_at: string | null;
  approved_by: string | null;
  approved_at: string | null;
  rejection_reason: string | null;
  is_test_data: boolean;
  translations: Translation[];
}

export interface AnnouncementCreate {
  title: string;
  body: string;
  category: string;
  target_audience?: string;
  event_date?: string;
  deadline?: string;
  valid_from?: string;
  source_type: "manual_text" | "kakao_message";
  source_published_at?: string;
  evidence_note?: string;
  evidence_url?: string;
  original_language?: LanguageCode;
  submit?: boolean;
  authorized_by_supporter?: boolean;
}

export interface AuditEntry {
  id: string;
  action: string;
  entity_type: string;
  entity_id: string | null;
  actor_id: string | null;
  actor_name: string | null;
  details: Record<string, unknown> | null;
  created_at: string;
}

export interface Overview {
  sources_total: number;
  sources_failed: number;
  versions_pending: number;
  announcements_pending: number;
  documents_approved: number;
  recent_jobs: Job[];
  recent_audit: AuditEntry[];
}

export interface AdminSettings {
  supabase_configured: boolean;
  embedding_provider: string;
  embedding_model: string;
  embedding_dimensions: number;
  allowed_domains: string[];
  max_upload_mb: number;
  max_response_mb: number;
  llm_provider: string;
  answer_generation: string;
  rate_limits: Record<string, string | number>;
}

export interface AdminUser {
  id: string;
  email: string | null;
  display_name: string | null;
  role: Role;
  preferred_language: LanguageCode;
  languages: LanguageCode[];
  created_at: string;
}
