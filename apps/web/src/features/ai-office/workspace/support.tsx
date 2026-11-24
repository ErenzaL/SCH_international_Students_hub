"use client";

/**
 * Sumin (Support coordinator) - a request workspace instead of a chat. Three explicit steps:
 *   1. the student fills in category, language, subject and details;
 *   2. "Review" stores the request as a task WAITING for approval (no ticket exists yet) and shows exactly what the
 *      server stored;
 *   3. only "Confirm and send" creates the human-support request (the existing approval endpoint); "Edit" declines
 *      the stored draft and returns to the form.
 * The history comes from get_support_request_status, which only ever returns the caller's own requests.
 */
import { useState } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { CheckCircle2, Loader2, Send } from "lucide-react";
import { Button } from "@/components/ui/button";
import { agentApi, useAgentTasks, type AgentTask } from "@/features/ai-office/agent-api";
import { TaskCard, fmt } from "@/features/ai-office/agent-work";
import { useWorkspace } from "@/features/ai-office/workspace/context";
import {
  AgentPermissionGate, EmptyState, LoadState, Notes, SignInPrompt, WorkspaceSection,
} from "@/features/ai-office/workspace/parts";
import { useOfficeLabels } from "@/features/ai-office/use-office-labels";
import { ApiError } from "@/lib/api";
import { useApi } from "@/lib/use-api";
import { cn } from "@/lib/utils";
import type { LanguageCode } from "@/types/api";

export const SUPPORT_CATEGORIES = ["visa", "academic", "housing", "scholarship", "work", "health", "daily", "other"] as const;
const LANGS: LanguageCode[] = ["ko", "en", "id", "vi", "zh-CN"];

export function SupportRequestWorkspace() {
  const t = useTranslations("office.ws.support");
  return (
    <AgentPermissionGate require="signedIn" fallback={<SignInPrompt text={t("signIn")} />}>
      <RequestFlow />
    </AgentPermissionGate>
  );
}

