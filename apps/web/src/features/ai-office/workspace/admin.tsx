"use client";

/**
 * Admin-only workspace tabs of the monitoring / discovery agents: the review queue of discovered official notices
 * and the official sources with their schedules. The tabs are only offered to admins by the backend and every call
 * here goes to an admin endpoint / admin-only tool, which checks the role again.
 */
import { useState } from "react";
import { useTranslations } from "next-intl";
import { ExternalLink, Loader2, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  agentApi, useAgentTasks, type MonitoredSchedule, type MonitoredSource,
} from "@/features/ai-office/agent-api";
import { AgentResultCard, ReviewContext, fmt } from "@/features/ai-office/agent-work";
import { useWorkspace } from "@/features/ai-office/workspace/context";
import {
  AgentActionBar, AgentPermissionGate, AgentTaskList, EmptyState, FilterChips, LoadState, WorkspaceSection,
} from "@/features/ai-office/workspace/parts";
import { ApiError } from "@/lib/api";
import { useApi } from "@/lib/use-api";
import { cn } from "@/lib/utils";

const DISCOVERY_TASKS = ["announcement_discovery", "opportunity_discovery"];

export function ReviewQueue() {
  const t = useTranslations("office.ws.review");
  return (
    <AgentPermissionGate require="admin" fallback={<EmptyState>{t("adminOnly")}</EmptyState>}>
      <ReviewQueueInner />
    </AgentPermissionGate>
  );
}

function ReviewQueueInner() {
  const ws = useWorkspace();
  const t = useTranslations("office.ws.review");
  const [status, setStatus] = useState<"candidate" | "imported" | "dismissed" | "all">("candidate");
  const [changedOnly, setChangedOnly] = useState(false);
  const tNext = useTranslations("office.ws.next");
  const data = useApi(`ws-review:${ws.agent.id}:${status}:${changedOnly}`, () =>
    agentApi.tool(ws.agent.id, "review_candidates", { status, changed_only: changedOnly, limit: 50 }, ws.language));
  const items = data.data?.result.items ?? [];
  return (
    // a reviewed card stays where it is and shows its new status (sent / dismissed); Refresh reloads the queue
    <ReviewContext.Provider value={{ isAdmin: true, onChanged: ws.onChanged }}>
      <div className="space-y-3" data-testid="review-queue">
        <div className="flex items-start gap-2">
          <p className="flex-1 text-muted-foreground">{t("intro")}</p>
          <Button size="sm" variant="outline" className="min-h-9 shrink-0" onClick={data.reload} data-testid="review-refresh">
            <RotateCcw className="size-3.5" aria-hidden /> {t("refresh")}
          </Button>
        </div>
        <FilterChips label={t("filter")} value={status} onChange={setStatus} testId="review-filter"
          options={(["candidate", "imported", "dismissed", "all"] as const).map((id) => ({ id, label: t(`statuses.${id}`) }))} />
        <label className="flex min-h-9 items-center gap-2 text-xs">
          <input type="checkbox" checked={changedOnly} onChange={(e) => setChangedOnly(e.target.checked)} className="size-4" />
          {t("changedOnly")}
        </label>
        <LoadState loading={data.loading && !data.data} error={data.error} onRetry={data.reload} />
        {data.data && (items.length === 0 ? <EmptyState next={[{ label: tNext("runCheck"), onClick: () => ws.openTab("sources") }]}>{t("empty")}</EmptyState> : (
          <ul className="space-y-1.5">
            {items.map((item) => <li key={item.id}><AgentResultCard item={item} /></li>)}
          </ul>
        ))}
      </div>
    </ReviewContext.Provider>
  );
}

export function SourcesAdmin() {
  const t = useTranslations("office.ws.review");
  return (
    <AgentPermissionGate require="admin" fallback={<EmptyState>{t("adminOnly")}</EmptyState>}>
      <SourcesAdminInner />
    </AgentPermissionGate>
  );
}

