import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithIntl } from "@/test/utils";
import ko from "@/messages/ko.json";
import zh from "@/messages/zh-CN.json";

/**
 * Character-specific workspaces: every character opens the interface the backend registry chose for it (chat,
 * service, discovery, monitoring, request), with real data from a fake backend that answers like
 * app/api/agents.py. Admin controls are hidden for students (and the endpoints are admin-only on the server).
 */
const session = { ready: true, userId: "u1" as string | null, email: null };
vi.mock("@/lib/use-session", () => ({ useSession: () => session }));
vi.mock("next/navigation", () => ({ usePathname: () => "/ai-office", useRouter: () => ({ refresh: vi.fn(), push: vi.fn() }) }));
const postStream = vi.fn();
vi.mock("@/lib/chat-stream", () => ({ postStream: (...a: unknown[]) => postStream(...a) }));
let token: string | null = "tok";
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
      patch: (path: string, body?: unknown) => handle({ method: "PATCH", path, body, auth: true }),
    },
  };
});

import { AiOffice } from "@/features/ai-office/ai-office";
import { INTERACTIVE } from "@/features/ai-office/characters";
import { splitEvents } from "@/features/ai-office/workspace/events";
import { byDeadline } from "@/features/ai-office/workspace/opportunities";
import { daysUntil } from "@/features/ai-office/workspace/parts";

const size = { w: 1440, h: 900 };
beforeAll(() => {
  Object.defineProperty(HTMLElement.prototype, "clientWidth", { configurable: true, get: () => size.w });
  Object.defineProperty(HTMLElement.prototype, "clientHeight", { configurable: true, get: () => size.h });
});
afterAll(() => {
  delete (HTMLElement.prototype as unknown as Record<string, unknown>).clientWidth;
  delete (HTMLElement.prototype as unknown as Record<string, unknown>).clientHeight;
});

// ------------------------------------------------------------------ fake backend (mirrors the registry)
let role: "visitor" | "student" | "admin" = "student";
const ADMIN_TABS = ["review", "sources"];
const tool = (name: string, extra: object = {}) => ({ name, available: true, unavailable_reason: null, requires_sign_in: false,
  background: false, uses_ai: false, needs_approval: false, ...extra });
type Act = { id: string; kind: "tool" | "task"; target: string; params?: object; admin_only?: boolean };
function agent(id: string, character_id: string, name: string, type: string, view: string, tabs: string[],
  actions: Act[] = [], extra: object = {}) {
  const visible = actions.filter((a) => !a.admin_only || role === "admin").map((a) => ({ params: {}, ...a }));
  const shownTabs = tabs.filter((x) => !ADMIN_TABS.includes(x) || role === "admin");
  return {
    id, character_id, name, department: "", languages: ["ko", "en"], fixed_language: null, task_types: [], can_delegate_to: [],
    restricted_actions: ["eligibility_decisions"], actions: visible, monitoring: false, state: "idle", active: 0, awaiting: 0,
    tools: [tool("rag_search"), tool("official_web_search", { available: false, unavailable_reason: "No web search" })],
    monitoring_check_running: false,
    interface: { type, default_view: view, tabs: shownTabs, capabilities: ["grounded_chat"], task_actions: visible.map((a) => a.id),
      allowed_user_roles: ["visitor", "student"], data_sources: ["published_announcements"] },
    ...extra,
  };
}
let robo: Record<string, unknown> = {};
const directory = () => {
  const chat = ["chat", "work", "about"];
  const items = [
    agent("reception", "reception", "Hana", "CHAT", "chat", ["chat", "work", "desks", "about"]),
    ...[["ko", "Minji"], ["en", "Alex"], ["id", "Sari"], ["vi", "Minh"], ["zh", "Mei"]].map(([l, n]) =>
      agent(`supporter-${l}`, `supporter-${l}`, n, "CHAT", "chat", chat)),
    agent("immigration", "visa", "Yuna", "SERVICE", "checklists", ["checklists", "chat", "guides", "work", "about"], [
      { id: "d2_extension", kind: "tool", target: "visa_checklist", params: { topic: "extension" } },
      { id: "residence_card", kind: "tool", target: "visa_checklist", params: { topic: "residence_card" } }]),
    agent("academic", "academic", "Joon", "SERVICE", "procedures", ["procedures", "notices", "guides", "chat", "work", "about"], [
      { id: "course_registration", kind: "tool", target: "academic_checklist", params: { topic: "registration" } },
      { id: "leave_of_absence", kind: "tool", target: "academic_checklist", params: { topic: "leave" } }]),
    agent("topik", "topik", "Seo", "SERVICE", "topik", ["topik", "guides", "chat", "work", "about"]),
    agent("scholarship", "opportunities", "Leo", "DISCOVERY", "opportunities", ["opportunities", "work", "chat", "about", "review", "sources"], [
      { id: "scan_sources", kind: "task", target: "scholarship_scan" },
      { id: "check_official_sources", kind: "task", target: "opportunity_discovery", admin_only: true }]),
    agent("events", "events", "Mia", "DISCOVERY", "events", ["events", "work", "chat", "about"], [
      { id: "what_changed", kind: "task", target: "event_digest" }]),
    agent("career", "career", "Daniel", "DISCOVERY", "careers", ["careers", "guides", "work", "chat", "about"]),
    { ...agent("announcement", "guide-bot", "Robo", "MONITORING", "monitoring", ["monitoring", "notices", "work", "about", "review", "sources"], [
      { id: "digest", kind: "task", target: "announcement_digest" },
      { id: "check_official_sources", kind: "task", target: "announcement_discovery", admin_only: true }]), ...robo },
    agent("support-coordinator", "supporter-lead", "Sumin", "TASK_WORKSPACE", "request", ["request", "requests", "chat", "about"], [
      { id: "my_requests", kind: "tool", target: "get_support_request_status" }]),
  ];
  return { items, signed_in: role !== "visitor", is_admin: role === "admin" };
};

