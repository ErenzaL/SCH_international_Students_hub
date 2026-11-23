import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { renderWithIntl } from "@/test/utils";
import ko from "@/messages/ko.json";

const session = { ready: true, userId: null as string | null, email: null };
vi.mock("@/lib/use-session", () => ({ useSession: () => session }));
vi.mock("next/navigation", () => ({ usePathname: () => "/ai-office", useRouter: () => ({ refresh: vi.fn(), push: vi.fn() }) }));
const postStream = vi.fn();
vi.mock("@/lib/chat-stream", () => ({ postStream: (...a: unknown[]) => postStream(...a) }));
const get = vi.fn();
vi.mock("@/lib/api", async (orig) => {
  const mod = await orig<typeof import("@/lib/api")>();
  return { ...mod, api: { ...mod.api, get: (...a: unknown[]) => get(...a), post: vi.fn() } };
});

import { AiOffice } from "@/features/ai-office/ai-office";
import { CHARACTERS, INTERACTIVE } from "@/features/ai-office/characters";
import { upcoming } from "@/features/ai-office/desk-resources";
import { shouldShowChat } from "@/features/chatbot/chat-widget";
import { isFullscreenRoute } from "@/components/layout/fullscreen-route";

// jsdom has no layout: give the office a desktop-sized viewport
const size = { w: 1440, h: 900 };
beforeAll(() => {
  Object.defineProperty(HTMLElement.prototype, "clientWidth", { configurable: true, get: () => size.w });
  Object.defineProperty(HTMLElement.prototype, "clientHeight", { configurable: true, get: () => size.h });
});
afterAll(() => {
  delete (HTMLElement.prototype as unknown as Record<string, unknown>).clientWidth;
  delete (HTMLElement.prototype as unknown as Record<string, unknown>).clientHeight;
});

const doc = (id: string, title: string) => ({ id, title, organization: "Hi Korea", category: "visa-immigration", language: "en" });
const ann = (id: string, title: string, extra: object = {}) => ({ id, title, category: "university-announcements", deadline: null,
  event_date: null, published_at: "2026-11-20", status: "active", original_language: "ko", available_languages: ["ko"], excerpt: "",
  is_test_data: false, source: {}, target_audience: null, ...extra });

beforeEach(() => {
  postStream.mockReset();
  get.mockReset();
  sessionStorage.clear();
  localStorage.clear();
  get.mockImplementation(async (path: string, q: Record<string, string> = {}) => {
    if (path === "/api/v1/knowledge/documents") return { items: q.category === "visa-immigration" ? [doc("d-visa", "D-2 visa extension")] : [], total: 0 };
    if (path === "/api/v1/announcements") {
      if (q.category === "scholarships") return { items: [], total: 0 };
      if (q.status === "upcoming") return { items: [ann("a2", "Spring orientation", { event_date: "2027-03-02" })], total: 1 };
      if (q.status === "active") return { items: [ann("a1", "Dormitory move-out", { deadline: "2026-12-20" }), ann("a3", "Library notice")], total: 2 };
      return { items: [ann("a1", "Dormitory move-out")], total: 1 };
    }
    return { items: [], total: 0 };
  });
  postStream.mockImplementation(async (_p: string, body: { language: string; message: string }, opts: { onEvent: (e: unknown) => void }) => {
    opts.onEvent({ event: "delta", data: { text: "…" } });
    return { answer: `answer in ${body.language} [1]`, language: body.language,
      citations: [{ n: 1, document_id: "d-visa", version_id: "v", chunk_id: "c", document_title: "D-2 visa extension", heading: null,
        source_url: null, organization: "Hi Korea", authority_type: "official_government", verified_at: null, is_stale: false, page: null, cited: true }],
      metadata: { answer_generation: "llm", offer_handoff: false } };
  });
});