function SourcesAdminInner() {
  const ws = useWorkspace();
  const t = useTranslations("office.ws.sources");
  const running = ws.agent.monitoring_check_running ? 1 : 0;
  const mon = useApi(`ws-mon-admin:${ws.agent.id}:${running}`, () => agentApi.monitoring(ws.agent.id));
  const { tasks, reload } = useAgentTasks(ws.agent, ws.signedIn, ws.onChanged);
  const checkIds = (ws.agent.interface?.task_actions ?? []).filter((id) =>
    ws.agent.actions.some((a) => a.id === id && a.admin_only && a.kind === "task"));
  return (
    <div className="space-y-5" data-testid="sources-admin">
      <WorkspaceSection title={t("checkNow")}>
        <p className="text-xs text-muted-foreground">{t("checkNowHint")}</p>
        <AgentActionBar ids={checkIds} variant="default" onDone={() => { void reload(); mon.reload(); }} />
        <AgentTaskList startHint tasks={tasks} types={DISCOVERY_TASKS} limit={1} title={t("latestCheck")}
          onChanged={() => { void reload(); ws.onChanged(); mon.reload(); }} />
      </WorkspaceSection>
      <LoadState loading={mon.loading && !mon.data} error={mon.error} onRetry={mon.reload} />
      {mon.data && (
        <>
          <WorkspaceSection title={t("schedules")} testId="schedules-admin">
            {mon.data.schedules_enabled_on_server === false && (
              <p className="rounded-lg bg-amber-50 p-2 text-xs text-amber-950 dark:bg-amber-950/30 dark:text-amber-100" data-testid="server-switch-off">
                {t("serverOff")}
              </p>
            )}
            {mon.data.schedules.length === 0 ? <EmptyState>{t("noSchedules")}</EmptyState> : (
              <ul className="space-y-2">
                {mon.data.schedules.map((s) => <li key={s.id ?? s.task_type}><ScheduleRow s={s} onChanged={mon.reload} /></li>)}
              </ul>
            )}
          </WorkspaceSection>
          <WorkspaceSection title={t("sources", { count: mon.data.sources.length })} testId="sources-list-admin">
            {mon.data.sources.length === 0 ? <EmptyState>{t("noSources")}</EmptyState> : (
              <ul className="space-y-2">
                {mon.data.sources.map((s) => <li key={s.id ?? s.url}><SourceRow s={s} onChanged={mon.reload} /></li>)}
              </ul>
            )}
            <p className="text-xs text-muted-foreground">{t("addSources")}</p>
          </WorkspaceSection>
        </>
      )}
    </div>
  );
}

export function HealthChip({ health }: { health: MonitoredSource["health"] }) {
  const t = useTranslations("office.ws.health");
  return (
    <span data-testid="source-health" data-health={health}
      className={cn("rounded-full px-1.5 text-[10px] font-bold",
        health === "ok" ? "bg-emerald-100 text-emerald-900" : health === "attention" ? "bg-amber-100 text-amber-900"
          : "bg-muted text-muted-foreground")}>
      {t(health)}
    </span>
  );
}

function useAdminAction(onChanged: () => void) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      onChanged();
    } catch (e) {
      setError(e instanceof ApiError ? e.code : "generic");
    } finally {
      setBusy(false);
    }
  };
  return { busy, error, run };
}

function SourceRow({ s, onChanged }: { s: MonitoredSource; onChanged: () => void }) {
  const t = useTranslations("office.ws.sources");
  const tAgent = useTranslations("office.agent");
  const { busy, error, run } = useAdminAction(onChanged);
  return (
    <article className={cn("space-y-1 rounded-xl border border-border p-2.5 text-xs", s.enabled === false && "opacity-70")}
      data-testid="source-row" data-enabled={String(s.enabled)}>
      <div className="flex flex-wrap items-center gap-1.5">
        <a href={s.url} target="_blank" rel="noopener noreferrer" className="font-semibold text-primary hover:underline">
          {s.name} <ExternalLink className="inline size-3" aria-hidden />
        </a>
        <HealthChip health={s.health} />
        {s.enabled === false && <span className="rounded-full bg-muted px-1.5 text-[10px] font-bold">{t("disabled")}</span>}
      </div>
      <p className="text-muted-foreground">
        {[t(`kinds.${s.kind}`), s.last_checked_at ? tAgent("lastChecked", { when: fmt(s.last_checked_at) }) : tAgent("neverChecked"),
          s.consecutive_failures ? t("failures", { count: s.consecutive_failures }) : null].filter(Boolean).join(" · ")}
      </p>
      {s.last_error && <p className="text-red-700 dark:text-red-300" data-testid="source-error">{s.last_error}</p>}
      {s.id && (
        <div className="flex flex-wrap gap-1.5 pt-0.5">
          <Button size="sm" variant="outline" className="h-8 px-2 text-xs" disabled={busy} data-testid="toggle-source"
            onClick={() => void run(() => agentApi.updateSource(s.id!, { enabled: !s.enabled }))}>
            {busy && <Loader2 className="size-3 animate-spin" aria-hidden />}
            {s.enabled ? t("disable") : t("enable")}
          </Button>
          {Boolean(s.consecutive_failures) && (
            <Button size="sm" variant="ghost" className="h-8 px-2 text-xs" disabled={busy} data-testid="reset-failures"
              onClick={() => void run(() => agentApi.updateSource(s.id!, { reset_failures: true }))}>
              <RotateCcw className="size-3" aria-hidden /> {t("resetFailures")}
            </Button>
          )}
        </div>
      )}
      {error && <p role="alert" className="text-red-700">{tAgent.has(`errors.${error}`) ? tAgent(`errors.${error}`) : tAgent("errors.generic")}</p>}
    </article>
  );
}

