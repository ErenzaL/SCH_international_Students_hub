/** Pure helpers for knowledge-source archive / restore / guarded permanent deletion. */
import { DELETE_REASON_MIN, titleMatches } from "@/lib/document-lifecycle";
import type { Source, SourceDeletionCheck } from "@/types/api";

export { DELETE_REASON_MIN };
export const SOURCE_ARCHIVE_REASON_MIN = 3;

export function isArchivedSource(s: Pick<Source, "archived_at">): boolean {
  return !!s.archived_at;
}

/** A source that still has documents needs the second, explicit "destructive cleanup" confirmation. */
export function needsDestructiveConfirmation(check: Pick<SourceDeletionCheck, "requires_destructive_confirmation" | "documents">): boolean {
  return check.requires_destructive_confirmation || check.documents > 0;
}

/** Archive is offered (and recommended) whenever the source has content and is not archived yet. */
export function offerArchive(check: Pick<SourceDeletionCheck, "recommended_action" | "documents" | "is_archived">): boolean {
  return !check.is_archived && (check.recommended_action === "archive" || check.documents > 0);
}

export interface SourceDeleteFormState {
  check: Pick<SourceDeletionCheck, "eligible" | "title" | "requires_destructive_confirmation" | "documents"> | null;
  typedTitle: string;
  reason: string;
  destructiveConfirmed: boolean;
  busy?: boolean;
}

/** Mirrors the server: eligible, exact title, a real reason, and the second confirmation when documents exist. */
export function canSubmitSourceDelete(s: SourceDeleteFormState): boolean {
  if (!s.check || !s.check.eligible || s.busy) return false;
  if (!titleMatches(s.typedTitle, s.check.title)) return false;
  if (s.reason.trim().length < DELETE_REASON_MIN) return false;
  return !needsDestructiveConfirmation(s.check) || s.destructiveConfirmed;
}

export const SOURCE_BLOCKER_CODES = ["published", "announcement", "busy"] as const;
