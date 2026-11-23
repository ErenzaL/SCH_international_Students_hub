"use client";

/**
 * The "Tasks" tab of a character: what this agent does (from the backend registry), its quick tasks, a free-text
 * request, and the student's tasks with their steps, sources and reliability labels. Nothing here decides
 * anything: permissions, routing, task state and results all come from the backend.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { AlertTriangle, ArrowRight, Check, CircleDashed, ExternalLink, Loader2, ShieldCheck, Sparkles, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  ACTIVE, agentApi, type AgentInfo, type AgentState, type AgentTask, type RequestOutcome, type ResultItem,
  type ToolResult,
} from "@/features/ai-office/agent-api";
import type { OfficeCharacter } from "@/features/ai-office/characters";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { LanguageCode } from "@/types/api";

const POLL_MS = 2500;

type Shown =
  | { kind: "result"; result: ToolResult; handledBy: string; delegatedFrom?: string | null }
  | { kind: "redirect"; character: string; agent: string }
  | { kind: "clarify"; options: string[] }
  | { kind: "error"; code: string };

export function AgentWork({ c, agent, agents, signedIn, onAnswerInChat, onSelect, onChanged }: {
  c: OfficeCharacter;
  agent: AgentInfo | undefined;
  agents: AgentInfo[] | null;
  signedIn: boolean;
  /** a question: the grounded chat answers it */
  onAnswerInChat: (message: string) => void;
  onSelect: (characterId: string) => void;
  /** a task was started / changed: refresh agent states in the office */
  onChanged: () => void;
}) {
  const t = useTranslations("office.agent");
  const locale = useLocale() as LanguageCode;
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [shown, setShown] = useState<Shown | null>(null);
  const [tasks, setTasks] = useState<AgentTask[] | null>(null);
  const language = (c.language ?? locale) as LanguageCode;
  const nameOf = useCallback((id: string) => agents?.find((a) => a.id === id)?.name ?? id, [agents]);

  const loadTasks = useCallback(async () => {
    if (!signedIn || !agent) return;
    try {
      const r = await agentApi.tasks(agent.id);
      setTasks(r.items);
    } catch {
      setTasks((prev) => prev ?? []);
    }
  }, [signedIn, agent]);

  useEffect(() => {
    const id = window.setTimeout(() => void loadTasks(), 0);
    return () => window.clearTimeout(id);
  }, [loadTasks]);

  // poll while one of the visible tasks is still queued / running
  const running = tasks?.some((x) => x.status === "queued" || x.status === "running");
  useEffect(() => {
    if (!running) return;
    const id = window.setInterval(() => void loadTasks().then(onChanged), POLL_MS);
    return () => window.clearInterval(id);
  }, [running, loadTasks, onChanged]);

  if (!agent) {
    return <p className="text-muted-foreground" data-testid="agent-unavailable">{t("loadError")}</p>;
  }

  const fail = (e: unknown) => setShown({ kind: "error", code: e instanceof ApiError ? e.code : "generic" });

  const runAction = async (actionId: string) => {
    const action = agent.actions.find((a) => a.id === actionId);
    if (!action) return;
    setBusy(true);
    setShown(null);
    try {
      if (action.kind === "tool") {
        const r = await agentApi.tool(agent.id, action.target, action.params, language);
        setShown({ kind: "result", result: r.result, handledBy: r.handled_by ?? agent.id });
      } else {
        await agentApi.createTask(agent.id, action.target, action.params, language);
        await loadTasks();
        onChanged();
      }
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };

  const send = async () => {
    const message = text.trim();
    if (!message) return;
    setBusy(true);
    setShown(null);
    try {
      const r: RequestOutcome = await agentApi.request(agent.id, message, language);
      if (r.route === "answer") {
        setText("");
        onAnswerInChat(message);
      } else if (r.route === "tool") {
        setShown({ kind: "result", result: r.result, handledBy: r.handled_by, delegatedFrom: r.delegated_from });
      } else if (r.route === "redirect") {
        setShown({ kind: "redirect", character: r.suggested_character, agent: r.suggested_agent });
      } else if (r.route === "clarify") {
        setShown({ kind: "clarify", options: r.options });
      } else {
        setText("");
        await loadTasks();
        onChanged();
      }
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };

  const ownTasks = tasks?.filter((x) => x.agent_id === agent.id) ?? [];

  return (
    <div className="space-y-4" data-testid="agent-work" data-agent={agent.id}>
      <section className="space-y-1.5">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-sm font-semibold">{t("title")}</h3>
          <StateBadge state={agent.state} />
          {agent.monitoring && <span className="rounded-full bg-sky-50 px-2 py-0.5 text-[11px] font-semibold text-sky-800">{t("monitoring")}</span>}
        </div>
        <p className="text-muted-foreground">{t(`scope.${c.role}`)}</p>
      </section>

      {agent.actions.length > 0 && (
        <section className="space-y-1.5">
          <h3 className="text-xs font-bold tracking-wide text-muted-foreground">{t("quick")}</h3>
          <div className="flex flex-wrap gap-1.5">
            {agent.actions.map((a) => {
              const needsSignIn = a.kind === "task" && !signedIn;
              return (
                <Button key={a.id} size="sm" variant="outline" disabled={busy || needsSignIn} data-testid={`action-${a.id}`}
                  onClick={() => void runAction(a.id)} title={needsSignIn ? t("signInForTasks", { name: agent.name }) : undefined}>
                  {a.kind === "task" && <CircleDashed className="size-3.5" aria-hidden />}
                  {t(`actions.${a.id}`)}
                </Button>
              );
            })}
          </div>
        </section>
      )}

      <section className="space-y-1.5">
        <label htmlFor={`agent-request-${agent.id}`} className="text-xs font-bold tracking-wide text-muted-foreground">
          {t("askLabel", { name: agent.name })}
        </label>
        <div className="flex gap-2">
          <textarea id={`agent-request-${agent.id}`} value={text} onChange={(e) => setText(e.target.value)} rows={2}
            maxLength={2000} placeholder={t(`placeholder.${c.role}`)} data-testid="agent-request-input"
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                void send();
              }
            }}
            className="min-h-[44px] flex-1 resize-none rounded-xl border border-input bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring" />
          <Button onClick={() => void send()} disabled={busy || !text.trim()} data-testid="agent-request-send" className="self-end">
            {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <ArrowRight className="size-4" aria-hidden />}
            <span className="sr-only sm:not-sr-only">{t("send")}</span>
          </Button>
        </div>
        {!signedIn && (
          <p className="text-xs text-muted-foreground">
            {t("signInForTasks", { name: agent.name })}{" "}
            <Link className="font-semibold text-primary underline" href="/login?next=%2Fai-office">{t("signIn")}</Link>
          </p>
        )}
      </section>

      <div aria-live="polite">
        {busy && <p className="flex items-center gap-2 text-muted-foreground"><Loader2 className="size-4 animate-spin" aria-hidden /> {t("working")}</p>}
        {shown?.kind === "result" && (
          <div className="space-y-2" data-testid="agent-result">
            {shown.delegatedFrom && (
              <p className="text-xs text-muted-foreground">{t("delegated", { from: nameOf(shown.delegatedFrom), to: nameOf(shown.handledBy) })}</p>
            )}
            <ResultView result={shown.result} />
          </div>
        )}
        {shown?.kind === "redirect" && (
          <div className="space-y-2 rounded-xl bg-muted p-3" data-testid="agent-redirect">
            <p>{t("redirect", { name: nameOf(shown.agent) })}</p>
            <Button size="sm" onClick={() => onSelect(shown.character)}>{t("goTo", { name: nameOf(shown.agent) })}</Button>
          </div>
        )}
        {shown?.kind === "clarify" && (
          <div className="space-y-2" data-testid="agent-clarify">
            <p>{t("clarify")}</p>
            <div className="flex flex-wrap gap-1.5">
              {shown.options.map((o) => (
                <Button key={o} size="sm" variant="outline" onClick={() => void runAction(o)}>{t(`actions.${o}`)}</Button>
              ))}
            </div>
          </div>
        )}
        {shown?.kind === "error" && (
          <p role="alert" className="flex items-start gap-2 rounded-xl bg-red-50 p-3 text-red-800 dark:bg-red-950/40 dark:text-red-200" data-testid="agent-error">
            <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
            {t.has(`errors.${shown.code}`) ? t(`errors.${shown.code}`) : t("errors.generic")}
          </p>
        )}
      </div>

      {signedIn && (
        <section className="space-y-2" data-testid="agent-tasks">
          <h3 className="text-sm font-semibold">{t("myTasks", { name: agent.name })}</h3>
          {tasks === null ? (
            <p className="text-muted-foreground">{t("loading")}</p>
          ) : ownTasks.length === 0 ? (
            <p className="text-muted-foreground">{t("noTasks")}</p>
          ) : (
            <ul className="space-y-2">
              {ownTasks.map((task) => (
                <li key={task.id}><TaskCard task={task} nameOf={nameOf} onChanged={() => { void loadTasks(); onChanged(); }} /></li>
              ))}
            </ul>
          )}
        </section>
      )}

      <details className="rounded-xl border border-border p-3" data-testid="agent-tools">
        <summary className="cursor-pointer text-sm font-semibold">{t("toolsTitle")}</summary>
        <ul className="mt-2 space-y-1">
          {agent.tools.map((tool) => (
            <li key={tool.name} className="flex flex-wrap items-center gap-1.5" data-tool={tool.name} data-available={tool.available}>
              {tool.available ? <Check className="size-3.5 text-emerald-600" aria-hidden /> : <X className="size-3.5 text-amber-600" aria-hidden />}
              <span className={cn(!tool.available && "text-muted-foreground")}>{t(`tools.${tool.name}`)}</span>
              {!tool.available && <Flag>{t("flags.unavailable")}</Flag>}
              {tool.uses_ai && <Flag>{t("flags.ai")}</Flag>}
              {tool.needs_approval && <Flag>{t("flags.approval")}</Flag>}
              {tool.requires_sign_in && <Flag>{t("flags.signIn")}</Flag>}
            </li>
          ))}
        </ul>
        {agent.restricted_actions.length > 0 && (
          <>
            <p className="mt-3 flex items-center gap-1.5 text-sm font-semibold"><ShieldCheck className="size-4 text-primary" aria-hidden /> {t("neverTitle")}</p>
            <ul className="mt-1 list-disc space-y-0.5 pl-5 text-muted-foreground">
              {agent.restricted_actions.map((r) => <li key={r}>{t(`never.${r}`)}</li>)}
            </ul>
          </>
        )}
      </details>
    </div>
  );
}

