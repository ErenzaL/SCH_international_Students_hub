import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithIntl } from "@/test/utils";
import type { AgentInfo } from "@/features/ai-office/agent-api";

const calls: { path: string; body?: Record<string, unknown> }[] = [];
let results: Record<string, unknown> = {};
let monitoring: Record<string, unknown> = {};
vi.mock("@/lib/supabase/client", () => ({ getAccessToken: async () => "tok", getSupabaseBrowserClient: () => null }));
vi.mock("@/lib/api", async (orig) => {
  const mod = await orig<typeof import("@/lib/api")>();
  const handle = async (path: string, body?: Record<string, unknown>) => {
    calls.push({ path, body });
    if (path.endsWith("/monitoring")) return monitoring;
    if (path.endsWith("/tools")) return { result: results[String(body?.tool)], handled_by: "x" };
    return { items: [], total: 0 };
  };
  return { ...mod, apiRequest: (_m: string, path: string, o: { body?: Record<string, unknown> } = {}) => handle(path, o.body),
    api: { ...mod.api, get: (p: string) => handle(p), post: (p: string, b?: Record<string, unknown>) => handle(p, b) } };
});
const agent = { id: "supporter-vi", name: "Minh", tools: [{ name: "request_translation_draft", available: true }], actions: [{ id: "check_official_sources", kind: "task", target: "guidance_discovery", params: {}, admin_only: true }],
  interface: { task_actions: ["check_official_sources"], tabs: [] }, state: "idle", monitoring_check_running: false } as unknown as AgentInfo;
let ws: Record<string, unknown> = {};
vi.mock("@/features/ai-office/workspace/context", () => ({ useWorkspace: () => ws }));

import { QueueWorkspace, TermsWorkspace } from "@/features/ai-office/workspace/staff";
import { UpdatesWorkspace } from "@/features/ai-office/workspace/updates";

beforeEach(() => {
  calls.length = 0;
  ws = { agent, agents: [agent], c: { name: "Minh", role: "supporter" }, signedIn: true, isAdmin: false, language: "vi", onChanged: () => {}, openTab: () => {}, onAnswerInChat: () => {}, onSelect: () => {}, ask: () => {} };
});

