"use client";

/**
 * Shared building blocks of the role-specific workspaces. They only display what the API returned: dates are the
 * source's dates, "open" is shown only when the backend derived it from the source, and admin controls are hidden
 * for everyone else AND protected by the admin endpoints.
 */
import { useState } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import {
  AlertTriangle, ArrowLeft, CalendarDays, CheckCircle2, CircleDashed, Clock, ExternalLink, Globe, Loader2, Lock,
  Minus, ShieldCheck, X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  agentApi, type AgentInfo, type AgentTask, type ResultItem, type ToolResult,
} from "@/features/ai-office/agent-api";
import { AgentResultCard, OpenStatus, Reliability, StateBadge, TaskCard, fmt } from "@/features/ai-office/agent-work";
import { Portrait } from "@/features/ai-office/portrait";
import type { OfficeCharacter } from "@/features/ai-office/characters";
import { useWorkspace } from "@/features/ai-office/workspace/context";
import { ApiError } from "@/lib/api";
import { cn, formatDate } from "@/lib/utils";
import type { AnnouncementSummary } from "@/types/api";

// ------------------------------------------------------------------ dates
/** Today in Korea (the university's calendar; the backend uses the same day). */
export function todayKst(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Seoul" }).format(new Date());
}

/** Whole days from today (KST) to a YYYY-MM-DD date; null for anything else. */
export function daysUntil(date: string | null | undefined, today = todayKst()): number | null {
  if (!date || !/^\d{4}-\d{2}-\d{2}/.test(date)) return null;
  const [y, m, d] = date.slice(0, 10).split("-").map(Number);
  const [ty, tm, td] = today.split("-").map(Number);
  return Math.round((Date.UTC(y, m - 1, d) - Date.UTC(ty, tm - 1, td)) / 86_400_000);
}

/** A date from the source with how far away it is. Never says whether something is open. */
export function DeadlineDisplay({ date, kind = "deadline", compact = false }: {
  date: string | null | undefined;
  kind?: "deadline" | "event";
  compact?: boolean;
}) {
  const t = useTranslations("office.ws.dates");
  const locale = useLocale();
  if (!date) return null;
  const days = daysUntil(date);
  const tone = days === null ? "text-muted-foreground" : days < 0 ? "text-muted-foreground line-through decoration-1"
    : kind === "deadline" && days <= 7 ? "text-amber-800 dark:text-amber-300" : "text-foreground";
  const relative = days === null ? null : days < 0 ? t("passed") : days === 0 ? t("today")
    : days === 1 ? t("tomorrow") : t("inDays", { count: days });
  return (
    <span className={cn("inline-flex items-center gap-1 text-xs", compact && "text-[11px]")} data-testid="deadline"
      data-kind={kind} data-days={days ?? "none"}>
      {kind === "event" ? <CalendarDays className="size-3.5 shrink-0" aria-hidden /> : <Clock className="size-3.5 shrink-0" aria-hidden />}
      <span className="font-semibold">{t(kind)}</span>
      <span className={tone}>{formatDate(date, locale)}</span>
      {relative && <span className={cn("rounded-full px-1.5 text-[10px] font-bold",
        days !== null && days < 0 ? "bg-muted text-muted-foreground"
          : kind === "deadline" && days !== null && days <= 7 ? "bg-amber-100 text-amber-900" : "bg-sky-50 text-sky-900")}>
        {relative}
      </span>}
    </span>
  );
}

