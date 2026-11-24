"use client";

/**
 * Robo (Announcement agent) - monitoring-first workspace: which official websites are watched, when they were last
 * checked, whether a check is running right now (backend task state), whether automatic checks are on, recent
 * PUBLISHED announcements and the viewer's own "what changed" digests. Students never see review candidates,
 * errors or logs: the monitoring endpoint returns only names, public URLs, times and ok / attention to them.
 */
import { useLocale, useTranslations } from "next-intl";
import { ExternalLink, Loader2, Radar } from "lucide-react";
import { Button } from "@/components/ui/button";
import { agentApi, useAgentTasks, type AgentTask, type MonitoringStatus } from "@/features/ai-office/agent-api";
import { fmt } from "@/features/ai-office/agent-work";
import { HealthChip, ScheduleState } from "@/features/ai-office/workspace/admin";
import { useWorkspace } from "@/features/ai-office/workspace/context";
import {
  AdminStrip, AgentActionBar, AgentActivityTimeline, AgentTaskList, AnnouncementCard, EmptyState, LoadState,
  SignInPrompt, WorkspaceSection, type TimelineEntry,
} from "@/features/ai-office/workspace/parts";
import { api } from "@/lib/api";
import { useApi } from "@/lib/use-api";
import type { AnnouncementSummary, Page } from "@/types/api";

const DIGESTS = ["announcement_digest", "event_digest"];

export function MonitoringWorkspace() {
  const ws = useWorkspace();
  const t = useTranslations("office.ws.mon");
  const tTypes = useTranslations("office.agent.taskTypes");
  const locale = useLocale();
  const running = Boolean(ws.agent.monitoring_check_running);
  // re-read when the directory reports that a check started or finished (the directory polls the backend)
  const mon = useApi(`ws-mon:${ws.agent.id}:${running ? 1 : 0}`, () => agentApi.monitoring(ws.agent.id));
  const recent = useApi(`ws-recent:${locale}`, async () =>
    (await api.get<Page<AnnouncementSummary>>("/api/v1/announcements", { page_size: 5, display_language: locale })).items);
  const { tasks, reload } = useAgentTasks(ws.agent, ws.signedIn, ws.onChanged);
  const status = mon.data;
  const checking = running || Boolean(status?.checking);
  const actionIds = ws.agent.interface?.task_actions ?? [];
  const isAdminAction = (id: string) => ws.agent.actions.some((a) => a.id === id && a.admin_only);

  return (
    <div className="space-y-5" data-testid="ws-monitoring">
      <section className={`space-y-2 rounded-2xl p-3 ${checking ? "bg-sky-50 dark:bg-sky-950/30" : "bg-muted/50"}`}
        data-testid="monitoring-status" data-checking={checking ? "true" : "false"} aria-live="polite">
        <p className="flex items-center gap-2 font-semibold">
          {checking ? <Loader2 className="size-4 animate-spin text-sky-700" aria-hidden /> : <Radar className="size-4 text-primary" aria-hidden />}
          {checking ? t("checkingNow") : t("notChecking")}
        </p>
        <LoadState loading={mon.loading && !status} error={mon.error} onRetry={mon.reload} />
        {status && (
          <>
            <p className="text-xs text-muted-foreground" data-testid="last-check">
              {status.last_checked_at ? t("lastCheck", { when: fmt(status.last_checked_at) }) : t("noCheckYet")}
              {status.last_success_at ? ` · ${t("lastSuccess", { when: fmt(status.last_success_at) })}` : ""}
            </p>
            {status.schedules.length > 0 ? (
              <ul className="space-y-1" data-testid="schedules">
                {status.schedules.map((s) => (
                  <li key={s.task_type} className="space-y-0.5">
                    <span className="block text-[11px] font-semibold text-muted-foreground">{tTypes.has(s.task_type) ? tTypes(s.task_type) : s.task_type}</span>
                    <ScheduleState s={s} />
                  </li>
                ))}
              </ul>
            ) : <p className="text-xs text-muted-foreground">{t("noSchedule")}</p>}
          </>
        )}
      </section>

      {status && <SourcesPublic status={status} />}

      <WorkspaceSection title={t("changesTitle")} testId="changes">
        <p className="text-xs text-muted-foreground">{t("changesHint")}</p>
        {ws.signedIn ? (
          <>
            <AgentActionBar ids={actionIds.filter((id) => !isAdminAction(id))} onDone={() => void reload()} />
            <AgentTaskList tasks={tasks} types={DIGESTS} limit={1} title={t("latestDigest")}
              onChanged={() => { void reload(); ws.onChanged(); }} />
          </>
        ) : <SignInPrompt text={t("signInForDigest")} />}
      </WorkspaceSection>

      <WorkspaceSection title={t("recentTitle")} testId="recent-announcements"
        action={<Button size="sm" variant="ghost" className="h-8 text-xs" onClick={() => ws.openTab("notices")}>{t("allNotices")}</Button>}>
        <LoadState loading={recent.loading && !recent.data} error={recent.error} onRetry={recent.reload} />
        {recent.data && (recent.data.length === 0 ? <EmptyState>{t("noRecent")}</EmptyState> : (
          <ul className="space-y-2">{recent.data.map((a) => <li key={a.id}><AnnouncementCard a={a} compact /></li>)}</ul>
        ))}
      </WorkspaceSection>

      <AgentActivityTimeline title={t("activityTitle")} entries={timeline(status, tasks, checking, t, (k) => tTypes.has(k) ? tTypes(k) : k)} />

      <AdminStrip>
        {status?.candidates_waiting !== undefined && (
          <p className="text-xs" data-testid="candidates-waiting">{t("candidatesWaiting", { count: status.candidates_waiting })}</p>
        )}
        <div className="flex flex-wrap gap-1.5">
          <Button size="sm" variant="outline" className="min-h-9" onClick={() => ws.openTab("review")} data-testid="open-review">{t("openReview")}</Button>
          <Button size="sm" variant="outline" className="min-h-9" onClick={() => ws.openTab("sources")}>{t("openSources")}</Button>
        </div>
        <AgentActionBar ids={actionIds.filter(isAdminAction)} onDone={() => { void reload(); mon.reload(); }} />
      </AdminStrip>
    </div>
  );
}