function Flag({ children }: { children: React.ReactNode }) {
  return <span className="rounded-full bg-muted px-1.5 py-0.5 text-[10px] font-semibold text-muted-foreground">{children}</span>;
}

export function StateBadge({ state, compact = false }: { state: AgentState; compact?: boolean }) {
  const t = useTranslations("office.agent.states");
  const style: Record<AgentState, string> = {
    idle: "bg-emerald-50 text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-200",
    working: "bg-sky-100 text-sky-900 dark:bg-sky-950/40 dark:text-sky-200",
    waiting: "bg-amber-100 text-amber-900 dark:bg-amber-950/40 dark:text-amber-200",
    completed: "bg-emerald-100 text-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-200",
    error: "bg-red-100 text-red-900 dark:bg-red-950/40 dark:text-red-200",
  };
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-full font-semibold", compact ? "px-1.5 py-0.5 text-[11px]" : "px-2 py-0.5 text-[11px]", style[state])}
      data-testid="agent-state" data-state={state}>
      {state === "working" && <Loader2 className="size-3 animate-spin" aria-hidden />}
      {state === "waiting" && <AlertTriangle className="size-3" aria-hidden />}
      {state === "completed" && <Check className="size-3" aria-hidden />}
      {state === "error" && <X className="size-3" aria-hidden />}
      {t(state)}
    </span>
  );
}