// ------------------------------------------------------------------ status
/** The agent's backend state, plus whether an official-source check is running and automatic checks are on. */
export function AgentStatus({ agent }: { agent: AgentInfo | undefined }) {
  const t = useTranslations("office.ws.status");
  if (!agent) return null;
  return (
    <span className="flex flex-wrap items-center gap-1" data-testid="agent-status">
      <StateBadge state={agent.state} compact />
      {agent.paused && (
        <span className="rounded-full bg-muted px-1.5 py-0.5 text-[11px] font-semibold text-muted-foreground" data-testid="agent-paused">
          {t("paused")}
        </span>
      )}
      {agent.monitoring_check_running && (
        <span className="inline-flex items-center gap-1 rounded-full bg-sky-100 px-1.5 py-0.5 text-[11px] font-semibold text-sky-900"
          data-testid="checking-sources">
          <Loader2 className="size-3 animate-spin" aria-hidden /> {t("checkingSources")}
        </span>
      )}
      {agent.awaiting > 0 && agent.state !== "waiting" && (
        <span className="rounded-full bg-amber-100 px-1.5 py-0.5 text-[11px] font-semibold text-amber-900">
          {t("awaiting", { count: agent.awaiting })}
        </span>
      )}
    </span>
  );
}

// ------------------------------------------------------------------ header
export function AgentHeader({ c, title, subtitle, agent, headingRef, controls, onBack }: {
  c: OfficeCharacter;
  title: string;
  subtitle: React.ReactNode;
  agent?: AgentInfo;
  headingRef?: React.Ref<HTMLHeadingElement>;
  controls?: React.ReactNode;
  /** phones: back to the office (the panel covers the whole screen there) */
  onBack: () => void;
}) {
  const t = useTranslations("office");
  return (
    <header className="flex items-center gap-2 rounded-t-3xl border-b border-border bg-[#F7FAFD] px-2 py-2.5 pt-[max(0.625rem,env(safe-area-inset-top))] dark:bg-muted/40 md:gap-3 md:px-3 md:pt-2.5">
      <Button size="sm" variant="ghost" className="size-10 shrink-0 p-0 md:hidden" aria-label={t("ws.backToOffice")}
        onClick={onBack} data-testid="panel-back">
        <ArrowLeft className="size-5" />
      </Button>
      <Portrait c={c} size={52} />
      <div className="min-w-0 flex-1">
        <h2 id="office-panel-title" ref={headingRef} tabIndex={-1} className="truncate text-base font-bold outline-none">{title}</h2>
        <div className="truncate text-xs text-muted-foreground">{subtitle}</div>
        <AgentStatus agent={agent} />
      </div>
      {controls}
    </header>
  );
}

/** The panel frame: right-hand panel on desktop (the office stays visible), full screen on phones. */
export function AgentWorkspaceShell({ type, children }: { type: string; children: React.ReactNode }) {
  return (
    <section role="dialog" aria-modal="false" aria-labelledby="office-panel-title" data-testid="office-panel" data-interface={type}
      className="fixed inset-0 z-[45] flex h-[100dvh] flex-col bg-card text-card-foreground md:inset-auto md:bottom-4 md:right-4 md:top-4 md:h-auto md:w-[420px] md:rounded-3xl md:border md:border-border md:shadow-2xl">
      {children}
    </section>
  );
}

// ------------------------------------------------------------------ layout helpers
export function WorkspaceSection({ title, icon, action, children, testId }: {
  title: React.ReactNode;
  icon?: React.ReactNode;
  action?: React.ReactNode;
  children: React.ReactNode;
  testId?: string;
}) {
  return (
    <section className="space-y-2" data-testid={testId}>
      <div className="flex items-center gap-2">
        <h3 className="flex min-w-0 items-center gap-1.5 text-sm font-semibold">
          {icon && <span className="text-primary" aria-hidden>{icon}</span>}
          {title}
        </h3>
        {action && <div className="ml-auto shrink-0">{action}</div>}
      </div>
      {children}
    </section>
  );
}

export interface NextStep {
  label: string;
  /** an in-app action (switch tab, open another desk, change a filter) */
  onClick?: () => void;
  /** a page of the Hub or an official site */
  href?: string;
}

