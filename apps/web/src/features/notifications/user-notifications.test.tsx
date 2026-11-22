/**
 * Regression: the admin pages crashed ("This page couldn't load") because two notification bells for the same
 * user (site header + admin shell) each called supabase.channel("user-notifications-<id>"). supabase-js returns the
 * EXISTING channel for a repeated topic, and calling .on("postgres_changes") on a channel that already
 * subscribed throws "cannot add `postgres_changes` callbacks ... after `subscribe()`" inside a React effect.
 * This test uses the real @supabase/supabase-js client (no mock of the Realtime layer).
 */
import { render, waitFor } from "@testing-library/react";
import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

let realClient: SupabaseClient;
vi.mock("@/lib/supabase/client", () => ({
  getSupabaseBrowserClient: () => realClient,
  getAccessToken: async () => "token",
}));
vi.mock("@/lib/api", async (orig) => {
  const mod = await orig<typeof import("@/lib/api")>();
  return { ...mod, api: { ...mod.api, get: vi.fn(async () => ({ items: [], unread: 0 })), post: vi.fn(async () => ({})) } };
});

import { useUserNotifications } from "@/features/notifications/user-notifications";

function Probe({ userId }: { userId: string }) {
  useUserNotifications(userId);
  return null;
}

describe("useUserNotifications realtime subscription", () => {
  beforeEach(() => {
    realClient = createClient("https://example.supabase.co", "public-anon-key", {
      realtime: { params: { eventsPerSecond: 1 } },
    });
  });
  afterEach(async () => {
    await realClient.removeAllChannels();
  });

  it("does not crash when two components subscribe for the same user (header bell + admin bell)", async () => {
    const errors: unknown[] = [];
    const onError = (e: ErrorEvent) => errors.push(e.error);
    window.addEventListener("error", onError);
    try {
      expect(() =>
        render(
          <>
            <Probe userId="u-1" />
            <Probe userId="u-1" />
          </>,
        ),
      ).not.toThrow();
    } finally {
      window.removeEventListener("error", onError);
    }
    expect(errors).toEqual([]);
    // one shared Realtime channel for the user, not one per component
    await waitFor(() =>
      expect(realClient.getChannels().filter((c) => c.topic === "realtime:user-notifications-u-1")).toHaveLength(1),
    );
  });

  it("releases the shared channel only after the last subscriber unmounts", async () => {
    const a = render(<Probe userId="u-2" />);
    const b = render(<Probe userId="u-2" />);
    a.unmount();
    expect(realClient.getChannels().some((c) => c.topic === "realtime:user-notifications-u-2")).toBe(true);
    b.unmount();
    await waitFor(() =>
      expect(realClient.getChannels().some((c) => c.topic === "realtime:user-notifications-u-2")).toBe(false),
    );
  });

  it("a Realtime failure never breaks the page (falls back to polling)", () => {
    realClient = {
      channel: () => {
        throw new Error("realtime unavailable");
      },
      removeChannel: async () => "ok",
      removeAllChannels: async () => [],
    } as never;
    expect(() => render(<Probe userId="u-3" />)).not.toThrow();
  });
});
