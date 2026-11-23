import { describe, expect, it, vi as vitest } from "vitest";
import userEvent from "@testing-library/user-event";
import { screen } from "@testing-library/react";
import { renderWithIntl } from "@/test/utils";
import { ApiError } from "@/lib/api";
import { ChatMessageView } from "@/features/chatbot/chat-message";
import { chatError } from "@/features/chatbot/chat-widget";
import en from "@/messages/en.json";
import ko from "@/messages/ko.json";
import id from "@/messages/id.json";
import vi from "@/messages/vi.json";
import zh from "@/messages/zh-CN.json";

const source = (n: number, cited = true) => ({
  n, document_id: `d${n}`, version_id: "v", chunk_id: `c${n}`, chunk_ids: [`c${n}`], document_title: `Guide ${n}`,
  heading: null, source_url: `https://www.hikorea.go.kr/${n}`, organization: "Immigration", authority_type: "official_government" as const,
  verified_at: null, is_stale: false, page: null, cited,
});

describe("ChatMessageView", () => {
  it("renders citations as small numbered links and lists each cited source once", () => {
    renderWithIntl(<ChatMessageView m={{ id: "a1",
      role: "assistant", content: "Bring your passport [1] and residence card [1][2].",
      citations: [source(1), source(2), source(3, false)], metadata: { answer_generation: "llm" },
    }} />);
    const links = screen.getAllByRole("link", { name: /Source 1/ });
    expect(links[0]).toHaveTextContent(/^1$/);                       // no raw "[1]" brackets
    expect(links[0]).toHaveAttribute("href", "/knowledge/d1");
    expect(screen.queryByText(/\[1\]/)).not.toBeInTheDocument();
    const list = screen.getByRole("list", { name: "Sources" });
    expect(list.querySelectorAll("li")).toHaveLength(2);              // uncited source 3 is not listed
    expect(screen.getByRole("link", { name: "Guide 1" })).toHaveAttribute("href", "/knowledge/d1");
  });
});

describe("Sources section", () => {
  it("shows one compact Sources section with each document once, and no markers in plain answers", () => {
    const passage = (n: number, doc: string) => ({ ...source(n), document_id: doc, document_title: `Guide ${doc}` });
    renderWithIntl(<ChatMessageView m={{ id: "a2", role: "assistant",
      content: "To extend your D-2 visa, you'll need:\n\n1. Passport\n2. Certificate of enrollment",
      citations: [passage(1, "d2"), passage(2, "d2"), passage(3, "x")], metadata: { answer_generation: "llm" },
    }} />);
    const sections = screen.getAllByTestId("answer-sources");
    expect(sections).toHaveLength(1);
    expect(sections[0]).toHaveTextContent(/^Sources/);
    expect(screen.getAllByRole("link", { name: "Guide d2" })).toHaveLength(1);     // same document listed once
    expect(screen.getByTestId("assistant-answer")).not.toHaveTextContent(/\[\d\]/);
  });
});

describe("chatError", () => {
  const tr = (msgs: { chatbot: { errors: Record<string, string> } }) => (key: string) =>
    msgs.chatbot.errors[key.replace("errors.", "")] ?? key;

  it("maps API error codes to friendly text in every language", () => {
    const limit = new ApiError({ status: 429, code: "daily_limit", message: "server english" });
    for (const m of [en, ko, id, vi, zh]) {
      expect(chatError(limit, tr(m))).toBe(m.chatbot.errors.dailyLimit);
    }
    expect(chatError(new ApiError({ status: 429, code: "rate_limited", message: "x" }), tr(ko))).toBe(ko.chatbot.errors.rateLimited);
    expect(chatError(new ApiError({ status: 0, code: "stream_interrupted", message: "x" }), tr(vi))).toBe(vi.chatbot.errors.network);
    expect(chatError(new ApiError({ status: 500, code: "internal_error", message: "x" }), tr(zh))).toBe(zh.chatbot.errors.generic);
    expect(chatError(new ApiError({ status: 422, code: "validation_error", message: "Message too long" }), tr(en)))
      .toBe("Message too long");
  });
});

describe("citation navigation", () => {
  const withLink = (n: number, link: { kind: "document" | "announcement" | "external"; href: string; page?: number | null },
    extra: Record<string, unknown> = {}) => ({ ...source(n), document_title: `Doc ${n}`, link, ...extra });

  it("opens each source type at the right place", () => {
    renderWithIntl(<ChatMessageView m={{ id: "a3", role: "assistant",
      content: "See [1], [2] and [3].", metadata: { answer_generation: "llm" },
      citations: [
        withLink(1, { kind: "document", href: "/knowledge/d1?page=40", page: 40 }, { source_type: "pdf" }),
        withLink(2, { kind: "announcement", href: "/announcements/a9" }),
        withLink(3, { kind: "external", href: "https://www.hikorea.go.kr/3" }, { source_type: "website" }),
      ] }} />);
    expect(screen.getByRole("link", { name: "Source 1" })).toHaveAttribute("href", "/knowledge/d1?page=40");
    expect(screen.getByRole("link", { name: "Doc 1" })).toHaveAttribute("href", "/knowledge/d1?page=40");
    const ann = screen.getByRole("link", { name: "Doc 2" });
    expect(ann).toHaveAttribute("href", "/announcements/a9");
    expect(ann).not.toHaveAttribute("target");
    const ext = screen.getByRole("link", { name: "Doc 3" });
    expect(ext).toHaveAttribute("href", "https://www.hikorea.go.kr/3");
    expect(ext).toHaveAttribute("target", "_blank");
    expect(ext).toHaveAttribute("rel", "noopener noreferrer");
    // the official-source icon is not repeated for a source whose title already opens that URL
    expect(screen.getAllByRole("link", { name: "Open the official source" })).toHaveLength(2);
  });

  it("keeps the old behaviour for messages stored before links existed and ignores unsafe URLs", () => {
    renderWithIntl(<ChatMessageView m={{ id: "a4", role: "assistant", content: "Old [1] and [2].",
      metadata: { answer_generation: "llm" },
      citations: [source(1), { ...source(2), document_id: null, source_url: "javascript:alert(1)", document_title: "Bad" }] }} />);
    expect(screen.getByRole("link", { name: "Source 1" })).toHaveAttribute("href", "/knowledge/d1");
    expect(screen.queryByRole("link", { name: "Source 2" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Bad" })).toBeNull();
  });

  it("reports internal navigation (so the phone layout can close the chat) but not external links", async () => {
    const onNavigate = vitest.fn();
    renderWithIntl(<ChatMessageView onNavigate={onNavigate} m={{ id: "a5", role: "assistant", content: "A [1] B [2].",
      metadata: { answer_generation: "llm" },
      citations: [withLink(1, { kind: "announcement", href: "/announcements/a1" }),
        withLink(2, { kind: "external", href: "https://www.hikorea.go.kr/2" })] }} />);
    const user = userEvent.setup();
    const ext = screen.getByRole("link", { name: "Source 2" });
    ext.addEventListener("click", (e) => e.preventDefault());
    await user.click(ext);
    expect(onNavigate).not.toHaveBeenCalled();
    const internal = screen.getByRole("link", { name: "Source 1" });
    internal.addEventListener("click", (e) => e.preventDefault());
    await user.click(internal);
    expect(onNavigate).toHaveBeenCalledTimes(1);
  });
});
