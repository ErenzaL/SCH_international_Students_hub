/** Types mirroring docs/api-contract.md. Keep in sync with the backend. */

export type LanguageCode = "ko" | "en" | "id" | "vi" | "zh-CN";
export type SourceType =
  | "website"
  | "sch_board"
  | "pdf"
  | "docx"
  | "text_file"
  | "screenshot"
  | "manual_text"
  | "kakao_message";
export type AuthorityType =
  | "official_university"
  | "official_government"
  | "staff_communication"
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
  | "blocked"
  | "inactive";
export type VerificationStatus =
  | "draft"
  | "pending_review"
  | "approved"
  | "rejected"
  | "superseded";
export type JobStatus = "queued" | "running" | "succeeded" | "failed";
export type JobOutcome = "new_version" | "unchanged" | "partial" | "extracted" | "activated";
export type JobType = "ingest" | "board_sync" | "ocr_intake" | "index_version";
export type IndexingStatus = "not_indexed" | "queued" | "indexing" | "indexed" | "failed";
export type PublicationStatus =
  | "draft"
  | "pending_approval"
  | "published"
  | "rejected"
  | "canceled";
export type AnnouncementStatus = "active" | "upcoming" | "expired";
export type TranslationStatus =
  | "todo"
  | "machine_draft"
  | "in_review"
  | "changes_requested"
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
  source_id?: string;
  source_type?: SourceType;
  valid_until?: string | null;
  exact_match?: boolean;
  is_stale?: boolean;
  verification_age_days?: number | null;
  stale_after_days?: number | null;
}

