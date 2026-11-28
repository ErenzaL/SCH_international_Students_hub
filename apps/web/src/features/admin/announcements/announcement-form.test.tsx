import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithIntl } from "@/test/utils";
import { cleanTargets, EMPTY_ANNOUNCEMENT_FORM, toAnnouncementCreate } from "@/features/admin/announcements/announcement-validation";

const post = vi.fn();
const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, refresh: vi.fn() }) }));
vi.mock("@/lib/api", async (orig) => {
  const mod = await orig<typeof import("@/lib/api")>();
  return { ...mod, api: { ...mod.api, post: (...a: unknown[]) => post(...a) } };
});

import { AnnouncementForm } from "@/features/admin/announcements/announcement-form";

beforeEach(() => {
  post.mockReset();
  push.mockReset();
});

describe("Automatic translation in the announcement form", () => {
  it("never offers the original language and sends the chosen targets with the draft", async () => {
    renderWithIntl(<AnnouncementForm />);
    const user = userEvent.setup();
    expect(screen.getByTestId("auto-tr-ko")).toBeDisabled();             // Korean is the original
    await user.click(screen.getByTestId("auto-tr-en"));
    await user.click(screen.getByTestId("auto-tr-id"));
    await user.selectOptions(screen.getByLabelText("Original language"), "en");
    expect(screen.getByTestId("auto-tr-en")).toBeDisabled();             // now English is the original
    expect(screen.getByTestId("auto-tr-ko")).toBeEnabled();
    await user.type(screen.getByLabelText("Title"), "Dormitory move-in guide");
    await user.type(screen.getByLabelText("Original text"), "Move-in starts on 24 February 2027 at 10:00.");
    post.mockResolvedValue({ id: "a1" });
    await user.click(screen.getByRole("button", { name: /Submit for approval/ }));
    await waitFor(() => expect(post).toHaveBeenCalled());
    const body = post.mock.calls[0][1];
    expect(body.original_language).toBe("en");
    expect(body.translation_targets).toEqual(["id"]);                    // English (the original) removed
    expect(body.submit).toBe(true);
  });

  it("no language chosen means no automatic translation", () => {
    expect(toAnnouncementCreate({ ...EMPTY_ANNOUNCEMENT_FORM, title: "x", body: "0123456789" }, false).translation_targets).toEqual([]);
    expect(cleanTargets({ original_language: "id", translation_targets: ["id", "ko", "ko"] })).toEqual(["ko"]);
  });
});