function RequestFlow() {
  const ws = useWorkspace();
  const t = useTranslations("office.ws.support");
  const tAgent = useTranslations("office.agent");
  const labels = useOfficeLabels();
  const locale = useLocale() as LanguageCode;
  const { tasks, reload } = useAgentTasks(ws.agent, ws.signedIn, ws.onChanged);
  const [category, setCategory] = useState<(typeof SUPPORT_CATEGORIES)[number]>("other");
  const [language, setLanguage] = useState<LanguageCode>(LANGS.includes(locale) ? locale : "en");
  const [subject, setSubject] = useState("");
  const [details, setDetails] = useState("");
  const [draft, setDraft] = useState<AgentTask | null>(null);
  const [sentId, setSentId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const nameOf = (id: string) => ws.agents?.find((a) => a.id === id)?.name ?? id;

  const call = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e instanceof ApiError ? e.code : "generic");
    } finally {
      setBusy(false);
    }
  };

  const prepare = () => call(async () => {
    const task = await agentApi.createTask(ws.agent.id, "support_request", {
      subject: `[${t(`categories.${category}`)}] ${subject.trim()}`, summary: details.trim(), language,
    }, language);
    setDraft(task);
    void reload();
    ws.onChanged();
  });
  const confirm = () => call(async () => {
    await agentApi.decide(draft!.id, true);
    setSentId(draft!.id);
    setDraft(null);
    setSubject("");
    setDetails("");
    void reload();
    ws.onChanged();
  });
  const edit = () => call(async () => {
    await agentApi.decide(draft!.id, false);      // the stored draft is discarded; the form keeps the text
    setDraft(null);
    void reload();
    ws.onChanged();
  });

  const sent = sentId ? tasks?.find((x) => x.id === sentId) ?? null : null;
  const ticket = sent?.output?.items?.[0];
  const otherPending = (tasks ?? []).filter((x) => x.task_type === "support_request" && x.status === "awaiting_approval"
    && x.id !== draft?.id);
  const valid = subject.trim().length >= 3 && details.trim().length >= 10;
  const stored = draft?.params as { subject?: string; summary?: string; language?: LanguageCode } | undefined;

  return (
    <div className="space-y-5" data-testid="ws-support">
      {sentId && (
        <section className="space-y-1.5 rounded-xl bg-emerald-50 p-3 text-emerald-950 dark:bg-emerald-950/30 dark:text-emerald-100" data-testid="request-sent" aria-live="polite">
          <p className="flex items-center gap-1.5 font-semibold">
            {ticket ? <CheckCircle2 className="size-4" aria-hidden /> : <Loader2 className="size-4 animate-spin" aria-hidden />}
            {ticket ? t("sent", { number: ticket.ticket_number ?? "" }) : t("sending")}
          </p>
          {ticket?.href && <Link href={ticket.href} className="text-xs font-semibold underline">{t("openRequest")}</Link>}
          {sent?.status === "failed" && <p className="text-xs text-red-700">{tAgent("errors.generic")}</p>}
        </section>
      )}

      {draft && stored ? (
        <section className="space-y-2 rounded-xl border-2 border-amber-300 bg-amber-50 p-3 text-amber-950 dark:bg-amber-950/30 dark:text-amber-100" data-testid="request-preview">
          <h3 className="font-bold">{t("previewTitle")}</h3>
          <p className="text-xs">{t("previewNote", { team: labels.languageName(stored.language ?? language) })}</p>
          <dl className="space-y-1.5 rounded-lg bg-white/80 p-2.5 text-sm text-foreground dark:bg-black/20">
            <dt className="text-[11px] font-bold text-muted-foreground">{t("subject")}</dt>
            <dd className="font-semibold" data-testid="preview-subject">{stored.subject}</dd>
            <dt className="text-[11px] font-bold text-muted-foreground">{t("details")}</dt>
            <dd className="whitespace-pre-line" data-testid="preview-details">{stored.summary}</dd>
            <dt className="text-[11px] font-bold text-muted-foreground">{t("language")}</dt>
            <dd>{labels.languageName(stored.language ?? language)}</dd>
          </dl>
          <div className="flex flex-wrap gap-2">
            <Button className="min-h-10" disabled={busy} onClick={() => void confirm()} data-testid="request-confirm">
              {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Send className="size-4" aria-hidden />} {t("confirm")}
            </Button>
            <Button variant="outline" className="min-h-10" disabled={busy} onClick={() => void edit()} data-testid="request-edit">{t("edit")}</Button>
          </div>
        </section>
      ) : (
        <WorkspaceSection title={t("formTitle")} testId="request-form">
          <p className="text-xs text-muted-foreground">{t("formIntro")}</p>
          <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (valid) void prepare(); }}>
            <fieldset className="space-y-1.5">
              <legend className="text-xs font-bold text-muted-foreground">{t("category")}</legend>
              <div className="flex flex-wrap gap-1.5" data-testid="request-category">
                {SUPPORT_CATEGORIES.map((c) => (
                  <button key={c} type="button" aria-pressed={category === c} onClick={() => setCategory(c)} data-value={c}
                    className={cn("min-h-9 rounded-full px-3 text-xs font-semibold ring-1",
                      category === c ? "bg-[#3D6A8C] text-white ring-[#3D6A8C]" : "ring-border hover:bg-muted")}>
                    {t(`categories.${c}`)}
                  </button>
                ))}
              </div>
            </fieldset>
            <label className="block space-y-1 text-xs font-bold text-muted-foreground">
              {t("language")}
              <select value={language} onChange={(e) => setLanguage(e.target.value as LanguageCode)} data-testid="request-language"
                className="block min-h-10 w-full rounded-xl border border-input bg-background px-3 text-sm font-normal text-foreground">
                {LANGS.map((l) => <option key={l} value={l}>{labels.languageName(l)}</option>)}
              </select>
            </label>
            <label className="block space-y-1 text-xs font-bold text-muted-foreground">
              {t("subject")}
              <input value={subject} onChange={(e) => setSubject(e.target.value)} maxLength={150} required data-testid="request-subject"
                className="block min-h-10 w-full rounded-xl border border-input bg-background px-3 text-sm font-normal text-foreground" />
            </label>
            <label className="block space-y-1 text-xs font-bold text-muted-foreground">
              {t("details")}
              <textarea value={details} onChange={(e) => setDetails(e.target.value)} maxLength={4000} rows={5} required data-testid="request-details"
                placeholder={t("detailsPlaceholder")}
                className="block w-full resize-y rounded-xl border border-input bg-background px-3 py-2 text-sm font-normal text-foreground" />
            </label>
            <p className="text-[11px] text-muted-foreground">{t("privacy")}</p>
            <Button type="submit" className="min-h-10" disabled={busy || !valid} data-testid="request-review">
              {busy && <Loader2 className="size-4 animate-spin" aria-hidden />} {t("review")}
            </Button>
          </form>
        </WorkspaceSection>
      )}
      {error && <p role="alert" className="text-xs text-red-700" data-testid="request-error">{tAgent.has(`errors.${error}`) ? tAgent(`errors.${error}`) : tAgent("errors.generic")}</p>}

      {otherPending.length > 0 && (
        <WorkspaceSection title={t("waitingTitle")} testId="pending-requests">
          <ul className="space-y-2">
            {otherPending.map((task) => <li key={task.id}><TaskCard task={task} nameOf={nameOf} onChanged={() => { void reload(); ws.onChanged(); }} /></li>)}
          </ul>
        </WorkspaceSection>
      )}
    </div>
  );
}