/** An empty result that says why it is empty AND what the student can do next. */
export function EmptyState({ children, next = [] }: { children: React.ReactNode; next?: NextStep[] }) {
  return (
    <div className="space-y-2 rounded-xl bg-muted/60 p-3 text-sm text-muted-foreground" data-testid="desk-empty">
      <p>{children}</p>
      {next.length > 0 && (
        <div className="flex flex-wrap gap-1.5" data-testid="next-steps">
          {next.map((n) => n.href ? (
            /^https?:\/\//.test(n.href)
              ? <a key={n.label} href={n.href} target="_blank" rel="noopener noreferrer" className={NEXT_CLS}>{n.label} <ExternalLink className="size-3" aria-hidden /></a>
              : <Link key={n.label} href={n.href} className={NEXT_CLS}>{n.label}</Link>
          ) : (
            <button key={n.label} type="button" onClick={n.onClick} className={NEXT_CLS}>{n.label}</button>
          ))}
        </div>
      )}
    </div>
  );
}

const NEXT_CLS = "inline-flex min-h-9 items-center gap-1 rounded-full bg-background px-3 text-xs font-semibold text-primary ring-1 ring-primary/30 hover:bg-primary/5";

/** Next steps every desk can offer: ask this desk in chat (when it has one) and reach a person through Sumin. */
export function useCommonNextSteps(): { askChat: NextStep[]; human: NextStep } {
  const ws = useWorkspace();
  const t = useTranslations("office.ws.next");
  const hasChat = ws.agent.interface?.tabs.includes("chat");
  return {
    askChat: hasChat ? [{ label: t("askInChat", { name: ws.agent.name }), onClick: () => ws.openTab("chat") }] : [],
    human: { label: t("askPerson"), onClick: () => ws.onSelect("supporter-lead") },
  };
}

export function LoadState({ loading, error, onRetry }: { loading: boolean; error: unknown; onRetry: () => void }) {
  const t = useTranslations("office");
  if (loading) {
    return <p className="flex items-center gap-2 py-4 text-sm text-muted-foreground" role="status"><Loader2 className="size-4 animate-spin" aria-hidden /> {t("loading")}</p>;
  }
  if (!error) return null;
  const code = error instanceof ApiError ? error.code : "generic";
  return (
    <p className="rounded-xl bg-red-50 p-3 text-sm text-red-800 dark:bg-red-950/40 dark:text-red-200" role="alert" data-testid="ws-error">
      {code === "rate_limited" ? t("agent.errors.rate_limited") : t("loadError")}{" "}
      <button type="button" onClick={onRetry} className="font-semibold underline">{t("retry")}</button>
    </p>
  );
}