const ann = (id: string, title: string, extra: object = {}) => ({ id, title, category: "university-announcements", deadline: null,
  event_date: null, published_at: "2026-11-20", status: "active", original_language: "ko", available_languages: ["ko"],
  excerpt: "", is_test_data: false, source: { organization: "SCH", url: "https://sgee.sch.ac.kr/notice/1" }, target_audience: null, ...extra });
const result = (tool: string, items: object[], notes: string[] = []) => ({ result: { tool, items, count: items.length, notes }, handled_by: "x" });
const reviewedItem = { kind: "discovered", id: "r1", title: "2027 Global Korea Summer Camp", href: "/knowledge/doc-camp",
  official_url: "https://www.studyinkorea.go.kr/ko/notice/camp.do", opportunity_kind: "program", open_status: "open",
  next_deadline: "2099-01-10", deadline: "2099-01-10", eligibility: ["international undergraduate students"],
  application_links: [{ url: "https://www.studyinkorea.go.kr/apply", text: "Apply online", kind: "link" }], flags: [],
  reliability: "verified", source_name: "Study in Korea", last_checked_at: "2026-11-24T01:00:00Z" };
const candidate = { ...reviewedItem, id: "c1", title: "UNREVIEWED candidate notice", href: "https://sgee.sch.ac.kr/x",
  official_url: undefined, reliability: "external_unverified", review_status: "candidate" };
const monitoring = (extra: object = {}) => ({
  agent_id: "announcement", supported: true, checking: false, schedules_enabled_on_server: false,
  last_checked_at: "2026-11-24T01:00:00Z", last_success_at: "2026-11-24T01:00:00Z",
  sources: [{ name: "SCH 국제교류처 공지", url: "https://sgee.sch.ac.kr/notice", kind: "sch_board", health: "ok",
    last_checked_at: "2026-11-24T01:00:00Z", last_success_at: "2026-11-24T01:00:00Z" },
  { name: "학사공지", url: "https://home.sch.ac.kr/notice", kind: "sch_board", health: "attention",
    last_checked_at: "2026-11-23T01:00:00Z", last_success_at: null }],
  schedules: [{ task_type: "announcement_discovery", state: "disabled", interval_minutes: 720, last_run_at: null,
    last_success_at: null, next_run_at: null }],
  ...(role === "admin" ? { candidates_waiting: 3 } : {}), ...extra });