export function MyRequestsWorkspace() {
  const t = useTranslations("office.ws.support");
  return (
    <AgentPermissionGate require="signedIn" fallback={<SignInPrompt text={t("signIn")} />}>
      <MyRequests />
    </AgentPermissionGate>
  );
}

function MyRequests() {
  const ws = useWorkspace();
  const t = useTranslations("office.ws.support");
  const tAgent = useTranslations("office.agent");
  const data = useApi(`ws-requests:${ws.agent.id}`, () =>
    agentApi.tool(ws.agent.id, "get_support_request_status", { limit: 20 }, ws.language));
  const items = data.data?.result.items ?? [];
  return (
    <div className="space-y-3" data-testid="ws-requests">
      <WorkspaceSection title={t("historyTitle")} action={<Button size="sm" variant="ghost" className="h-8 text-xs" onClick={data.reload}>{t("refresh")}</Button>}>
        <LoadState loading={data.loading && !data.data} error={data.error} onRetry={data.reload} />
        {data.data && (items.length === 0 ? <EmptyState>{t("noRequests")}</EmptyState> : (
          <ul className="space-y-1.5">
            {items.map((r) => (
              <li key={r.id}>
                <Link href={r.href ?? "/support"} className="block rounded-xl border border-border px-3 py-2 hover:bg-muted" data-testid="request-row">
                  <span className="flex flex-wrap items-center gap-1.5">
                    <span className="font-semibold">#{r.ticket_number}</span>
                    <span className="rounded-full bg-muted px-1.5 text-[10px] font-bold">
                      {r.status && tAgent.has(`ticketStatus.${r.status}`) ? tAgent(`ticketStatus.${r.status}`) : r.status}
                    </span>
                  </span>
                  <span className="block text-sm">{r.subject}</span>
                  {r.updated_at && <span className="block text-[11px] text-muted-foreground">{t("updated", { when: fmt(r.updated_at) })}</span>}
                </Link>
              </li>
            ))}
          </ul>
        ))}
        <Notes notes={data.data?.result.notes.filter((n) => n !== "no_tickets") ?? []} />
      </WorkspaceSection>
      <Link href="/support" className="inline-block text-sm font-medium text-primary hover:underline">{t("allRequests")}</Link>
    </div>
  );
}
