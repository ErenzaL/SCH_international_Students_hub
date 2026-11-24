import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithIntl } from "@/test/utils";

/** Signed in, the account links live in one profile menu so the header keeps a single row. */
const session = { ready: true, userId: "u1" as string | null, email: "student@example.test" as string | null };
vi.mock("@/lib/use-session", () => ({ useSession: () => session }));
const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, refresh: vi.fn() }), usePathname: () => "/" }));
const signOut = vi.fn(async () => ({}));
vi.mock("@/lib/supabase/client", () => ({ getSupabaseBrowserClient: () => ({ auth: { signOut } }), getAccessToken: async () => "t" }));
let me: Record<string, unknown> = {};
vi.mock("@/lib/api", async (orig) => {
  const mod = await orig<typeof import("@/lib/api")>();
  return { ...mod, api: { ...mod.api, get: async (path: string) => (path === "/api/v1/me" ? me : { items: [], unread: 0 }) } };
});
vi.mock("@/features/notifications/user-notifications", () => ({ UserNotificationBell: () => <span data-testid="bell" /> }));

import { AuthMenu } from "@/components/layout/auth-menu";

beforeEach(() => {
  session.userId = "u1";
  push.mockReset();
  signOut.mockClear();
  me = { id: "u1", email: "student@example.test", display_name: null, role: "student", is_staff: false,
    preferred_language: "en", preferred_language_confirmed: true, languages: [] };
});

describe("AuthMenu", () => {
  it("shows one profile button instead of a row of links, with the links in its menu", async () => {
    renderWithIntl(<AuthMenu />);
    expect(screen.getByTestId("bell")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /My requests/ })).toBeNull();
    await userEvent.click(screen.getByTestId("profile-menu-button"));
    const menu = screen.getByTestId("profile-menu");
    expect(menu).toHaveTextContent("student@example.test");
    expect(screen.getByRole("menuitem", { name: /My requests/ })).toHaveAttribute("href", "/support/requests");
    expect(screen.getByRole("menuitem", { name: /Account/ })).toHaveAttribute("href", "/account");
    expect(screen.queryByRole("menuitem", { name: /Admin/ })).toBeNull();          // students: no admin link
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByTestId("profile-menu")).toBeNull();
  });

  it("staff also get the admin link, and sign out works from the menu", async () => {
    me = { ...me, role: "admin", is_staff: true };
    renderWithIntl(<AuthMenu />);
    await waitFor(() => expect(screen.getByTestId("profile-menu-button")).toBeInTheDocument());
    await userEvent.click(screen.getByTestId("profile-menu-button"));
    expect(await screen.findByRole("menuitem", { name: /Admin/ })).toHaveAttribute("href", "/admin");
    await userEvent.click(screen.getByRole("menuitem", { name: /Sign out/ }));
    await waitFor(() => expect(signOut).toHaveBeenCalled());
    expect(push).toHaveBeenCalledWith("/");
  });
});