export function ScheduleState({ s }: { s: MonitoredSchedule }) {
  const t = useTranslations("office.ws.schedule");
  const hours = s.interval_minutes ? Math.round(s.interval_minutes / 60) : null;
  return (
    <span className="flex flex-wrap items-center gap-1.5 text-xs" data-testid="schedule-state" data-state={s.state}>
      <span className={cn("rounded-full px-2 py-0.5 text-[11px] font-bold",
        s.state === "active" ? "bg-emerald-100 text-emerald-900" : s.state === "off_on_server" ? "bg-amber-100 text-amber-900"
          : "bg-muted text-muted-foreground")}>
        {t(`states.${s.state}`)}
      </span>
      <span className="text-muted-foreground">
        {s.state === "active" && hours ? t("every", { hours }) : t(`explain.${s.state}`)}
        {s.state === "active" && s.next_run_at ? ` · ${t("next", { when: fmt(s.next_run_at) })}` : ""}
      </span>
    </span>
  );
}

function ScheduleRow({ s, onChanged }: { s: MonitoredSchedule; onChanged: () => void }) {
  const t = useTranslations("office.ws.schedule");
  const tAgent = useTranslations("office.agent");
  const { busy, error, run } = useAdminAction(onChanged);
  const [confirming, setConfirming] = useState(false);
  const hours = s.interval_minutes ? Math.round(s.interval_minutes / 60) : 0;
  return (
    <article className="space-y-1.5 rounded-xl border border-border p-2.5" data-testid="schedule-row">
      <p className="text-xs font-semibold">{tAgent.has(`taskTypes.${s.task_type}`) ? tAgent(`taskTypes.${s.task_type}`) : s.task_type}</p>
      <ScheduleState s={s} />
      <p className="text-[11px] text-muted-foreground">
        {s.last_run_at ? t("lastRun", { when: fmt(s.last_run_at) }) : t("neverRun")}
        {s.last_success_at ? ` · ${t("lastSuccess", { when: fmt(s.last_success_at) })}` : ""}
      </p>
      {s.last_error && <p className="text-xs text-red-700 dark:text-red-300">{s.last_error}</p>}
      {s.id && (confirming ? (
        <div className="space-y-1.5 rounded-lg bg-amber-50 p-2 text-xs text-amber-950 dark:bg-amber-950/30 dark:text-amber-100" data-testid="schedule-confirm">
          <p>{t("confirmOn", { hours })}</p>
          <div className="flex gap-1.5">
            <Button size="sm" className="h-8 text-xs" disabled={busy} data-testid="schedule-confirm-yes"
              onClick={() => void run(() => agentApi.updateSchedule(s.id!, { enabled: true })).then(() => setConfirming(false))}>
              {t("turnOn")}
            </Button>
            <Button size="sm" variant="ghost" className="h-8 text-xs" onClick={() => setConfirming(false)}>{tAgent("cancel")}</Button>
          </div>
        </div>
      ) : (
        <Button size="sm" variant="outline" className="h-8 px-2 text-xs" disabled={busy} data-testid="toggle-schedule"
          onClick={() => (s.enabled ? void run(() => agentApi.updateSchedule(s.id!, { enabled: false })) : setConfirming(true))}>
          {s.enabled ? t("turnOff") : t("turnOn")}
        </Button>
      ))}
      {error && <p role="alert" className="text-xs text-red-700">{tAgent.has(`errors.${error}`) ? tAgent(`errors.${error}`) : tAgent("errors.generic")}</p>}
    </article>
  );
}