describe("AI Office page", () => {
  it("shows every staff member as an accessible button with its own original artwork", () => {
    renderWithIntl(<AiOffice />);
    for (const c of INTERACTIVE) {
      const btn = screen.getByTestId(`character-${c.id}`);
      expect(btn.tagName).toBe("BUTTON");
      expect(btn).toHaveAccessibleName(expect.stringContaining(c.name));
      expect(btn.querySelector("img")).toHaveAttribute("src", `/office/characters/${c.file}`);
    }
    // visiting students are scenery: not focusable
    for (const c of CHARACTERS.filter((x) => !x.interactive)) {
      expect(screen.queryByTestId(`character-${c.id}`)).toBeNull();
    }
    expect(screen.getByText("GLOBAL SUPPORTERS")).toBeInTheDocument();
    expect(screen.getAllByText("AI SUPPORT CENTER").length).toBeGreaterThan(0);
    expect(screen.getByTestId("back-to-hub")).toHaveAttribute("href", "/");
  });

  it.each([
    ["supporter-ko", "ko", "Answers in Korean", "안녕하세요, 한국어 지원 담당 민지예요"],
    ["supporter-id", "id", "Answers in Indonesian", "Halo, saya Sari"],
    ["supporter-zh", "zh-CN", "Answers in Chinese", "你好，我是中文支持的 Mei"],
  ])("%s answers through the existing assistant in its own language", async (id, lang, label, welcome) => {
    renderWithIntl(<AiOffice />);
    const user = userEvent.setup();
    await user.click(screen.getByTestId(`character-${id}`));
    const panel = await screen.findByTestId("office-panel");
    expect(within(panel).getByTestId("panel-language")).toHaveTextContent(label);
    expect(within(panel).getByTestId("chat-welcome")).toHaveTextContent(welcome);
    expect(screen.getByTestId("speech-bubble")).toBeInTheDocument();          // greeting above the character
    await user.type(within(panel).getByLabelText("Your message"), "Hello{Enter}");
    await within(panel).findByText(`answer in ${lang}`);
    expect(postStream).toHaveBeenCalledWith("/api/v1/assistant/chat/stream",
      expect.objectContaining({ message: "Hello", language: lang }), expect.anything());
  });

  it("keeps the conversation for follow-up questions and links citations to the source", async () => {
    renderWithIntl(<AiOffice />);
    const user = userEvent.setup();
    await user.click(screen.getByTestId("character-supporter-en"));
    const panel = await screen.findByTestId("office-panel");
    await user.type(within(panel).getByLabelText("Your message"), "How do I extend my visa?{Enter}");
    await within(panel).findByText("answer in en");
    expect(within(panel).getByRole("link", { name: "D-2 visa extension" })).toHaveAttribute("href", "/knowledge/d-visa");
    await user.type(within(panel).getByLabelText("Your message"), "And the fee?{Enter}");
    await waitFor(() => expect(postStream).toHaveBeenCalledTimes(2));
    expect(postStream.mock.calls[1][1].history).toEqual([{ role: "user", content: "How do I extend my visa?" }]);
  });

  it("desk staff answer in the site language and show real Knowledge Center guides", async () => {
    renderWithIntl(<AiOffice />);
    const user = userEvent.setup();
    await user.click(screen.getByTestId("character-visa"));
    const panel = await screen.findByTestId("office-panel");
    expect(within(panel).getByTestId("panel-language")).toHaveTextContent("Answers in your site language (English)");
    await user.click(within(panel).getByTestId("tab-guides"));
    const link = await within(panel).findByRole("link", { name: /D-2 visa extension/ });
    expect(link).toHaveAttribute("href", "/knowledge/d-visa");
    expect(get).toHaveBeenCalledWith("/api/v1/knowledge/documents", expect.objectContaining({ category: "visa-immigration" }));
    await user.click(within(panel).getByTestId("tab-chat"));
    await user.type(within(panel).getByLabelText("Your message"), "visa?{Enter}");
    await waitFor(() => expect(postStream).toHaveBeenCalledWith("/api/v1/assistant/chat/stream",
      expect.objectContaining({ language: "en" }), expect.anything()));
  });

  it("the events desk lists published current and upcoming events, soonest first, linking to them", async () => {
    renderWithIntl(<AiOffice />);
    const user = userEvent.setup();
    await user.click(screen.getByTestId("character-events"));
    const list = await screen.findByTestId("desk-events");
    await within(list).findByRole("link", { name: /Dormitory move-out/ });
    const links = within(list).getAllByRole("link").filter((a) => a.getAttribute("href")?.startsWith("/announcements/"));
    expect(links.map((a) => a.getAttribute("href"))).toEqual(["/announcements/a1", "/announcements/a2"]);   // undated notice left out
    expect(get).toHaveBeenCalledWith("/api/v1/announcements", expect.objectContaining({ status: "upcoming" }));
  });

  it("the opportunities desk says honestly when nothing is published, and shows planned features as not active", async () => {
    renderWithIntl(<AiOffice />);
    const user = userEvent.setup();
    await user.click(screen.getByTestId("character-opportunities"));
    expect(await screen.findByTestId("desk-empty")).toHaveTextContent("No scholarship or opportunity notices are published");
    await user.click(screen.getByTestId("tab-about"));
    const caps = screen.getByTestId("desk-capabilities");
    expect(within(caps).getByText("Coming later")).toBeInTheDocument();
    expect(caps.querySelectorAll('[data-status="planned"]').length).toBeGreaterThan(0);
  });

  it("is keyboard accessible: focus a character, Enter opens it, Escape closes and returns focus", async () => {
    renderWithIntl(<AiOffice />);
    const user = userEvent.setup();
    const btn = screen.getByTestId("character-reception");
    btn.focus();
    await user.keyboard("{Enter}");
    expect(await screen.findByTestId("office-panel")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByTestId("office-panel")).toBeNull();
    expect(btn).toHaveFocus();
  });

  it("offers a people & desks menu (for small screens) that opens the chosen character", async () => {
    renderWithIntl(<AiOffice />);
    const user = userEvent.setup();
    await user.click(screen.getByTestId("people-menu-button"));
    await user.click(within(await screen.findByTestId("people-menu")).getByTestId("menu-career"));
    const panel = await screen.findByTestId("office-panel");
    expect(within(panel).getByRole("heading", { name: "Daniel" })).toBeInTheDocument();
  });

  it("reception guides visitors to the right desk", async () => {
    renderWithIntl(<AiOffice />);
    const user = userEvent.setup();
    await user.click(screen.getByTestId("character-reception"));
    await user.click(screen.getByTestId("tab-desks"));
    await user.click(within(screen.getByTestId("desk-directory")).getByRole("button", { name: /Yuna/ }));
    expect(within(screen.getByTestId("office-panel")).getByRole("heading", { name: "Yuna" })).toBeInTheDocument();
  });

  it("does not leak listeners when conversations are opened and closed repeatedly", async () => {
    const add = vi.spyOn(document, "addEventListener");
    const remove = vi.spyOn(document, "removeEventListener");
    const { unmount } = renderWithIntl(<AiOffice />);
    const user = userEvent.setup();
    for (let i = 0; i < 5; i++) {
      await user.click(screen.getByTestId("character-supporter-vi"));
      await screen.findByTestId("office-panel");
      await user.click(screen.getByTestId("panel-close"));
    }
    unmount();
    const count = (spy: typeof add, type: string) => spy.mock.calls.filter((c) => c[0] === type).length;
    for (const type of ["keydown", "visibilitychange"]) expect(count(remove, type)).toBe(count(add, type));
    add.mockRestore();
    remove.mockRestore();
  });

  it("updates its labels when the site language changes (no reload)", () => {
    const { rerender } = renderWithIntl(<AiOffice />);
    expect(screen.getByText("GLOBAL SUPPORTERS")).toBeInTheDocument();
    rerender(<AiOfficeIn locale="ko" />);
    expect(screen.getByText("글로벌 서포터즈")).toBeInTheDocument();
    expect(screen.getByTestId("character-supporter-ko")).toHaveAccessibleName(/Minji/);   // names are not translated
  });
});