let tasks: Record<string, unknown>[] = [];
let events: object[] = [];
beforeEach(() => {
  calls.length = 0;
  token = "tok";
  role = "student";
  session.userId = "u1";
  robo = {};
  tasks = [];
  events = [ann("e1", "Spring orientation", { event_date: "2099-03-02", category: "daily-living" }),
    ann("e2", "Dormitory move-out", { deadline: "2099-12-20", category: "dormitory-housing" }),
    ann("e3", "Autumn festival", { event_date: "2020-10-01", status: "expired" })];
  postStream.mockReset();
  sessionStorage.clear();
  localStorage.clear();
  backend = (c) => {
    const body = c.body as { tool?: string; task_type?: string; params?: Record<string, unknown> } | undefined;
    if (c.path === "/api/v1/agents") return directory();
    if (c.path.endsWith("/monitoring")) return monitoring();
    if (c.path.endsWith("/tools")) {
      switch (body?.tool) {
        case "scholarship_search": return result("scholarship_search", [
          { kind: "announcement", id: "a1", title: "Hub merit scholarship", href: "/announcements/a1", reliability: "verified",
            deadline: "2099-02-01", status: "active" }], ["eligibility_office"]);
        case "opportunity_search": return body.params?.kind === "job" ? result("opportunity_search", [], ["no_reviewed_discoveries"])
          : result("opportunity_search", role === "admin" ? [reviewedItem, candidate] : [reviewedItem], ["official_reviewed"]);
        case "review_candidates": return result("review_candidates", role === "admin" ? [candidate] : []);
        case "career_opportunity_search": return result("career_opportunity_search", [], ["nothing_published", "work_permission"]);
        case "visa_checklist": return result("visa_checklist", [
          { kind: "passage", title: "D-2 extension guide", href: "/knowledge/d-visa", quote: "Apply before your stay expires.", reliability: "verified" }],
        ["checklist_quoted", "visa_not_decision"]);
        case "topik_dates": return result("topik_dates", [
          { kind: "announcement", id: "t1", title: "TOPIK 105th registration", href: "/announcements/t1", reliability: "verified",
            dates: [{ date: "2099-01-05", kind: "deadline", quote: "접수 마감 1월 5일" }] }]);
        case "get_support_request_status": return result("get_support_request_status", [
          { kind: "ticket", id: "k1", ticket_number: 12, status: "assigned", subject: "[Housing] Contract", href: "/support/requests/k1" }]);
        default: return result(body?.tool ?? "?", []);
      }
    }
    if (c.path.match(/^\/api\/v1\/agents\/[^/]+\/tasks$/)) {
      const t = { id: `t${tasks.length + 1}`, agent_id: c.path.split("/")[4], agent_name: "", task_type: body?.task_type,
        status: body?.task_type === "support_request" ? "awaiting_approval" : "queued", stage: null, params: body?.params ?? {},
        output: null, error_code: null, attempts: 0, created_at: "2026-11-24T02:00:00Z", completed_at: null };
      tasks.push(t);
      return t;
    }
    if (c.path === "/api/v1/agent-tasks" && c.method === "GET") {
      return { items: tasks.filter((t) => !c.query?.agent_id || t.agent_id === c.query.agent_id) };
    }
    const decision = c.path.match(/^\/api\/v1\/agent-tasks\/([^/]+)\/decision$/);
    if (decision) {
      const t = tasks.find((x) => x.id === decision[1])!;
      Object.assign(t, (c.body as { approve: boolean }).approve
        ? { status: "completed", completed_at: "2026-11-24T02:01:00Z",
          output: { tool: "create_support_request", count: 1, notes: [], items: [{ kind: "ticket", id: "k2", ticket_number: 13, href: "/support/requests/k2" }] } }
        : { status: "cancelled" });
      return t;
    }
    const one = c.path.match(/^\/api\/v1\/agent-tasks\/([^/]+)$/);
    if (one) return { ...tasks.find((x) => x.id === one[1]), events: [], children: [] };
    if (c.path === "/api/v1/announcements") {
      if (c.query?.status === "expired") return { items: events.filter((e) => (e as { status: string }).status === "expired"), total: 0 };
      if (c.query?.status) return { items: events.filter((e) => (e as { status: string }).status !== "expired"), total: 0 };
      return { items: [ann("n1", "Course registration notice")], total: 1 };
    }
    if (c.path.startsWith("/api/v1/announcements/")) return { ...ann("e1", "Spring orientation", { event_date: "2099-03-02" }), body: "Place: Auditorium.\nRegister at the office." };
    if (c.path.startsWith("/api/v1/knowledge")) return { items: [], total: 0 };
    return {};
  };
});

