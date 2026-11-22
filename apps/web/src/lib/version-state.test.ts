import { afterEach, describe, expect, it, vi } from "vitest";
import { activationOutcome, ragHasActiveWork, relativeTime, versionState, waitForActivation } from "@/lib/version-state";
import type { RagStatus, Version } from "@/types/api";

vi.mock("@/lib/supabase/client", () => ({ getAccessToken: async () => "test-token" }));

const base = { verification_status: "pending_review", is_current: false, indexing_status: "not_indexed", activation_requested_at: null } as const;

describe("versionState", () => {
  it("derives each lifecycle state", () => {
    expect(versionState({ ...base })).toBe("pending_review");
    expect(versionState({ ...base, activation_requested_at: "2030-01-01T00:00:00Z", indexing_status: "queued" })).toBe("indexing");
    expect(versionState({ ...base, indexing_status: "indexing" })).toBe("indexing");
    expect(versionState({ ...base, activation_requested_at: "2030-01-01T00:00:00Z", indexing_status: "failed" })).toBe("index_failed");
    expect(versionState({ ...base, indexing_status: "failed" })).toBe("pending_review"); // not approved yet
    expect(versionState({ ...base, verification_status: "approved", is_current: true })).toBe("active");
    expect(versionState({ ...base, verification_status: "approved", is_current: false })).toBe("approved_inactive");
    expect(versionState({ ...base, verification_status: "superseded" })).toBe("superseded");
    expect(versionState({ ...base, verification_status: "draft" })).toBe("draft");
    expect(versionState({ ...base, verification_status: "rejected" })).toBe("rejected");
  });
});

describe("activationOutcome", () => {
  it("stops polling on active or failed only", () => {
    expect(activationOutcome({ ...base, verification_status: "approved", is_current: true })).toBe("active");
    expect(activationOutcome({ ...base, indexing_status: "failed" })).toBe("failed");
    expect(activationOutcome({ ...base, verification_status: "rejected" })).toBe("failed");
    expect(activationOutcome({ ...base, indexing_status: "queued" })).toBe("pending");
    expect(activationOutcome({ ...base, indexing_status: "indexing" })).toBe("pending");
  });
});

describe("waitForActivation", () => {
  afterEach(() => vi.restoreAllMocks());

  it("polls until the version is active", async () => {
    const states: Partial<Version>[] = [
      { ...base, indexing_status: "queued" },
      { ...base, indexing_status: "indexing" },
      { ...base, verification_status: "approved", is_current: true, indexing_status: "indexed" },
    ];
    let i = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation(async () =>
      new Response(JSON.stringify({ id: "v1", ...states[Math.min(i++, states.length - 1)] }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    const seen: string[] = [];
    const res = await waitForActivation("v1", { intervalMs: 1, maxMs: 5000, onUpdate: (v) => seen.push(String(v.indexing_status)) });
    expect(res.outcome).toBe("active");
    expect(seen).toEqual(["queued", "indexing", "indexed"]);
  });

  it("gives up as 'pending' after the time budget", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async () =>
      new Response(JSON.stringify({ id: "v1", ...base, indexing_status: "queued" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    const res = await waitForActivation("v1", { intervalMs: 1, maxMs: 15 });
    expect(res.outcome).toBe("pending");
  });
});

describe("ragHasActiveWork", () => {
  const counts = { waiting_for_indexing: 0, indexing_now: 0 } as RagStatus["counts"];
  it("is true only while jobs are queued or running", () => {
    expect(ragHasActiveWork(null)).toBe(false);
    expect(ragHasActiveWork({ counts, queue: [] })).toBe(false);
    expect(ragHasActiveWork({ counts: { ...counts, indexing_now: 1 }, queue: [] })).toBe(true);
    expect(ragHasActiveWork({ counts, queue: [{ status: "queued" } as RagStatus["queue"][number]] })).toBe(true);
    expect(ragHasActiveWork({ counts, queue: [{ status: "failed" } as RagStatus["queue"][number]] })).toBe(false);
  });
});

describe("relativeTime", () => {
  const now = Date.parse("2030-01-01T12:00:00Z");
  it("formats past times", () => {
    expect(relativeTime("2030-01-01T11:57:00Z", "en", now)).toBe("3 minutes ago");
    expect(relativeTime("2030-01-01T09:00:00Z", "en", now)).toBe("3 hours ago");
    expect(relativeTime(null, "en", now)).toBe("—");
    expect(relativeTime("garbage", "en", now)).toBe("—");
  });
});
