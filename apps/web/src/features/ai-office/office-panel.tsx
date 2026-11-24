"use client";

/**
 * The selected character's panel. Each employee opens its own workspace, chosen by the backend registry
 * (AgentInterface): chat-first for Hana and the language supporters (the EXISTING assistant, same hook and view as
 * the floating chat widget), service checklists for Yuna / Joon / Seo, discovery lists for Leo / Mia / Daniel, a
 * monitoring desk for Robo and a request workspace for Sumin. Each character keeps its own conversation.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { BadgeCheck, Clock, History, LifeBuoy, Lock, Minus, Plus, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ChatBody } from "@/features/chatbot/chat-body";
import { useAssistantChat } from "@/features/chatbot/use-assistant-chat";
import type { AgentInfo } from "@/features/ai-office/agent-api";
import { AgentWork } from "@/features/ai-office/agent-work";
import { CAPABILITIES, capability, tabsFor, type PanelTab } from "@/features/ai-office/agents";
import { INTERACTIVE, type OfficeCharacter } from "@/features/ai-office/characters";
import { EventsList, GuidesList, NoticesList, OpportunitiesList } from "@/features/ai-office/desk-resources";
import { Portrait } from "@/features/ai-office/portrait";
import { SUPPORTER_LINES } from "@/features/ai-office/supporter-lines";
import { useOfficeLabels } from "@/features/ai-office/use-office-labels";
import { WorkspaceContext, type WorkspaceContextValue } from "@/features/ai-office/workspace/context";
import { WORKSPACE_VIEWS, WorkspaceView } from "@/features/ai-office/workspace/index";
import { AgentHeader, AgentWorkspaceShell } from "@/features/ai-office/workspace/parts";
import { cn } from "@/lib/utils";
import type { LanguageCode } from "@/types/api";

export function OfficePanel({ c, minimized, onClose, onMinimize, onRestore, onSelect, agent, agents, agentsSignedIn = false,
  agentsAdmin = false, onAgentsChanged }: {
  c: OfficeCharacter;
  minimized: boolean;
  onClose: () => void;
  onMinimize: () => void;
  onRestore: () => void;
  onSelect: (id: string) => void;
  /** this character's backend agent (directory entry, incl. its interface for this viewer) and all agents */
  agent?: AgentInfo;
  agents?: AgentInfo[] | null;
  agentsSignedIn?: boolean;
  agentsAdmin?: boolean;
  onAgentsChanged?: () => void;
}) {
  const t = useTranslations("office");
  const locale = useLocale() as LanguageCode;
  const labels = useOfficeLabels();
  // the backend chooses the workspace (interface type, default view, tabs for this viewer); until the directory is
  // loaded - or if it cannot be - the chat-first layout is used
  const iface = agent?.interface;
  const tabs = (iface?.tabs as PanelTab[] | undefined) ?? tabsFor(c.role);
  const defaultTab = (iface?.default_view as PanelTab | undefined) ?? tabs[0] ?? "about";
  const [chosen, setChosen] = useState<PanelTab | null>(null);
  const tab: PanelTab = chosen && tabs.includes(chosen) ? chosen : defaultTab;
  const language = c.language ?? locale;
  const chat = useAssistantChat({ language, scope: `office:${c.id}`, active: !minimized && tab === "chat" });
  const heading = useRef<HTMLHeadingElement>(null);
  const signedIn = agentsSignedIn || chat.signedIn;
  const changed = useCallback(() => onAgentsChanged?.(), [onAgentsChanged]);

  // chat characters: the message box gets focus (ChatBody); workspaces: the panel heading, for screen readers
  useEffect(() => {
    if (!minimized && defaultTab !== "chat") heading.current?.focus();
  }, [minimized, defaultTab]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && !minimized && onClose();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [minimized, onClose]);

  const role = labels.roleTitle(c);
  const lines = c.role === "supporter" && c.language ? SUPPORTER_LINES[c.language] : null;
  // only characters with a chat have welcome / example texts (the guide robot has none)
  const hasChat = tabs.includes("chat");
  const welcome = lines ? lines.welcome : hasChat ? t(`desk.${c.role}.welcome`, { name: c.name }) : "";
  const examples = lines ? [...lines.examples] : hasChat
    ? [t(`desk.${c.role}.example1`), t(`desk.${c.role}.example2`), t(`desk.${c.role}.example3`)] : [];

  const ctx: WorkspaceContextValue | null = agent ? {
    c, agent, agents: agents ?? null, signedIn, isAdmin: agentsAdmin, language, onChanged: changed, onSelect,
    openTab: setChosen,
    askInChat: hasChat ? (message: string) => {
      setChosen("chat");
      void chat.send(message);
    } : undefined,
  } : null;

  if (minimized) {
    return (
      <button type="button" onClick={onRestore} data-testid="panel-restore"
        className="fixed bottom-[calc(1rem+env(safe-area-inset-bottom))] right-4 z-[45] flex items-center gap-2 rounded-full bg-white py-1.5 pl-1.5 pr-4 text-sm font-semibold text-[#3D4B5C] shadow-xl ring-1 ring-black/5 hover:bg-[#F4F8FC]">
        <Portrait c={c} size={36} />
        {chat.busy ? t("answering", { name: c.name }) : t("restore", { name: c.name })}
      </button>
    );
  }

  const workspace = Boolean(iface && ctx && WORKSPACE_VIEWS[tab]);
  return (
    <AgentWorkspaceShell type={iface?.type ?? "CHAT"}>
      <AgentHeader c={c} title={c.name} agent={agent} headingRef={heading} onBack={onClose}
        subtitle={(
          <>
            <span className="block truncate">{role}</span>
            {hasChat && tab === "chat" && (
              <span className="block truncate font-medium text-[#3D6A8C] dark:text-sky-300" data-testid="panel-language">
                {c.language ? t("answersIn", { language: labels.languageName(language) }) : t("siteLanguage", { language: labels.languageName(language) })}
              </span>
            )}
          </>
        )}
        controls={(
          <>
            {tab === "chat" && chat.signedIn && (
              <Button size="sm" variant="ghost" className="size-9 p-0" aria-label={t("history")} onClick={() => void chat.openHistory()}><History /></Button>
            )}
            {tab === "chat" && (
              <Button size="sm" variant="ghost" className="size-9 p-0" aria-label={t("newChat")} onClick={chat.newChat}><Plus /></Button>
            )}
            <Button size="sm" variant="ghost" className="hidden size-8 p-0 md:inline-flex" aria-label={t("minimize")} onClick={onMinimize}><Minus /></Button>
            <Button size="sm" variant="ghost" className="hidden size-8 p-0 md:inline-flex" aria-label={t("close")} onClick={onClose} data-testid="panel-close"><X /></Button>
          </>
        )} />
      {tabs.length > 1 && (
        <div role="tablist" aria-label={t("tabsLabel")} className="border-b border-border px-2 py-1.5" data-testid="panel-tabs">
          {/* phones scroll the tabs sideways; desktop wraps them so every tab stays visible */}
          <div className="flex gap-1 overflow-x-auto md:flex-wrap md:overflow-visible">
            {tabs.filter((id) => !ADMIN_TABS.has(id)).map((id) => <TabButton key={id} id={id} selected={tab === id} onSelect={setChosen} />)}
          </div>
          {/* admins: the review and source tools always have their own visible row (the API checks the role again) */}
          {tabs.some((id) => ADMIN_TABS.has(id)) && (
            <div className="mt-1 flex items-center gap-1 border-t border-dashed border-violet-200 pt-1 dark:border-violet-900" data-testid="admin-tabs">
              <span className="flex items-center gap-1 px-1 text-[10px] font-bold uppercase tracking-wide text-violet-800 dark:text-violet-300">
                <Lock className="size-3" aria-hidden /> {t("ws.adminTabs")}
              </span>
              {tabs.filter((id) => ADMIN_TABS.has(id)).map((id) => <TabButton key={id} id={id} selected={tab === id} onSelect={setChosen} admin />)}
            </div>
          )}
        </div>
      )}
      {tab === "chat" ? (
        <ChatBody chat={chat} welcome={welcome} examples={examples} inputId="office-chat-input" lang={lines ? language : undefined} />
      ) : (
        <div className="flex-1 space-y-4 overflow-y-auto overscroll-contain p-4 pb-[max(1rem,env(safe-area-inset-bottom))] text-sm" role="tabpanel"
          data-testid="workspace" data-view={tab}>
          {workspace && ctx ? (
            <WorkspaceContext.Provider value={ctx}><WorkspaceView view={tab} /></WorkspaceContext.Provider>
          ) : (
            <>
              {tab === "guides" && <GuidesList categories={capability(c.role, "knowledge_list")?.categories ?? []} />}
              {tab === "notices" && <NoticesList category={capability(c.role, "announcement_list")?.announcementCategory} />}
              {tab === "events" && <EventsList />}
              {tab === "opportunities" && (
                <OpportunitiesList announcementCategory={capability(c.role, "announcement_list", "opportunities")?.announcementCategory ?? "scholarships"}
                  categories={capability(c.role, "announcement_list", "opportunities")?.categories ?? ["scholarships"]} />
              )}
              {tab === "desks" && <Directory self={c.id} onSelect={onSelect} />}
              {tab === "help" && <HelpContent />}
              {tab === "support" && <SupportContent signedIn={chat.signedIn} onAskInChat={() => {
                chat.setDraft(t("support.draft"));
                setChosen("chat");
              }} />}
              {tab === "about" && <Capabilities c={c} />}
              {tab === "work" && (
                <AgentWork c={c} agent={agent} agents={agents ?? null} signedIn={signedIn} isAdmin={agentsAdmin}
                  onSelect={onSelect} onChanged={changed}
                  onAnswerInChat={(message) => {
                    setChosen("chat");
                    void chat.send(message);
                  }} />
              )}
              {(tab === "guides" || tab === "notices" || tab === "events" || tab === "opportunities") && hasChat && (
                <Button variant="outline" size="sm" onClick={() => setChosen("chat")}>{t("askMe", { name: c.name })}</Button>
              )}
            </>
          )}
        </div>
      )}
    </AgentWorkspaceShell>
  );
}