async function open(id: string, locale?: [string, object]) {
  if (locale) renderWithIntl(<AiOffice />, locale[0], locale[1]);
  else renderWithIntl(<AiOffice />);
  const user = userEvent.setup();
  await waitFor(() => expect(calls.some((c) => c.path === "/api/v1/agents")).toBe(true));
  await act(async () => {});
  await user.click(screen.getByTestId(`character-${id}`));
  const panel = await screen.findByTestId("office-panel");
  return { user, panel };
}

const EXPECTED: Record<string, [string, string]> = {
  reception: ["CHAT", "chat"], "supporter-ko": ["CHAT", "chat"], "supporter-en": ["CHAT", "chat"], "supporter-id": ["CHAT", "chat"],
  "supporter-vi": ["CHAT", "chat"], "supporter-zh": ["CHAT", "chat"], visa: ["SERVICE", "checklists"],
  academic: ["SERVICE", "procedures"], topik: ["SERVICE", "topik"], opportunities: ["DISCOVERY", "opportunities"],
  events: ["DISCOVERY", "events"], career: ["DISCOVERY", "careers"], "guide-bot": ["MONITORING", "monitoring"],
  "supporter-lead": ["TASK_WORKSPACE", "request"],
};

describe("character-specific workspaces", () => {
  it("opens the interface the backend chose for every character", async () => {
    expect(Object.keys(EXPECTED).sort()).toEqual(INTERACTIVE.map((c) => c.id).sort());
    renderWithIntl(<AiOffice />);
    const user = userEvent.setup();
    await waitFor(() => expect(calls.some((c) => c.path === "/api/v1/agents")).toBe(true));
    await act(async () => {});
    for (const [id, [type, view]] of Object.entries(EXPECTED)) {
      await user.click(screen.getByTestId(`character-${id}`));
      const panel = await screen.findByTestId("office-panel");
      await waitFor(() => expect(panel).toHaveAttribute("data-interface", type));
      expect(within(panel).getByTestId(`tab-${view}`)).toHaveAttribute("aria-selected", "true");
      if (view === "chat") {
        expect(within(panel).getByRole("textbox")).toBeInTheDocument();      // chat-first
      } else {
        expect(within(panel).getByTestId("workspace")).toHaveAttribute("data-view", view);
        expect(within(panel).queryByRole("textbox", { name: /message/i })).toBeNull();   // not a chatbot
      }
    }
  });

  it("keeps the grounded chat with citations for Hana and the language supporters", async () => {
    postStream.mockImplementation(async (_p: string, body: { language: string }, opts: { onEvent: (e: unknown) => void }) => {
      opts.onEvent({ event: "delta", data: { text: "…" } });
      return { answer: `answer in ${body.language} [1]`, language: body.language,
        citations: [{ n: 1, document_id: "d-visa", version_id: "v", chunk_id: "c", document_title: "D-2 visa extension", heading: null,
          source_url: null, organization: "Hi Korea", authority_type: "official_government", verified_at: null, is_stale: false, page: null, cited: true }],
        metadata: { answer_generation: "llm", offer_handoff: false } };
    });
    role = "visitor";                     // the public stream (signed-in chats use the conversations API)
    token = null;
    session.userId = null;
    const { user, panel } = await open("supporter-vi");
    await user.type(within(panel).getByRole("textbox"), "Gia hạn visa thế nào?{Enter}");
    await waitFor(() => expect(postStream).toHaveBeenCalled());
    expect(postStream.mock.calls[0][1]).toMatchObject({ language: "vi" });
    const link = await within(panel).findByRole("link", { name: /D-2 visa extension/ });
    expect(link.getAttribute("href")).toContain("/knowledge/d-visa");
  });

  it("Leo lists approved opportunities only, with deadlines, verification and official links", async () => {
    const { panel } = await open("opportunities");
    const list = await within(panel).findByTestId("opportunity-list");
    await waitFor(() => expect(within(list).getAllByTestId("opportunity-card")).toHaveLength(2));
    const cards = within(list).getAllByTestId("opportunity-card");
    expect(cards[0].textContent).toContain("2027 Global Korea Summer Camp");  // soonest deadline first
    expect(cards[1].textContent).toContain("Hub merit scholarship");
    expect(within(cards[0]).getByTestId("open-status")).toHaveTextContent("Open until 2099-01-10");
    expect(within(cards[1]).queryByTestId("open-status")).toBeNull();        // Hub notices: no open/closed claim
    const cites = within(cards[0]).getAllByTestId("source-citation");
    expect(cites.map((a) => a.getAttribute("href"))).toEqual(["/knowledge/doc-camp", "https://www.studyinkorea.go.kr/ko/notice/camp.do"]);
    expect(cites[1]).toHaveAttribute("rel", "noopener noreferrer");
    expect(within(cards[0]).getByTestId("application-link")).toHaveAttribute("href", "https://www.studyinkorea.go.kr/apply");
    expect(within(panel).getByTestId("opp-last-checked")).toBeInTheDocument();
    // students: no admin strip, no admin tabs, no admin action
    expect(within(panel).queryByTestId("admin-strip")).toBeNull();
    expect(within(panel).queryByTestId("tab-review")).toBeNull();
    expect(within(panel).queryByTestId("action-check_official_sources")).toBeNull();
    expect(panel.textContent).not.toContain("UNREVIEWED");
    // filter: programs only
    await userEvent.setup().click(within(panel).getByRole("button", { name: "Programs" }));
    expect(within(list).getAllByTestId("opportunity-card")).toHaveLength(1);
  });

  it("never mixes unreviewed candidates into Leo's list, even for admins, and gives admins the review queue", async () => {
    role = "admin";
    const { user, panel } = await open("opportunities");
    const list = await within(panel).findByTestId("opportunity-list");
    await waitFor(() => expect(within(list).getAllByTestId("opportunity-card")).toHaveLength(2));
    expect(list.textContent).not.toContain("UNREVIEWED");
    expect(within(panel).getByTestId("admin-unreviewed").textContent).toContain("1 unreviewed item");
    expect(within(panel).getByTestId("action-check_official_sources")).toBeInTheDocument();
    await user.click(within(panel).getByTestId("tab-review"));
    const queue = await within(panel).findByTestId("review-queue");
    await waitFor(() => expect(queue.textContent).toContain("UNREVIEWED candidate notice"));
    expect(within(queue).getByTestId("send-to-review")).toBeInTheDocument();
    const call = calls.find((c) => (c.body as { tool?: string })?.tool === "review_candidates");
    expect(call?.path).toBe("/api/v1/agents/scholarship/tools");
  });

  it("Robo shows real monitoring status: sources, health, disabled schedule, activity", async () => {
    const { panel } = await open("guide-bot");
    const status = await within(panel).findByTestId("monitoring-status");
    await waitFor(() => expect(within(status).getByTestId("schedule-state")).toHaveAttribute("data-state", "disabled"));
    expect(within(status).getByTestId("schedules").textContent).toContain("Official notice check");
    expect(status).toHaveAttribute("data-checking", "false");
    expect(status.textContent).toContain("Automatic checks off");
    const sources = within(panel).getAllByTestId("monitored-source");
    expect(sources.map((s) => within(s).getByTestId("source-health").getAttribute("data-health"))).toEqual(["ok", "attention"]);
    expect(within(panel).getByTestId("activity-timeline").textContent).toContain("Checked SCH 국제교류처 공지");
    expect(within(panel).queryByTestId("admin-strip")).toBeNull();
    expect(within(panel).queryByText(/candidate/i)).toBeNull();
    expect(within(panel).getByTestId("recent-announcements").textContent).toContain("Course registration notice");
  });

  it("Robo shows a running check from the backend state (no timers) and admins get the review count", async () => {
    role = "admin";
    robo = { state: "working", monitoring_check_running: true };
    const { panel } = await open("guide-bot");
    const status = await within(panel).findByTestId("monitoring-status");
    expect(status).toHaveAttribute("data-checking", "true");
    expect(within(panel).getByTestId("checking-sources")).toBeInTheDocument();
    expect(await within(panel).findByTestId("candidates-waiting")).toHaveTextContent("3 discovered notices");
    expect(screen.getByTestId("character-guide-bot").closest("[data-actor]")).toHaveAttribute("data-state", "working");
  });

  it("Mia lists upcoming and past events with an inline detail view; empty lists say so", async () => {
    const { user, panel } = await open("events");
    const list = await within(panel).findByTestId("events-list");
    await waitFor(() => expect(within(list).getAllByTestId("announcement-card")).toHaveLength(2));
    expect(within(list).getAllByTestId("announcement-card")[0].textContent).toContain("Spring orientation");
    await user.click(within(panel).getByRole("button", { name: /Past/ }));
    expect(within(list).getAllByTestId("announcement-card").map((x) => x.textContent)).toEqual([expect.stringContaining("Autumn festival")]);
    await user.click(within(panel).getByRole("button", { name: /Upcoming/ }));
    await user.click(within(panel).getAllByTestId("announcement-open")[0]);
    const detail = await within(panel).findByTestId("event-detail");
    await waitFor(() => expect(detail.textContent).toContain("Place: Auditorium."));
    expect(within(detail).getAllByTestId("source-citation")[1]).toHaveAttribute("href", "https://sgee.sch.ac.kr/notice/1");
    expect(detail.textContent).not.toMatch(/registration (is )?open/i);
    await user.click(within(detail).getByTestId("event-back"));
    expect(await within(panel).findByTestId("events-list")).toBeInTheDocument();
  });

  it("Mia says clearly when nothing is published", async () => {
    events = [];
    const { panel } = await open("events");
    expect(await within(panel).findByTestId("desk-empty")).toHaveTextContent("No upcoming event is published right now.");
  });

  it("Daniel states that external job search is not connected and invents nothing", async () => {
    const { panel } = await open("career");
    expect(await within(panel).findByTestId("external-search-status")).toHaveAttribute("data-available", "false");
    await waitFor(() => expect(within(panel).getAllByTestId("desk-empty").length).toBe(2));
    expect(panel.textContent).toContain("No career notice is published right now.");
    expect(within(panel).queryAllByTestId("opportunity-card")).toHaveLength(0);
    expect(panel.textContent).toContain("check part-time work permission");
  });

  it("Yuna runs a checklist with quoted sources and keeps the chat one tab away", async () => {
    const { user, panel } = await open("visa");
    await user.click(await within(panel).findByTestId("topic-d2_extension"));
    const r = await within(panel).findByTestId("procedure-result");
    expect(r.textContent).toContain("Apply before your stay expires.");
    expect(r.textContent).toContain("not a decision about your visa");
    await user.click(within(panel).getByTestId("procedure-back"));
    await user.click(within(panel).getByTestId("open-chat"));
    expect(within(panel).getByTestId("tab-chat")).toHaveAttribute("aria-selected", "true");
  });

  it("Seo shows TOPIK dates quoted from published notices", async () => {
    const { panel } = await open("topik");
    const notice = await within(panel).findByTestId("topik-notice");
    expect(notice.textContent).toContain("접수 마감 1월 5일");
    expect(within(notice).getByTestId("deadline")).toHaveAttribute("data-kind", "deadline");
  });

  it("Sumin creates a request only after the student confirms the exact stored content", async () => {
    const { user, panel } = await open("supporter-lead");
    await user.click(within(panel).getByRole("button", { name: "Housing" }));
    await user.type(within(panel).getByTestId("request-subject"), "Dormitory contract");
    await user.type(within(panel).getByTestId("request-details"), "My contract ends next week and I need help.");
    await user.click(within(panel).getByTestId("request-review"));
    const preview = await within(panel).findByTestId("request-preview");
    expect(within(preview).getByTestId("preview-subject")).toHaveTextContent("[Housing] Dormitory contract");
    const created = calls.find((c) => c.path === "/api/v1/agents/support-coordinator/tasks");
    expect(created?.body).toMatchObject({ task_type: "support_request" });
    // nothing approved yet: no decision call
    expect(calls.some((c) => c.path.endsWith("/decision"))).toBe(false);
    await user.click(within(preview).getByTestId("request-confirm"));
    await waitFor(() => expect(calls.find((c) => c.path.endsWith("/decision"))?.body).toEqual({ approve: true }));
    expect(await within(panel).findByTestId("request-sent")).toHaveTextContent("Request #13 was sent.");
  });

  it("Sumin's Edit declines the stored draft and keeps the text; history lists the student's requests", async () => {
    const { user, panel } = await open("supporter-lead");
    await user.type(within(panel).getByTestId("request-subject"), "Bank account");
    await user.type(within(panel).getByTestId("request-details"), "How do I open a bank account?");
    await user.click(within(panel).getByTestId("request-review"));
    await user.click(await within(panel).findByTestId("request-edit"));
    await waitFor(() => expect(calls.find((c) => c.path.endsWith("/decision"))?.body).toEqual({ approve: false }));
    expect(await within(panel).findByTestId("request-subject")).toHaveValue("Bank account");
    await user.click(within(panel).getByTestId("tab-requests"));
    expect(await within(panel).findByTestId("request-row")).toHaveTextContent("#12");
  });

  it("asks visitors to sign in instead of showing private task or request controls", async () => {
    role = "visitor";
    token = null;
    session.userId = null;
    const { panel } = await open("supporter-lead");
    expect(await within(panel).findByTestId("sign-in-prompt")).toBeInTheDocument();
    expect(within(panel).queryByTestId("request-form")).toBeNull();
  });

  it("a task keeps running after the panel is closed; the character shows the backend state", async () => {
    const { user, panel } = await open("events");
    // from now on the backend reports Mia's (queued / running) task: the refresh after starting it shows that
    const base = backend;
    backend = (c) => c.path === "/api/v1/agents"
      ? { ...directory(), items: directory().items.map((a) => a.id === "events" ? { ...a, state: "working", active: 1 } : a) }
      : base(c);
    await user.click(await within(panel).findByTestId("action-what_changed"));
    await waitFor(() => expect(tasks).toHaveLength(1));
    await user.click(within(panel).getByTestId("panel-close"));
    expect(screen.queryByTestId("office-panel")).toBeNull();
    await waitFor(() => expect(screen.getByTestId("character-events").closest("[data-actor]")).toHaveAttribute("data-state", "working"));
    expect(screen.getByTestId("state-events")).toBeInTheDocument();
    expect(screen.getByTestId("character-events")).toHaveAccessibleName(expect.stringContaining("Working"));
    await user.click(screen.getByTestId("character-events"));           // still clickable
    const again = await screen.findByTestId("office-panel");
    expect(within(again).getByTestId("agent-status").textContent).toContain("Working");
  });

  it("switches workspace labels with the site language", async () => {
    const { panel } = await open("opportunities", ["ko", ko]);
    await within(panel).findByTestId("opportunity-list");
    expect(within(panel).getByTestId("tab-opportunities")).toHaveTextContent("기회");
    expect(panel.textContent).toContain("내 장학금 확인");
  });

  it("works in Simplified Chinese for the monitoring desk", async () => {
    const { panel } = await open("guide-bot", ["zh-CN", zh]);
    const status = await within(panel).findByTestId("monitoring-status");
    await waitFor(() => expect(status.textContent).toContain("自动检查已关闭"));
    expect(within(panel).getByTestId("tab-monitoring")).toHaveTextContent("监测");
  });

  it("a greeting bubble never blocks clicks on a neighbour", async () => {
    await open("academic");
    expect(screen.getByTestId("speech-bubble").className).toContain("pointer-events-none");
  });

  it("has a back button for phones that returns to the office", async () => {
    const { user, panel } = await open("career");
    await user.click(within(panel).getByTestId("panel-back"));
    expect(screen.queryByTestId("office-panel")).toBeNull();
  });
});

