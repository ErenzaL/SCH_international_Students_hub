"use client";

/**
 * Conversation / desk panel for the selected character. The chat is the EXISTING assistant (same hook and view as
 * the floating chat widget): language supporters fix the answer language to theirs; desk staff answer in the site
 * language. Desk tabs show real Hub data (desk-resources). Each character keeps its own conversation.
 */
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { BadgeCheck, Clock, History, LifeBuoy, Minus, Plus, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ChatBody } from "@/features/chatbot/chat-body";
import { useAssistantChat } from "@/features/chatbot/use-assistant-chat";
import type { AgentInfo } from "@/features/ai-office/agent-api";
import { AgentWork } from "@/features/ai-office/agent-work";
import { CAPABILITIES, capability, tabsFor, type PanelTab } from "@/features/ai-office/agents";
import { INTERACTIVE, type OfficeCharacter } from "@/features/ai-office/characters";
import { EventsList, GuidesList, NoticesList, OpportunitiesList } from "@/features/ai-office/desk-resources";
import { SUPPORTER_LINES } from "@/features/ai-office/supporter-lines";
import { useOfficeLabels } from "@/features/ai-office/use-office-labels";
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
  /** Phase 2: this character's backend agent (directory entry) and all agents (names for delegation) */
  agent?: AgentInfo;
  agents?: AgentInfo[] | null;
  agentsSignedIn?: boolean;
  agentsAdmin?: boolean;
  onAgentsChanged?: () => void;
}) {
  const t = useTranslations("office");
  const locale = useLocale() as LanguageCode;
  const labels = useOfficeLabels();
  const tabs = tabsFor(c.role);
  const [tab, setTab] = useState<PanelTab>(tabs[0] ?? "about");
  const language = c.language ?? locale;
  const chat = useAssistantChat({ language, scope: `office:${c.id}`, active: !minimized && tab === "chat" });
  const heading = useRef<HTMLHeadingElement>(null);

  // chat characters: the message box gets focus (ChatBody); others: the panel heading, for screen readers
  const firstTab = tabs[0];
  useEffect(() => {
    if (!minimized && firstTab !== "chat") heading.current?.focus();
  }, [minimized, firstTab]);

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

  if (minimized) {
    return (
      <button type="button" onClick={onRestore} data-testid="panel-restore"
        className="fixed bottom-[calc(1rem+env(safe-area-inset-bottom))] right-4 z-[45] flex items-center gap-2 rounded-full bg-white py-1.5 pl-1.5 pr-4 text-sm font-semibold text-[#3D4B5C] shadow-xl ring-1 ring-black/5 hover:bg-[#F4F8FC]">
        <Portrait c={c} size={36} />
        {chat.busy ? t("answering", { name: c.name }) : t("restore", { name: c.name })}
      </button>
    );
  }

  return (
    <section role="dialog" aria-modal="false" aria-labelledby="office-panel-title" data-testid="office-panel"
      className="fixed inset-0 z-[45] flex h-[100dvh] flex-col bg-card text-card-foreground md:inset-auto md:bottom-4 md:right-4 md:top-4 md:h-auto md:w-[420px] md:rounded-3xl md:border md:border-border md:shadow-2xl">
      <header className="flex items-center gap-3 rounded-t-3xl border-b border-border bg-[#F7FAFD] px-3 py-2.5 pt-[max(0.625rem,env(safe-area-inset-top))] md:pt-2.5">
        <Portrait c={c} size={52} />
        <div className="min-w-0 flex-1">
          <h2 id="office-panel-title" ref={heading} tabIndex={-1} className="truncate text-base font-bold outline-none">{c.name}</h2>
          <p className="truncate text-xs text-muted-foreground">{role}</p>
          {tabs.includes("chat") && (
            <p className="truncate text-xs font-medium text-[#3D6A8C]" data-testid="panel-language">
              {c.language ? t("answersIn", { language: labels.languageName(language) }) : t("siteLanguage", { language: labels.languageName(language) })}
            </p>
          )}
        </div>
        {tab === "chat" && chat.signedIn && (
          <Button size="sm" variant="ghost" className="size-8 p-0" aria-label={t("history")} onClick={() => void chat.openHistory()}><History /></Button>
        )}
        {tab === "chat" && (
          <Button size="sm" variant="ghost" className="size-8 p-0" aria-label={t("newChat")} onClick={chat.newChat}><Plus /></Button>
        )}
        <Button size="sm" variant="ghost" className="hidden size-8 p-0 md:inline-flex" aria-label={t("minimize")} onClick={onMinimize}><Minus /></Button>
        <Button size="sm" variant="ghost" className="size-8 p-0" aria-label={t("close")} onClick={onClose} data-testid="panel-close"><X /></Button>
      </header>
      {tabs.length > 1 && (
        <div role="tablist" aria-label={t("tabsLabel")} className="flex gap-1 overflow-x-auto border-b border-border px-2 py-1.5">
          {tabs.map((id) => (
            <button key={id} type="button" role="tab" aria-selected={tab === id} data-testid={`tab-${id}`}
              onClick={() => setTab(id)}
              className={cn("shrink-0 rounded-full px-3 py-1.5 text-xs font-semibold",
                tab === id ? "bg-[#3D6A8C] text-white" : "text-[#4B5D73] hover:bg-muted")}>
              {t(`tabs.${id}`)}
            </button>
          ))}
        </div>
      )}
      {tab === "chat" ? (
        <ChatBody chat={chat} welcome={welcome} examples={examples} inputId="office-chat-input" lang={lines ? language : undefined} />
      ) : (
        <div className="flex-1 space-y-4 overflow-y-auto p-4 text-sm" role="tabpanel">
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
            setTab("chat");
          }} />}
          {tab === "about" && <Capabilities c={c} />}
          {tab === "work" && (
            <AgentWork c={c} agent={agent} agents={agents ?? null} signedIn={agentsSignedIn || chat.signedIn} isAdmin={agentsAdmin}
              onSelect={onSelect} onChanged={() => onAgentsChanged?.()}
              onAnswerInChat={(message) => {
                setTab("chat");
                void chat.send(message);
              }} />
          )}
          {tab !== "about" && tab !== "help" && tab !== "work" && tabs.includes("chat") && (
            <Button variant="outline" size="sm" onClick={() => setTab("chat")}>{t("askMe", { name: c.name })}</Button>
          )}
        </div>
      )}
    </section>
  );
}

export function Portrait({ c, size }: { c: OfficeCharacter; size: number }) {
  return (
    <span className="flex shrink-0 items-end justify-center overflow-hidden rounded-2xl bg-[#E8F2FB]" style={{ width: size, height: size }}>
      {/* eslint-disable-next-line @next/next/no-img-element -- the original artwork, whole figure, not cropped */}
      <img src={`/office/characters/${c.file}`} alt="" className="h-full w-full object-contain p-0.5" />
    </span>
  );
}

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