export interface SearchResponse {
  query: string;
  results: SearchResult[];
  retrieval: {
    mode: "hybrid" | "vector" | "keyword";
    embedding_model: string;
    total: number;
    warning: string | null;
    exact_terms?: string[];
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
  source_type?: SourceType;
  valid_until?: string | null;
  is_stale?: boolean;
  verification_age_days?: number | null;
  stale_after_days?: number | null;
}

export interface Attachment {
  name: string;
  url: string;
}

export interface KnowledgeDocumentDetail extends KnowledgeDocumentSummary {
  content: string;
  version_id: string;
  version_number: number;
  key_facts?: Record<string, unknown>;
  attachments?: Attachment[];
  notice_no?: string | null;
}

export interface Me {
  id: string;
  email: string | null;
  display_name: string | null;
  role: Role;
  preferred_language: LanguageCode;
  preferred_language_confirmed?: boolean;
  languages: LanguageCode[];
  is_staff: boolean;
}

export interface JobResultSummary {
  job_id: string;
  status: JobStatus;
  outcome: JobOutcome | null;
  message: string | null;
  completed_at: string | null;
  error_code?: string | null;
}

export interface BoardConfig {
  max_items?: number;
  max_pages?: number;
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
  config?: BoardConfig;
  stale_after_days?: number | null;
  last_success_at?: string | null;
  last_change_at?: string | null;
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
  config?: BoardConfig;
  stale_after_days?: number;
}

export interface SourcePatch {
  title?: string;
  organization?: string;
  category?: string;
  sync_frequency?: SyncFrequency;
  language?: LanguageCode;
  scope?: Scope;
  authority_type?: AuthorityType;
  config?: BoardConfig;
  stale_after_days?: number;
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
  statistics: Record<string, unknown>;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  job_type?: JobType;
  attempts?: number;
  max_attempts?: number;
  file?: { filename: string; mime_type: string; size: number } | null;
  heartbeat_at?: string | null;
}

export interface JobEvent {
  id: number;
  level: "info" | "warning" | "error";
  step: string;
  message: string;
  data: Record<string, unknown>;
  created_at: string;
}

export interface BoardNoticeStat {
  notice_no: string;
  title: string;
  outcome: JobOutcome;
  document_id: string | null;
  version_id: string | null;
}

export interface BoardFailure {
  notice_no: string;
  title: string;
  code: string;
  message: string;
}

export interface JobAccepted {
  job_id: string;
  status: JobStatus;
}

export type DocumentLifecycle = "published" | "unpublished" | "archived" | "withdrawn";
export type LifecycleFilter = "active" | "archived" | "withdrawn";

export interface DeletionCheck {
  eligible: boolean;
  blockers: string[];
  title: string;
  versions: number;
  approved_versions: number;
  chunks: number;
  storage_files: string[];
  is_published: boolean;
  is_archived: boolean;
  is_withdrawn: boolean;
  suppress_reimport: boolean;
  recommended_action: "archive" | "delete";
}

export interface DeletionResult {
  deleted: boolean;
  title: string;
  versions: number;
  chunks: number;
  files_removed: number;
  files_failed: string[];
  reimport_blocked: boolean;
}

export interface DocumentSuppression {
  id: number;
  canonical_url: string | null;
  external_id: string | null;
  title: string | null;
  reason: string | null;
  suppressed_by: string | null;
  created_at: string;
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
  lifecycle?: DocumentLifecycle;
  archived_at?: string | null;
  archive_reason?: string | null;
  canceled_at?: string | null;
  canceled_reason?: string | null;
  source_type?: SourceType | null;
  authority_type?: AuthorityType | null;
  pending_status?: VerificationStatus | null;
  updated_at?: string | null;
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
  created_by?: string | null;
  edited_by?: string | null;
  edited_at?: string | null;
  review_note?: string | null;
  submitted_at?: string | null;
  indexing_status?: IndexingStatus;
  indexed_at?: string | null;
  indexing_error?: string | null;
  extraction_meta?: Record<string, unknown>;
  warnings?: string[];
  requires_field_confirmation?: boolean;
  structured_data?: StructuredData;
  original_file?: { filename: string; mime_type: string; size: number; sha256: string } | null;
  has_raw_text?: boolean;
  activation_requested_by?: string | null;
  activation_requested_at?: string | null;
}

export interface Version extends VersionSummary {
  extracted_text: string;
  raw_text?: string | null;
}

export interface StructuredField {
  value: unknown;
  evidence: string | null;
  confirmed: boolean;
  source: string;
  needs_year?: boolean;
}

export interface StructuredData {
  fields?: Record<string, StructuredField>;
  dates?: { iso: string | null; text: string; year: number | null }[];
  links?: string[];
  identifiers?: string[];
  warnings?: string[];
  fields_confirmed?: boolean;
  detector?: string;
}

export interface ReviewWarning {
  code: string;
  message: string;
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
  metadata?: { notice_no?: string; author?: string; attachments?: Attachment[]; pinned?: boolean };
  review_warnings?: ReviewWarning[];
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

// ------------------------------------------------------------------ Phase 2
export interface KnowledgeStats {
  sources_total: number;
  sources_active: number;
  sources_failed: number;
  versions_pending: number;
  versions_draft: number;
  documents_approved: number;
  jobs_failed: number;
  jobs_queued: number;
  searchable_chunks: number;
  latest_success_at: string | null;
  ocr_provider: string;
  ocr_available: boolean;
  ocr_reason: string | null;
  job_execution: string;
  embedding_model: string;
}

export interface UrlCheckItem {
  name: "allowlist" | "network" | "robots" | "board" | "duplicate";
  ok: boolean;
  message: string;
  source_id?: string;
}

export interface UrlValidation {
  ok: boolean;
  url: string;
  checks: UrlCheckItem[];
}

export interface PagePreview {
  kind: "page";
  final_url: string;
  title: string;
  text: string;
  truncated: boolean;
  content_chars: number;
  content_hash: string;
  source_published_at: string | null;
  links: { text?: string; url?: string; href?: string }[];
  warnings: string[];
  extractor: string | null;
  estimated_chunks: number;
  structured: StructuredData;
}

export interface BoardPreview {
  kind: "board";
  final_url: string;
  notices: { notice_no: string; title: string; url: string; posted: string | null; author: string | null; pinned: boolean }[];
  notice_count: number;
  sample_notice: { title: string; text: string; posted_at: string | null; attachments: Attachment[]; warnings: string[] } | null;
}

export type UrlPreview = PagePreview | BoardPreview;

export interface SourceMeta {
  title: string;
  organization: string;
  category: string;
  scope: Scope;
  authority_type: AuthorityType;
  language: LanguageCode;
  original_url?: string;
}

export interface OcrStatus {
  provider: string;
  available: boolean;
  reason: string | null;
  languages: string | null;
  external_processing: boolean;
}

export interface OcrResult {
  provider: string;
  available: boolean;
  text: string;
  mean_confidence: number | null;
  uncertain_lines: { text: string; confidence: number | null }[];
  warnings: string[];
  model: string | null;
  extracted_at?: string;
  error_code?: string;
}

export interface ScreenshotIntake {
  source?: Source;
  job: Job;
  ocr: OcrResult;
  detected: StructuredData | null;
  image: { filename: string; mime_type: string; size: number };
}

export interface MySubmission {
  id: string;
  document_id: string;
  document_title: string | null;
  version_number: number;
  verification_status: VerificationStatus;
  review_note: string | null;
  created_at: string;
  submitted_at: string | null;
  approved_at: string | null;
  rejected_reason: string | null;
  indexing_status: IndexingStatus;
}

export interface AllowedDomain {
  domain: string;
  origin: "environment" | "admin";
  note: string | null;
  added_by: string | null;
  created_at: string | null;
  removable: boolean;
}

export interface SourceHistory {
  jobs: Job[];
  audit: { id: number | string; action: string; actor_id: string | null; details: Record<string, unknown>; created_at: string }[];
}

/** POST /admin/versions/{id}/approve (202): the version plus the durable indexing job it queued. */
export interface ApproveResult extends Version {
  indexing_job_id: string;
  indexing_job_status: JobStatus;
}

export interface RagQueueItem {
  job_id: string;
  status: JobStatus;
  attempts: number | null;
  max_attempts: number | null;
  error_code: string | null;
  error_message: string | null;
  run_after: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  version_id: string | null;
  version_number: number | null;
  version_status: VerificationStatus | null;
  indexing_status: IndexingStatus | null;
  document_id: string | null;
  document_title: string | null;
  statistics: Record<string, unknown>;
}

export interface RagSource {
  id: string;
  title: string;
  source_type: SourceType;
  status: SourceStatus;
  sync_frequency: SyncFrequency;
  last_checked_at: string | null;
  last_success_at: string | null;
  last_change_at: string | null;
  is_active: boolean;
}

export interface RagStatus {
  counts: {
    sources_registered: number;
    sources_active: number;
    sources_failed_or_blocked: number;
    pending_review: number;
    waiting_for_indexing: number;
    indexing_now: number;
    indexing_failed: number;
    active_versions: number;
    searchable_chunks: number;
    chunks_with_current_model: number;
    failed_jobs: number;
  };
  last_sync_at: string | null;
  embedding: { model: string; dimensions: number; provider: string; loaded: boolean };
  job_execution: string;
  queue: RagQueueItem[];
  recent_activations: { at: string; document_id: string | null; document_title: string | null; version_number: number | null; chunks: number | null }[];
  sources: RagSource[];
}

export type NotificationSeverity = "info" | "warning" | "error";

export interface AdminNotification {
  id: number;
  kind: string;
  severity: NotificationSeverity;
  title: string;
  message: string | null;
  entity_type: string | null;
  entity_id: string | null;
  link: string | null;
  created_at: string;
  unread: boolean;
}

export interface NotificationList {
  items: AdminNotification[];
  unread: number;
  last_read_at: string | null;
}


// ---------------------------------------------------------------- 0008: support, AI history, translation review
export interface UserNotification {
  id: number;
  kind: string;
  title: string;
  body: string | null;
  entity_type: string | null;
  entity_id: string | null;
  link: string | null;
  read_at: string | null;
  created_at: string;
}
export interface UserNotificationList {
  items: UserNotification[];
  unread: number;
}

export interface Conversation {
  id: string;
  title: string;
  language: LanguageCode;
  is_private: boolean;
  message_count: number;
  last_message_at: string | null;
  last_message_preview: string | null;
  created_at: string;
  updated_at: string | null;
}
export type HandoffReason = "no_evidence" | "asked_for_human" | "individual_decision" | "disputed_answer";
export interface ConversationCitation {
  n: number;
  document_id: string | null;
  version_id: string | null;
  chunk_id: string | null;
  document_title: string | null;
  heading: string | null;
  source_url: string | null;
  organization: string | null;
  authority_type: AuthorityType | null;
  verified_at: string | null;
  is_stale: boolean | null;
  page: number | null;
  similarity: number | null;
}
export interface ConversationMessage {
  id: string;
  conversation_id?: string;
  role: "user" | "assistant";
  content: string;
  language: LanguageCode;
  citations: ConversationCitation[];
  metadata: {
    offer_handoff?: boolean;
    handoff_reasons?: HandoffReason[];
    evidence?: number;
    retrieval_mode?: string;
    answer_generation?: string;
    warning?: string | null;
  };
  created_at: string;
}
export interface ConversationDetail extends Conversation {
  messages: ConversationMessage[];
}
export interface AskResponse {
  user_message: ConversationMessage;
  assistant_message: ConversationMessage;
  conversation: Conversation;
}

export type TicketStatus = "waiting" | "assigned" | "open" | "waiting_for_student" | "resolved";
export type TicketPriority = "low" | "normal" | "high" | "urgent";
export interface SharedContextItem {
  role: "user" | "assistant";
  content: string;
  created_at: string;
  citations?: { document_title: string | null; source_url: string | null }[];
}
export interface TicketMessage {
  id: string;
  author_role: "student" | "supporter" | "admin" | "system";
  kind: "message" | "info_request" | "status" | "system";
  body: string;
  author_name: string | null;
  created_at: string;
}
export interface SupportTicket {
  id: string;
  ticket_number: number;
  language: LanguageCode;
  subject: string;
  summary: string;
  priority: TicketPriority;
  status: TicketStatus;
  status_message: string;
  assigned_supporter: { display_name: string } | null;
  team: string;
  shared_context: SharedContextItem[];
  consent_at: string;
  context_withdrawn_at: string | null;
  escalated: boolean;
  created_at: string;
  updated_at: string | null;
  last_message_at: string | null;
  resolved_at: string | null;
  satisfaction: number | null;
  satisfaction_comment: string | null;
  messages?: TicketMessage[];
  // staff view only
  assigned_to?: string | null;
  assigned_at?: string | null;
  accepted_at?: string | null;
  escalation_reason?: string | null;
  student_display_name?: string | null;
  student_preferred_language?: LanguageCode | null;
  is_mine?: boolean;
  can_manage?: boolean;
}
export interface InboxItem {
  id: string;
  ticket_number: number;
  language: LanguageCode;
  subject: string;
  priority: TicketPriority;
  status: TicketStatus;
  created_at: string;
  last_message_at: string | null;
  escalated: boolean;
  assigned_to: string | null;
  assigned_to_name: string | null;
  is_mine: boolean;
  can_open: boolean;
}
export type InboxView = "queue" | "mine" | "assigned" | "open" | "waiting" | "resolved" | "team";
export interface InboxResponse extends Page<InboxItem> {
  counts: { queue: number; assigned: number; open: number; waiting_for_student: number; resolved: number };
  languages: LanguageCode[];
  lead_languages: LanguageCode[];
}
export interface TransferTarget {
  id: string;
  display_name: string | null;
  is_available: boolean;
}
export interface AgentStatus {
  supporter_id?: string;
  is_available: boolean;
  max_active_tickets: number;
}
export interface TicketCreateBody {
  language: LanguageCode;
  subject: string;
  summary: string;
  conversation_id?: string;
  message_ids: string[];
  additional_message?: string;
  consent: boolean;
}

export interface TeamMember {
  user_id: string;
  display_name: string | null;
  email: string | null;
  role: Role;
  can_support: boolean;
  can_review_translations: boolean;
  is_team_lead: boolean;
  is_available: boolean;
}
export interface LanguageTeam {
  language: LanguageCode;
  members: TeamMember[];
  waiting: number;
  active: number;
}
export interface LanguageTeams {
  items: LanguageTeam[];
  can_manage_members: boolean;
}
export interface TeamAssignment {
  language: LanguageCode;
  can_support: boolean;
  can_review_translations: boolean;
  is_team_lead: boolean;
}

export interface TranslationView extends Translation {
  is_outdated: boolean;
  published: boolean;
  review_note: string | null;
  last_edited_by: string | null;
  last_edited_by_name: string | null;
  last_edited_at: string | null;
  submitted_at: string | null;
  original_verified_at: string | null;
  updated_at?: string | null;
}
export interface TranslationTask extends TranslationView {
  announcement_title: string;
  announcement_status: PublicationStatus;
  original_language: LanguageCode;
  can_edit: boolean;
  can_review: boolean;
}
export interface TranslationOriginal {
  announcement_id: string;
  title: string;
  body: string;
  language: LanguageCode;
  publication_status: PublicationStatus;
  version_id: string | null;
  content_hash: string;
  category: string;
  deadline: string | null;
  event_date: string | null;
  is_test_data: boolean;
}
export interface TranslationRevision {
  id: number;
  action: "save" | "submit" | "approve" | "reject" | "request_changes" | "outdated";
  translation_status: TranslationStatus;
  title: string | null;
  body: string | null;
  note: string | null;
  actor_id: string | null;
  actor_name: string | null;
  source_content_hash: string | null;
  created_at: string;
}
export interface TranslationDetail {
  original: TranslationOriginal;
  translation: TranslationView | null;
  revisions: TranslationRevision[];
  permissions: { can_edit: boolean; can_review: boolean };
  language: LanguageCode;
}
