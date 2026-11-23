import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithIntl } from "@/test/utils";
import ko from "@/messages/ko.json";

/**
 * AI Office Phase 2 - the Tasks tab and agent states, against a fake backend that answers like
 * app/api/agents.py. Everything shown comes from the backend responses.
 */
const session = { ready: true, userId: null as string | null, email: null };
vi.mock("@/lib/use-session", () => ({ useSession: () => session }));
vi.mock("next/navigation", () => ({ usePathname: () => "/ai-office", useRouter: () => ({ refresh: vi.fn(), push: vi.fn() }) }));
const postStream = vi.fn();
vi.mock("@/lib/chat-stream", () => ({ postStream: (...a: unknown[]) => postStream(...a) }));
let token: string | null = null;
vi.mock("@/lib/supabase/client", () => ({ getAccessToken: async () => token, getSupabaseBrowserClient: () => null }));

type Call = { method: string; path: string; body?: unknown; auth?: boolean; query?: Record<string, unknown> };
const calls: Call[] = [];
let backend: (c: Call) => unknown = () => ({});
vi.mock("@/lib/api", async (orig) => {
  const mod = await orig<typeof import("@/lib/api")>();
  const handle = async (c: Call) => {
    calls.push(c);
    const out = backend(c);
    if (out instanceof mod.ApiError) throw out;
    return out;
  };
  return {
    ...mod,
    apiRequest: (method: string, path: string, opts: { body?: unknown; auth?: boolean } = {}) =>
      handle({ method, path, body: opts.body, auth: opts.auth }),
    api: {
      ...mod.api,
      get: (path: string, query?: Record<string, unknown>, opts?: { auth?: boolean }) =>
        handle({ method: "GET", path, query, auth: opts?.auth }),
      post: (path: string, body?: unknown, opts?: { auth?: boolean }) => handle({ method: "POST", path, body, auth: opts?.auth }),
    },
  };
});

import { ApiError } from "@/lib/api";
import { AiOffice } from "@/features/ai-office/ai-office";

const size = { w: 1440, h: 900 };
beforeAll(() => {
  Object.defineProperty(HTMLElement.prototype, "clientWidth", { configurable: true, get: () => size.w });
  Object.defineProperty(HTMLElement.prototype, "clientHeight", { configurable: true, get: () => size.h });
});
afterAll(() => {
  delete (HTMLElement.prototype as unknown as Record<string, unknown>).clientWidth;
  delete (HTMLElement.prototype as unknown as Record<string, unknown>).clientHeight;
});

const tool = (name: string, extra: object = {}) => ({ name, available: true, unavailable_reason: null, requires_sign_in: false,
  background: false, uses_ai: false, needs_approval: false, ...extra });
const agent = (id: string, character_id: string, name: string, extra: object = {}) => ({
  id, character_id, name, department: "", languages: ["ko", "en"], fixed_language: null, task_types: [], can_delegate_to: [],
  restricted_actions: ["eligibility_decisions"], actions: [], monitoring: false, state: "idle", active: 0, awaiting: 0,
  tools: [tool("rag_search")], ...extra });

const agents = () => [
  agent("reception", "reception", "Hana", { can_delegate_to: ["scholarship"] }),
  agent("scholarship", "opportunities", "Leo", {
    actions: [{ id: "find_scholarships", kind: "tool", target: "scholarship_search", params: {} },
      { id: "scan_sources", kind: "task", target: "scholarship_scan", params: {} }],
    tools: [tool("scholarship_search"), tool("official_web_search", { available: false, unavailable_reason: "No web search provider" })],
    restricted_actions: ["eligibility_decisions", "scholarship_eligibility"] }),
  agent("events", "events", "Mia", { state: "working", active: 1 }),
  agent("immigration", "visa", "Yuna", { state: "waiting", awaiting: 1 }),
  agent("support-coordinator", "supporter-lead", "Sumin"),
];

const scholarshipResult = { tool: "scholarship_search", count: 1, notes: ["eligibility_office"], items: [
  { kind: "announcement", id: "a1", title: "2027 Global scholarship", href: "/announcements/a1", deadline: "2027-01-10",
    status: "active", reliability: "verified", excerpt: "Apply online" }] };