describe("workspace helpers", () => {
  it("counts days in Korean time and sorts by the soonest future deadline", () => {
    expect(daysUntil("2026-12-01", "2026-11-24")).toBe(7);
    expect(daysUntil("2026-11-20", "2026-11-24")).toBe(-4);
    expect(daysUntil(null)).toBeNull();
    const items = [{ kind: "announcement", title: "past", deadline: "2000-01-01" }, { kind: "announcement", title: "none" },
      { kind: "announcement", title: "late", deadline: "2099-05-01" }, { kind: "announcement", title: "soon", deadline: "2099-01-01" }];
    expect([...items].sort(byDeadline as never).map((i) => i.title)).toEqual(["soon", "late", "none", "past"]);
  });

  it("splits dated announcements into upcoming and past and drops undated ones", () => {
    const a = (id: string, extra: object) => ({ ...ann(id, id), ...extra }) as never;
    const { upcoming, past } = splitEvents([a("u2", { event_date: "2026-12-05" }), a("u1", { deadline: "2026-11-30" }),
      a("p", { event_date: "2026-11-01" }), a("none", {}), a("u1", { deadline: "2026-11-30" })], "2026-11-24");
    expect(upcoming.map((x: { id: string }) => x.id)).toEqual(["u1", "u2"]);
    expect(past.map((x: { id: string }) => x.id)).toEqual(["p"]);
  });
});
