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
}

export interface AgentAction {
  id: string;
  kind: "tool" | "task";
  target: string;
  params: Record<string, unknown>;
}

export interface AgentInfo {
  id: string;
  character_id: string;
  name: string;
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
}

export interface FoundDate {
  date: string;
  kind: "deadline" | "event" | "date" | "period_start";
  quote: string | null;
  reviewed?: boolean;
  year_assumed?: boolean;
}

export interface ResultItem {
  kind: "announcement" | "document" | "passage" | "external_page" | "summary" | "translation" | "ticket" | "url";
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
  change?: "new" | "updated" | null;
  dates?: FoundDate[];
  date?: string;
  error?: string;
  reliability?: Reliability | null;
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
  list: () => call<{ items: AgentInfo[]; signed_in: boolean }>("GET", "/api/v1/agents"),
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
};

const FAST_MS = 3000;
const SLOW_MS = 30000;

/**
 * The agent directory with each agent's state for this viewer. Polls quickly while an agent is working, slowly
 * otherwise, and not at all while the tab is hidden. `refresh()` after starting a task.
 */
export function useAgentDirectory() {
  const [agents, setAgents] = useState<AgentInfo[] | null>(null);
  const [signedIn, setSignedIn] = useState(false);
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
  return { agents, signedIn, error, refresh, byCharacter };
}
