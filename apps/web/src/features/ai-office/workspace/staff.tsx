"use client";

/**
 * Supporter desks: the term list (everyone) and the translation review queue (Global Supporters and admins of that language).
 * Sumin's staff queue: waiting support requests as metadata. The backend decides who sees what; the student's words are never
 * part of these lists.
 */
import { useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { BookA, Languages, Loader2, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { agentApi, type ResultItem, type ToolResult } from "@/features/ai-office/agent-api";
import { fmt } from "@/features/ai-office/agent-work";
import { useWorkspace } from "@/features/ai-office/workspace/context";
import { EmptyState, LoadState, WorkspaceSection } from "@/features/ai-office/workspace/parts";
import { ApiError } from "@/lib/api";
import { LOCALES, LOCALE_LABELS } from "@/lib/constants";
import { useApi } from "@/lib/use-api";

export function TermsWorkspace() {
  const ws = useWorkspace();
  const t = useTranslations("office.ws.terms");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ToolResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function search() {
    const q = text.trim();
    if (!q || busy) return;
    setBusy(true);
    setError(null);
    try {
      setResult((await agentApi.tool(ws.agent.id, "terminology_lookup", { text: q.slice(0, 2000) }, ws.language)).result);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t("error"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4" data-testid="ws-terms">
      <p className="text-muted-foreground">{t("intro")}</p>
      <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); void search(); }}>
        <label htmlFor="terms-text" className="text-xs font-semibold">{t("label")}</label>
        <textarea id="terms-text" value={text} onChange={(e) => setText(e.target.value)} rows={3} maxLength={2000} data-testid="terms-input"
          className="w-full rounded-xl border border-input bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring" />
        <Button type="submit" size="sm" className="min-h-10" disabled={busy || !text.trim()} data-testid="terms-search">
          {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Search className="size-4" aria-hidden />} {t("search")}
        </Button>
      </form>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      {result && (
        <div aria-live="polite" data-testid="terms-result">
          {result.items.length === 0 ? <EmptyState>{t("none")}</EmptyState> : (
            <ul className="space-y-2">
              {result.items.map((i) => (
                <li key={i.title} className="rounded-2xl border border-border p-3 text-sm">
                  <p className="flex items-center gap-1.5 font-semibold"><BookA className="size-4 text-primary" aria-hidden />{i.title}</p>
                  <dl className="mt-1 grid gap-x-3 gap-y-0.5 text-xs sm:grid-cols-[8rem_1fr]">
                    {LOCALES.filter((l) => l !== "ko").map((l) => (
                      <div key={l} className="contents"><dt className="text-muted-foreground">{LOCALE_LABELS[l]}</dt><dd lang={l}>{i.terms?.[l]}</dd></div>
                    ))}
                  </dl>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-2 text-xs text-amber-900 dark:text-amber-300">{t("draft")}</p>
        </div>
      )}
    </div>
  );
}

export function QueueWorkspace() {
  const ws = useWorkspace();
  return ws.agent.id === "support-coordinator" ? <SupportQueue /> : <TranslationQueue />;
}

function TranslationQueue() {
  const ws = useWorkspace();
  const t = useTranslations("office.ws.queue");
  const data = useApi(`ws-trq:${ws.agent.id}`, () => agentApi.tool(ws.agent.id, "translation_review_queue", { limit: 50 }, ws.language));
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);
  const result = data.data?.result;
  const draftTool = ws.agent.tools.find((x) => x.name === "request_translation_draft");

  async function draft(item: ResultItem, summary = false) {
    setBusy(item.id ?? "");
    setNotice(null);
    try {
      const r = await agentApi.tool(ws.agent.id, "request_translation_draft",
        item.content_kind === "announcement" ? { announcement_id: item.ref } : { document_id: item.ref, ...(summary ? { summary: true } : {}) }, ws.language);
      setNotice({ ok: true, text: r.result.items[0]?.executor === "gpu" ? t("queuedGpu") : t("queued") });
      data.reload();
    } catch (e) {
      setNotice({ ok: false, text: e instanceof ApiError ? e.message : t("error") });
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-4" data-testid="ws-translation-queue">
      <p className="text-muted-foreground">{t("intro")}</p>
      {notice && <p role="status" className={`text-sm ${notice.ok ? "text-emerald-800 dark:text-emerald-300" : "text-destructive"}`}>{notice.text}</p>}
      {draftTool && !draftTool.available && <p className="text-xs text-muted-foreground" data-testid="drafts-unavailable">{t("noModel")}</p>}
      <LoadState loading={data.loading && !result} error={data.error} onRetry={data.reload} />
      {result?.notes.includes("not_your_language") ? <EmptyState>{t("notYours")}</EmptyState> : result && (
        <>
          <ul className="flex flex-wrap gap-1.5" aria-label={t("counts")}>
            {Object.entries(result.counts ?? {}).map(([k, n]) => (
              <li key={k} className="rounded-full bg-muted px-2 py-0.5 text-[11px] font-semibold">{t.has(`status.${k}`) ? t(`status.${k}`) : k}: {n}</li>
            ))}
          </ul>
          {result.items.length === 0 ? <EmptyState>{t("empty")}</EmptyState> : (
            <ul className="space-y-2">
              {result.items.map((i) => (
                <li key={i.id} className="space-y-1.5 rounded-2xl border border-border p-3 text-sm" data-testid="queue-item">
                  <p className="font-semibold">{i.title}</p>
                  <p className="text-xs text-muted-foreground">
                    {t(`kinds.${i.content_kind ?? "document"}`)} · {i.outdated ? t("status.outdated") : t.has(`status.${i.status}`) ? t(`status.${i.status}`) : i.status}
                    {i.updated_at ? ` · ${fmt(i.updated_at)}` : ""}
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    <Button asChild size="sm" variant="outline" className="min-h-9"><Link href={i.href ?? "/admin/translations"}><Languages className="size-4" aria-hidden /> {t("open")}</Link></Button>
                    {i.status === "todo" && i.machine_draft === false && (
                      <span className="self-center text-xs text-muted-foreground" data-testid="hand-only">{t("handOnly")}</span>
                    )}
                    {i.status === "todo" && i.machine_draft !== false && (
                      <Button size="sm" variant="ghost" className="min-h-9" disabled={!draftTool?.available || busy !== null} onClick={() => void draft(i)} data-testid="request-draft">
                        {busy === i.id && <Loader2 className="size-4 animate-spin" aria-hidden />} {t("draft")}
                      </Button>
                    )}
                    {i.status === "todo" && i.content_kind === "document" && (
                      <Button size="sm" variant="ghost" className="min-h-9" disabled={!draftTool?.available || busy !== null} onClick={() => void draft(i, true)} data-testid="request-summary">
                        {t("summary")}
                      </Button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}

function SupportQueue() {
  const ws = useWorkspace();
  const t = useTranslations("office.ws.queue");
  const data = useApi("ws-support-queue", () => agentApi.tool(ws.agent.id, "support_queue", { limit: 50 }, ws.language));
  const result = data.data?.result;
  return (
    <div className="space-y-4" data-testid="ws-support-queue">
      <p className="text-muted-foreground">{t("supportIntro")}</p>
      <LoadState loading={data.loading && !result} error={data.error} onRetry={data.reload} />
      {result && (
        <WorkspaceSection title={t("waiting", { count: result.items.length })}>
          {result.items.length === 0 ? <EmptyState next={[{ label: t("openInbox"), href: "/admin/support" }]}>{t("supportEmpty")}</EmptyState> : (
            <ul className="space-y-2">
              {result.items.map((i) => (
                <li key={i.id} className="flex flex-wrap items-center gap-2 rounded-2xl border border-border p-3 text-sm" data-testid="support-queue-item">
                  <span className="font-semibold">#{i.ticket_number}</span>
                  <span className="text-xs text-muted-foreground">{LOCALE_LABELS[(i.language ?? "en") as keyof typeof LOCALE_LABELS] ?? i.language} · {i.priority}{i.created_at ? ` · ${fmt(i.created_at)}` : ""}</span>
                  <Button asChild size="sm" variant="outline" className="ml-auto min-h-9"><Link href={i.href ?? "/admin/support"}>{t("open")}</Link></Button>
                </li>
              ))}
            </ul>
          )}
        </WorkspaceSection>
      )}
    </div>
  );
}
