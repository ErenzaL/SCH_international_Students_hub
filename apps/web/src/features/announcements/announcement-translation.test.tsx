import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithIntl } from "@/test/utils";
import type { AnnouncementDetail, AnnouncementSummary } from "@/types/api";

const get = vi.fn();
vi.mock("@/lib/api", async (orig) => {
  const mod = await orig<typeof import("@/lib/api")>();
  return { ...mod, api: { ...mod.api, get: (...a: unknown[]) => get(...a) } };
});

import { AnnouncementDetail as Detail } from "@/features/announcements/announcement-detail";
import { AnnouncementCard } from "@/features/announcements/announcement-card";

const base: AnnouncementDetail = {
  id: "a1", title: "장학금 신청 안내", category: "scholarships", target_audience: null, event_date: null,
  deadline: "2026-12-15", published_at: "2026-11-20T00:00:00Z", status: "active", original_language: "ko",
  available_languages: ["ko"], excerpt: "", is_test_data: false,
  source: { title: "SCH", organization: "SCH", url: null, authority_type: "official_university", scope: "university" },
  body: "장학금 신청 기간은 12월 15일까지입니다.", source_published_at: null, verified_at: null, version_id: "v1",
  translations: [], translation: null,
};

beforeEach(() => get.mockReset());

describe("announcement reading language", () => {
  it("shows the English machine translation labelled as unverified, with the original one click away", async () => {
    get.mockImplementation(async (_p: string, q?: { lang: string }) => q?.lang === "en"
      ? { ...base, translation: { status: "machine", language: "en", title: "Scholarship application",
        body: "Apply by December 15.", high_risk: true, reviewed_at: null, generated_at: "2026-11-21T00:00:00Z" } }
      : base);
    renderWithIntl(<Detail id="a1" />);                                  // site language: English
    expect(await screen.findByTestId("announcement-title")).toHaveTextContent("Scholarship application");
    expect(screen.getByTestId("machine-notice")).toHaveTextContent("Unverified machine translation");
    expect(screen.getByTestId("announcement-body")).toHaveTextContent("Apply by December 15.");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /View original/ }));
    expect(screen.getByTestId("announcement-title")).toHaveTextContent("장학금 신청 안내");
    expect(screen.getByTestId("announcement-body")).toHaveTextContent("12월 15일");
    expect(screen.queryByTestId("machine-notice")).toBeNull();
  });

  it("switching to Korean shows the original; a missing translation falls back to the original with a note", async () => {
    get.mockResolvedValue(base);
    renderWithIntl(<Detail id="a1" />);
    expect(await screen.findByTestId("fallback-notice")).toBeInTheDocument();      // English requested, none yet
    expect(screen.getByTestId("announcement-body")).toHaveTextContent("12월 15일");
    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText(/Read in/), "ko");
    expect(get).toHaveBeenLastCalledWith("/api/v1/announcements/a1", { lang: "ko" });
    expect(await screen.findByTestId("announcement-title")).toHaveTextContent("장학금 신청 안내");
    expect(screen.queryByTestId("fallback-notice")).toBeNull();
  });
});

describe("release 1 announcement languages", () => {
  it("Vietnamese and Chinese readers get the original with a clear 'not offered yet' note", async () => {
    get.mockResolvedValue(base);
    renderWithIntl(<Detail id="a1" />);
    await screen.findByTestId("fallback-notice");
    const user = userEvent.setup();
    for (const lang of ["vi", "zh-CN"]) {
      await user.selectOptions(screen.getByLabelText(/Read in/), lang);
      expect(get).toHaveBeenLastCalledWith("/api/v1/announcements/a1", { lang });
      const note = await screen.findByTestId("fallback-notice");
      expect(note).toHaveTextContent(/not translated into/);
      expect(screen.getByTestId("announcement-body")).toHaveTextContent("12월 15일");     // the approved original
    }
    await user.selectOptions(screen.getByLabelText(/Read in/), "id");
    expect(await screen.findByTestId("fallback-notice")).not.toHaveTextContent(/not translated into/);
  });
});

describe("announcement list titles", () => {
  it("shows the translated title, the original title, and a machine-translation badge", () => {
    const a: AnnouncementSummary = { ...base, display_title: "Scholarship application", display_title_status: "machine" };
    renderWithIntl(<AnnouncementCard announcement={a} />);
    expect(screen.getByRole("link", { name: "Scholarship application" })).toHaveAttribute("href", "/announcements/a1");
    expect(screen.getByText("장학금 신청 안내")).toBeInTheDocument();
    expect(screen.getByText("Machine-translated")).toBeInTheDocument();
  });
});