function SourcesPublic({ status }: { status: MonitoringStatus }) {
  const t = useTranslations("office.ws.mon");
  const tKinds = useTranslations("office.ws.sources.kinds");
  const tAgent = useTranslations("office.agent");
  return (
    <WorkspaceSection title={t("sourcesTitle", { count: status.sources.length })} testId="monitored-sources">
      {status.sources.length === 0 ? <EmptyState>{t("noSources")}</EmptyState> : (
        <ul className="space-y-1.5">
          {status.sources.map((s) => (
            <li key={s.url} className="rounded-xl border border-border px-3 py-2 text-xs" data-testid="monitored-source">
              <div className="flex flex-wrap items-center gap-1.5">
                <a href={s.url} target="_blank" rel="noopener noreferrer" className="font-semibold text-primary hover:underline">
                  {s.name} <ExternalLink className="inline size-3" aria-hidden />
                </a>
                <HealthChip health={s.health} />
              </div>
              <p className="text-muted-foreground">
                {tKinds(s.kind)} · {s.last_checked_at ? tAgent("lastChecked", { when: fmt(s.last_checked_at) }) : tAgent("neverChecked")}
              </p>
            </li>
          ))}
        </ul>
      )}
    </WorkspaceSection>
  );
}

type Tr = (key: string, values?: Record<string, string | number>) => string;

/** Timeline from stored timestamps only: source checks, scheduled runs and the viewer's own tasks. */
export function timeline(status: MonitoringStatus | null, tasks: AgentTask[] | null, checking: boolean, t: Tr,
  typeName: (k: string) => string): TimelineEntry[] {
  const out: TimelineEntry[] = [];
  if (checking) out.push({ at: new Date().toISOString(), label: t("timeline.checking"), tone: "running" });
  for (const s of status?.sources ?? []) {
    if (s.last_checked_at) {
      out.push({ at: s.last_checked_at, label: t(s.health === "ok" ? "timeline.checkedOk" : "timeline.checkedAttention", { name: s.name }),
        tone: s.health === "ok" ? "ok" : "attention" });
    }
  }
  for (const s of status?.schedules ?? []) {
    if (s.last_run_at) out.push({ at: s.last_run_at, label: t("timeline.scheduled"), tone: "info" });
  }
  for (const task of tasks ?? []) {
    const name = typeName(task.task_type);
    if (task.completed_at) {
      out.push({ at: task.completed_at, label: t(task.status === "completed" ? "timeline.taskDone" : "timeline.taskFailed", { task: name }),
        tone: task.status === "completed" ? "ok" : "attention" });
    } else {
      out.push({ at: task.created_at, label: t("timeline.taskStarted", { task: name }),
        tone: task.status === "queued" || task.status === "running" ? "running" : "info" });
    }
  }
  return out;
}
