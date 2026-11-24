import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithIntl } from "@/test/utils";

const session = { ready: true, userId: null as string | null, email: null };
vi.mock("@/lib/use-session", () => ({ useSession: () => session }));
const pathnameMock = vi.fn(() => "/knowledge");
vi.mock("next/navigation", () => ({ usePathname: () => pathnameMock() }));
const postStream = vi.fn();
vi.mock("@/lib/chat-stream", () => ({ postStream: (...a: unknown[]) => postStream(...a) }));
const get = vi.fn();
const post = vi.fn();
vi.mock("@/lib/api", async (orig) => {
  const mod = await orig<typeof import("@/lib/api")>();
  return { ...mod, api: { ...mod.api, get: (...a: unknown[]) => get(...a), post: (...a: unknown[]) => post(...a) } };
});

import { ChatWidget, shouldShowChat } from "@/features/chatbot/chat-widget";
import { openChat } from "@/features/chatbot/open-chat";
import { act } from "@testing-library/react";

const citation = { n: 1, document_id: "d1", version_id: "v1", chunk_id: "c1", document_title: "Visa and Stay",
  heading: null, source_url: "https://www.studyinkorea.go.kr/v", organization: "NIIED", authority_type: "official_government",
  verified_at: null, is_stale: false, page: null, similarity: 0.9, cited: true } as const;

beforeEach(() => {
  postStream.mockReset();
  get.mockReset();
  post.mockReset();
  session.userId = null;
  sessionStorage.clear();
  localStorage.clear();
});

