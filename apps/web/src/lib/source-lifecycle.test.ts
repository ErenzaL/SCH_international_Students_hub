import { describe, expect, it } from "vitest";
import { canSubmitSourceDelete, isArchivedSource, needsDestructiveConfirmation, offerArchive } from "@/lib/source-lifecycle";

const empty = { eligible: true, title: "Old visa page", requires_destructive_confirmation: false, documents: 0 };
const withDocs = { ...empty, requires_destructive_confirmation: true, documents: 3 };
const base = { typedTitle: "Old visa page", reason: "registered by mistake", destructiveConfirmed: false };

describe("canSubmitSourceDelete", () => {
  it("allows an unused source with the exact title and a reason", () => {
    expect(canSubmitSourceDelete({ ...base, check: empty })).toBe(true);
  });
  it("requires the second explicit confirmation when documents would be destroyed", () => {
    expect(canSubmitSourceDelete({ ...base, check: withDocs })).toBe(false);
    expect(canSubmitSourceDelete({ ...base, check: withDocs, destructiveConfirmed: true })).toBe(true);
  });
  it("blocks ineligible sources, wrong titles, short reasons and in-flight requests", () => {
    expect(canSubmitSourceDelete({ ...base, check: { ...empty, eligible: false } })).toBe(false);
    expect(canSubmitSourceDelete({ ...base, check: empty, typedTitle: "old visa page" })).toBe(false);
    expect(canSubmitSourceDelete({ ...base, check: empty, reason: "oops" })).toBe(false);
    expect(canSubmitSourceDelete({ ...base, check: empty, busy: true })).toBe(false);
    expect(canSubmitSourceDelete({ ...base, check: null })).toBe(false);
  });
});

describe("archive recommendation", () => {
  it("offers Archive for sources with content that are not archived yet", () => {
    expect(offerArchive({ recommended_action: "archive", documents: 2, is_archived: false })).toBe(true);
    expect(offerArchive({ recommended_action: "archive", documents: 2, is_archived: true })).toBe(false);
    expect(offerArchive({ recommended_action: "delete", documents: 0, is_archived: false })).toBe(false);
  });
  it("detects destructive cleanup and archived sources", () => {
    expect(needsDestructiveConfirmation(withDocs)).toBe(true);
    expect(needsDestructiveConfirmation(empty)).toBe(false);
    expect(isArchivedSource({ archived_at: "2026-11-22T00:00:00Z" })).toBe(true);
    expect(isArchivedSource({ archived_at: null })).toBe(false);
  });
});
