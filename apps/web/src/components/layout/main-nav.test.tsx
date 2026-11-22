import { describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithIntl } from "@/test/utils";
import { MainNav } from "@/components/layout/main-nav";
import { NAV_ITEMS, isActivePath } from "@/components/layout/nav-items";

vi.mock("next/navigation", () => ({
  usePathname: () => "/announcements/123",
  useRouter: () => ({ refresh: vi.fn(), push: vi.fn() }),
}));

describe("MainNav", () => {
  it("renders every main navigation link with the right href", () => {
    renderWithIntl(<MainNav />);
    const expected: Record<string, string> = {
      Home: "/",
      Announcements: "/announcements",
      "Knowledge Center": "/knowledge",
      "AI Assistant": "/assistant",
      "Student Support": "/support",
    };
    for (const [label, href] of Object.entries(expected)) {
      expect(screen.getByRole("link", { name: label })).toHaveAttribute("href", href);
    }
    expect(NAV_ITEMS).toHaveLength(5);
  });

  it("marks the current section with aria-current", () => {
    renderWithIntl(<MainNav />);
    expect(screen.getByRole("link", { name: "Announcements" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Home" })).not.toHaveAttribute("aria-current");
  });

  it("matches active paths correctly", () => {
    expect(isActivePath("/", "/")).toBe(true);
    expect(isActivePath("/knowledge/abc", "/knowledge")).toBe(true);
    expect(isActivePath("/knowledgebase", "/knowledge")).toBe(false);
  });
});