describe("ChatWidget", () => {
  it("is available on every student page, hidden only in admin and on the login page", () => {
    expect(shouldShowChat("/admin/documents")).toBe(false);
    expect(shouldShowChat("/login")).toBe(false);
    expect(shouldShowChat("/support")).toBe(true);
    expect(shouldShowChat("/announcements/1")).toBe(true);
    expect(shouldShowChat("/knowledge/abc")).toBe(true);
    expect(shouldShowChat("/")).toBe(true);
  });

  it("opens as a chat (no menus), streams a grounded answer with clickable sources and no supporter offer", async () => {
    postStream.mockImplementation(async (_path: string, _body: unknown, opts: { onEvent: (e: unknown) => void }) => {
      opts.onEvent({ event: "status", data: { stage: "searching" } });
      opts.onEvent({ event: "delta", data: { text: "Register at the " } });
      return { answer: "Register at the **immigration office** [1].", language: "en", citations: [citation],
        metadata: { answer_generation: "llm", evidence_level: "sufficient", offer_handoff: false,
          follow_ups: ["What documents do I need?"] } };
    });
    renderWithIntl(<ChatWidget />);
    const user = userEvent.setup();
    await user.click(screen.getByTestId("chat-launcher"));
    expect(screen.getByRole("dialog", { name: "SCH Assistant" })).toBeInTheDocument();
    expect(screen.getByText(/Ask me anything about studying at SCH/)).toBeInTheDocument();
    expect(screen.queryByTestId("handoff-offer")).toBeNull();                 // no support prompt on opening
    await user.type(screen.getByLabelText("Your message"), "Where do I register?{Enter}");
    expect(await screen.findByText("immigration office")).toBeInTheDocument();
    expect(postStream).toHaveBeenCalledWith("/api/v1/assistant/chat/stream",
      expect.objectContaining({ message: "Where do I register?", language: "en", history: [] }), expect.anything());
    expect(screen.getByRole("link", { name: "Source 1" })).toHaveAttribute("href", "/knowledge/d1");
    expect(screen.getByRole("link", { name: "Open the official source" })).toHaveAttribute("href", citation.source_url);
    expect(screen.queryByTestId("handoff-offer")).toBeNull();                 // no premature escalation
    expect(screen.getByRole("button", { name: "What documents do I need?" })).toBeInTheDocument();
  });

  it("multi-turn: the visitor's earlier turns are sent as context", async () => {
    postStream.mockResolvedValue({ answer: "Bring your passport [1].", language: "en", citations: [citation],
      metadata: { answer_generation: "llm", offer_handoff: false } });
    renderWithIntl(<ChatWidget />);
    const user = userEvent.setup();
    await user.click(screen.getByTestId("chat-launcher"));
    await user.type(screen.getByLabelText("Your message"), "Where do I register?{Enter}");
    await screen.findAllByText(/Bring your passport/);
    await user.type(screen.getByLabelText("Your message"), "and what should I bring?{Enter}");
    await waitFor(() => expect(postStream).toHaveBeenCalledTimes(2));
    expect(postStream.mock.calls[1][1].history).toEqual([{ role: "user", content: "Where do I register?" }]);
  });

  it("visitors are asked to sign in instead of creating a request", async () => {
    postStream.mockResolvedValue({ answer: "I couldn't find this.", language: "en", citations: [],
      metadata: { offer_handoff: true, handoff_reasons: ["no_evidence"], evidence_level: "none" } });
    renderWithIntl(<ChatWidget />);
    const user = userEvent.setup();
    await user.click(screen.getByTestId("chat-launcher"));
    await user.type(screen.getByLabelText("Your message"), "kimchi recipe{Enter}");
    expect(await screen.findByTestId("handoff-offer")).toHaveTextContent("Sign in to send them a request");
    expect(post).not.toHaveBeenCalled();
  });

  it("signed in: a request is created only after reviewing the draft and giving consent", async () => {
    session.userId = "u1";
    post.mockImplementation(async (path: string) => {
      if (path === "/api/v1/conversations") return { id: "c1" };
      if (path.endsWith("/handoff-draft")) return { subject: "My visa expired", summary: "Needs a person.", language: "vi",
        message_ids: ["m1", "m2"], references: [{ title: "Visa and Stay", url: citation.source_url }], reasons: ["asked_for_human"],
        messages: [{ id: "m1", role: "user", content: "My visa expired", created_at: "" },
          { id: "m2", role: "assistant", content: "…", created_at: "" }] };
      if (path === "/api/v1/support/tickets") return { id: "t1", ticket_number: 1001, status: "assigned" };
      throw new Error(path);
    });
    get.mockResolvedValue({ id: "c1", messages: [] });
    postStream.mockResolvedValue({
      user_message: { id: "m1", role: "user", content: "talk to a person", citations: [], metadata: {} },
      assistant_message: { id: "m2", role: "assistant", content: "I can help prepare a request.", citations: [],
        metadata: { offer_handoff: true, handoff_reasons: ["asked_for_human"], answer_generation: "llm" } },
    });
    renderWithIntl(<ChatWidget />);
    const user = userEvent.setup();
    await user.click(screen.getByTestId("chat-launcher"));
    await user.type(screen.getByLabelText("Your message"), "talk to a person{Enter}");
    const offer = await screen.findByTestId("handoff-offer");
    expect(screen.getAllByTestId("handoff-offer")).toHaveLength(1);           // rendered once, as a structured action
    expect(screen.getAllByText("Would you like a Global Supporter to help with this?")).toHaveLength(1);
    expect(screen.getByTestId("assistant-answer")).toHaveTextContent(/^I can help prepare a request\.$/);
    expect(post).not.toHaveBeenCalledWith("/api/v1/support/tickets", expect.anything());
    await user.click(screen.getByRole("button", { name: "Yes, prepare a request" }));
    expect(await screen.findByTestId("handoff-review")).toHaveTextContent("Tiếng Việt");
    const sendBtn = screen.getByRole("button", { name: "Send request" });
    expect(sendBtn).toBeDisabled();                                          // consent first
    expect(post).not.toHaveBeenCalledWith("/api/v1/support/tickets", expect.anything());
    await user.click(screen.getByTestId("handoff-consent"));
    await user.click(sendBtn);
    await waitFor(() => expect(post).toHaveBeenCalledWith("/api/v1/support/tickets", {
      subject: "My visa expired", summary: "Needs a person.", conversation_id: "c1", message_ids: ["m1", "m2"], consent: true }));
    expect(offer).toBeDefined();
  });

  it("uses a full-screen sheet with safe areas on phones and a floating panel on larger screens", async () => {
    renderWithIntl(<ChatWidget />);
    await userEvent.setup().click(screen.getByTestId("chat-launcher"));
    const panel = screen.getByTestId("chat-panel");
    for (const cls of ["inset-0", "h-[100dvh]", "sm:w-[420px]", "sm:rounded-2xl", "sm:h-[min(680px,calc(100dvh-2.5rem))]"]) {
      expect(panel.className).toContain(cls);
    }
    const form = panel.querySelector("form")!;
    expect(form.className).toContain("pb-[max(0.75rem,env(safe-area-inset-bottom))]");
    expect(screen.getByLabelText("Your message").className).toContain("text-base");   // no iOS zoom on focus
    const minimize = screen.getByRole("button", { name: "Minimize" }).className.split(/\s+/);
    expect(minimize).toContain("hidden");               // phones: the sheet is closed, not minimized
    expect(minimize).toContain("sm:inline-flex");
  });
});

describe("opening the assistant from other places", () => {
  it("openChat() opens the panel with the question prefilled but not sent", async () => {
    renderWithIntl(<ChatWidget />);
    expect(screen.queryByTestId("chat-panel")).toBeNull();
    act(() => openChat("About “Visa and Stay”: "));
    expect(await screen.findByTestId("chat-panel")).toBeInTheDocument();
    expect(screen.getByLabelText("Your message")).toHaveValue("About “Visa and Stay”: ");
    expect(postStream).not.toHaveBeenCalled();
  });

  it("?ask= (the old /assistant?q= links) opens the chat with the question and cleans the address bar", async () => {
    window.history.replaceState(null, "", "/?ask=How%20do%20I%20extend%20my%20visa%3F#chat");
    renderWithIntl(<ChatWidget />);
    expect(await screen.findByLabelText("Your message")).toHaveValue("How do I extend my visa?");
    expect(window.location.search).toBe("");
    expect(window.location.hash).toBe("#chat");
    window.history.replaceState(null, "", "/");
  });
});