describe("supporter desks", () => {
  it("shows terms in the other languages and says that the list is a draft", async () => {
    results = { terminology_lookup: { tool: "terminology_lookup", items: [{ kind: "term", title: "외국인등록증", terms: { ko: "외국인등록증", en: "residence card (ARC)", id: "kartu", vi: "thẻ", "zh-CN": "登录证" } }], count: 1, notes: ["terms_draft"] } };
    renderWithIntl(<TermsWorkspace />);
    expect(screen.getByTestId("terms-search")).toBeDisabled();
    await userEvent.type(screen.getByTestId("terms-input"), "residence card");
    await userEvent.click(screen.getByTestId("terms-search"));
    expect(await screen.findByText("residence card (ARC)")).toBeInTheDocument();
    expect(screen.getByText(/Draft term list/)).toBeInTheDocument();
  });

  it("lists the translations of the language and requests a draft only for tasks nobody started", async () => {
    results = { translation_review_queue: { tool: "q", count: 2, notes: [], counts: { todo: 1, in_review: 1 }, items: [
      { kind: "translation_task", id: "1", title: "Dorm notice", content_kind: "announcement", ref: "a1", status: "todo", href: "/admin/translations/a1/vi" },
      { kind: "translation_task", id: "2", title: "Guide", content_kind: "document", ref: "d1", status: "in_review", href: "/admin/translations/documents/d1/vi" }] },
      request_translation_draft: { tool: "d", count: 1, notes: [], items: [{ kind: "translation_job", id: "j", executor: "gpu" }] } };
    renderWithIntl(<QueueWorkspace />);
    expect(await screen.findAllByTestId("queue-item")).toHaveLength(2);
    expect(screen.getAllByTestId("request-draft")).toHaveLength(1);
    await userEvent.click(screen.getByTestId("request-draft"));
    expect(await screen.findByText(/queued for the university GPU/)).toBeInTheDocument();
    expect(calls.find((c) => c.body?.tool === "request_translation_draft")?.body?.params).toEqual({ announcement_id: "a1" });
  });

  it("offers no machine draft of an announcement where the release does not make one (Vietnamese)", async () => {
    results = { translation_review_queue: { tool: "q", count: 2, notes: [], counts: { todo: 2 }, items: [
      { kind: "translation_task", id: "1", title: "Dorm notice", content_kind: "announcement", ref: "a1", status: "todo", machine_draft: false, href: "/admin/translations/a1/vi" },
      { kind: "translation_task", id: "2", title: "Guide", content_kind: "document", ref: "d1", status: "todo", machine_draft: true, href: "/admin/translations/documents/d1/vi" }] } };
    renderWithIntl(<QueueWorkspace />);
    const items = await screen.findAllByTestId("queue-item");
    expect(within(items[0]).queryByTestId("request-draft")).toBeNull();
    expect(within(items[0]).getByTestId("hand-only")).toHaveTextContent(/Translate by hand/);
    expect(within(items[1]).getByTestId("request-draft")).toBeInTheDocument();
  });

  it("tells a supporter of another language that this is not their queue", async () => {
    results = { translation_review_queue: { tool: "q", count: 0, notes: ["not_your_language"], items: [], counts: {} } };
    renderWithIntl(<QueueWorkspace />);
    expect(await screen.findByText("You are not assigned to this language.")).toBeInTheDocument();
  });

  it("Sumin's staff queue shows numbers, never text", async () => {
    ws = { ...ws, agent: { ...agent, id: "support-coordinator" } };
    results = { support_queue: { tool: "support_queue", count: 1, notes: [], items: [{ kind: "ticket", id: "t", ticket_number: 12, title: "#12", language: "id", priority: "normal", href: "/admin/support" }] } };
    renderWithIntl(<QueueWorkspace />);
    expect(await screen.findByTestId("support-queue-item")).toHaveTextContent("#12");
  });
});

describe("updates of a monitoring desk", () => {
  const base = { agent_id: "immigration", supported: true, schedules: [], checking: false, last_checked_at: null, last_success_at: null };
  it("says honestly that no source is configured and no check ran", async () => {
    monitoring = { ...base, sources: [] };
    results = { official_updates: { tool: "official_updates", items: [], count: 0, notes: ["no_sources"], sources: [] } };
    renderWithIntl(<UpdatesWorkspace />);
    expect(await screen.findByText("No official website is configured for this desk yet.")).toBeInTheDocument();
    expect(screen.getByText("No check has run yet.")).toBeInTheDocument();
    expect(screen.getByTestId("updates-status")).toHaveAttribute("data-checking", "false");
    expect(screen.queryByText("Check official sources now")).toBeNull();
  });

  it("lists reviewed items with their Knowledge Center link and the watched websites", async () => {
    monitoring = { ...base, last_checked_at: "2026-11-25T01:00:00Z", sources: [{ name: "HiKorea", url: "https://www.hikorea.go.kr/x", kind: "page", health: "ok", last_checked_at: null, last_success_at: null }] };
    results = { official_updates: { tool: "official_updates", count: 1, notes: ["official_reviewed"], items: [{ kind: "discovered", id: "i1", title: "Stay extension", href: "/knowledge/d1", reliability: "verified", open_status: "unknown" }] } };
    renderWithIntl(<UpdatesWorkspace />);
    expect((await screen.findByText("Stay extension")).closest("a") ?? screen.getByRole("link", { name: /Stay extension/ })).toHaveAttribute("href", "/knowledge/d1");
    expect(screen.getByRole("link", { name: /HiKorea/ })).toHaveAttribute("href", "https://www.hikorea.go.kr/x");
  });
});
