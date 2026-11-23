import { describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithIntl } from "@/test/utils";

const post = vi.fn();
vi.mock("@/lib/api", async (orig) => {
  const mod = await orig<typeof import("@/lib/api")>();
  return { ...mod, api: { ...mod.api, post: (...a: unknown[]) => post(...a) } };
});

import { LlmCheckCard } from "@/features/admin/settings/llm-check";

describe("LlmCheckCard", () => {
  it("runs the server-side model check and shows each model's result", async () => {
    post.mockResolvedValue({ provider: "gemini", primary: "gemini-3.8-flash", fallback: "gemini-3.5-flash-lite", probes: [
      { role: "primary", model: "gemini-3.8-flash", call: "generate", ok: false, latency_ms: 210, error: "llm_quota",
        http: 429, status: "RESOURCE_EXHAUSTED", detail: "Quota exceeded ... limit: 0" },
      { role: "fallback", model: "gemini-3.5-flash-lite", call: "stream", ok: true, latency_ms: 900,
        served_by: "gemini-3.5-flash-lite", total_tokens: 12 },
    ] });
    renderWithIntl(<LlmCheckCard />);
    await userEvent.setup().click(screen.getByTestId("llm-check"));
    expect(post).toHaveBeenCalledWith("/api/v1/admin/system/llm-check");
    expect(await screen.findByText("llm_quota")).toBeInTheDocument();
    expect(screen.getByText(/429 · RESOURCE_EXHAUSTED · Quota exceeded/)).toBeInTheDocument();
    expect(screen.getByText("OK")).toBeInTheDocument();
    expect(screen.getByText(/gemini-3.5-flash-lite · 12 tokens/)).toBeInTheDocument();
  });
});