/** The small round status mark shown on a character in the office (the text is in its accessible name). */
export function StateDot({ state }: { state: Exclude<AgentState, "idle"> }) {
  const t = useTranslations("office.agent.states");
  const style: Record<Exclude<AgentState, "idle">, string> = {
    working: "bg-sky-500", waiting: "bg-amber-500", completed: "bg-emerald-500", error: "bg-red-500",
  };
  return (
    <span title={t(state)} data-testid="agent-state" data-state={state}
      className={cn("flex size-6 items-center justify-center rounded-full text-white shadow-md ring-2 ring-white", style[state])}>
      {state === "working" && <Loader2 className="size-3.5 animate-spin" aria-hidden />}
      {state === "waiting" && <span className="text-[13px] font-black leading-none" aria-hidden>!</span>}
      {state === "completed" && <Check className="size-3.5" strokeWidth={3} aria-hidden />}
      {state === "error" && <X className="size-3.5" strokeWidth={3} aria-hidden />}
    </span>
  );
}

function ResultView({ result }: { result: ToolResult }) {
  const t = useTranslations("office.agent");
  return (
    <div className="space-y-2">
      <p className="text-xs font-semibold text-muted-foreground">
        {t("resultCount", { count: result.count })}
        {result.new_count ? ` · ${t("newCount", { count: result.new_count })}` : ""}
        {result.updated_count ? ` · ${t("updatedCount", { count: result.updated_count })}` : ""}
      </p>
      {result.items.length > 0 && (
        <ul className="space-y-1.5">
          {result.items.map((item, i) => <li key={`${item.id ?? item.href ?? ""}-${i}`}><Item item={item} /></li>)}
        </ul>
      )}
      {result.notes.filter((n) => t.has(`notes.${n}`)).map((n) => (
        <p key={n} className="flex items-start gap-1.5 text-xs text-muted-foreground" data-note={n}>
          <ShieldCheck className="mt-0.5 size-3.5 shrink-0" aria-hidden /> {t(`notes.${n}`)}
        </p>
      ))}
    </div>
  );
}

