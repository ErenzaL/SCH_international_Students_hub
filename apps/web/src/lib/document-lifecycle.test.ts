import { describe, expect, it } from "vitest";
import {
  canArchive,
  canRestore,
  canSubmitDelete,
  lifecycleOf,
  parseBlocker,
  recommendArchive,
  titleMatches,
} from "@/lib/document-lifecycle";

const eligible = { eligible: true, title: "Dormitory rules 2026" };

describe("canSubmitDelete", () => {
  it("requires eligibility, the exact title and a reason of at least 5 characters", () => {
    expect(canSubmitDelete({ check: eligible, typedTitle: "Dormitory rules 2026", reason: "duplicate" })).toBe(true);
    expect(canSubmitDelete({ check: { ...eligible, eligible: false }, typedTitle: "Dormitory rules 2026", reason: "duplicate" })).toBe(false);
    expect(canSubmitDelete({ check: eligible, typedTitle: "dormitory rules 2026", reason: "duplicate" })).toBe(false);
    expect(canSubmitDelete({ check: eligible, typedTitle: "Dormitory rules 2026", reason: " abcd " })).toBe(false);
    expect(canSubmitDelete({ check: null, typedTitle: "x", reason: "duplicate" })).toBe(false);
    expect(canSubmitDelete({ check: eligible, typedTitle: "Dormitory rules 2026", reason: "duplicate", busy: true })).toBe(false);
  });
  it("trims like the server (btrim on both sides)", () => {
    expect(titleMatches("  Dormitory rules 2026 ", "Dormitory rules 2026")).toBe(true);
    expect(titleMatches("   ", "   ")).toBe(false);
  });
});

describe("lifecycle", () => {
  const base = { is_canceled: false, archived_at: null, current_version_id: null };
  it("prefers the API field and falls back for older payloads", () => {
    expect(lifecycleOf({ ...base, lifecycle: "archived" })).toBe("archived");
    expect(lifecycleOf({ ...base, is_canceled: true })).toBe("withdrawn");
    expect(lifecycleOf({ ...base, archived_at: "2026-11-01" })).toBe("archived");
    expect(lifecycleOf({ ...base, current_version_id: "v1" })).toBe("published");
    expect(lifecycleOf(base)).toBe("unpublished");
  });
  it("offers archive for active documents and restore for archived/withdrawn ones", () => {
    expect(canArchive("published") && canArchive("unpublished")).toBe(true);
    expect(canArchive("archived") || canArchive("withdrawn")).toBe(false);
    expect(canRestore("archived") && canRestore("withdrawn")).toBe(true);
    expect(canRestore("published")).toBe(false);
  });
});

describe("deletion check helpers", () => {
  it("parses 'code: message' blockers", () => {
    expect(parseBlocker("published: withdraw or archive the document first")).toEqual({
      code: "published",
      message: "withdraw or archive the document first",
    });
    expect(parseBlocker("something odd")).toEqual({ code: "other", message: "something odd" });
  });
  it("recommends archive when approved versions exist", () => {
    expect(recommendArchive({ approved_versions: 2, recommended_action: "archive" })).toBe(true);
    expect(recommendArchive({ approved_versions: 0, recommended_action: "delete" })).toBe(false);
  });
});
