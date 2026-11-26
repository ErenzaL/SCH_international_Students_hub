import { describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithIntl } from "@/test/utils";
import type { AiUsage } from "@/features/admin/settings/ai-usage";

const get = vi.fn();
const post = vi.fn();
vi.mock("@/lib/api", async (orig) => {
  const mod = await orig<typeof import("@/lib/api")>();
  return { ...mod, api: { ...mod.api, get: (...a: unknown[]) => get(...a), post: (...a: unknown[]) => post(...a) } };
});

import { AiUsageCard } from "@/features/admin/settings/ai-usage";

const usage = (stopped: boolean): AiUsage => ({
  provider: "gemini",
  usage: { prices_configured: ["gemini-3.6-flash"], price_errors: [], by_purpose: {} },
  daily_budget: { global_limit: 1500, global_generated: 3, global_used_all_processes: 41, persistent: true, persist_error: null },
  background_budget: { attempts_today: 2, attempts_today_all_processes: 7, daily_attempt_limit: 150, persistent: true, persist_error: null },
  background_controls: { stopped, stop_from_env: false, flags_available: true, daily_usd_limit: 0.5, estimated_spend_today_usd: 0.0123,
    unpriced_attempts_today: 0, model: "gemini-3.6-flash", model_priced: true },
  daily: { available: true, totals: [
    { day: "2026-11-27", lane: "chat", attempts: 41, failed: 1, input_tokens: 200000, output_tokens: 12000, est_cost_usd: 0.195, fully_priced: true },
    { day: "2026-11-27", lane: "background", attempts: 7, failed: 0, input_tokens: 9000, output_tokens: 3000, est_cost_usd: 0, fully_priced: false },
  ] },
});

describe("AiUsageCard", () => {
  it("shows budgets across processes, estimated cost only where priced, and stops background AI after confirmation", async () => {
    get.mockResolvedValue(usage(false));
    post.mockResolvedValue({ stopped: true });
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    renderWithIntl(<AiUsageCard />);
    expect(await screen.findByTestId("chat-budget")).toHaveTextContent("41 / 1500");
    expect(screen.getByTestId("background-budget")).toHaveTextContent("7 / 150");
    expect(screen.getByTestId("budget-persistence")).toHaveTextContent(/stored in the database/);
    expect(screen.getByTestId("usage-days")).toHaveTextContent("$0.1950");
    expect(screen.getByTestId("usage-days")).toHaveTextContent("unknown");          // an unpriced day is never "$0"
    expect(screen.getByTestId("background-stop")).toHaveTextContent("$0.0123 of the $0.50 USD limit");
    get.mockResolvedValue(usage(true));
    await userEvent.setup().click(screen.getByTestId("stop-background"));
    expect(confirm).toHaveBeenCalled();
    expect(post).toHaveBeenCalledWith("/api/v1/admin/system/ai-background-stop", { stop: true });
    expect(await screen.findByTestId("resume-background")).toBeInTheDocument();
  });

  it("does nothing when the stop is not confirmed", async () => {
    get.mockResolvedValue(usage(false));
    post.mockReset();
    vi.spyOn(window, "confirm").mockReturnValue(false);
    renderWithIntl(<AiUsageCard />);
    await userEvent.setup().click(await screen.findByTestId("stop-background"));
    expect(post).not.toHaveBeenCalled();
  });
});