function Item({ item }: { item: ResultItem }) {
  const t = useTranslations("office.agent");
  const title = item.title || (item.ticket_number ? `#${item.ticket_number}` : item.kind);
  const external = Boolean(item.href && /^https?:\/\//.test(item.href));
  const link = item.href ? (
    external ? (
      <a href={item.href} target="_blank" rel="noopener noreferrer" className="font-medium text-primary hover:underline">
        {title} <ExternalLink className="inline size-3" aria-hidden />
      </a>
    ) : (
      <Link href={item.href} className="font-medium text-primary hover:underline">{title}</Link>
    )
  ) : <span className="font-medium">{title}</span>;
  return (
    <div className="rounded-xl bg-muted/60 px-3 py-2" data-testid="agent-item" data-reliability={item.reliability ?? "none"}>
      <div className="flex flex-wrap items-center gap-1.5">
        {link}
        {item.change && <span className="rounded-full bg-sky-100 px-1.5 text-[10px] font-bold text-sky-900">{t(`change.${item.change}`)}</span>}
        {item.reliability && <Reliability r={item.reliability} />}
        {item.error && <span className="text-xs text-red-700">{t.has(`errors.${item.error}`) ? t(`errors.${item.error}`) : t("errors.fetch_failed")}</span>}
      </div>
      <p className="mt-0.5 text-xs text-muted-foreground">
        {[item.heading, item.page ? t("page", { page: item.page }) : null,
          item.deadline ? `${t("dateKinds.deadline")} ${item.deadline}` : null,
          item.event_date ? `${t("dateKinds.event")} ${item.event_date}` : null,
          item.status && item.kind === "ticket" ? t(`ticketStatus.${item.status}`) : null,
          item.date ? `${t.has(`dateKinds.${item.kind}`) ? t(`dateKinds.${item.kind}`) : ""} ${item.date}`.trim() : null]
          .filter(Boolean).join(" · ")}
      </p>
      {(item.quote || item.excerpt) && <p className="mt-1 line-clamp-3 text-xs">{item.quote || item.excerpt}</p>}
      {item.body && <p className="mt-1 whitespace-pre-line text-xs">{item.body}</p>}
      {item.dates && item.dates.length > 0 && (
        <ul className="mt-1 space-y-0.5 text-xs">
          {item.dates.slice(0, 4).map((d, i) => (
            <li key={i}><span className="font-semibold">{t(`dateKinds.${d.kind}`)} {d.date}</span>
              {d.quote ? <span className="text-muted-foreground"> — “{d.quote}”</span> : null}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Reliability({ r }: { r: NonNullable<ResultItem["reliability"]> }) {
  const t = useTranslations("office.agent.reliability");
  const tone = r === "verified" ? "bg-emerald-100 text-emerald-900" : r === "ai_generated" || r === "external_unverified"
    ? "bg-violet-100 text-violet-900" : "bg-amber-100 text-amber-900";
  return (
    <span className={cn("inline-flex items-center gap-0.5 rounded-full px-1.5 text-[10px] font-bold", tone)} data-testid="reliability">
      {r === "ai_generated" && <Sparkles className="size-2.5" aria-hidden />}
      {t(r)}
    </span>
  );
}

function TaskCard({ task, nameOf, onChanged }: { task: AgentTask; nameOf: (id: string) => string; onChanged: () => void }) {
  const t = useTranslations("office.agent");
  const [full, setFull] = useState<AgentTask | null>(null);
  const [acting, setActing] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const loaded = useRef(false);

  const loadFull = useCallback(async () => {
    try {
      setFull(await agentApi.task(task.id));
    } catch {
      /* keep the summary */
    }
  }, [task.id]);

  // the result and steps of a finished task are loaded once; re-load when the status changes
  useEffect(() => {
    loaded.current = false;
  }, [task.status]);
  useEffect(() => {
    if (loaded.current) return;
    loaded.current = true;
    const id = window.setTimeout(() => void loadFull(), 0);
    return () => window.clearTimeout(id);
  }, [loadFull, task.status]);

  const view = full && full.status === task.status ? full : task;
  const act = async (fn: () => Promise<unknown>) => {
    setActing(true);
    setErr(null);
    try {
      await fn();
      onChanged();
    } catch (e) {
      setErr(e instanceof ApiError ? e.code : "generic");
    } finally {
      setActing(false);
    }
  };
  const preview = view.params as { subject?: string; summary?: string };

  return (
    <article className="space-y-2 rounded-xl border border-border p-3" data-testid="agent-task" data-status={view.status}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{t.has(`taskTypes.${view.task_type}`) ? t(`taskTypes.${view.task_type}`) : view.task_type}</span>
        <TaskStatusPill status={view.status} />
        <span className="ml-auto text-[11px] text-muted-foreground">{new Date(view.created_at).toLocaleString()}</span>
      </div>

      {view.status === "awaiting_approval" && (
        <div className="space-y-2 rounded-lg bg-amber-50 p-2.5 text-amber-950 dark:bg-amber-950/30 dark:text-amber-100" data-testid="approval">
          <p className="font-semibold">{t("approveTitle")}</p>
          {preview.subject && <p className="text-xs"><span className="font-semibold">{preview.subject}</span></p>}
          {preview.summary && preview.summary !== preview.subject && <p className="whitespace-pre-line text-xs">{preview.summary}</p>}
          <p className="text-xs">{t("approveNote")}</p>
          <div className="flex gap-2">
            <Button size="sm" disabled={acting} onClick={() => void act(() => agentApi.decide(view.id, true))} data-testid="approve">{t("approve")}</Button>
            <Button size="sm" variant="outline" disabled={acting} onClick={() => void act(() => agentApi.decide(view.id, false))} data-testid="decline">{t("decline")}</Button>
          </div>
        </div>
      )}

      {view.status === "failed" && view.error_code && (
        <p className="text-xs text-red-700 dark:text-red-300">{t.has(`errors.${view.error_code}`) ? t(`errors.${view.error_code}`) : t("errors.generic")}</p>
      )}
      {view.status === "completed" && view.output && <ResultView result={view.output} />}
      {view.output?.provenance && (
        <p className="text-[11px] text-muted-foreground">
          {view.output.provenance.generated_by === "deterministic" ? t("provenance.deterministic") : t("provenance.model", { model: view.output.provenance.generated_by })}
        </p>
      )}

      {ACTIVE.includes(view.status) && view.status !== "awaiting_approval" && (
        <Button size="sm" variant="ghost" disabled={acting} onClick={() => void act(() => agentApi.cancel(view.id))} data-testid="cancel-task">{t("cancel")}</Button>
      )}
      {err && <p role="alert" className="text-xs text-red-700">{t.has(`errors.${err}`) ? t(`errors.${err}`) : t("errors.generic")}</p>}

      {full?.events && full.events.length > 0 && (
        <details>
          <summary className="cursor-pointer text-xs font-semibold text-muted-foreground">{t("showSteps")}</summary>
          <ol className="mt-1 space-y-0.5 border-l border-border pl-3 text-xs" data-testid="task-steps">
            {[...full.events, ...(full.children ?? []).flatMap((ch) => ch.events ?? [])]
              .sort((a, b) => a.created_at.localeCompare(b.created_at))
              .map((e) => (
                <li key={`${e.id}-${e.step}`}>
                  {t(`steps.${e.step}`, {
                    name: nameOf(e.agent_id),
                    tool: e.tool ? (t.has(`tools.${e.tool}`) ? t(`tools.${e.tool}`) : e.tool) : "",
                    to: nameOf(String((e.data as { to?: string }).to ?? "")),
                    count: Number((e.data as { count?: number }).count ?? 0),
                  })}
                </li>
              ))}
          </ol>
        </details>
      )}
    </article>
  );
}

function TaskStatusPill({ status }: { status: AgentTask["status"] }) {
  const t = useTranslations("office.agent.status");
  const tone = status === "completed" ? "bg-emerald-100 text-emerald-900" : status === "failed" ? "bg-red-100 text-red-900"
    : status === "awaiting_approval" ? "bg-amber-100 text-amber-900" : status === "cancelled" ? "bg-muted text-muted-foreground"
      : "bg-sky-100 text-sky-900";
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold", tone)} data-testid="task-status">
      {(status === "queued" || status === "running") && <Loader2 className="size-3 animate-spin" aria-hidden />}
      {t(status)}
    </span>
  );
}