function AiOfficeIn({ locale }: { locale: string }) {
  // re-render inside a provider with other messages (what router.refresh() does after a language change)
  return <NextIntlClientProvider locale={locale} messages={ko as never}><AiOffice /></NextIntlClientProvider>;
}

describe("office helpers", () => {
  it("orders events by date and leaves out undated notices", () => {
    const items = [ann("x", "late", { event_date: "2027-05-01" }), ann("y", "none"), ann("z", "soon", { deadline: "2026-12-01" }),
      ann("x", "dup", { event_date: "2027-05-01" })];
    expect(upcoming(items as never).map((a) => a.id)).toEqual(["z", "x"]);
  });

  it("hides the floating chat and the site chrome on the full-screen office", () => {
    expect(shouldShowChat("/ai-office")).toBe(false);
    expect(shouldShowChat("/knowledge")).toBe(true);
    expect(isFullscreenRoute("/ai-office")).toBe(true);
    expect(isFullscreenRoute("/announcements")).toBe(false);
  });

  it("respects reduced motion (characters stay at their spots)", async () => {
    const mm = window.matchMedia;
    window.matchMedia = vi.fn().mockImplementation((q: string) => ({ matches: q.includes("reduce"), media: q,
      addEventListener: vi.fn(), removeEventListener: vi.fn() })) as unknown as typeof window.matchMedia;
    const raf = vi.spyOn(window, "requestAnimationFrame");
    renderWithIntl(<AiOffice />);
    await act(async () => { await new Promise((r) => setTimeout(r, 30)); });
    expect(raf).not.toHaveBeenCalled();
    raf.mockRestore();
    window.matchMedia = mm;
  });
});
