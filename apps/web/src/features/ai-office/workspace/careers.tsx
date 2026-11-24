"use client";

/**
 * Daniel (Career agent) - opportunity-first workspace: published career / internship notices and approved
 * employment guides (career_opportunity_search), job postings from official university websites that staff reviewed
 * and approved (opportunity_search, kind=job), and the honest status of external job search (not connected).
 */
import { useState } from "react";
import { useTranslations } from "next-intl";
import { Info, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { agentApi, useAgentTasks } from "@/features/ai-office/agent-api";
import { useWorkspace } from "@/features/ai-office/workspace/context";
import { byDeadline } from "@/features/ai-office/workspace/opportunities";
import {
  AgentTaskList, EmptyState, LoadState, Notes, OpportunityCard, WorkspaceSection, useCommonNextSteps,
} from "@/features/ai-office/workspace/parts";
import { useApi } from "@/lib/use-api";

export function CareersWorkspace() {
  const ws = useWorkspace();
  const t = useTranslations("office.ws.careers");
  const [draft, setDraft] = useState("");
  const [q, setQ] = useState("");
  const [showExpired, setShowExpired] = useState(false);
  const base = q ? { q } : {};
  const hub = useApi(`ws-career:${ws.agent.id}:${q}:${showExpired}:${ws.language}`, () =>
    agentApi.tool(ws.agent.id, "career_opportunity_search", { ...base, include_expired: showExpired, limit: 30 }, ws.language));
  const jobs = useApi(`ws-jobs:${ws.agent.id}:${q}:${ws.isAdmin}`, () =>
    agentApi.tool(ws.agent.id, "opportunity_search", { ...base, kind: "job", limit: 20 }, ws.language));
  const { tasks, reload } = useAgentTasks(ws.agent, ws.signedIn, ws.onChanged);
  const external = ws.agent.tools.find((x) => x.name === "official_web_search");
  const tNext = useTranslations("office.ws.next");
  const common = useCommonNextSteps();
  const guides = { label: tNext("employmentGuides"), onClick: () => ws.openTab("guides") };
  const notices = [...(hub.data?.result.items ?? [])].sort(byDeadline);
  // only reviewed + approved postings (admins also receive unreviewed candidates: those stay in review)
  const postings = (jobs.data?.result.items ?? []).filter((i) => i.reliability === "verified");

  return (
    <div className="space-y-4" data-testid="ws-careers">
      <p className="text-muted-foreground">{t("intro")}</p>
      <form className="flex gap-2" role="search" onSubmit={(e) => { e.preventDefault(); setQ(draft.trim()); }}>
        <label htmlFor="career-search" className="sr-only">{t("search")}</label>
        <input id="career-search" value={draft} onChange={(e) => setDraft(e.target.value)} placeholder={t("searchPlaceholder")}
          maxLength={200} className="min-h-10 min-w-0 flex-1 rounded-xl border border-input bg-background px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring" />
        <Button type="submit" size="sm" className="min-h-10" aria-label={t("search")}><Search className="size-4" aria-hidden /></Button>
      </form>
      <label className="flex min-h-9 items-center gap-2 text-xs">
        <input type="checkbox" checked={showExpired} onChange={(e) => setShowExpired(e.target.checked)} className="size-4" />
        {t("showExpired")}
      </label>

      <WorkspaceSection title={t("noticesTitle", { count: notices.length })} testId="career-notices">
        <LoadState loading={hub.loading && !hub.data} error={hub.error} onRetry={hub.reload} />
        {hub.data && (notices.length === 0 ? <EmptyState next={[...(q ? [{ label: tNext("clearSearch"), onClick: () => { setQ(""); setDraft(""); } }] : []),
          guides, ...common.askChat]}>{q ? t("noMatch") : t("noNotices")}</EmptyState> : (
          <ul className="space-y-2">{notices.map((item, i) => <li key={`${item.href}-${i}`}><OpportunityCard item={item} /></li>)}</ul>
        ))}
        <Notes notes={hub.data?.result.notes.filter((n) => n !== "nothing_published") ?? []} />
      </WorkspaceSection>

      <WorkspaceSection title={t("postingsTitle", { count: postings.length })} testId="career-postings">
        <LoadState loading={jobs.loading && !jobs.data} error={jobs.error} onRetry={jobs.reload} />
        {jobs.data && (postings.length === 0 ? <EmptyState next={[{ label: tNext("careerNotices"), href: "/announcements" },
          common.human]}>{t("noPostings")}</EmptyState> : (
          <ul className="space-y-2">{postings.map((item) => <li key={item.id}><OpportunityCard item={item} /></li>)}</ul>
        ))}
      </WorkspaceSection>

      <p className="flex items-start gap-2 rounded-xl bg-sky-50 p-3 text-xs text-sky-950 dark:bg-sky-950/30 dark:text-sky-100" data-testid="external-search-status"
        data-available={external?.available ? "true" : "false"}>
        <Info className="mt-0.5 size-4 shrink-0" aria-hidden />
        {external?.available ? t("externalOn") : t("externalOff")}
      </p>

      <Button variant="outline" size="sm" className="min-h-9" onClick={() => ws.openTab("guides")}>{t("openGuides")}</Button>

      <AgentTaskList tasks={tasks} title={t("myResults")} onChanged={() => { void reload(); ws.onChanged(); }} />
    </div>
  );
}