/** Pill buttons for one filter (touch friendly, the selected one is marked for screen readers). */
export function FilterChips<T extends string>({ label, value, options, onChange, testId }: {
  label: string;
  value: T;
  options: { id: T; label: string }[];
  onChange: (v: T) => void;
  testId?: string;
}) {
  return (
    <div role="group" aria-label={label} className="flex gap-1.5 overflow-x-auto pb-0.5" data-testid={testId}>
      {options.map((o) => (
        <button key={o.id} type="button" aria-pressed={value === o.id} onClick={() => onChange(o.id)} data-value={o.id}
          className={cn("min-h-9 shrink-0 rounded-full px-3 text-xs font-semibold ring-1 transition-colors",
            value === o.id ? "bg-[#3D6A8C] text-white ring-[#3D6A8C]" : "bg-background text-[#4B5D73] ring-border hover:bg-muted dark:text-foreground")}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------ sources
/** A link to where an item comes from, saying whether the Hub approved it or it is the official page itself. */
export function SourceCitation({ href, label, kind }: { href: string; label?: string | null; kind: "hub" | "official" }) {
  const t = useTranslations("office.ws.source");
  const external = /^https?:\/\//.test(href);
  const body = (
    <>
      {kind === "hub" ? <ShieldCheck className="size-3" aria-hidden /> : <Globe className="size-3" aria-hidden />}
      <span className="truncate">{label || t(kind)}</span>
      {external && <ExternalLink className="size-3 shrink-0" aria-hidden />}
    </>
  );
  const cls = cn("inline-flex max-w-full items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold ring-1",
    kind === "hub" ? "bg-emerald-50 text-emerald-900 ring-emerald-200 dark:bg-emerald-950/30 dark:text-emerald-200"
      : "bg-white text-primary ring-primary/30 dark:bg-transparent");
  return external
    ? <a href={href} target="_blank" rel="noopener noreferrer" className={cls} data-testid="source-citation" data-kind={kind}>{body}</a>
    : <Link href={href} className={cls} data-testid="source-citation" data-kind={kind}>{body}</Link>;
}

// ------------------------------------------------------------------ cards
/**
 * A scholarship, competition, program or job: a published Hub notice / guide, or an official-site notice that an
 * admin reviewed and the Knowledge Center approved. Open / closed only as the backend derived it from the source.
 */
export function OpportunityCard({ item }: { item: ResultItem }) {
  const t = useTranslations("office.ws");
  const tKinds = useTranslations("office.agent.kinds");
  const locale = useLocale();
  const discovered = item.kind === "discovered";
  const deadline = item.next_deadline ?? item.deadline;
  const kind = item.opportunity_kind;
  const internal = item.href && !/^https?:\/\//.test(item.href);
  const title = item.title || "—";
  return (
    <article className="space-y-1.5 rounded-xl border border-border bg-background p-3" data-testid="opportunity-card"
      data-kind={item.kind} data-reliability={item.reliability ?? "none"}>
      <div className="flex flex-wrap items-center gap-1.5">
        {kind && <span className="rounded-full bg-[#FFF6D9] px-1.5 text-[10px] font-bold text-[#7A5A00]">{tKinds(kind)}</span>}
        {!kind && <span className="rounded-full bg-muted px-1.5 text-[10px] font-bold text-muted-foreground">{t(`itemKinds.${item.kind === "document" ? "guide" : "notice"}`)}</span>}
        {item.reliability && <Reliability r={item.reliability} />}
        {discovered && <OpenStatus item={item} />}
      </div>
      <h4 className="font-semibold leading-snug">
        {item.href ? (
          internal ? <Link href={item.href} className="hover:underline">{title}</Link>
            : <a href={item.href} target="_blank" rel="noopener noreferrer" className="hover:underline">{title}</a>
        ) : title}
      </h4>
      <div className="flex flex-col gap-1">
        {deadline && <DeadlineDisplay date={deadline} />}
        {item.event_date && <DeadlineDisplay date={item.event_date} kind="event" />}
      </div>
      {item.eligibility && item.eligibility.length > 0 && (
        <div className="text-xs" data-testid="eligibility">
          <span className="font-semibold">{t("eligibilityQuoted")}</span>
          <ul className="list-disc pl-4 text-muted-foreground">{item.eligibility.slice(0, 2).map((e, i) => <li key={i}>“{e}”</li>)}</ul>
        </div>
      )}
      {!item.eligibility?.length && item.excerpt && <p className="line-clamp-2 text-xs text-muted-foreground">{item.excerpt}</p>}
      <div className="flex flex-wrap items-center gap-1.5">
        {item.href && internal && <SourceCitation href={item.href} kind="hub" />}
        {item.official_url && <SourceCitation href={item.official_url} kind="official" />}
        {item.application_links?.slice(0, 2).map((l) => (
          <a key={l.url} href={l.url} target="_blank" rel="noopener noreferrer" data-testid="application-link"
            className="inline-flex items-center gap-1 rounded-full bg-primary px-2 py-0.5 text-[11px] font-semibold text-primary-foreground hover:bg-primary/90">
            {l.text || t("apply")} <ExternalLink className="size-3" aria-hidden />
          </a>
        ))}
      </div>
      <p className="text-[11px] text-muted-foreground">
        {[item.source_name ?? item.organization ?? item.source,
          item.published_on ? t("publishedOn", { date: formatDate(item.published_on, locale) })
            : item.published_at ? t("publishedOn", { date: formatDate(item.published_at, locale) }) : null,
          item.verified_at ? t("verifiedOn", { date: formatDate(item.verified_at, locale) }) : null,
          item.last_checked_at ? t("lastChecked", { when: fmt(item.last_checked_at) }) : null].filter(Boolean).join(" · ")}
      </p>
    </article>
  );
}

/** A published announcement (title in the reader's language when an approved / labelled translation exists). */
export function AnnouncementCard({ a, onOpen, compact = false }: {
  a: AnnouncementSummary;
  onOpen?: (id: string) => void;
  compact?: boolean;
}) {
  const t = useTranslations("office.ws");
  const tCat = useTranslations("categories");
  const locale = useLocale();
  const title = a.display_title ?? a.title;
  return (
    <article className="space-y-1 rounded-xl border border-border bg-background p-3" data-testid="announcement-card" data-id={a.id}>
      <div className="flex flex-wrap items-center gap-1.5 text-[10px] font-bold">
        <span className="rounded-full bg-muted px-1.5 text-muted-foreground">{tCat.has(a.category) ? tCat(a.category) : a.category}</span>
        {a.status === "upcoming" && <span className="rounded-full bg-sky-50 px-1.5 text-sky-900">{t("annStatus.upcoming")}</span>}
        {a.status === "expired" && <span className="rounded-full bg-muted px-1.5 text-muted-foreground">{t("annStatus.expired")}</span>}
      </div>
      <h4 className="font-semibold leading-snug">
        {onOpen ? (
          <button type="button" onClick={() => onOpen(a.id)} className="text-left hover:underline" data-testid="announcement-open">{title}</button>
        ) : <Link href={`/announcements/${a.id}`} className="hover:underline">{title}</Link>}
      </h4>
      <div className="flex flex-col gap-1">
        {a.event_date && <DeadlineDisplay date={a.event_date} kind="event" />}
        {a.deadline && <DeadlineDisplay date={a.deadline} />}
      </div>
      {!compact && a.excerpt && <p className="line-clamp-2 text-xs text-muted-foreground">{a.excerpt}</p>}
      <p className="text-[11px] text-muted-foreground">
        {[a.source?.organization, a.published_at ? t("publishedOn", { date: formatDate(a.published_at, locale) }) : null]
          .filter(Boolean).join(" · ")}
      </p>
    </article>
  );
}

// ------------------------------------------------------------------ actions
type ActionOutcome = { kind: "result"; result: ToolResult } | { kind: "task"; task: AgentTask };

/**
 * Buttons for the agent's backend-defined actions (only those the directory returned for this viewer). Tools run
 * now; tasks need a signed-in user and run in the background. The API checks every permission again.
 */
export function AgentActionBar({ ids, onDone, variant = "outline", label }: {
  ids: string[];
  onDone: (o: ActionOutcome) => void;
  variant?: "outline" | "default";
  label?: string;
}) {
  const ws = useWorkspace();
  const t = useTranslations("office.agent");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const actions = ids.map((id) => ws.agent.actions.find((a) => a.id === id)).filter((a) => a !== undefined);
  if (!actions.length) return null;
  const run = async (id: string) => {
    const a = actions.find((x) => x.id === id)!;
    setBusy(id);
    setError(null);
    try {
      if (a.kind === "tool") {
        const r = await agentApi.tool(ws.agent.id, a.target, a.params, ws.language);
        onDone({ kind: "result", result: r.result });
      } else {
        const task = await agentApi.createTask(ws.agent.id, a.target, a.params, ws.language);
        onDone({ kind: "task", task });
        ws.onChanged();
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.code : "generic");
    } finally {
      setBusy(null);
    }
  };
  return (
    <div className="space-y-1.5" data-testid="action-bar">
      {label && <p className="text-xs font-bold tracking-wide text-muted-foreground">{label}</p>}
      <div className="flex flex-wrap gap-1.5">
        {actions.map((a) => {
          const needsSignIn = a.kind === "task" && !ws.signedIn;
          return (
            <Button key={a.id} size="sm" variant={a.admin_only ? "outline" : variant} disabled={busy !== null || needsSignIn}
              className={cn("min-h-9", a.admin_only && "border-violet-300 text-violet-900 dark:text-violet-200")}
              data-testid={`action-${a.id}`} data-admin={a.admin_only ? "true" : undefined}
              title={needsSignIn ? t("signInForTasks", { name: ws.agent.name }) : undefined} onClick={() => void run(a.id)}>
              {busy === a.id ? <Loader2 className="size-3.5 animate-spin" aria-hidden />
                : a.admin_only ? <Lock className="size-3.5" aria-hidden />
                  : a.kind === "task" ? <CircleDashed className="size-3.5" aria-hidden /> : null}
              {t(`actions.${a.id}`)}
            </Button>
          );
        })}
      </div>
      {error && (
        <p role="alert" className="flex items-start gap-1.5 text-xs text-red-700 dark:text-red-300" data-testid="action-error">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          {t.has(`errors.${error}`) ? t(`errors.${error}`) : t("errors.generic")}
        </p>
      )}
    </div>
  );
}

/**
 * Shows its children only to admins / signed-in users. Presentation only: the API enforces the same rule, so a
 * hidden control is never the protection.
 */
export function AgentPermissionGate({ require, children, fallback = null }: {
  require: "admin" | "signedIn";
  children: React.ReactNode;
  fallback?: React.ReactNode;
}) {
  const ws = useWorkspace();
  const ok = require === "admin" ? ws.isAdmin : ws.signedIn;
  return <>{ok ? children : fallback}</>;
}

export function SignInPrompt({ text }: { text: string }) {
  const t = useTranslations("office.agent");
  return (
    <p className="rounded-xl bg-muted/60 p-3 text-xs text-muted-foreground" data-testid="sign-in-prompt">
      {text}{" "}
      <Link className="font-semibold text-primary underline" href="/login?next=%2Fai-office">{t("signIn")}</Link>
    </p>
  );
}

/** Admin-only strip inside a student-facing view. */
export function AdminStrip({ children }: { children: React.ReactNode }) {
  const t = useTranslations("office.ws");
  return (
    <AgentPermissionGate require="admin">
      <div className="space-y-2 rounded-xl border border-violet-200 bg-violet-50/60 p-3 dark:border-violet-900 dark:bg-violet-950/20" data-testid="admin-strip">
        <p className="flex items-center gap-1.5 text-xs font-bold text-violet-900 dark:text-violet-200"><Lock className="size-3.5" aria-hidden /> {t("adminOnly")}</p>
        {children}
      </div>
    </AgentPermissionGate>
  );
}

// ------------------------------------------------------------------ tasks and activity
/** The viewer's own tasks of this agent (optionally only some task types), newest first. */
export function AgentTaskList({ tasks, types, onChanged, limit = 3, title, startHint = false, hideWhenEmpty = false }: {
  tasks: AgentTask[] | null;
  types?: string[];
  onChanged: () => void;
  limit?: number;
  title: string;
  /** an action button that starts these tasks is shown just above the list */
  startHint?: boolean;
  /** no section at all while the student has no such tasks (desks without a start button) */
  hideWhenEmpty?: boolean;
}) {
  const ws = useWorkspace();
  const t = useTranslations("office.agent");
  const tWs = useTranslations("office.ws.next");
  const nameOf = (id: string) => ws.agents?.find((a) => a.id === id)?.name ?? id;
  if (!ws.signedIn) return null;
  const shown = (tasks ?? []).filter((x) => !types || types.includes(x.task_type)).slice(0, limit);
  if (hideWhenEmpty && shown.length === 0) return null;
  return (
    <WorkspaceSection title={title} testId="agent-task-list">
      {tasks === null ? <p className="text-xs text-muted-foreground">{t("loading")}</p>
        : shown.length === 0 ? <p className="text-xs text-muted-foreground" data-testid="no-tasks">{t("noTasks")}{startHint ? ` ${tWs("noTasksHint")}` : ""}</p> : (
          <ul className="space-y-2">
            {shown.map((task) => <li key={task.id}><TaskCard task={task} nameOf={nameOf} onChanged={onChanged} /></li>)}
          </ul>
        )}
    </WorkspaceSection>
  );
}

export interface TimelineEntry {
  at: string;
  label: string;
  tone: "ok" | "attention" | "running" | "info";
}

/** What the agent did recently, from stored timestamps only (checks, scheduled runs, the viewer's own tasks). */
export function AgentActivityTimeline({ entries, title }: { entries: TimelineEntry[]; title: string }) {
  const t = useTranslations("office.ws");
  const sorted = [...entries].sort((a, b) => b.at.localeCompare(a.at)).slice(0, 8);
  return (
    <WorkspaceSection title={title} testId="activity-timeline">
      {sorted.length === 0 ? <p className="text-xs text-muted-foreground">{t("noActivity")}</p> : (
        <ol className="space-y-1.5 border-l-2 border-border pl-3">
          {sorted.map((e, i) => (
            <li key={`${e.at}-${i}`} className="relative text-xs" data-tone={e.tone}>
              <span className={cn("absolute -left-[19px] top-0.5 flex size-3.5 items-center justify-center rounded-full ring-2 ring-card",
                e.tone === "ok" ? "bg-emerald-500" : e.tone === "attention" ? "bg-amber-500" : e.tone === "running" ? "bg-sky-500" : "bg-slate-400")}
                aria-hidden>
                {e.tone === "ok" ? <CheckCircle2 className="size-2.5 text-white" /> : e.tone === "attention" ? <X className="size-2.5 text-white" />
                  : e.tone === "running" ? <Loader2 className="size-2.5 animate-spin text-white" /> : <Minus className="size-2.5 text-white" />}
              </span>
              <span className="font-medium">{e.label}</span>
              <span className="block text-[11px] text-muted-foreground">{fmt(e.at)}</span>
            </li>
          ))}
        </ol>
      )}
    </WorkspaceSection>
  );
}

/** Results of a tool shown inside a workspace (reuses the Tasks tab's result cards). */
export function ToolResultList({ result }: { result: ToolResult }) {
  const t = useTranslations("office.agent");
  return (
    <div className="space-y-1.5" data-testid="workspace-result">
      <ul className="space-y-1.5">
        {result.items.map((item, i) => <li key={`${item.id ?? item.href ?? ""}-${i}`}><AgentResultCard item={item} /></li>)}
      </ul>
      {result.notes.filter((n) => t.has(`notes.${n}`)).map((n) => (
        <p key={n} className="flex items-start gap-1.5 text-xs text-muted-foreground" data-note={n}>
          <ShieldCheck className="mt-0.5 size-3.5 shrink-0" aria-hidden /> {t(`notes.${n}`)}
        </p>
      ))}
    </div>
  );
}

export function Notes({ notes }: { notes: string[] }) {
  const t = useTranslations("office.agent");
  const shown = [...new Set(notes)].filter((n) => t.has(`notes.${n}`));
  if (!shown.length) return null;
  return (
    <div className="space-y-1">
      {shown.map((n) => (
        <p key={n} className="flex items-start gap-1.5 text-xs text-muted-foreground" data-note={n}>
          <ShieldCheck className="mt-0.5 size-3.5 shrink-0" aria-hidden /> {t(`notes.${n}`)}
        </p>
      ))}
    </div>
  );
}