const ADMIN_TABS = new Set<PanelTab>(["review", "sources", "queue"]);

function TabButton({ id, selected, onSelect, admin = false }: {
  id: PanelTab;
  selected: boolean;
  onSelect: (id: PanelTab) => void;
  admin?: boolean;
}) {
  const t = useTranslations("office");
  return (
    <button type="button" role="tab" aria-selected={selected} data-testid={`tab-${id}`} onClick={() => onSelect(id)}
      className={cn("min-h-9 shrink-0 rounded-full px-3 py-1.5 text-xs font-semibold",
        selected ? (admin ? "bg-violet-700 text-white" : "bg-[#3D6A8C] text-white")
          : admin ? "text-violet-800 hover:bg-violet-50 dark:text-violet-300 dark:hover:bg-violet-950/40"
            : "text-[#4B5D73] hover:bg-muted dark:text-foreground")}>
      {t(`tabs.${id}`)}
    </button>
  );
}

export { Portrait };

function Directory({ self, onSelect }: { self: string; onSelect: (id: string) => void }) {
  const t = useTranslations("office");
  const labels = useOfficeLabels();
  return (
    <section className="space-y-2" data-testid="desk-directory">
      <h3 className="text-sm font-semibold">{t("directory.title")}</h3>
      <ul className="space-y-1">
        {INTERACTIVE.filter((x) => x.id !== self).map((x) => (
          <li key={x.id}>
            <button type="button" onClick={() => onSelect(x.id)}
              className="flex w-full items-center gap-3 rounded-xl px-2 py-1.5 text-left hover:bg-muted">
              <Portrait c={x} size={36} />
              <span className="min-w-0">
                <span className="block font-medium">{x.name} · {labels.roleTitle(x)}</span>
                <span className="block truncate text-xs text-muted-foreground">{labels.roleDescription(x)}</span>
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function HelpContent() {
  const t = useTranslations("office.helpDialog");
  return (
    <section className="space-y-3" data-testid="office-help">
      <p>{t("intro")}</p>
      <ol className="list-decimal space-y-1.5 pl-5">
        {["step1", "step2", "step3", "step4"].map((k) => <li key={k}>{t(k)}</li>)}
      </ol>
      <p className="text-muted-foreground">{t("privacy")}</p>
      <p className="text-muted-foreground">{t("motion")}</p>
    </section>
  );
}

function SupportContent({ signedIn, onAskInChat }: { signedIn: boolean; onAskInChat: () => void }) {
  const t = useTranslations("office.support");
  return (
    <section className="space-y-3" data-testid="desk-support">
      <h3 className="flex items-center gap-2 text-sm font-semibold"><LifeBuoy className="size-4 text-primary" aria-hidden /> {t("title")}</h3>
      <p>{signedIn ? t("signedInBody") : t("body")}</p>
      <div className="flex flex-wrap gap-2">
        <Button asChild size="sm"><Link href="/support">{t("goToSupport")}</Link></Button>
        {signedIn ? (
          <Button size="sm" variant="outline" onClick={onAskInChat}>{t("askInChat")}</Button>
        ) : (
          <Button asChild size="sm" variant="outline"><Link href="/login?next=%2Fai-office">{t("signIn")}</Link></Button>
        )}
      </div>
    </section>
  );
}

function Capabilities({ c }: { c: OfficeCharacter }) {
  const t = useTranslations("office.about");
  const caps = CAPABILITIES[c.role];
  return (
    <section className="space-y-3" data-testid="desk-capabilities">
      {(["available", "planned"] as const).map((status) => {
        const list = caps.filter((x) => x.status === status);
        if (!list.length) return null;
        return (
          <div key={status} className="space-y-1.5">
            <h3 className="flex items-center gap-1.5 text-sm font-semibold">
              {status === "available" ? <BadgeCheck className="size-4 text-emerald-600" aria-hidden /> : <Clock className="size-4 text-amber-600" aria-hidden />}
              {t(status)}
            </h3>
            <ul className="space-y-1">
              {list.map((x) => (
                <li key={x.id} className={cn("rounded-xl px-3 py-2", status === "available" ? "bg-emerald-50 dark:bg-emerald-950/30" : "bg-amber-50 dark:bg-amber-950/30")}
                  data-status={status}>
                  {t(`tools.${x.tool}`)}
                  {x.access === "write" && <span className="ml-1 text-xs text-muted-foreground">({t("confirm")})</span>}
                </li>
              ))}
            </ul>
          </div>
        );
      })}
      {caps.some((x) => x.status === "planned") && <p className="text-xs text-muted-foreground">{t("plannedNote")}</p>}
    </section>
  );
}
