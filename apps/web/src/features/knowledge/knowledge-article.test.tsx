import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithIntl } from "@/test/utils";
import type { KnowledgeDocumentDetail } from "@/types/api";

const get = vi.fn();
vi.mock("@/lib/api", async (orig) => {
  const mod = await orig<typeof import("@/lib/api")>();
  return { ...mod, api: { ...mod.api, get: (...a: unknown[]) => get(...a) } };
});

import { KnowledgeArticle } from "@/features/knowledge/knowledge-article";
import { OPEN_CHAT_EVENT } from "@/features/chatbot/open-chat";

const base: KnowledgeDocumentDetail = {
  id: "d1", title: "Visa and Stay", category: "visa-immigration", organization: "NIIED", scope: "national",
  authority_type: "official_government", language: "en", source_url: "https://www.studyinkorea.go.kr/v",
  source_published_at: null, verified_at: "2026-11-01T00:00:00Z", excerpt: "", content: "# Visa and Stay\n\nKeep your status valid.",
  version_id: "v1", version_number: 3, verified_languages: ["id"], translation: null,
};

function respond(lang: string): KnowledgeDocumentDetail {
  if (lang === "id") {
    return { ...base, translation: { status: "verified", language: "id", title: "Visa dan Izin Tinggal",
      content: "# Visa dan Izin Tinggal\n\nJaga status izin tinggal Anda.", headings: ["Visa dan Izin Tinggal"],
      reviewed_at: "2026-11-20T00:00:00Z", generated_at: null, source_version_number: 3 } };
  }
  if (lang === "zh-CN") {
    return { ...base, translation: { status: "machine", language: "zh-CN", title: "签证与居留", content: "# 签证与居留\n\n保持身份有效。",
      headings: [], reviewed_at: null, generated_at: "2026-11-21T00:00:00Z", source_version_number: 3 } };
  }
  return base;
}

beforeEach(() => {
  get.mockReset();
  get.mockImplementation(async (_path: string, q: { lang: string }) => respond(q.lang));
});

describe("KnowledgeArticle (multilingual)", () => {
  it("shows the approved Indonesian translation for an Indonesian reader, with the official source", async () => {
    renderWithIntl(<KnowledgeArticle id="d1" />, "id");
    expect(await screen.findByRole("heading", { level: 1, name: "Visa dan Izin Tinggal" })).toBeInTheDocument();
    expect(get).toHaveBeenCalledWith("/api/v1/knowledge/documents/d1", { lang: "id" });
    expect(screen.getAllByText("Verified translation").length).toBeGreaterThan(0);
    expect(screen.getByText(/reviewed by an SCH Global Supporter/)).toBeInTheDocument();
    expect(within(screen.getByTestId("article-body")).getByText("Jaga status izin tinggal Anda.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /studyinkorea\.go\.kr/ })).toHaveAttribute("href", "https://www.studyinkorea.go.kr/v");
    expect(screen.getByText("Original title: Visa and Stay")).toBeInTheDocument();
    // View original
    await userEvent.setup().click(screen.getByRole("button", { name: /View original/ }));
    expect(screen.getByRole("heading", { level: 1, name: "Visa and Stay" })).toBeInTheDocument();
    expect(screen.getByTestId("article-body")).toHaveAttribute("lang", "en");
  });

  it("falls back to the original when Vietnamese has no approved translation (switching never touches the profile)", async () => {
    renderWithIntl(<KnowledgeArticle id="d1" />, "id");
    await screen.findByRole("heading", { level: 1, name: "Visa dan Izin Tinggal" });
    await userEvent.setup().selectOptions(screen.getByLabelText(/Read in/), "vi");
    expect(await screen.findByText(/No verified Tiếng Việt translation yet|No verified .* translation yet/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "Visa and Stay" })).toBeInTheDocument();
    expect(get).toHaveBeenLastCalledWith("/api/v1/knowledge/documents/d1", { lang: "vi" });
  });

  it("shows the English original in English without translation notices", async () => {
    renderWithIntl(<KnowledgeArticle id="d1" />, "en");
    expect(await screen.findByRole("heading", { level: 1, name: "Visa and Stay" })).toBeInTheDocument();
    expect(screen.queryByText(/No verified/)).not.toBeInTheDocument();
    expect(screen.queryByText("Verified translation")).not.toBeInTheDocument();
  });

  it("labels an unreviewed machine translation clearly and never as verified", async () => {
    renderWithIntl(<KnowledgeArticle id="d1" />, "zh-CN");
    expect(await screen.findByRole("heading", { level: 1, name: "签证与居留" })).toBeInTheDocument();
    expect(screen.getAllByText("Machine translation – not reviewed").length).toBeGreaterThan(0);
    expect(screen.queryByText("Verified translation")).not.toBeInTheDocument();
  });

  it("“Ask the assistant about this” opens the floating chatbot with the document as context", async () => {
    const seen: (string | undefined)[] = [];
    const onOpen = (e: Event) => seen.push((e as CustomEvent<{ question?: string }>).detail.question);
    window.addEventListener(OPEN_CHAT_EVENT, onOpen);
    renderWithIntl(<KnowledgeArticle id="d1" />, "id");
    await screen.findByRole("heading", { level: 1, name: "Visa dan Izin Tinggal" });
    await userEvent.setup().click(screen.getByTestId("ask-about-document"));
    window.removeEventListener(OPEN_CHAT_EVENT, onOpen);
    expect(seen).toEqual(["About “Visa dan Izin Tinggal”: "]);
  });
});
