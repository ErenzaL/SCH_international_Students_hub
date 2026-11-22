"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { AlertTriangle, ExternalLink, LifeBuoy, Loader2, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { renderMarkdown } from "@/lib/chat-markdown";
import { cn } from "@/lib/utils";
import type { ConversationCitation, ConversationMessage, SupportTicket } from "@/types/api";

export interface ChatMsg extends Pick<ConversationMessage, "role" | "content" | "citations" | "metadata"> {
  id: string;
  language?: string;
  streaming?: boolean;
  failed?: boolean;
}

function citeHref(c: ConversationCitation | undefined): string | null {
  if (!c) return null;
  return c.document_id ? `/knowledge/${c.document_id}` : c.source_url;
}

/** Sources to list under an answer: the ones the answer cites (or all, for evidence-only replies). */
export function visibleCitations(m: Pick<ChatMsg, "citations" | "metadata">): ConversationCitation[] {
  const cs = m.citations ?? [];
  const generated = m.metadata?.answer_generation === "llm";
  const cited = cs.filter((c) => c.cited);
  return generated ? cited : cs;
}

export function ChatMessageView({ m, onRetry }: { m: ChatMsg; onRetry?: () => void }) {
  const t = useTranslations("chatbot");
  const isUser = m.role === "user";
  if (m.metadata?.kind === "handoff_created") return <TicketCard m={m} />;
  const sources = isUser ? [] : visibleCitations(m);
  const byN = new Map((m.citations ?? []).map((c) => [c.n, c]));
  return (
    <div className={cn("flex", isUser ? "justify-end" : "justify-start")}>
      <div
        className={cn(
          "max-w-[85%] space-y-2 rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed",
          isUser ? "rounded-br-md bg-primary text-primary-foreground" : "rounded-bl-md bg-muted text-foreground",
          m.failed && "border border-destructive/50",
        )}
        lang={m.language}
      >
        {isUser ? (
          <p className="whitespace-pre-wrap break-words">{m.content}</p>
        ) : m.streaming && !m.content ? (
          <span className="inline-flex items-center gap-1" aria-label={t("thinking")}>
            <span className="size-1.5 animate-bounce rounded-full bg-muted-foreground [animation-delay:-0.2s]" />
            <span className="size-1.5 animate-bounce rounded-full bg-muted-foreground [animation-delay:-0.1s]" />
            <span className="size-1.5 animate-bounce rounded-full bg-muted-foreground" />
          </span>
        ) : (
          <div className="space-y-2 break-words" data-testid="assistant-answer">
            {renderMarkdown(m.content, {
              renderCitation: (n, key) => {
                const href = citeHref(byN.get(n));
                return href ? (
                  <a key={key} href={href} className="align-super text-[0.7em] font-semibold text-primary no-underline"
                     aria-label={t("sourceN", { n })} title={byN.get(n)?.document_title ?? undefined}>
                    [{n}]
                  </a>
                ) : null;
              },
            })}
          </div>
        )}
        {m.failed && (
          <p className="flex items-center gap-2 text-xs text-destructive">
            <AlertTriangle className="size-3.5" aria-hidden /> {m.content ? null : t("failed")}
            {onRetry && (
              <Button size="sm" variant="ghost" className="h-6 px-2" onClick={onRetry}>
                <RotateCcw className="size-3" /> {t("retry")}
              </Button>
            )}
          </p>
        )}
        {sources.length > 0 && !m.streaming && (
          <ol className="space-y-1 border-t border-border/60 pt-2 text-xs" aria-label={t("sources")}>
            {sources.map((c) => (
              <li key={c.n} className="flex items-start gap-1.5">
                <span className="font-semibold text-muted-foreground">[{c.n}]</span>
                <span className="min-w-0 flex-1">
                  {c.document_id ? (
                    <Link href={`/knowledge/${c.document_id}`} className="font-medium text-primary hover:underline">
                      {c.document_title}
                    </Link>
                  ) : (
                    <span className="font-medium">{c.document_title}</span>
                  )}
                  {c.organization && <span className="text-muted-foreground"> · {c.organization}</span>}
                  {c.is_stale && <span className="ml-1 text-amber-700 dark:text-amber-300">({t("maybeOutdated")})</span>}
                </span>
                {c.source_url && (
                  <a href={c.source_url} target="_blank" rel="noopener noreferrer" aria-label={t("officialSource")}
                     className="shrink-0 text-muted-foreground hover:text-primary">
                    <ExternalLink className="size-3.5" />
                  </a>
                )}
              </li>
            ))}
          </ol>
        )}
      </div>
    </div>
  );
}

function TicketCard({ m }: { m: ChatMsg }) {
  const t = useTranslations("chatbot");
  const ts = useTranslations("requests.status");
  const id = m.metadata?.ticket_id;
  const [status, setStatus] = useState(m.metadata?.ticket_status ?? null);
  useEffect(() => {
    if (!id) return;
    let alive = true;
    api.get<SupportTicket>(`/api/v1/support/tickets/${encodeURIComponent(id)}`)
      .then((tk) => alive && setStatus(tk.status))
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [id]);
  return (
    <div className="rounded-xl border border-primary/30 bg-primary/5 p-3 text-sm" data-testid="ticket-card">
      <p className="flex items-center gap-2 font-medium">
        <LifeBuoy className="size-4 text-primary" aria-hidden /> {t("requestSent", { number: m.metadata?.ticket_number ?? "" })}
      </p>
      <p className="mt-1 whitespace-pre-wrap text-muted-foreground">{m.content}</p>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
        {status ? <span className="rounded-full bg-background px-2 py-0.5 font-medium">{ts(status)}</span>
          : <Loader2 className="size-3 animate-spin" aria-hidden />}
        {id && <Link href={`/support/requests/${id}`} className="font-medium text-primary hover:underline">{t("openRequest")}</Link>}
      </div>
    </div>
  );
}
