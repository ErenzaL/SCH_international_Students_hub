"use client";

/**
 * AI Office Phase 2: the backend agent system (app/services/agents). The backend owns everything here - which
 * agent may use which tool, task state, results and their sources. The office only displays it.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { api, apiRequest } from "@/lib/api";
import { getAccessToken } from "@/lib/supabase/client";
import type { LanguageCode } from "@/types/api";

export type AgentState = "idle" | "working" | "waiting" | "completed" | "error";
export type TaskStatus = "queued" | "running" | "awaiting_approval" | "completed" | "failed" | "cancelled";
export type Reliability = "verified" | "possibly_outdated" | "expired" | "external_unverified" | "ai_generated"
  | "student_input";

export interface AgentTool {
  name: string;
  available: boolean;
  unavailable_reason: string | null;
  requires_sign_in: boolean;
  background: boolean;
  uses_ai: boolean;
  needs_approval: boolean;
  admin_only?: boolean;
}

export interface AgentAction {
  id: string;
  kind: "tool" | "task";
  target: string;
  params: Record<string, unknown>;
  admin_only?: boolean;
}

/** How the office presents an agent (backend registry). Presentation only: it never grants anything. */
export type InterfaceType = "CHAT" | "SERVICE" | "DISCOVERY" | "MONITORING" | "TASK_WORKSPACE";

export interface AgentInterfaceView {
  type: InterfaceType;
  /** the workspace view opened first */
  default_view: string;
  /** tabs this viewer may open (admin tabs only for admins; the admin endpoints check the role again) */
  tabs: string[];
  capabilities: string[];
  /** ids of this agent's actions shown in the workspace action bar */
  task_actions: string[];
  allowed_user_roles: string[];
  data_sources: string[];
}

export interface AgentInfo {
  id: string;
  character_id: string;
  name: string;
  title?: string;
  department: string;
  languages: LanguageCode[];
  fixed_language: LanguageCode | null;
  tools: AgentTool[];
  task_types: string[];
  can_delegate_to: string[];
  restricted_actions: string[];
  actions: AgentAction[];
  monitoring: boolean;
  state: AgentState;
  active: number;
  awaiting: number;
  interface?: AgentInterfaceView;
  /** an official-source check of this agent is queued or running (public, no details) */
  monitoring_check_running?: boolean;
}

export interface MonitoredSource {
  name: string;
  url: string;
  kind: "sch_board" | "listing" | "page";
  health: "ok" | "attention" | "not_checked";
  last_checked_at: string | null;
  last_success_at: string | null;
  // admins only
  id?: string;
  enabled?: boolean;
  last_status?: "ok" | "partial" | "failed" | "blocked" | null;
  last_error?: string | null;
  consecutive_failures?: number;
}

export interface MonitoredSchedule {
  task_type: string;
  /** active = runs automatically; off_on_server = enabled but the server switch is off; disabled */
  state: "active" | "disabled" | "off_on_server";
  interval_minutes: number | null;
  last_run_at: string | null;
  last_success_at: string | null;
  next_run_at: string | null;
  // admins only
  id?: string;
  enabled?: boolean;
  last_error?: string | null;
}

export interface MonitoringStatus {
  agent_id: string;
  supported: boolean;
  sources: MonitoredSource[];
  schedules: MonitoredSchedule[];
  schedules_enabled_on_server: boolean;
  checking: boolean;
  last_checked_at: string | null;
  last_success_at: string | null;
  candidates_waiting?: number;
}

export interface FoundDate {
  date: string;
  kind: "deadline" | "event" | "date" | "period_start";
  quote: string | null;
  reviewed?: boolean;
  year_assumed?: boolean;
}

