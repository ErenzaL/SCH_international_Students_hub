/** Pure helpers for document archive / restore / guarded permanent deletion. */
import type { DeletionCheck, DocumentItem, DocumentLifecycle } from "@/types/api";

type Variant = "default" | "secondary" | "outline" | "success" | "warning" | "danger" | "info" | "muted";

export const DELETE_REASON_MIN = 5;
export const ARCHIVE_REASON_MIN = 3;

/** Lifecycle from the API, with a fallback for older payloads that lack the field. */
export function lifecycleOf(
  d: Pick<DocumentItem, "lifecycle" | "is_canceled" | "archived_at" | "current_version_id">,
): DocumentLifecycle {
  if (d.lifecycle) return d.lifecycle;
  if (d.is_canceled) return "withdrawn";
  if (d.archived_at) return "archived";
  return d.current_version_id ? "published" : "unpublished";
}

export const LIFECYCLE_VARIANT: Record<DocumentLifecycle, Variant> = {
  published: "success",
  unpublished: "muted",
  archived: "secondary",
  withdrawn: "danger",
};

export function canArchive(l: DocumentLifecycle): boolean {
  return l === "published" || l === "unpublished";
}
export function canRestore(l: DocumentLifecycle): boolean {
  return l === "archived" || l === "withdrawn";
}

/** Blockers arrive as "code: explanation" strings. */
export function parseBlocker(b: string): { code: string; message: string } {
  const i = b.indexOf(":");
  if (i <= 0) return { code: "other", message: b.trim() };
  return { code: b.slice(0, i).trim(), message: b.slice(i + 1).trim() };
}

/** The server compares btrim(confirm_title) with btrim(title); mirror that exactly (case-sensitive). */
export function titleMatches(typed: string, title: string): boolean {
  return typed.trim().length > 0 && typed.trim() === title.trim();
}

export interface DeleteFormState {
  check: Pick<DeletionCheck, "eligible" | "title"> | null;
  typedTitle: string;
  reason: string;
  busy?: boolean;
}

/** Delete is possible only when the check says eligible, the exact title is typed and a real reason is given. */
export function canSubmitDelete(s: DeleteFormState): boolean {
  if (!s.check || !s.check.eligible || s.busy) return false;
  return titleMatches(s.typedTitle, s.check.title) && s.reason.trim().length >= DELETE_REASON_MIN;
}

/** Archive is the safer choice whenever students may already have relied on an approved version. */
export function recommendArchive(check: Pick<DeletionCheck, "approved_versions" | "recommended_action">): boolean {
  return check.recommended_action === "archive" || check.approved_versions > 0;
}
