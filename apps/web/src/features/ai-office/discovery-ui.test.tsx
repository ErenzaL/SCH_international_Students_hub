import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithIntl } from "@/test/utils";
import ko from "@/messages/ko.json";

/**
 * AI Office Phase 3 - official-source discovery in the Tasks tab: live progress of a running check, verified vs
 * unverified results, deadlines, application links, uncertainty flags, last-checked times and admin review actions.
 * Against a fake backend that answers like app/api/agents.py.
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



const discovered = (id: string, title: string, extra: object = {}) => ({
  kind: "discovered", id, title, href: `https://sgee.sch.ac.kr/notice/notice01.php?admin_mode=read&no=${id}`,
  published_on: "2026-11-20", opportunity_kind: "scholarship", open_status: "open", open_reason: "deadline_in_future",
  next_deadline: "2026-12-10", deadline: "2026-12-10", eligibility: ["지원 자격: 직전 학기 평점 3.5 이상"],
  application_links: [{ url: "https://forms.gle/abcd", text: "온라인 신청서", kind: "link" }], flags: [], change: "new",
  last_checked_at: "2026-11-24T01:00:00Z", source_name: "SCH 유학생 공지사항", reliability: "external_unverified",
  review_status: "candidate", ...extra });

let isAdmin = false;
let taskState: "running" | "completed" = "running";
const leo = () => agent("scholarship", "opportunities", "Leo", {
  actions: [{ id: "official_opportunities", kind: "tool", target: "opportunity_search", params: {} },
    { id: "scan_sources", kind: "task", target: "scholarship_scan", params: {} },
    ...(isAdmin ? [{ id: "check_official_sources", kind: "task", target: "opportunity_discovery", params: {}, admin_only: true }] : [])],
  tools: [tool("opportunity_search"), tool("official_source_check", { admin_only: true, background: true })] });

const task = () => ({
  id: "t9", agent_id: "scholarship", agent_name: "Leo", task_type: "opportunity_discovery", status: taskState, stage: "checking",
  params: {}, error_code: null, attempts: 1, created_at: "2026-11-24T01:00:00Z",
  completed_at: taskState === "completed" ? "2026-11-24T01:00:09Z" : null,
  progress: { sources_total: 3, sources_done: 2, items_found: 7, current: "GKS scholarship page",
    sources: [{ name: "SCH 유학생 공지사항", url: "https://sgee.sch.ac.kr/notice/notice01.php", status: "ok", found: 6, new: 2, updated: 1,
      checked_at: "2026-11-24T01:00:03Z" },
    { name: "Study in Korea", url: "https://www.studyinkorea.go.kr/ko/notice/scholarshipsList.do", status: "blocked", found: 0,
      error: "robots_disallowed" },
    { name: "GKS scholarship page", url: "https://www.studyinkorea.go.kr/ko/plan/scholarship.do", status: "checking" }] },
  output: taskState === "completed" ? {
    tool: "official_source_check", count: 3, notes: ["candidates_need_review", "some_sources_failed"], new_count: 2, updated_count: 1,
    items: [
      { kind: "announcement", id: "a1", title: "Hub scholarship notice", href: "/announcements/a1", reliability: "verified", deadline: "2026-12-01" },
      discovered("6801", "[장학] 성적우수 장학금 신청 안내"),
      discovered("4530", "GKS Newsletter", { open_status: "unknown", open_reason: "no_deadline", next_deadline: null, deadline: null,
        eligibility: [], application_links: [], flags: ["missing_deadline", "no_detail_page"], href: "https://www.studyinkorea.go.kr/ko/notice/scholarshipsList.do" })],
    sources: [{ name: "SCH 유학생 공지사항", url: "https://sgee.sch.ac.kr/notice/notice01.php", status: "ok", found: 6, new: 2, updated: 1,
      checked_at: "2026-11-24T01:00:03Z" }],
    provenance: { generated_by: "deterministic" } } : null,
  events: [], children: [] });

beforeEach(() => {
  calls.length = 0;
  token = "tok";
  isAdmin = false;
  taskState = "running";
  postStream.mockReset();
  sessionStorage.clear();
  localStorage.clear();
  backend = (c) => {
    if (c.path === "/api/v1/agents") return { items: [leo(), agent("reception", "reception", "Hana")], signed_in: true, is_admin: isAdmin };
    if (c.path === "/api/v1/agent-tasks" && c.method === "GET") return { items: [task()] };
    if (c.path === "/api/v1/agent-tasks/t9") return task();
    if (c.path.startsWith("/api/v1/admin/discovery/items/")) return { knowledge_source_id: "ks1" };
    if (c.path.startsWith("/api/v1/announcements") || c.path.startsWith("/api/v1/knowledge")) return { items: [], total: 0 };
    return {};
  };
});

async function openLeo() {
  const user = userEvent.setup();
  await waitFor(() => expect(calls.some((c) => c.path === "/api/v1/agents")).toBe(true));
  await user.click(screen.getByTestId("character-opportunities"));
  const panel = await screen.findByTestId("office-panel");
  await user.click(within(panel).getByTestId("tab-work"));
  await within(panel).findByTestId("agent-work");
  return { user, panel };
}

describe("AI Office official-source discovery (Phase 3)", () => {
  it("shows live progress of a running check from the task record", async () => {
    renderWithIntl(<AiOffice />);
    const { panel } = await openLeo();
    const progress = await within(panel).findByTestId("task-progress");
    expect(progress.textContent).toContain("2 of 3 sources checked");
    expect(progress.textContent).toContain("7 items found");
    expect(progress.textContent).toContain("Checking: GKS scholarship page");
    expect(within(progress).getByRole("progressbar")).toHaveAttribute("aria-valuenow", "2");
    const statuses = [...progress.querySelectorAll("[data-source-status]")].map((x) => x.getAttribute("data-source-status"));
    expect(statuses).toEqual(["ok", "blocked", "checking"]);
    expect(progress.textContent).toContain("The site does not allow automated access.");
  });

  it("separates verified Hub results from unverified official-site results, with deadlines and links", async () => {
    taskState = "completed";
    renderWithIntl(<AiOffice />);
    const { panel } = await openLeo();
    const verified = await within(panel).findByTestId("verified-results");
    const unverified = within(panel).getByTestId("unverified-results");
    expect(verified.textContent).toContain("Hub scholarship notice");
    expect(unverified.textContent).toContain("From official websites, not reviewed (2)");
    const items = within(unverified).getAllByTestId("agent-item");
    expect(within(items[0]).getByTestId("open-status")).toHaveTextContent("Open until 2026-12-10");
    expect(within(items[0]).getByTestId("application-links").querySelector("a")).toHaveAttribute("href", "https://forms.gle/abcd");
    expect(within(items[0]).getByTestId("application-links").querySelector("a")).toHaveAttribute("rel", "noopener noreferrer");
    expect(within(items[0]).getByTestId("eligibility").textContent).toContain("평점 3.5");
    expect(items[0].textContent).toContain("checked");
    expect(within(items[1]).getByTestId("open-status")).toHaveTextContent("Status unknown");
    expect(within(items[1]).getByTestId("item-flags").textContent).toContain("no deadline found");
    expect(panel.textContent).toContain("Nothing is published automatically.");
    // students see no review buttons
    expect(within(panel).queryByTestId("review-actions")).toBeNull();
    expect(within(panel).queryByTestId("action-check_official_sources")).toBeNull();
  });

  it("lets an admin send a candidate to the normal review queue or dismiss it", async () => {
    taskState = "completed";
    isAdmin = true;
    renderWithIntl(<AiOffice />);
    const { user, panel } = await openLeo();
    expect(await within(panel).findByTestId("action-check_official_sources")).toBeEnabled();
    const actions = await within(panel).findAllByTestId("review-actions");
    expect(within(actions[1]).getByTestId("send-to-review")).toBeDisabled();       // no page of its own
    await user.click(within(actions[0]).getByTestId("send-to-review"));
    await waitFor(() => expect(calls.some((c) => c.path === "/api/v1/admin/discovery/items/6801/send-to-review")).toBe(true));
    expect(calls.find((c) => c.path.endsWith("/send-to-review"))?.auth).toBe(true);
    await waitFor(() => expect(actions[0].textContent).toContain("Sent to review"));
    await user.click(within(actions[1]).getByTestId("dismiss"));
    await waitFor(() => expect(calls.some((c) => c.path === "/api/v1/admin/discovery/items/4530/dismiss")).toBe(true));
  });

  it("shows open status and flags in the student's language", async () => {
    taskState = "completed";
    renderWithIntl(<AiOffice />, "ko", ko);
    const { panel } = await openLeo();
    const unverified = await within(panel).findByTestId("unverified-results");
    expect(unverified.textContent).toContain("2026-12-10까지 접수");
    expect(unverified.textContent).toContain("마감일 없음");
    expect(unverified.textContent).toContain("공식 웹사이트, 미검토");
  });
});
