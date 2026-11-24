import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithIntl } from "@/test/utils";

type Call = { method: string; path: string; body?: unknown; query?: Record<string, unknown> };
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
  return { ...mod, api: { ...mod.api,
    get: (path: string, query?: Record<string, unknown>) => handle({ method: "GET", path, query }),
    post: (path: string, body?: unknown) => handle({ method: "POST", path, body }),
    put: (path: string, body?: unknown) => handle({ method: "PUT", path, body }),
    patch: (path: string, body?: unknown) => handle({ method: "PATCH", path, body }),
    delete: (path: string) => handle({ method: "DELETE", path }) } };
});
let role = "super_admin";
vi.mock("@/features/admin/shell/admin-context", async (orig) => ({
  ...(await orig<typeof import("@/features/admin/shell/admin-context")>()), useMe: () => ({ role }) }));

import { ApiError } from "@/lib/api";
import { AgentsPage } from "@/features/admin/agents/agents-page";
import { GpuWorkerPage } from "@/features/admin/gpu/gpu-worker-page";
import { ADMIN_NAV, navForRole } from "@/features/admin/shell/admin-context";

const zero = { queued: 0, running: 0, awaiting_approval: 0, completed: 0, failed: 0, cancelled: 0 };
const desk = (id: string, name: string, extra: object = {}) => ({ id, name, title: `${name} title`, paused: false, tasks_7d: { ...zero }, last_success_at: null,
  last_failure_at: null, last_error: null, tools_available: 5, tools_unavailable: [], monitors: true, sources: 2, sources_enabled: 1, sources_failing: 0, schedules: [], ...extra });
const health = { schedules_enabled_on_server: false, tasks_enabled: true,
  queues: { agent_tasks: { queued: 3, running: 1, failed_7d: 2, oldest_queued_minutes: 190, stuck: true }, jobs: { queued: 0, running: 0, failed_7d: 0, oldest_queued_minutes: null, stuck: false }, gpu_jobs: null },
  agents: [desk("career", "Daniel", { tasks_7d: { ...zero, completed: 4, failed: 1 }, sources_failing: 1 }), desk("events", "Mia", { paused: true })] };
const task = (id: string, extra: object = {}) => ({ id, agent_id: "topik", agent_name: "Seo", task_type: "guidance_discovery", status: "failed", attempts: 3, max_attempts: 3,
  error_code: "interrupted", created_at: "2026-11-25T01:00:00Z", completed_at: null, requested: "administrator", can_rerun: true, can_cancel: false, ...extra });

beforeEach(() => {
  calls.length = 0;
  role = "super_admin";
  backend = (c) => {
    if (c.path === "/api/v1/admin/agent-operations") return health;
    if (c.path === "/api/v1/admin/agent-operations/tasks") return { items: [task("t1"), task("t2", { status: "queued", can_rerun: false, can_cancel: true, requested: "student", task_type: "support_request" })], total: 2, page: 1, page_size: 20 };
    if (c.path === "/api/v1/admin/agent-schedules") return { globally_enabled: false, items: [{ id: "s1", agent_id: "topik", agent_name: "Seo", task_type: "guidance_discovery", enabled: false, interval_minutes: 2880, last_run_at: null, last_success_at: null, last_error: null }] };
    if (c.path === "/api/v1/admin/storage") return { available: true, limit_bytes: 500 * 1024 * 1024, database_bytes: 375 * 1024 * 1024, share: 0.75, level: "warning", tables: [{ table_name: "document_chunks", total_bytes: 2_000_000, index_bytes: 900_000, row_estimate: 700 }], rows_added_30d: { document_chunks: 12 } };
    return {};
  };
});

