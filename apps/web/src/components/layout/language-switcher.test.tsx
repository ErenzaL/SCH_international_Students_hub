import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithIntl } from "@/test/utils";
import { LanguageSwitcher } from "@/components/layout/language-switcher";
import { LOCALE_COOKIE, LOCALE_STORAGE_KEY } from "@/lib/constants";

const refresh = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh, push: vi.fn() }),
  usePathname: () => "/",
}));

describe("LanguageSwitcher", () => {
  beforeEach(() => {
    refresh.mockClear();
    localStorage.clear();
    document.cookie = `${LOCALE_COOKIE}=; path=/; max-age=0`;
  });

  it("offers all five languages by their native names", () => {
    renderWithIntl(<LanguageSwitcher />);
    const options = screen.getAllByRole("option").map((o) => o.textContent);
    expect(options).toEqual(["English", "한국어", "Bahasa Indonesia", "Tiếng Việt", "简体中文"]);
  });

  it("saves the choice to a cookie and localStorage and refreshes", async () => {
    // Pre-set a cookie so the restore-from-storage effect does not interfere.
    document.cookie = `${LOCALE_COOKIE}=en; path=/`;
    renderWithIntl(<LanguageSwitcher />);
    await userEvent.selectOptions(screen.getByLabelText("Language"), "ko");
    expect(document.cookie).toContain(`${LOCALE_COOKIE}=ko`);
    expect(localStorage.getItem(LOCALE_STORAGE_KEY)).toBe("ko");
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("restores a stored preference when the cookie is missing", () => {
    localStorage.setItem(LOCALE_STORAGE_KEY, "vi");
    renderWithIntl(<LanguageSwitcher />);
    expect(document.cookie).toContain(`${LOCALE_COOKIE}=vi`);
    expect(refresh).toHaveBeenCalled();
  });
});
