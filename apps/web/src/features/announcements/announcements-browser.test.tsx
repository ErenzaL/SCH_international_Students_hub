import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import { renderWithIntl } from "@/test/utils";
import { AnnouncementsBrowser } from "@/features/announcements/announcements-browser";
import { ApiError, api } from "@/lib/api";

const get = vi.spyOn(api, "get");
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }), usePathname: () => "/" }));

describe("AnnouncementsBrowser states", () => {
  beforeEach(() => {
    get.mockReset();
  });

  it("shows a loading state while the request is pending", () => {
    get.mockReturnValue(new Promise(() => {}) as never);
    renderWithIntl(<AnnouncementsBrowser />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading");
  });

  it("shows an honest empty state when nothing is published", async () => {
    get.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 12 } as never);
    renderWithIntl(<AnnouncementsBrowser />);
    expect(await screen.findByText("No announcements found")).toBeInTheDocument();
    expect(screen.getByText(/Only approved and published/)).toBeInTheDocument();
  });

  it("renders returned announcements with status and test-data badges", async () => {
    get.mockResolvedValue({
      items: [
        {
          id: "a1",
          title: "[SAMPLE] Test notice",
          category: "university-announcements",
          target_audience: "All international students",
          event_date: null,
          deadline: "2030-01-31",
          published_at: "2030-01-01T00:00:00Z",
          status: "active",
          original_language: "ko",
          available_languages: ["ko"],
          excerpt: "Excerpt",
          is_test_data: true,
          source: { title: "S", organization: "Org", url: null, authority_type: "supporter_submitted", scope: "university" },
        },
      ],
      total: 1,
      page: 1,
      page_size: 12,
    });
    renderWithIntl(<AnnouncementsBrowser />);
    expect(await screen.findByRole("link", { name: "[SAMPLE] Test notice" })).toHaveAttribute("href", "/announcements/a1");
    expect(screen.getByText("Test data")).toBeInTheDocument();
    expect(within(screen.getByRole("list")).getByText("Active")).toBeInTheDocument();
  });

  it("surfaces API errors instead of fake data", async () => {
    get.mockRejectedValue(new ApiError({ status: 500, code: "boom", message: "Database exploded" }));
    renderWithIntl(<AnnouncementsBrowser />);
    expect(await screen.findByText("Database exploded")).toBeInTheDocument();
  });

  it("shows setup instructions when Supabase is not configured on the backend", async () => {
    get.mockRejectedValue(new ApiError({ status: 503, code: "supabase_not_configured", message: "x" }));
    renderWithIntl(<AnnouncementsBrowser />);
    await waitFor(() => expect(screen.getByText("Database not configured")).toBeInTheDocument());
  });
});
