/**
 * AI Office agents - Phase 1 contracts.
 *
 * Every character is an agent PROFILE: identity (from characters.ts) + capabilities. A capability names the tool it
 * uses, whether it only reads or would change something, whether the student must confirm it, and whether it is
 * AVAILABLE now (backed by an existing Hub API) or only PLANNED. The UI shows planned capabilities as "coming later"
 * and never runs them. Phase 1 has read-only tools only:
 *
 *   rag_chat           the existing grounded assistant (/api/v1/assistant/chat/stream or /conversations/...)
 *   knowledge_list     approved Knowledge Center documents of given categories (/api/v1/knowledge/documents)
 *   announcement_list  published announcements of a category (/api/v1/announcements)
 *   event_list         published announcements that are active or upcoming, ordered by date
 *   office_directory   the office's own desk directory (no API)
 *   office_help        how the office works (no API)
 *   human_handoff      the existing consented Global Supporter request (inside rag_chat for signed-in students,
 *                      or the Student Support page) - the student writes and sends it themselves
 *
 * Phase 2 (agent-api.ts, agent-work.tsx): the capabilities marked available below that are not Phase 1 tools run
 * through the backend agent system (app/services/agents) in each character's "Tasks" tab.
 * Future agents (competition / program discovery, drafting notices ...) plug into the same shapes:
 * `AgentTask` carries status, sources and a confirmation step; anything with access "write" must stop at
 * "needs_confirmation" until a person approves it.
 */
import type { CharacterRole } from "@/features/ai-office/characters";

export type ToolId =
  | "rag_chat" | "knowledge_list" | "announcement_list" | "event_list" | "office_directory" | "office_help"
  | "human_handoff"
  // planned (Phase 2): not executed anywhere in Phase 1
  | "scholarship_search" | "competition_discovery" | "program_discovery" | "event_monitor" | "deadline_tracker"
  | "notice_summary" | "notice_drafting" | "job_search" | "visa_procedure_guide";

export interface AgentCapability {
  id: string;
  tool: ToolId;
  status: "available" | "planned";
  access: "read" | "write";
  requiresConfirmation: boolean;
  /** Knowledge Center categories / announcement category the tool reads */
  categories?: string[];
  announcementCategory?: string;
}

export type AgentTaskStatus = "queued" | "running" | "needs_confirmation" | "done" | "failed" | "canceled";

export interface SourceRef {
  kind: "document" | "announcement" | "external";
  href: string;
  title: string;
}

/** Phase 2: a unit of work an agent performs with a tool (not created anywhere in Phase 1). */
export interface AgentTask {
  id: string;
  agentId: string;
  capabilityId: string;
  status: AgentTaskStatus;
  /** who must approve before a write action runs (always the student or an authorized staff member) */
  confirmation?: { required: boolean; approvedBy?: string; approvedAt?: string };
  sources: SourceRef[];
  result?: { summary: string; items?: { title: string; href: string; date?: string }[] };
  error?: string;
  createdAt: string;
}

export type PanelTab = "chat" | "work" | "guides" | "notices" | "events" | "opportunities" | "desks" | "help" | "support" | "about"
  // role-specific workspaces (the backend registry offers them per agent and viewer: AgentInterface.tabs)
  | "checklists" | "procedures" | "topik" | "careers" | "monitoring" | "review" | "sources" | "request" | "requests"
  | "updates" | "terms" | "queue";

const read = (id: string, tool: ToolId, extra: Partial<AgentCapability> = {}): AgentCapability =>
  ({ id, tool, status: "available", access: "read", requiresConfirmation: false, ...extra });
const planned = (id: string, tool: ToolId, access: "read" | "write" = "read"): AgentCapability =>
  ({ id, tool, status: "planned", access, requiresConfirmation: access === "write" });

/** Capabilities by role; tabs follow the order of the available ones. */
export const CAPABILITIES: Record<CharacterRole, AgentCapability[]> = {
  reception: [read("chat", "rag_chat"), read("directory", "office_directory")],
  guide: [read("help", "office_help"), read("directory", "office_directory"), read("notice_summary", "notice_summary")],
  supporter: [read("chat", "rag_chat"), planned("notice_drafting", "notice_drafting", "write")],
  supporterLead: [read("handoff", "human_handoff"), read("chat", "rag_chat")],
  visa: [read("chat", "rag_chat"), read("guides", "knowledge_list", { categories: ["visa-immigration"] }),
    read("visa_procedure_guide", "visa_procedure_guide")],
  academic: [read("chat", "rag_chat"), read("guides", "knowledge_list", { categories: ["academic-life"] }),
    read("notices", "announcement_list", { announcementCategory: "university-announcements" })],
  topik: [read("chat", "rag_chat"), read("guides", "knowledge_list", { categories: ["topik-korean"] })],
  opportunities: [
    read("opportunities", "announcement_list", { announcementCategory: "scholarships", categories: ["scholarships"] }),
    read("chat", "rag_chat"),
    read("scholarship_search", "scholarship_search"), planned("deadline_tracker", "deadline_tracker"),
    planned("competition_discovery", "competition_discovery"), planned("program_discovery", "program_discovery")],
  events: [read("events", "event_list"), read("chat", "rag_chat"), read("event_monitor", "event_monitor")],
  career: [read("chat", "rag_chat"),
    read("guides", "knowledge_list", { categories: ["employment-internships", "part-time-employment"] }),
    read("job_search", "job_search")],
  visitor: [],
};

const TAB_FOR_TOOL: Partial<Record<ToolId, PanelTab>> = {
  rag_chat: "chat", knowledge_list: "guides", announcement_list: "notices", event_list: "events",
  office_directory: "desks", office_help: "help", human_handoff: "support",
};

/** Tabs used until (or if) the backend directory with each agent's interface is available: the chat-first layout. */
export function tabsFor(role: CharacterRole): PanelTab[] {
  const tabs: PanelTab[] = [];
  for (const c of CAPABILITIES[role]) {
    if (c.status !== "available") continue;
    const tab = c.id === "opportunities" ? "opportunities" : TAB_FOR_TOOL[c.tool];
    if (tab && !tabs.includes(tab)) tabs.push(tab);
  }
  // Phase 2: every staff member has a "Tasks" tab backed by the backend agent system (second, after the main tab)
  if (CAPABILITIES[role].length > 0) tabs.splice(Math.min(1, tabs.length), 0, "work");
  if (CAPABILITIES[role].length > 0) tabs.push("about");
  return tabs;
}

export function capability(role: CharacterRole, tool: ToolId, id?: string): AgentCapability | undefined {
  return CAPABILITIES[role].find((c) => c.tool === tool && (!id || c.id === id) && c.status === "available");
}
