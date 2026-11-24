"use client";

/**
 * Service desks: Yuna (immigration checklists + chat), Joon (academic procedures, notices, resources) and Seo
 * (TOPIK dates and resources). Each procedure is a backend action of the agent (a read-only checklist tool built
 * from approved guides with quotes); nothing is generated or invented here.
 */
import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { ArrowLeft, BookOpen, ClipboardList, Loader2, MessageCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { agentApi, type ResultItem, type ToolResult } from "@/features/ai-office/agent-api";
import { useWorkspace } from "@/features/ai-office/workspace/context";
import {
  AnnouncementCard, DeadlineDisplay, EmptyState, LoadState, Notes, SourceCitation, ToolResultList, WorkspaceSection,
  useCommonNextSteps,
} from "@/features/ai-office/workspace/parts";
import { api, ApiError } from "@/lib/api";
import { useApi } from "@/lib/use-api";
import type { AnnouncementSummary, Page } from "@/types/api";

/** Procedure topics = this agent's checklist actions (from the backend registry, in its order). */
function useTopics() {
  const ws = useWorkspace();
  const ids = ws.agent.interface?.task_actions ?? [];
  return ws.agent.actions.filter((a) => ids.includes(a.id) && a.kind === "tool" && a.target.endsWith("_checklist"));
}

function ProcedurePicker({ intro }: { intro: string }) {
  const ws = useWorkspace();
  const t = useTranslations("office.ws.procedures");
  const tActions = useTranslations("office.agent.actions");
  const tAgent = useTranslations("office.agent");
  const topics = useTopics();
  const tNext = useTranslations("office.ws.next");
  const common = useCommonNextSteps();
  const [open, setOpen] = useState<string | null>(null);
  const [result, setResult] = useState<ToolResult | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async (id: string) => {
    const a = topics.find((x) => x.id === id)!;
    setBusy(id);
    setError(null);
    try {
      const r = await agentApi.tool(ws.agent.id, a.target, a.params, ws.language);
      setResult(r.result);
      setOpen(id);
    } catch (e) {
      setError(e instanceof ApiError ? e.code : "generic");
    } finally {
      setBusy(null);
    }
  };

  if (open && result) {
    return (
      <div className="space-y-3" data-testid="procedure-result" data-topic={open}>
        <Button size="sm" variant="ghost" className="-ml-2 min-h-9" onClick={() => { setOpen(null); setResult(null); }} data-testid="procedure-back">
          <ArrowLeft className="size-4" aria-hidden /> {t("otherTopics")}
        </Button>
        <h3 className="text-base font-bold">{tActions(open)}</h3>
        {result.items.length === 0 ? <><EmptyState next={[...common.askChat, common.human]}>{t("noGuide")}</EmptyState><Notes notes={result.notes} /></>
          : <ToolResultList result={result} />}
        {ws.askInChat && (
          <Button size="sm" variant="outline" className="min-h-9" onClick={() => ws.askInChat?.(tActions(open))}>
            <MessageCircle className="size-4" aria-hidden /> {t("askAbout", { name: ws.agent.name })}
          </Button>
        )}
      </div>
    );
  }
  return (
    <WorkspaceSection title={t("title")} icon={<ClipboardList className="size-4" />} testId="procedure-topics">
      <p className="text-xs text-muted-foreground">{intro}</p>
      {topics.length === 0 ? <EmptyState next={[...common.askChat, { label: tNext("guides"), onClick: () => ws.openTab("guides") }]}>{t("noTopics")}</EmptyState> : (
        <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {topics.map((a) => (
            <li key={a.id}>
              <button type="button" onClick={() => void run(a.id)} disabled={busy !== null} data-testid={`topic-${a.id}`}
                className="flex min-h-14 w-full items-center gap-2 rounded-xl border border-border bg-background px-3 py-2 text-left text-sm font-semibold hover:border-primary/50 hover:bg-primary/5 disabled:opacity-60">
                {busy === a.id ? <Loader2 className="size-4 shrink-0 animate-spin text-primary" aria-hidden /> : <ClipboardList className="size-4 shrink-0 text-primary" aria-hidden />}
                {tActions(a.id)}
              </button>
            </li>
          ))}
        </ul>
      )}
      {error && <p role="alert" className="text-xs text-red-700">{tAgent.has(`errors.${error}`) ? tAgent(`errors.${error}`) : tAgent("errors.generic")}</p>}
    </WorkspaceSection>
  );
}

/** Yuna: immigration checklists first, with the grounded chat one tab away (hybrid). */
export function ChecklistsWorkspace() {
  const ws = useWorkspace();
  const t = useTranslations("office.ws.visa");
  return (
    <div className="space-y-4" data-testid="ws-checklists">
      <ProcedurePicker intro={t("intro")} />
      <div className="flex flex-wrap gap-1.5">
        {ws.agent.interface?.tabs.includes("chat") && (
          <Button size="sm" className="min-h-9" onClick={() => ws.openTab("chat")} data-testid="open-chat">
            <MessageCircle className="size-4" aria-hidden /> {t("askQuestion", { name: ws.agent.name })}
          </Button>
        )}
        <Button size="sm" variant="outline" className="min-h-9" onClick={() => ws.openTab("guides")}>
          <BookOpen className="size-4" aria-hidden /> {t("guides")}
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">{t("notDecision")}</p>
    </div>
  );
}

/** Joon: university procedures, the latest academic notices and Knowledge Center resources. */
export function ProceduresWorkspace() {
  const ws = useWorkspace();
  const t = useTranslations("office.ws.academic");
  const locale = useLocale();
  const tNext = useTranslations("office.ws.next");
  const notices = useApi(`ws-academic-notices:${locale}`, async () => (await api.get<Page<AnnouncementSummary>>(
    "/api/v1/announcements", { category: "university-announcements", page_size: 3, display_language: locale })).items);
  return (
    <div className="space-y-5" data-testid="ws-procedures">
      <ProcedurePicker intro={t("intro")} />
      <WorkspaceSection title={t("noticesTitle")} testId="academic-notices"
        action={<Button size="sm" variant="ghost" className="h-8 text-xs" onClick={() => ws.openTab("notices")}>{t("allNotices")}</Button>}>
        <LoadState loading={notices.loading && !notices.data} error={notices.error} onRetry={notices.reload} />
        {notices.data && (notices.data.length === 0 ? <EmptyState next={[{ label: tNext("allAnnouncements"), href: "/announcements" }]}>{t("noNotices")}</EmptyState> : (
          <ul className="space-y-2">{notices.data.map((a) => <li key={a.id}><AnnouncementCard a={a} compact /></li>)}</ul>
        ))}
      </WorkspaceSection>
      <Button size="sm" variant="outline" className="min-h-9" onClick={() => ws.openTab("guides")}>
        <BookOpen className="size-4" aria-hidden /> {t("resources")}
      </Button>
    </div>
  );
}

/** Seo: TOPIK dates and registration notices (dates quoted from published notices) and study resources. */
export function TopikWorkspace() {
  const ws = useWorkspace();
  const t = useTranslations("office.ws.topik");
  const tNext = useTranslations("office.ws.next");
  const common = useCommonNextSteps();
  const data = useApi(`ws-topik:${ws.agent.id}:${ws.language}`, () => agentApi.tool(ws.agent.id, "topik_dates", {}, ws.language));
  const items = data.data?.result.items ?? [];
  const notices = items.filter((i) => i.kind === "announcement");
  const guides = items.filter((i) => i.kind !== "announcement");
  return (
    <div className="space-y-5" data-testid="ws-topik">
      <p className="text-muted-foreground">{t("intro")}</p>
      <LoadState loading={data.loading && !data.data} error={data.error} onRetry={data.reload} />
      {data.data && (
        <>
          <WorkspaceSection title={t("datesTitle")} testId="topik-dates">
            {notices.length === 0 ? (
              <EmptyState next={[{ label: tNext("officialTopik"), href: "https://www.topik.go.kr" }, ...common.askChat]}>
                {t("noNotices")}
              </EmptyState>
            ) : (
              <ul className="space-y-2">{notices.map((n) => <li key={n.id}><TopikNotice item={n} /></li>)}</ul>
            )}
          </WorkspaceSection>
          <WorkspaceSection title={t("resourcesTitle")} testId="topik-resources">
            {guides.length === 0 ? <EmptyState next={[{ label: tNext("knowledgeCenter"), href: "/knowledge?category=topik-korean" }]}>{t("noResources")}</EmptyState> : (
              <ul className="space-y-1.5">
                {guides.map((g, i) => (
                  <li key={`${g.href}-${i}`} className="flex flex-wrap items-center gap-1.5 text-sm">
                    {g.href ? <SourceCitation href={g.href} kind="hub" label={g.title} /> : <span>{g.title}</span>}
                  </li>
                ))}
              </ul>
            )}
          </WorkspaceSection>
          <Notes notes={data.data.result.notes} />
        </>
      )}
      <Button size="sm" variant="outline" className="min-h-9" onClick={() => ws.openTab("guides")}>
        <BookOpen className="size-4" aria-hidden /> {t("allGuides")}
      </Button>
    </div>
  );
}

function TopikNotice({ item }: { item: ResultItem }) {
  const t = useTranslations("office.ws.topik");
  const dates = item.dates ?? [];
  return (
    <article className="space-y-1.5 rounded-xl border border-border bg-background p-3" data-testid="topik-notice">
      <h4 className="font-semibold leading-snug">{item.title}</h4>
      {dates.length === 0 && item.deadline && <DeadlineDisplay date={item.deadline} />}
      {dates.length === 0 && !item.deadline && <p className="text-xs text-muted-foreground">{t("noDates")}</p>}
      <ul className="space-y-1">
        {dates.slice(0, 5).map((d, i) => (
          <li key={i} className="text-xs">
            <DeadlineDisplay date={d.date} kind={d.kind === "deadline" ? "deadline" : "event"} />
            {d.quote && <span className="block pl-5 text-muted-foreground">“{d.quote}”</span>}
          </li>
        ))}
      </ul>
      {item.href && <SourceCitation href={item.href} kind="hub" label={t("openNotice")} />}
    </article>
  );
}