export interface ResultItem {
  kind: "announcement" | "document" | "passage" | "external_page" | "summary" | "translation" | "ticket" | "url"
    | "discovered";
  id?: string;
  title?: string;
  href?: string | null;
  link_kind?: string;
  heading?: string | null;
  quote?: string;
  excerpt?: string;
  body?: string;
  page?: number | null;
  deadline?: string | null;
  event_date?: string | null;
  status?: string;
  ticket_number?: number;
  verdict?: string;
  change?: "new" | "updated" | "unchanged" | null;
  dates?: FoundDate[];
  date?: string;
  error?: string;
  reliability?: Reliability | null;
  // official-source discovery (Phase 3)
  published_on?: string | null;
  opportunity_kind?: "scholarship" | "competition" | "program" | "job" | null;
  open_status?: "open" | "closed" | "unknown";
  open_reason?: string | null;
  next_deadline?: string | null;
  eligibility?: string[];
  application_links?: { url: string; text: string; kind: string }[];
  /** reviewed discoveries: the official page (href is then the approved Knowledge Center document) */
  official_url?: string | null;
  category?: string | null;
  organization?: string | null;
  source?: string | null;
  verified_at?: string | null;
  published_at?: string | null;
  updated_at?: string | null;
  subject?: string | null;
  flags?: string[];
  last_checked_at?: string | null;
  source_name?: string | null;
  review_status?: "candidate" | "dismissed" | "imported";
  summary?: string | null;
}

export interface SourceRun {
  id?: string;
  source_id?: string;
  name: string;
  url: string;
  status: "pending" | "checking" | "ok" | "partial" | "failed" | "blocked" | "recently_checked" | null;
  new?: number;
  updated?: number;
  found?: number;
  error?: string | null;
  checked_at?: string | null;
  last_checked_at?: string | null;
}

export interface TaskProgress {
  sources_total?: number;
  sources_done?: number;
  items_found?: number;
  new?: number;
  updated?: number;
  current?: string;
  stage?: string;
  sources?: SourceRun[];
}

export interface ToolResult {
  tool: string;
  items: ResultItem[];
  count: number;
  notes: string[];
  agent_id?: string;
  handled_by?: string;
  new_count?: number;
  updated_count?: number;
  first_run?: boolean;
  verified_count?: number;
  unverified_count?: number;
  sources?: SourceRun[];
}

export interface TaskEvent {
  id: number;
  agent_id: string;
  step: "queued" | "start" | "tool" | "delegate" | "result" | "error" | "cancel" | "approval";
  tool: string | null;
  data: Record<string, unknown>;
  created_at: string;
}

export interface AgentTask {
  id: string;
  agent_id: string;
  agent_name: string;
  task_type: string;
  status: TaskStatus;
  stage: string | null;
  params: Record<string, unknown>;
  output: (ToolResult & { provenance?: { generated_by: string } }) | null;
  error_code: string | null;
  attempts: number;
  progress?: TaskProgress;
  created_at: string;
  completed_at: string | null;
  events?: TaskEvent[];
  children?: AgentTask[];
}

export type RequestOutcome =
  | { route: "answer"; agent_id: string; language: LanguageCode }
  | { route: "clarify"; agent_id: string; options: string[] }
  | { route: "redirect"; agent_id: string; suggested_agent: string; suggested_character: string }
  | { route: "tool"; agent_id: string; handled_by: string; delegated_from: string | null; result: ToolResult }
  | { route: "task" | "approval"; agent_id: string; handled_by: string; delegated_from: string | null; task: AgentTask };

export const ACTIVE: TaskStatus[] = ["queued", "running", "awaiting_approval"];

/** Sends the access token when there is a session (agent endpoints also work for visitors). */
async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const token = await getAccessToken().catch(() => null);
  return apiRequest<T>(method, path, { body, auth: Boolean(token) });
}