describe("ChatWidget on phones", () => {
  const setPhone = (phone: boolean) => {
    window.matchMedia = vi.fn().mockImplementation((q: string) => ({ matches: phone && q.includes("max-width"), media: q,
      addEventListener: vi.fn(), removeEventListener: vi.fn(), addListener: vi.fn(), removeListener: vi.fn(),
      onchange: null, dispatchEvent: vi.fn() })) as unknown as typeof window.matchMedia;
  };
  const announcementCitation = { ...citation, document_title: "Illegal work notice", source_url: null,
    link: { kind: "announcement", href: "/announcements/a1" } };

  async function answerWithSource() {
    postStream.mockResolvedValue({ answer: "Do not work without a permit [1].", language: "en",
      citations: [announcementCitation], metadata: { answer_generation: "llm", offer_handoff: false } });
    renderWithIntl(<ChatWidget />);
    const user = userEvent.setup();
    await user.click(screen.getByTestId("chat-launcher"));
    await user.type(screen.getByLabelText("Your message"), "Can I work?{Enter}");
    const link = await screen.findByRole("link", { name: "Illegal work notice" });
    expect(link).toHaveAttribute("href", "/announcements/a1");
    link.addEventListener("click", (e) => e.preventDefault());        // jsdom: no real navigation
    await user.click(link);
    return user;
  }

  it("closes the full-screen chat when a source is opened, and keeps the conversation", async () => {
    setPhone(true);
    const user = await answerWithSource();
    expect(screen.queryByRole("dialog", { name: "SCH Assistant" })).toBeNull();
    await user.click(screen.getByTestId("chat-launcher"));
    expect(screen.getAllByText(/Do not work without a permit/).length).toBeGreaterThan(0);
  });

  it("keeps the chat open beside the page on wider screens", async () => {
    setPhone(false);
    await answerWithSource();
    expect(screen.getByRole("dialog", { name: "SCH Assistant" })).toBeInTheDocument();
  });
});


describe("AI assistant launcher", () => {
  it("says it is an AI assistant and introduces itself in a bubble at intervals, a few times per visit", async () => {
    vi.useFakeTimers();
    try {
      const { NUDGE } = await import("@/features/chatbot/chat-widget");
      renderWithIntl(<ChatWidget />);
      expect(screen.getByTestId("chat-launcher")).toHaveTextContent("AI assistant");
      expect(screen.queryByTestId("assistant-nudge")).toBeNull();
      act(() => { vi.advanceTimersByTime(NUDGE.firstMs); });
      expect(screen.getByTestId("assistant-nudge")).toHaveTextContent("I'm the SCH AI assistant");
      act(() => { vi.advanceTimersByTime(NUDGE.showMs); });
      expect(screen.queryByTestId("assistant-nudge")).toBeNull();
      act(() => { vi.advanceTimersByTime(NUDGE.everyMs - NUDGE.showMs); });
      expect(screen.getByTestId("assistant-nudge")).toHaveTextContent("visas, dormitories or scholarships");
      // closing a bubble stops it for the rest of the visit
      act(() => { screen.getByTestId("assistant-nudge-close").click(); });
      act(() => { vi.advanceTimersByTime(NUDGE.everyMs * 3); });
      expect(screen.queryByTestId("assistant-nudge")).toBeNull();
      expect(sessionStorage.getItem("sch-assistant-nudge")).toBe("done");
    } finally {
      vi.useRealTimers();
    }
  });

  it("stops after the per-visit maximum and opens the chat when the bubble is clicked", async () => {
    vi.useFakeTimers();
    try {
      const { NUDGE } = await import("@/features/chatbot/chat-widget");
      renderWithIntl(<ChatWidget />);
      let seen = 0;
      act(() => { vi.advanceTimersByTime(NUDGE.firstMs); });
      for (let i = 0; i < NUDGE.maxPerSession + 2; i++) {
        if (screen.queryByTestId("assistant-nudge")) seen += 1;
        act(() => { vi.advanceTimersByTime(NUDGE.everyMs); });
      }
      expect(seen).toBe(NUDGE.maxPerSession);
    } finally {
      vi.useRealTimers();
    }
    sessionStorage.clear();
    vi.useFakeTimers();
    try {
      const { NUDGE } = await import("@/features/chatbot/chat-widget");
      renderWithIntl(<ChatWidget />);
      act(() => { vi.advanceTimersByTime(NUDGE.firstMs); });
      act(() => { screen.getAllByTestId("assistant-nudge")[0].querySelector("button")!.click(); });
      expect(screen.getByRole("dialog")).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });
});
