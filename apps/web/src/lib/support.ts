/** Pure helpers for AI history, handoff, support tickets, notifications and translation review. */
import type {
  ConversationMessage,
  LanguageCode,
  TicketCreateBody,
  TicketPriority,
  TicketStatus,
  TranslationStatus,
  UserNotification,
} from "@/types/api";

type Variant = "default" | "secondary" | "outline" | "success" | "warning" | "danger" | "info" | "muted";

export const SUPPORT_LANGUAGES: LanguageCode[] = ["ko", "en", "id", "vi", "zh-CN"];
export const SUMMARY_MAX = 4000;
export const SUBJECT_MIN = 3;
export const SUBJECT_MAX = 200;

/** Default selection for sharing: every student message + the latest assistant answer. */
export function defaultSelection(messages: Pick<ConversationMessage, "id" | "role">[]): string[] {
  const lastAssistant = [...messages].reverse().find((m) => m.role === "assistant");
  return messages.filter((m) => m.role === "user" || m.id === lastAssistant?.id).map((m) => m.id);
}

/** Prefill: the student's last question (they can edit it). */
export function defaultSummary(messages: Pick<ConversationMessage, "role" | "content">[]): string {
  const lastUser = [...messages].reverse().find((m) => m.role === "user");
  return (lastUser?.content ?? "").replace(/\s+/g, " ").trim().slice(0, 600);
}

export function defaultSubject(summary: string): string {
  const s = summary.replace(/\s+/g, " ").trim();
  if (s.length <= 80) return s;
  return `${s.slice(0, 77).trimEnd()}…`;
}

export interface HandoffDraft {
  language: LanguageCode | "";
  subject: string;
  summary: string;
  conversationId?: string | null;
  selectedIds: string[];
  availableIds?: string[];
  additional?: string;
  consent: boolean;
  isPrivate?: boolean;
}
export type HandoffError = "language" | "subject" | "summary" | "consent" | "private" | "selection";

/** Validates the confirmation form and builds the exact POST /support/tickets body (no extra data). */
export function buildHandoffPayload(d: HandoffDraft): { ok: true; body: TicketCreateBody } | { ok: false; errors: HandoffError[] } {
  const errors: HandoffError[] = [];
  const subject = d.subject.trim();
  const summary = d.summary.trim();
  if (!d.language || !SUPPORT_LANGUAGES.includes(d.language)) errors.push("language");
  if (subject.length < SUBJECT_MIN || subject.length > SUBJECT_MAX) errors.push("subject");
  if (!summary || summary.length > SUMMARY_MAX) errors.push("summary");
  if (!d.consent) errors.push("consent");
  if (d.isPrivate && d.selectedIds.length > 0) errors.push("private");
  if (d.availableIds && d.selectedIds.some((id) => !d.availableIds!.includes(id))) errors.push("selection");
  if (errors.length) return { ok: false, errors };
  const body: TicketCreateBody = {
    language: d.language as LanguageCode,
    subject,
    summary,
    message_ids: d.conversationId && !d.isPrivate ? [...new Set(d.selectedIds)] : [],
    consent: true,
  };
  if (d.conversationId && !d.isPrivate) body.conversation_id = d.conversationId;
  const extra = d.additional?.trim();
  if (extra) body.additional_message = extra;
  return { ok: true, body };
}

export const TICKET_STATUS_VARIANT: Record<TicketStatus, Variant> = {
  waiting: "warning",
  assigned: "info",
  open: "success",
  waiting_for_student: "secondary",
  resolved: "muted",
};
export const PRIORITY_VARIANT: Record<TicketPriority, Variant> = {
  low: "muted",
  normal: "secondary",
  high: "warning",
  urgent: "danger",
};

/** Ticket states in which a student may still write. */
export function studentCanReply(status: TicketStatus): boolean {
  return status !== "resolved";
}

export type TranslationBadgeKey = TranslationStatus | "outdated" | "published";
/** One badge per translation: outdated wins, then approved+published, then the workflow status. */
export function translationBadge(t: { translation_status: TranslationStatus; is_outdated?: boolean; published?: boolean }): {
  key: TranslationBadgeKey;
  variant: Variant;
} {
  if (t.is_outdated && t.translation_status !== "todo") return { key: "outdated", variant: "danger" };
  if (t.translation_status === "human_approved") return { key: t.published ? "published" : "human_approved", variant: "success" };
  const v: Record<TranslationStatus, Variant> = {
    todo: "muted",
    machine_draft: "secondary",
    needs_review: "warning",
    in_review: "info",
    changes_requested: "warning",
    human_approved: "success",
    rejected: "danger",
  };
  return { key: t.translation_status, variant: v[t.translation_status] };
}

/** Same-site links only (never follow an absolute/external URL from a notification). */
export function notificationHref(n: Pick<UserNotification, "link" | "entity_type" | "entity_id">, isStaff = false): string | null {
  const link = n.link ?? "";
  if (link.startsWith("/") && !link.startsWith("//") && !link.includes("\\")) return link;
  if (n.entity_type === "support_ticket" && n.entity_id) {
    return isStaff ? `/admin/support/${n.entity_id}` : `/support/requests/${n.entity_id}`;
  }
  return null;
}

/** Thread polling: only while the ticket can still change and the tab is visible. */
export function shouldPollTicket(status: TicketStatus | undefined, visible: boolean): boolean {
  return Boolean(status) && status !== "resolved" && visible;
}