export const agentApi = {
  list: () => call<{ items: AgentInfo[]; signed_in: boolean; is_admin?: boolean }>("GET", "/api/v1/agents"),
  request: (agentId: string, message: string, language?: LanguageCode) =>
    call<RequestOutcome>("POST", `/api/v1/agents/${agentId}/requests`, { message, language }),
  tool: (agentId: string, tool: string, params: Record<string, unknown>, language?: LanguageCode) =>
    call<{ result: ToolResult; handled_by: string }>("POST", `/api/v1/agents/${agentId}/tools`, { tool, params, language }),
  createTask: (agentId: string, taskType: string, params: Record<string, unknown>, language?: LanguageCode) =>
    api.post<AgentTask>(`/api/v1/agents/${agentId}/tasks`, { task_type: taskType, params, language }, { auth: true }),
  tasks: (agentId: string) =>
    api.get<{ items: AgentTask[] }>("/api/v1/agent-tasks", { agent_id: agentId, page_size: 10 }, { auth: true }),
  task: (id: string) => api.get<AgentTask>(`/api/v1/agent-tasks/${id}`, undefined, { auth: true }),
  cancel: (id: string) => api.post<AgentTask>(`/api/v1/agent-tasks/${id}/cancel`, {}, { auth: true }),
  decide: (id: string, approve: boolean) =>
    api.post<AgentTask>(`/api/v1/agent-tasks/${id}/decision`, { approve }, { auth: true }),
  // admin review of discovered official notices (Phase 3)
  dismiss: (itemId: string) => api.post<ResultItem>(`/api/v1/admin/discovery/items/${itemId}/dismiss`, {}, { auth: true }),
  sendToReview: (itemId: string) =>
    api.post<{ knowledge_source_id: string }>(`/api/v1/admin/discovery/items/${itemId}/send-to-review`, {}, { auth: true }),
  // monitoring desks (public status; admins get more) and admin source / schedule management
  monitoring: (agentId: string) => call<MonitoringStatus>("GET", `/api/v1/agents/${agentId}/monitoring`),
  updateSource: (sourceId: string, patch: { enabled?: boolean; reset_failures?: boolean }) =>
    api.patch<MonitoredSource>(`/api/v1/admin/discovery/sources/${sourceId}`, patch),
  updateSchedule: (scheduleId: string, patch: { enabled: boolean }) =>
    api.patch<MonitoredSchedule>(`/api/v1/admin/agent-schedules/${scheduleId}`, patch),
};

const TASK_POLL_MS = 2500;

/**
 * The signed-in viewer's own tasks of one agent (the API only ever returns the caller's tasks). Re-polls while one
 * of them is queued or running; `onChanged` lets the office refresh the character's state.
 */
export function useAgentTasks(agent: AgentInfo | undefined, signedIn: boolean, onChanged: () => void) {
  const [tasks, setTasks] = useState<AgentTask[] | null>(null);
  const agentId = agent?.id;

  const reload = useCallback(async () => {
    if (!signedIn || !agentId) return;
    try {
      const r = await agentApi.tasks(agentId);
      setTasks(r.items.filter((x) => x.agent_id === agentId));
    } catch {
      setTasks((prev) => prev ?? []);
    }
  }, [signedIn, agentId]);

  useEffect(() => {
    const id = window.setTimeout(() => void reload(), 0);
    return () => window.clearTimeout(id);
  }, [reload]);

  const running = tasks?.some((x) => x.status === "queued" || x.status === "running");
  useEffect(() => {
    if (!running) return;
    const id = window.setInterval(() => void reload().then(onChanged), TASK_POLL_MS);
    return () => window.clearInterval(id);
  }, [running, reload, onChanged]);

  return { tasks, reload };
}

const FAST_MS = 3000;
const SLOW_MS = 30000;

/**
 * The agent directory with each agent's state for this viewer. Polls quickly while an agent is working, slowly
 * otherwise, and not at all while the tab is hidden. `refresh()` after starting a task.
 */
export function useAgentDirectory() {
  const [agents, setAgents] = useState<AgentInfo[] | null>(null);
  const [signedIn, setSignedIn] = useState(false);
  const [isAdmin, setIsAdmin] = useState(false);
  const [error, setError] = useState(false);
  const loadNow = useRef<() => void>(() => {});

  useEffect(() => {
    let alive = true;
    let timer: number | null = null;
    const schedule = (ms: number) => {
      if (timer) window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        if (document.visibilityState === "hidden") schedule(SLOW_MS);
        else void load();
      }, ms);
    };
    const load = async () => {
      let next = SLOW_MS;
      try {
        const r = await agentApi.list();
        if (!alive) return;
        setAgents(r.items);
        setSignedIn(r.signed_in);
        setIsAdmin(Boolean(r.is_admin));
        setError(false);
        if (r.items.some((a) => a.state === "working")) next = FAST_MS;
      } catch {
        if (!alive) return;
        setError(true);
      }
      schedule(next);
    };
    loadNow.current = () => schedule(0);
    schedule(0);
    return () => {
      alive = false;
      if (timer) window.clearTimeout(timer);
      loadNow.current = () => {};
    };
  }, []);

  const refresh = useCallback(() => loadNow.current(), []);
  const byCharacter = useCallback((characterId: string) => agents?.find((a) => a.character_id === characterId),
    [agents]);
  return { agents, signedIn, isAdmin, error, refresh, byCharacter };
}
