"use client";

/**
 * What every role-specific workspace needs about the open character: its backend agent (directory entry with the
 * interface the backend chose for this viewer), the viewer's sign-in / admin flags and navigation. The flags only
 * decide what is SHOWN; every action is checked again by the API.
 */
import { createContext, useContext } from "react";
import type { AgentInfo } from "@/features/ai-office/agent-api";
import type { PanelTab } from "@/features/ai-office/agents";
import type { OfficeCharacter } from "@/features/ai-office/characters";
import type { LanguageCode } from "@/types/api";

export interface WorkspaceContextValue {
  c: OfficeCharacter;
  agent: AgentInfo;
  agents: AgentInfo[] | null;
  signedIn: boolean;
  isAdmin: boolean;
  /** the language results are prepared in (a supporter's own language, else the site language) */
  language: LanguageCode;
  /** a task was started or changed: refresh the office's agent states */
  onChanged: () => void;
  /** open another character */
  onSelect: (characterId: string) => void;
  /** switch to another tab of this workspace */
  openTab: (tab: PanelTab) => void;
  /** open the chat tab of this character and send a question (when it has one) */
  askInChat?: (message: string) => void;
}

export const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);

export function useWorkspace(): WorkspaceContextValue {
  const ctx = useContext(WorkspaceContext);
  if (!ctx) throw new Error("useWorkspace outside a workspace");
  return ctx;
}
