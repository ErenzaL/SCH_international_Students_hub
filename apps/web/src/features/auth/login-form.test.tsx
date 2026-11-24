import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithIntl } from "@/test/utils";

/** Student and staff sign-in: staff can never sign up here, and an account without a staff role is not let in. */
const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, refresh: vi.fn() }) }));
vi.mock("@/lib/constants", async (orig) => ({ ...(await orig<typeof import("@/lib/constants")>()), isSupabaseConfigured: true }));
const auth = { signInWithPassword: vi.fn(), signUp: vi.fn(), signOut: vi.fn() };
vi.mock("@/lib/supabase/client", () => ({ getSupabaseBrowserClient: () => ({ auth }), getAccessToken: async () => "t" }));
let me: Record<string, unknown> = {};
vi.mock("@/lib/api", async (orig) => {
  const mod = await orig<typeof import("@/lib/api")>();
  return { ...mod, api: { ...mod.api, get: async () => me } };
});

import { initialAudience, LoginForm, safeNextPath } from "@/features/auth/login-form";

beforeEach(() => {
  push.mockReset();
  Object.values(auth).forEach((f) => f.mockReset());
  auth.signInWithPassword.mockResolvedValue({ error: null });
  auth.signOut.mockResolvedValue({});
  me = { role: "student", is_staff: false, preferred_language: "en", preferred_language_confirmed: false };
});

async function signIn(email = "a@example.test") {
  await userEvent.type(screen.getByLabelText("Email"), email);
  await userEvent.type(screen.getByLabelText("Password"), "password123");
  await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
}

describe("LoginForm", () => {
  it("students sign in or create an account and land on the page they came from (or home)", async () => {
    renderWithIntl(<LoginForm />);
    expect(screen.getByTestId("login-student")).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("button", { name: "Sign up" })).toBeInTheDocument();
    await signIn();
    await waitFor(() => expect(push).toHaveBeenCalledWith("/"));
  });

  it("staff sign-in has no sign-up and explains how access is granted", async () => {
    renderWithIntl(<LoginForm />);
    await userEvent.click(screen.getByTestId("login-staff"));
    expect(screen.getByRole("heading", { name: "Staff sign in" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Sign up" })).toBeNull();
    expect(screen.getByTestId("staff-no-signup")).toHaveTextContent("granted by a super admin");
  });

  it("an account without a staff role is signed out again on the staff side", async () => {
    renderWithIntl(<LoginForm as="staff" />);
    await signIn();
    expect(await screen.findByText(/has no staff access/)).toBeInTheDocument();
    expect(auth.signOut).toHaveBeenCalled();
    expect(push).not.toHaveBeenCalled();
  });

  it("staff land in the admin area; admin pages open the staff sign-in", async () => {
    me = { role: "admin", is_staff: true, preferred_language: "en" };
    renderWithIntl(<LoginForm next="/admin/review" />);
    expect(screen.getByTestId("login-staff")).toHaveAttribute("aria-selected", "true");
    await signIn();
    await waitFor(() => expect(push).toHaveBeenCalledWith("/admin/review"));
    expect(auth.signOut).not.toHaveBeenCalled();
    expect(initialAudience(undefined, "/ai-office")).toBe("student");
    expect(initialAudience("student", "/admin")).toBe("student");
    expect(safeNextPath("//evil.example", "/")).toBe("/");
  });
});
