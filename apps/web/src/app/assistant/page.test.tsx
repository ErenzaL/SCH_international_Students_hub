import { describe, expect, it, vi } from "vitest";

const redirect = vi.fn((url: string) => {
  throw new Error(`REDIRECT ${url}`);
});
vi.mock("next/navigation", () => ({ redirect: (url: string) => redirect(url) }));

import AssistantPage from "@/app/assistant/page";

describe("/assistant (replaced by the floating SCH Assistant)", () => {
  it("redirects to the homepage with the assistant open", async () => {
    await expect(AssistantPage({ searchParams: Promise.resolve({}) })).rejects.toThrow("REDIRECT /#chat");
  });
  it("keeps a question passed as ?q= for the chat", async () => {
    await expect(AssistantPage({ searchParams: Promise.resolve({ q: "비자 연장 방법?" }) }))
      .rejects.toThrow(`REDIRECT /?ask=${encodeURIComponent("비자 연장 방법?")}#chat`);
  });
});
