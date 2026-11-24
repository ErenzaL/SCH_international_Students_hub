"use client";

/**
 * "Updates" of a desk with official sources (Yuna, Joon, Seo, Mia, Daniel): when its official websites were last checked and
 * which of their items staff reviewed and approved. Candidates that nobody reviewed are only returned to admins (and labelled).
 */
import { useTranslations } from "next-intl";
import { ExternalLink, Radar } from "lucide-react";
import { agentApi, useAgentTasks } from "@/features/ai-office/agent-api";
import { AgentResultCard, fmt } from "@/features/ai-office/agent-work";
import { HealthChip, ScheduleState } from "@/features/ai-office/workspace/admin";
import { useWorkspace } from "@/features/ai-office/workspace/context";
import {
  AdminStrip, AgentActionBar, AgentTaskList, EmptyState, LoadState, Notes, WorkspaceSection, useCommonNextSteps,
} from "@/features/ai-office/workspace/parts";
import { useApi } from "@/lib/use-api";

const CHECKS = ["guidance_discovery", "event_discovery", "opportunity_discovery", "announcement_discovery"];

export function UpdatesWorkspace() {
  const ws = useWorkspace();
  const t = useTranslations("office.ws.updates");
  const tMon = useTranslations("office.ws.mon");
  const common = useCommonNextSteps();
  const running = Boolean(ws.agent.monitoring_check_running);
  const key = `${ws.agent.id}:${running ? 1 : 0}`;
  const mon = useApi(`ws-up-mon:${key}`, () => agentApi.monitoring(ws.agent.id));
  const items = useApi(`ws-up:${key}`, () => agentApi.tool(ws.agent.id, "official_updates", { limit: 20 }, ws.language));
  const { tasks, reload } = useAgentTasks(ws.agent, ws.signedIn, ws.onChanged);
  const status = mon.data;
  const result = items.data?.result;
  const adminActions = (ws.agent.interface?.task_actions ?? []).filter((id) => ws.agent.actions.some((a) => a.id === id && a.admin_only));

  return (
    <div className="space-y-5" data-testid="ws-updates">
      <p className="text-muted-foreground">{t("intro")}</p>
      <section className={`space-y-2 rounded-2xl p-3 ${running ? "bg-sky-50 dark:bg-sky-950/30" : "bg-muted/50"}`} aria-live="polite"
        data-testid="updates-status" data-checking={running ? "true" : "false"}>
        <p className="flex items-center gap-2 font-semibold"><Radar className="size-4 text-primary" aria-hidden />{running ? tMon("checkingNow") : tMon("notChecking")}</p>
        <LoadState loading={mon.loading && !status} error={mon.error} onRetry={mon.reload} />
        {status && (
          <>
            <p className="text-xs text-muted-foreground" data-testid="last-check">
              {status.last_checked_at ? tMon("lastCheck", { when: fmt(status.last_checked_at) }) : tMon("noCheckYet")}
              {status.last_success_at ? ` · ${tMon("lastSuccess", { when: fmt(status.last_success_at) })}` : ""}
            </p>
            {status.schedules.length > 0
              ? <ul className="space-y-1">{status.schedules.map((s) => <li key={s.task_type}><ScheduleState s={s} /></li>)}</ul>
              : <p className="text-xs text-muted-foreground">{tMon("noSchedule")}</p>}
          </>
        )}
      </section>

      <WorkspaceSection title={t("listTitle")} testId="updates-list">
        <LoadState loading={items.loading && !result} error={items.error} onRetry={items.reload} />
        {result && (result.items.length === 0
          ? <EmptyState next={[...common.askChat]}>{status && status.sources.length === 0 ? tMon("noSources") : t("empty")}</EmptyState>
          : <ul className="space-y-2">{result.items.map((i) => <li key={i.id}><AgentResultCard item={i} /></li>)}</ul>)}
        {result && result.items.length > 0 && <Notes notes={result.notes} />}
      </WorkspaceSection>

      {status && status.sources.length > 0 && (
        <WorkspaceSection title={tMon("sourcesTitle", { count: status.sources.length })} testId="monitored-sources">
          <ul className="space-y-1.5">
            {status.sources.map((s) => (
              <li key={s.url} className="flex flex-wrap items-center gap-1.5 rounded-xl border border-border px-3 py-2 text-xs">
                <a href={s.url} target="_blank" rel="noopener noreferrer" className="min-w-0 break-words font-semibold text-primary hover:underline">
                  {s.name} <ExternalLink className="inline size-3" aria-hidden />
                </a>
                <HealthChip health={s.health} />
              </li>
            ))}
          </ul>
        </WorkspaceSection>
      )}

      <AdminStrip>
        {status?.candidates_waiting !== undefined && <p className="text-xs">{tMon("candidatesWaiting", { count: status.candidates_waiting })}</p>}
        <AgentActionBar ids={adminActions} onDone={() => { void reload(); mon.reload(); items.reload(); }} />
        <AgentTaskList tasks={tasks} types={CHECKS} limit={2} hideWhenEmpty title={t("checks")} onChanged={() => { void reload(); ws.onChanged(); }} />
      </AdminStrip>
    </div>
  );
}
