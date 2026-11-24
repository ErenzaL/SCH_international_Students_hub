"use client";

/**
 * Leo (Scholarship agent) - discovery-first workspace. Shows ONLY approved content: published Hub notices and
 * guides (scholarship_search) and official-site notices that an admin reviewed and the Knowledge Center approved
 * (opportunity_search; the backend returns nothing else to non-admins). Admins additionally get a strip pointing
 * to the review queue; unreviewed candidates are never mixed into this list, not even for admins.
 */
import { useState } from "react";
import { useTranslations } from "next-intl";
import { Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { agentApi, useAgentTasks, type ResultItem } from "@/features/ai-office/agent-api";
import { fmt } from "@/features/ai-office/agent-work";
import { useWorkspace } from "@/features/ai-office/workspace/context";
import {
  AdminStrip, AgentActionBar, AgentTaskList, EmptyState, FilterChips, LoadState, Notes, OpportunityCard, SignInPrompt,
  WorkspaceSection, daysUntil,
} from "@/features/ai-office/workspace/parts";
import { useApi } from "@/lib/use-api";

type Kind = "all" | "scholarship" | "competition" | "program";

/** soonest future deadline first, then items without a deadline, then passed ones */
export function byDeadline(a: ResultItem, b: ResultItem): number {
  const rank = (i: ResultItem) => {
    const d = daysUntil(i.next_deadline ?? i.deadline);
    return d === null ? [1, 0] : d < 0 ? [2, -d] : [0, d];
  };
  const [ra, da] = rank(a);
  const [rb, db] = rank(b);
  return ra - rb || da - db || (a.title ?? "").localeCompare(b.title ?? "");
}

export function OpportunitiesWorkspace() {
  const ws = useWorkspace();
  const t = useTranslations("office.ws.opp");
  const [kind, setKind] = useState<Kind>("all");
  const [draft, setDraft] = useState("");
  const [q, setQ] = useState("");
  const [showClosed, setShowClosed] = useState(false);
  const base = q ? { q, limit: 30 } : { limit: 30 };
  const hub = useApi(`ws-opp-hub:${ws.agent.id}:${q}:${showClosed}:${ws.language}`, () =>
    agentApi.tool(ws.agent.id, "scholarship_search", { ...base, include_expired: showClosed }, ws.language));
  const official = useApi(`ws-opp-official:${ws.agent.id}:${q}:${showClosed}:${ws.isAdmin}`, () =>
    agentApi.tool(ws.agent.id, "opportunity_search", { ...base, include_closed: showClosed }, ws.language));
  const monitor = useApi(`ws-mon:${ws.agent.id}`, () => agentApi.monitoring(ws.agent.id));
  const { tasks, reload } = useAgentTasks(ws.agent, ws.signedIn, ws.onChanged);

  const officialAll = official.data?.result.items ?? [];
  // admins receive unreviewed candidates from the same tool: those belong to the Review tab, never to this list
  const reviewed = officialAll.filter((i) => i.reliability === "verified");
  const unreviewed = officialAll.length - reviewed.length;
  const seen = new Set(reviewed.map((i) => i.href));
  const items = [...reviewed, ...(hub.data?.result.items ?? []).filter((i) => !seen.has(i.href))]
    .filter((i) => kind === "all" || (i.opportunity_kind ?? "scholarship") === kind).sort(byDeadline);

  const loading = (hub.loading && !hub.data) || (official.loading && !official.data);
  const actionIds = ws.agent.interface?.task_actions ?? [];
  const isAdminAction = (id: string) => ws.agent.actions.some((a) => a.id === id && a.admin_only);
  const notes = [...(hub.data?.result.notes ?? []), ...(official.data?.result.notes ?? [])]
    .filter((n) => n !== "official_unreviewed" && n !== "no_discoveries");

  return (
    <div className="space-y-4" data-testid="ws-opportunities">
      <p className="text-muted-foreground">{t("intro")}</p>
      <form className="flex gap-2" role="search" onSubmit={(e) => { e.preventDefault(); setQ(draft.trim()); }}>
        <label htmlFor="opp-search" className="sr-only">{t("search")}</label>
        <input id="opp-search" value={draft} onChange={(e) => setDraft(e.target.value)} placeholder={t("searchPlaceholder")}
          maxLength={200} data-testid="opp-search"
          className="min-h-10 min-w-0 flex-1 rounded-xl border border-input bg-background px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring" />
        <Button type="submit" size="sm" className="min-h-10" aria-label={t("search")}><Search className="size-4" aria-hidden /></Button>
      </form>
      <FilterChips label={t("kindFilter")} value={kind} onChange={setKind} testId="opp-kind-filter"
        options={(["all", "scholarship", "competition", "program"] as const).map((id) => ({ id, label: t(`kinds.${id}`) }))} />
      <label className="flex min-h-9 items-center gap-2 text-xs">
        <input type="checkbox" checked={showClosed} onChange={(e) => setShowClosed(e.target.checked)} className="size-4" data-testid="opp-show-closed" />
        {t("showClosed")}
      </label>

      <WorkspaceSection title={t("listTitle", { count: items.length })} testId="opportunity-list"
        action={monitor.data?.last_checked_at
          ? <span className="text-[11px] text-muted-foreground" data-testid="opp-last-checked">{t("lastChecked", { when: fmt(monitor.data.last_checked_at) })}</span>
          : null}>
        <LoadState loading={loading} error={hub.error ?? official.error} onRetry={() => { hub.reload(); official.reload(); }} />
        {!loading && !hub.error && (items.length === 0 ? <EmptyState>{q || kind !== "all" ? t("noMatch") : t("empty")}</EmptyState> : (
          <ul className="space-y-2">
            {items.map((item, i) => <li key={`${item.href ?? item.id}-${i}`}><OpportunityCard item={item} /></li>)}
          </ul>
        ))}
        <Notes notes={notes} />
      </WorkspaceSection>

      {monitor.data && monitor.data.sources.length > 0 && (
        <p className="text-xs text-muted-foreground" data-testid="opp-sources">
          {t("watching", { names: monitor.data.sources.map((s) => s.name).join(", ") })}
        </p>
      )}

      <AdminStrip>
        <p className="text-xs" data-testid="admin-unreviewed">{t("adminUnreviewed", { count: unreviewed })}</p>
        <div className="flex flex-wrap gap-1.5">
          <Button size="sm" variant="outline" className="min-h-9" onClick={() => ws.openTab("review")} data-testid="open-review">{t("openReview")}</Button>
          <Button size="sm" variant="outline" className="min-h-9" onClick={() => ws.openTab("sources")}>{t("openSources")}</Button>
        </div>
        <AgentActionBar ids={actionIds.filter(isAdminAction)} onDone={() => void reload()} />
      </AdminStrip>

      <WorkspaceSection title={t("myChecks")}>
        <p className="text-xs text-muted-foreground">{t("myChecksHint")}</p>
        {ws.signedIn ? (
          <AgentActionBar ids={actionIds.filter((id) => !isAdminAction(id))} onDone={() => void reload()} />
        ) : <SignInPrompt text={t("signInForChecks")} />}
        <AgentTaskList tasks={tasks} types={["scholarship_scan"]} title={t("recentChecks")} onChanged={() => { void reload(); ws.onChanged(); }} />
      </WorkspaceSection>
    </div>
  );
}