describe("Admin: agents", () => {
  it("shows every desk with its real numbers, stuck queues and the switched-off schedules", async () => {
    renderWithIntl(<AgentsPage />);
    const daniel = await screen.findByTestId("desk-career");
    expect(within(daniel).getByText("failed: 1")).toBeInTheDocument();
    expect(within(daniel).getByText("1 of 2 on")).toBeInTheDocument();
    expect(screen.getByTestId("queue-agent_tasks")).toHaveTextContent("This queue is stuck.");
    expect(screen.getByTestId("queue-gpu_jobs")).toHaveTextContent("Needs a database migration.");
    expect(screen.getByText("Automatic checks are switched off on the server")).toBeInTheDocument();
  });

  it("pauses and resumes a desk through the API", async () => {
    renderWithIntl(<AgentsPage />);
    await userEvent.click(await screen.findByTestId("pause-career"));
    await userEvent.click(screen.getByTestId("pause-events"));
    await waitFor(() => expect(calls.filter((c) => c.method === "PUT").map((c) => [c.path, c.body])).toEqual([
      ["/api/v1/admin/agent-operations/agents/career", { paused: true }], ["/api/v1/admin/agent-operations/agents/events", { paused: false }]]));
  });

  it("offers re-run and cancel only where the backend allows it", async () => {
    renderWithIntl(<AgentsPage />);
    await userEvent.click(screen.getByRole("tab", { name: "Tasks" }));
    const rows = await screen.findAllByTestId("admin-task");
    expect(within(rows[0]).queryByRole("button", { name: /Cancel/ })).toBeNull();
    expect(within(rows[1]).queryByRole("button", { name: /Run again/ })).toBeNull();
    await userEvent.click(within(rows[0]).getByRole("button", { name: /Run again/ }));
    expect(calls.some((c) => c.path.endsWith("/t1/rerun"))).toBe(true);
    expect(screen.getByText("Parameters and results of students are never shown here.")).toBeInTheDocument();
  });

  it("switches a schedule on only by an explicit click and explains the second switch", async () => {
    renderWithIntl(<AgentsPage />);
    await userEvent.click(screen.getByRole("tab", { name: "Schedules" }));
    const sw = await screen.findByRole("switch");
    expect(sw).toHaveAttribute("aria-checked", "false");
    expect(screen.getByText(/runs only when it is on here AND/)).toBeInTheDocument();
    expect(calls.some((c) => c.method === "PATCH")).toBe(false);
    await userEvent.click(sw);
    expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ enabled: true });
  });

  it("shows the storage level and says that nothing is deleted", async () => {
    renderWithIntl(<AgentsPage />);
    await userEvent.click(screen.getByRole("tab", { name: "Storage" }));
    expect(await screen.findByText("Database: 375.0 MB of 500.0 MB (75 %)")).toBeInTheDocument();
    expect(screen.getByText(/Nothing is deleted automatically/)).toBeInTheDocument();
  });

  it("adds a prepared source and deletes one only after a second click", async () => {
    const prev = backend;
    backend = (c) => {
      if (c.path === "/api/v1/admin/discovery/catalog") return { items: [{ agent_id: "topik", name: "TOPIK page", kind: "page", url: "https://x.go.kr/t", category: "topik-korean", language: "ko", config: {}, added: false, ready: true, needs: null, validated: { status: "ok", checked: "2026-11-25" }, recommended_interval_minutes: 2880 },
        { agent_id: "career", name: "Saramin", kind: "saramin_api", url: "https://www.saramin.co.kr/", category: "employment-internships", language: "ko", config: {}, added: false, ready: false, needs: "SARAMIN_ACCESS_KEY", validated: {}, recommended_interval_minutes: 1440 }] };
      if (c.path === "/api/v1/admin/discovery/sources" && c.method === "GET") return { items: [{ id: "s9", agent_id: "career", name: "Jobs", kind: "listing", url: "https://y.ac.kr", enabled: true, last_checked_at: null, last_status: "failed", last_error: "http_503", consecutive_failures: 2 }] };
      return prev(c);
    };
    renderWithIntl(<AgentsPage />);
    await userEvent.click(screen.getByRole("tab", { name: "Sources" }));
    const cards = await screen.findAllByTestId("prepared");
    expect(cards[1]).toHaveTextContent("needs SARAMIN_ACCESS_KEY on the API service");
    await userEvent.click(within(cards[0]).getByRole("button", { name: /Add/ }));
    expect(calls.find((c) => c.method === "POST")?.body).toMatchObject({ agent_id: "topik", kind: "page", url: "https://x.go.kr/t" });
    await userEvent.click(screen.getByRole("button", { name: "Remove" }));
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
    await userEvent.click(screen.getByRole("button", { name: "Remove with its candidates" }));
    expect(calls.find((c) => c.method === "DELETE")?.path).toBe("/api/v1/admin/discovery/sources/s9");
  });

  it("is in the navigation of administrators only", () => {
    expect(navForRole("supporter").map((n) => n.key)).not.toContain("agents");
    expect(navForRole("admin").map((n) => n.key)).toEqual(expect.arrayContaining(["agents", "gpuWorker"]));
    expect(new Set(ADMIN_NAV.map((n) => n.href)).size).toBe(ADMIN_NAV.length);
  });
});

describe("Admin: GPU worker", () => {
  const status = { available: false, routed_job_types: ["translate_announcement"], queue: { queued: 1, running: 0 }, last_24h: { succeeded: 2, failed: { llm_timeout: 1 }, average_seconds: 12 },
    workers: [{ id: "w1", name: "school-gpu", status: "active", expires_at: "2027-01-01T00:00:00Z", expired: false, last_seen_at: null }], jobs: [] };

  it("says plainly when the feature is off", async () => {
    backend = () => new ApiError({ status: 404, code: "not_found", message: "Not found." });
    renderWithIntl(<GpuWorkerPage />);
    expect(await screen.findByTestId("gpu-off")).toHaveTextContent("GPU_WORKER_ENABLED is off");
    expect(screen.queryByRole("button", { name: /Create/ })).toBeNull();
  });

  it("shows a new token once and can hide it", async () => {
    backend = (c) => (c.method === "POST" ? { name: "gpu-2", token: "schgw_TEST" } : status);
    renderWithIntl(<GpuWorkerPage />);
    await userEvent.click(await screen.findByRole("button", { name: /Create/ }));
    expect(await screen.findByTestId("gpu-token")).toHaveTextContent("schgw_TEST");
    await userEvent.click(screen.getByRole("button", { name: "Hide" }));
    expect(screen.queryByText("schgw_TEST")).toBeNull();
  });

  it("revokes only after a second click, and only super administrators see token controls", async () => {
    backend = () => status;
    const { unmount } = renderWithIntl(<GpuWorkerPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Revoke" }));
    expect(calls.some((c) => c.method === "PATCH")).toBe(false);
    await userEvent.click(screen.getByRole("button", { name: "Revoke for good" }));
    expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ status: "revoked" });
    unmount();
    role = "admin";
    renderWithIntl(<GpuWorkerPage />);
    expect(await screen.findByText("Only super administrators manage tokens.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /New token/ })).toBeNull();
  });
});
