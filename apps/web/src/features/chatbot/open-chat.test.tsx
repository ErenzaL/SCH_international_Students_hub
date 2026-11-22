import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { OPEN_CHAT_EVENT, OpenChatButton } from "@/features/chatbot/open-chat";

describe("OpenChatButton (homepage, Support page, My requests)", () => {
  it("opens the floating assistant instead of navigating to a separate page", async () => {
    const seen: unknown[] = [];
    const onOpen = (e: Event) => seen.push((e as CustomEvent).detail);
    window.addEventListener(OPEN_CHAT_EVENT, onOpen);
    render(<OpenChatButton>Ask the assistant</OpenChatButton>);
    const btn = screen.getByRole("button", { name: "Ask the assistant" });
    expect(btn.closest("a")).toBeNull();
    await userEvent.setup().click(btn);
    window.removeEventListener(OPEN_CHAT_EVENT, onOpen);
    expect(seen).toEqual([{ question: undefined }]);
  });
});