beforeEach(() => {
  calls.length = 0;
  token = null;
  postStream.mockReset();
  sessionStorage.clear();
  localStorage.clear();
  backend = (c) => {
    if (c.path === "/api/v1/agents") return { items: agents(), signed_in: token !== null };
    if (c.path === "/api/v1/agents/scholarship/tools") return { route: "tool", handled_by: "scholarship", result: scholarshipResult };
    if (c.path.startsWith("/api/v1/announcements") || c.path.startsWith("/api/v1/knowledge")) return { items: [], total: 0 };
    return {};
  };
});

async function openTasks(characterId: string) {
  const user = userEvent.setup();
  await user.click(screen.getByTestId(`character-${characterId}`));
  const panel = await screen.findByTestId("office-panel");
  await user.click(within(panel).getByTestId("tab-work"));
  await within(panel).findByTestId("agent-work");
  return { user, panel };
}

describe("AI Office agents (Phase 2)", () => {
  it("shows backend-owned states on the characters", async () => {
    renderWithIntl(<AiOffice />);
    const badge = await screen.findByTestId("state-events");
    expect(within(badge).getByTestId("agent-state")).toHaveAttribute("data-state", "working");
    expect(within(screen.getByTestId("state-visa")).getByTestId("agent-state")).toHaveAttribute("title", "Waiting for you");
    expect(screen.queryByTestId("state-reception")).toBeNull();                       // idle: no badge
    expect(screen.getByTestId("character-events")).toHaveAccessibleName(expect.stringContaining("Working"));
    expect(document.querySelector('[data-actor="events"]')).toHaveAttribute("data-state", "working");
  });

  it("runs a quick tool and shows sources with reliability labels and notes", async () => {
    renderWithIntl(<AiOffice />);
    await screen.findByTestId("state-events");
    const { user, panel } = await openTasks("opportunities");
    expect(within(panel).getByTestId("agent-work")).toHaveAttribute("data-agent", "scholarship");
    // background tasks need sign-in: the button is disabled for visitors
    expect(within(panel).getByTestId("action-scan_sources")).toBeDisabled();
    await user.click(within(panel).getByTestId("action-find_scholarships"));
    const result = await within(panel).findByTestId("agent-result");
    const link = within(result).getByRole("link", { name: "2027 Global scholarship" });
    expect(link).toHaveAttribute("href", "/announcements/a1");
    expect(within(result).getByTestId("reliability")).toHaveTextContent("Approved source");
    expect(result.textContent).toContain("only the scholarship office can confirm");
    const call = calls.find((c) => c.path === "/api/v1/agents/scholarship/tools");
    expect(call?.body).toMatchObject({ tool: "scholarship_search", params: {} });
  });

  it("lists tools honestly, including unavailable ones, and what the agent never does", async () => {
    renderWithIntl(<AiOffice />);
    await screen.findByTestId("state-events");
    const { panel } = await openTasks("opportunities");
    const tools = within(panel).getByTestId("agent-tools");
    expect(tools.querySelector('[data-tool="official_web_search"]')).toHaveAttribute("data-available", "false");
    expect(tools.textContent).toContain("not available");
    expect(tools.textContent).toContain("decide whether you qualify for a scholarship");
  });

  it("routes a free-text request: redirect to the right desk, or answer in the chat", async () => {
    backend = ((prev) => (c: Call) => {
      if (c.path === "/api/v1/agents/scholarship/requests") {
        const m = (c.body as { message: string }).message;
        return m.includes("visa")
          ? { route: "redirect", agent_id: "scholarship", suggested_agent: "immigration", suggested_character: "visa" }
          : { route: "answer", agent_id: "scholarship", language: "en" };
      }
      return prev(c);
    })(backend);
    postStream.mockResolvedValue({ answer: "ok", language: "en", citations: [], metadata: { answer_generation: "llm" } });
    renderWithIntl(<AiOffice />);
    await screen.findByTestId("state-events");
    const { user, panel } = await openTasks("opportunities");
    await user.type(within(panel).getByTestId("agent-request-input"), "How do I extend my visa?");
    await user.click(within(panel).getByTestId("agent-request-send"));
    const redirect = await within(panel).findByTestId("agent-redirect");
    expect(redirect.textContent).toContain("This is Yuna's job.");
    await user.click(within(redirect).getByRole("button", { name: "Go to Yuna" }));
    await waitFor(() => expect(screen.getByTestId("office-panel")).toHaveTextContent("Yuna"));

    const again = await openTasks("opportunities");
    await again.user.type(within(again.panel).getByTestId("agent-request-input"), "What documents do scholarships need?");
    await again.user.click(within(again.panel).getByTestId("agent-request-send"));
    await waitFor(() => expect(postStream).toHaveBeenCalled());
    expect(postStream.mock.calls[0][1]).toMatchObject({ message: "What documents do scholarships need?" });
    expect(within(again.panel).getByTestId("tab-chat")).toHaveAttribute("aria-selected", "true");
  });

  it("a signed-in student confirms a support request; nothing is sent before that", async () => {
    token = "tok";
    let status = "awaiting_approval";
    const task = () => ({ id: "t1", agent_id: "support-coordinator", agent_name: "Sumin", task_type: "support_request", status,
      stage: status, params: { subject: "Housing help", summary: "I need help with my dormitory contract" }, output: status === "completed"
        ? { tool: "create_support_request", count: 1, notes: [], items: [{ kind: "ticket", id: "k1", ticket_number: 42, status: "waiting",
          title: "Housing help", href: "/support/requests/k1", reliability: "verified" }], provenance: { generated_by: "deterministic" } }
        : null,
      error_code: null, attempts: 1, created_at: "2026-11-24T00:00:00Z", completed_at: null,
      events: [{ id: 1, agent_id: "support-coordinator", step: "approval", tool: null, data: {}, created_at: "2026-11-24T00:00:00Z" }],
      children: [] });
    backend = ((prev) => (c: Call) => {
      if (c.path === "/api/v1/agent-tasks" && c.method === "GET") return { items: [task()] };
      if (c.path === "/api/v1/agent-tasks/t1" && c.method === "GET") return task();
      if (c.path === "/api/v1/agent-tasks/t1/decision") {
        status = "completed";
        return task();
      }
      return prev(c);
    })(backend);
    renderWithIntl(<AiOffice />);
    await screen.findByTestId("state-events");
    const { user, panel } = await openTasks("supporter-lead");
    const card = await within(panel).findByTestId("agent-task");
    expect(card).toHaveAttribute("data-status", "awaiting_approval");
    const approval = within(card).getByTestId("approval");
    expect(approval.textContent).toContain("Housing help");
    expect(calls.some((c) => c.path.endsWith("/decision"))).toBe(false);
    await user.click(within(approval).getByTestId("approve"));
    await waitFor(() => expect(within(panel).getByTestId("agent-task")).toHaveAttribute("data-status", "completed"));
    const decision = calls.find((c) => c.path === "/api/v1/agent-tasks/t1/decision");
    expect(decision?.body).toEqual({ approve: true });
    expect(decision?.auth).toBe(true);
    expect(within(panel).getByRole("link", { name: "Housing help" })).toHaveAttribute("href", "/support/requests/k1");
    expect(panel.textContent).toContain("Found in the Hub's published content (no AI).");
  });

  it("shows backend errors in the student's language", async () => {
    backend = ((prev) => (c: Call) => {
      if (c.path === "/api/v1/agents/scholarship/tools") {
        return new ApiError({ status: 429, code: "rate_limited", message: "Too many requests." });
      }
      return prev(c);
    })(backend);
    renderWithIntl(<AiOffice />, "ko", ko);
    await screen.findByTestId("state-events");
    const { user, panel } = await openTasks("opportunities");
    expect(within(panel).getByTestId("tab-work")).toHaveTextContent("작업");
    await user.click(within(panel).getByTestId("action-find_scholarships"));
    expect(await within(panel).findByTestId("agent-error")).toHaveTextContent("요청이 너무 많아요");
  });

  it("keeps the office usable when the agent service is unreachable", async () => {
    backend = ((prev) => (c: Call) => {
      if (c.path === "/api/v1/agents") return new ApiError({ status: 0, code: "network_error", message: "down", kind: "network" });
      return prev(c);
    })(backend);
    renderWithIntl(<AiOffice />);
    const user = userEvent.setup();
    await user.click(screen.getByTestId("character-opportunities"));
    const panel = await screen.findByTestId("office-panel");
    await user.click(within(panel).getByTestId("tab-work"));
    expect(within(panel).getByTestId("agent-unavailable")).toBeInTheDocument();
    expect(screen.queryByTestId("state-events")).toBeNull();
    await user.click(within(panel).getByTestId("tab-chat"));
    expect(within(panel).getByTestId("tab-chat")).toHaveAttribute("aria-selected", "true");
  });
});
